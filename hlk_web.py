# -*- coding: utf-8 -*-
"""HLK Viewer web server (Dev-Toolbox web mode, TOOL-SPEC 5).

Pure stdlib (ThreadingHTTPServer), binds 127.0.0.1 only. Reuses hlk_core /
hlk_wtl, so behaviour matches the tkinter GUI.

Usage:
    python hlk_web.py [--port 8780] [--open-browser] [--parent-pid <pid>]
                      [--data-dir <path>] [--hub-origin http://127.0.0.1:<p>]

Prints "READY http://127.0.0.1:<port>" on stdout once listening.

API (POST needs header X-Toolbox-Request: 1, JSON body):
    GET  /api/health          ok/id/version/pid/port/uptimeSec
    GET  /api/pkg             load state + project summary + test list (or .hlkp runs/errors)
    POST /api/open  {path}    load a .hlk/.hlkx/.hlkp (background) or .wtl (single-file mode)
    POST /api/close           unload current package
    POST /api/shutdown        graceful stop (Hub 的乾淨關機路徑)
    GET  /api/log?i=&l=       one log converted to HTML (preview; dl=1 下載轉換後的 .htm)
    GET  /api/wtl?dl=         獨立 .wtl 單檔模式: 預覽 HTML（dl=1 下載轉換後的 .htm）
    POST /api/export {mode,items,outdir?}   start export job (te | all)
    GET  /api/export          export job progress/result + suggested outdir
    POST /api/export-xlsx {tests?}  依指定側項（預設全部）產生側項結果 Excel → /report/<file>
    GET  /export/<file>       files produced by the current export job
    GET  /api/browse?path=    list directories + .hlk/.hlkx/.hlkp files (file picker)
    POST /api/upload          raw body + X-Filename header -> dataDir/uploads (drag & drop)
    GET  /api/chunks          .hlkp only: streamdata log chunk 清單（WTT log / Controller 通訊）
    GET  /api/pchunk?c=&dl=   一個 chunk 的預覽 HTML（dl=1 下載原始檔、dl=htm 下載轉換後 .htm）
    ※ dl=1 語意注意: /api/log 與 /api/wtl 的 dl=1 ＝「轉換後的 .htm」,
      /api/pchunk 的 dl=1 ＝「原始位元組」（轉換後另用 dl=htm）, 兩組相反。
"""

import argparse
import ctypes
import errno
import json
import os
import re
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse, quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hlk_core                                    # noqa: E402
import hlk_wtl                                     # noqa: E402
import hlk_xlsx                                    # noqa: E402
from hlk_core import STATUS_TEXT                   # noqa: E402
from standalone_update import handle_update        # noqa: E402

VERSION = '1.2.8'
TOOL_ID = 'hlk-viewer'
DEFAULT_PORT = 8780
MAX_PORT_SCAN = 20
MAX_BODY = 1 * 1024 * 1024
HLK_EXTS = ('.hlk', '.hlkx', '.hlkp')
OPEN_EXTS = HLK_EXTS + ('.wtl',)        # 開檔/上傳/瀏覽接受副檔名（.wtl＝單檔預覽模式）
UPLOAD_MAX = 4 * 1024 * 1024 * 1024        # /api/upload 單檔上限（拖曳上傳, loopback 大檔也夠用）
WTL_PREVIEW_MAX = 512 * 1024 * 1024        # /api/wtl 轉換上限: 整份讀入記憶體, 過大改請用 GUI
BROWSE_CAP = 2000                          # /api/browse 每個清單的項目上限
UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui')
UI_FILES = {'/': 'index.html', '/index.html': 'index.html', '/app.js': 'app.js',
            '/app.css': 'app.css', '/ui-kit.css': 'ui-kit.css',
            '/tb-theme.js': 'tb-theme.js', '/tb-icons.js': 'tb-icons.js',
            '/tb-dirpicker.js': 'tb-dirpicker.js', '/tb-standalone-update.js': 'tb-standalone-update.js'}
CSP_PAGE = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-src 'self'; ")
# exported/previewed HTML: no scripts, but hlk_wtl emits inline styles
CSP_VIEW = ("default-src 'none'; style-src 'unsafe-inline'; img-src data:; ")
STARTED_AT = time.time()

# ---------------------------------------------------------------- shared state
STATE_LOCK = threading.Lock()          # guards the fields below
PKG = None                             # loaded hlk_core.HlkPackage or None
WTL = None                             # 獨立 .wtl 單檔模式 {'path','name','size'}; 與 PKG 互斥
LOAD = {'state': 'idle', 'error': '', 'path': ''}      # idle|loading|ready|error
EXPORT = {'state': 'idle'}             # idle|running|done|error (+ job fields)
EXPORT_DIR = None                      # directory of the current/last export job
REPORT_DIR = None                      # Excel 報表目錄（/report/<file>, 與 /export/ 互不干擾）
HTTPD = None                           # ThreadingHTTPServer instance (for /api/shutdown)
DATA_DIR = None


def default_export_dir():
    return os.path.join(DATA_DIR, 'exports', time.strftime('%Y%m%d-%H%M%S'))


def default_report_dir():
    return os.path.join(DATA_DIR, 'reports', time.strftime('%Y%m%d'))


def sweep_uploads():
    """清除拖曳上傳暫存檔（開機清上次殘留、優雅關閉時清本輪）。使用中删不掉就跳過。"""
    if not DATA_DIR:
        return
    d = os.path.join(DATA_DIR, 'uploads')
    if not os.path.isdir(d):
        return
    for fn in os.listdir(d):
        fp = os.path.join(d, fn)
        try:
            if os.path.isfile(fp):
                os.remove(fp)
        except OSError:
            pass


def pick_te(t):
    """Same rule as the GUI: Run Test task's Te.wtl, else any Te.wtl."""
    cands = [l for l in t['logs'] if l['name'].lower() == 'te.wtl']
    for l in cands:
        if l['task'] == 'Run Test':
            return l
    return cands[0] if cands else None


def previewable(name):
    """與 hlk_wtl.log_to_html 同規則: 這些副檔名能在瀏覽器內預覽。"""
    ext = os.path.splitext(name)[1].lower()
    return ext in hlk_wtl.TEXT_EXTS or ext in ('.wtl', '.html')


def test_row(i, t):
    run = t['rid'] is not None
    num = t['rstatus'] if run else t['tstatus']
    te = pick_te(t) if run else None
    return {
        'i': i, 'name': t['name'], 'run': run, 'status': num,
        'statusText': STATUS_TEXT.get(num, ''), 'features': list(t['features']),
        'machine': t['machine'], 'start': t['start'], 'end': t['end'],
        'te': te['log_id'] if te else None,
        'logs': [{'l': l['log_id'], 'name': l['name'], 'task': l['task'],
                  'size': l['size'], 'pv': previewable(l['name'])} for l in t['logs']],
    }


def close_pkg_later(pkg, delay=15.0):
    """延後釋放換檔/關檔的舊封裝：進行中的 /api/pkg（project 要解 telemetry）與
    /api/log 預覽可能在舊參照上跑數秒, 立即 close 會讓在途請求失敗。"""
    if pkg is None:
        return

    def _do():
        try:
            pkg.close()
        except Exception:
            pass
    t = threading.Timer(delay, _do)
    t.daemon = True
    t.start()


def loader_thread(path):
    global PKG
    global WTL
    try:
        cls = hlk_core.HlkProject if path.lower().endswith('.hlkp') else hlk_core.HlkPackage
        pkg = cls(path)
        with STATE_LOCK:
            old = PKG
            PKG = pkg
            WTL = None                           # 開封裝檔時退出 .wtl 單檔模式
            LOAD.update(state='ready', error='', path=path)
        if old is not None and old is not pkg:
            close_pkg_later(old)           # 換檔時延後釋放舊 zip/sqlite 句柄
    except Exception as e:
        with STATE_LOCK:
            LOAD.update(state='error', error='%s\n%s' % (e, __import__('traceback').format_exc()[:1500]))


def export_thread(pkg, items, outdir):
    global EXPORT_DIR
    try:
        def prog(i, n, nm):
            with STATE_LOCK:
                EXPORT.update(i=i, n=n, current=nm)

        n, errs, idx = hlk_wtl.export_logs(pkg, items, outdir, progress=prog)
        with STATE_LOCK:
            EXPORT_DIR = outdir          # 先指位再公開 done, 前端點索引連結不會落空
            EXPORT.update(state='done', i=n, n=len(items), current='',
                          result={'count': n, 'errors': errs[:20],
                                  'indexUrl': '/export/' + os.path.basename(idx)})
    except Exception as e:
        with STATE_LOCK:
            EXPORT_DIR = outdir
            EXPORT.update(state='error', error='%s' % e)


def _graceful_stop():
    """優雅關閉：先關封裝（釋放 uploads 檔鎖）→ 清上傳暫存 → 停 listen。"""
    global PKG, WTL
    with STATE_LOCK:
        pkg, PKG, WTL = PKG, None, None
        LOAD.update(state='idle', error='', path='')
    if pkg is not None:
        try:
            pkg.close()
        except Exception:
            pass
    sweep_uploads()
    if HTTPD is not None:
        HTTPD.shutdown()


# ---------------------------------------------------------------- http handler
def content_disposition(name):
    """attachment 的 Content-Disposition 值: 引號/控制字元一律過濾（log 名來自封裝內
    DB, 不可信）; 中文等非 ASCII 檔名另用 RFC 5987 filename* 帶出。"""
    fb = re.sub(r'[^\x20-\x7e]', '_', name).replace('"', '').strip() or 'download'
    try:
        name.encode('ascii')
    except UnicodeEncodeError:
        return "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (fb, quote(name, safe=''))
    return 'attachment; filename="%s"' % fb


class Handler(BaseHTTPRequestHandler):
    server_version = 'HLKViewer/' + VERSION
    protocol_version = 'HTTP/1.1'
    port = DEFAULT_PORT
    hub_origins = ('http://127.0.0.1:8700', 'http://localhost:8700')

    def log_message(self, fmt, *args):      # keep stdout clean (READY contract)
        pass

    # ---------------- helpers
    def _base_headers(self, status=200, ctype='application/json; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        return self

    def _frame_ancestors(self, extra_csp=''):
        ancestors = 'frame-ancestors ' + ' '.join(["'self'"] + list(self.hub_origins))
        self.send_header('Content-Security-Policy', (extra_csp + ancestors) if extra_csp else ancestors)

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self._base_headers(status)
        self._frame_ancestors()
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _send_err(self, code, message, status=400):
        # 錯誤回應後一律關連線: 未讀完的 body 殘留在 keep-alive 連線會錯序
        self.close_connection = True
        self._send_json({'ok': False, 'error': {'code': code, 'message': message,
                                                'detail': None}}, status)

    def _send_bytes(self, data, ctype, csp=None, download_name=None):
        self._base_headers(200, ctype)
        self._frame_ancestors(csp or CSP_PAGE)
        if download_name:
            self.send_header('Content-Disposition', content_disposition(download_name))
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def _host_ok(self):
        host = (self.headers.get('Host') or '').lower()
        return host in ('127.0.0.1:%d' % self.port, 'localhost:%d' % self.port)

    def _origin_ok(self):
        origin = (self.headers.get('Origin') or '').lower()
        if not origin:
            return True                      # same-origin form/non-browser call
        allowed = tuple('http://%s:%d' % (h, self.port) for h in ('127.0.0.1', 'localhost')) \
            + tuple(self.hub_origins)
        return origin in allowed

    # ---------------- GET
    def do_GET(self):
        if not self._host_ok():
            return self._send_err('BAD_HOST', 'Host 標頭不合法', 400)
        url = urlparse(self.path)
        path = url.path
        if path == '/api/health':
            return self._send_json({'ok': True, 'id': TOOL_ID, 'version': VERSION,
                                    'pid': os.getpid(), 'port': self.port,
                                    'uptimeSec': int(time.time() - STARTED_AT)})
        if path == '/api/pkg':
            with STATE_LOCK:
                state, err = LOAD['state'], LOAD['error']
                pkg = PKG
                wtl = dict(WTL) if WTL else None
            if state != 'ready' or (pkg is None and wtl is None):
                return self._send_json({'ok': True, 'result': {'state': state, 'error': err}})
            if wtl is not None and pkg is None:
                return self._send_json({'ok': True, 'result': {
                    'state': 'ready', 'kind': 'wtl', 'name': wtl['name'],
                    'path': wtl['path'], 'size': wtl['size']}})
            if getattr(pkg, 'KIND', '') == 'project':
                runs, _ = pkg.runs()
                errors, _ = pkg.errors()
                return self._send_json({'ok': True, 'result': {
                    'state': 'ready', 'kind': 'project', 'name': pkg.name,
                    'project': pkg.info['project'].get('name', ''),
                    'path': LOAD['path'], 'summary': pkg.summary(),
                    'info': pkg.info, 'runs': runs, 'errors': errors}})
            s = pkg.summary()
            return self._send_json({'ok': True, 'result': {
                'state': 'ready', 'kind': 'results', 'name': pkg.name,
                'project': pkg.project_name,
                'path': LOAD['path'], 'summary': s,
                'tests': [test_row(i, t) for i, t in enumerate(pkg.tests)]}})
        if path == '/api/log':
            return self._api_log(parse_qs(url.query))
        if path == '/api/wtl':
            return self._api_wtl(parse_qs(url.query))
        if path == '/api/browse':
            return self._api_browse(parse_qs(url.query))
        if path == '/api/chunks':
            return self._api_chunks()
        if path == '/api/pchunk':
            return self._api_pchunk(parse_qs(url.query))
        if path == '/api/export':
            with STATE_LOCK:
                job = dict(EXPORT)
                job['defaultOutdir'] = os.path.join(DATA_DIR, 'exports',
                                                    time.strftime('%Y%m%d'))
            return self._send_json({'ok': True, 'result': job})
        if path.startswith('/export/'):
            return self._export_file(unquote(path[len('/export/'):]))
        if path.startswith('/report/'):
            return self._report_file(unquote(path[len('/report/'):]))
        return self._static(path)

    do_HEAD = do_GET

    # ---------------- POST
    def do_POST(self):
        if urlparse(self.path).path == '/api/upload':
            return self._api_upload()      # raw body 上傳: 在 JSON 驗證前單獨處理
        # 先讀完 body 再做標頭驗證: 錯誤路徑若留下未讀的 body,
        # HTTP/1.1 keep-alive 連線的下一個請求會被錯序解析（對照 Key-Manager server.py）
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            return self._send_err('BAD_LENGTH', '內容長度不合法', 400)
        raw = self.rfile.read(length)
        if not self._host_ok():
            return self._send_err('BAD_HOST', 'Host 標頭不合法', 400)
        if self.headers.get('X-Toolbox-Request') != '1':
            return self._send_err('MISSING_TOOLBOX_HEADER', '缺少 X-Toolbox-Request 標頭', 403)
        if not self._origin_ok():
            return self._send_err('FORBIDDEN_ORIGIN', 'Origin 不接受', 403)
        ctype = (self.headers.get('Content-Type') or '').lower()
        if 'application/json' not in ctype:
            return self._send_err('BAD_CONTENT_TYPE', 'Content-Type 必須是 application/json', 400)
        try:
            body = json.loads(raw.decode('utf-8'))
        except Exception:
            return self._send_err('BAD_JSON', 'JSON 解析失敗', 400)
        path = urlparse(self.path).path
        if path == '/api/standalone-update':
            if self.managed:
                return self._send_err('MANAGED_BY_HUB', '請從 Hub 更新工具。', 403)
            return self._send_json(handle_update(Path(__file__).resolve().parent, body))
        if path == '/api/open':
            return self._api_open(body if isinstance(body, dict) else {})
        if path == '/api/close':
            global PKG, WTL
            with STATE_LOCK:
                if LOAD['state'] == 'loading' or EXPORT.get('state') == 'running':
                    return self._send_err('BUSY', '載入／匯出進行中', 409)
                old = PKG
                PKG = None
                WTL = None
                LOAD.update(state='idle', error='', path='')
            if old is not None:
                close_pkg_later(old)     # 延後釋放 zip/sqlite 句柄（在途請求不失敗）
            return self._send_json({'ok': True, 'result': {'state': 'idle'}})
        if path == '/api/export':
            return self._api_export(body if isinstance(body, dict) else {})
        if path == '/api/export-xlsx':
            return self._api_export_xlsx(body if isinstance(body, dict) else {})
        if path == '/api/shutdown':
            # Hub 的優雅關閉路徑（先回响应再停 serve_forever）
            self._send_json({'ok': True, 'result': {'stopping': True}})
            if HTTPD is not None:
                threading.Thread(target=_graceful_stop, daemon=True).start()
            return
        return self._send_err('NOT_FOUND', '未知的端點', 404)

    # ---------------- .hlkp Log 串流（streamdata chunks）
    def _project_only(self):
        with STATE_LOCK:
            pkg = PKG
        if pkg is None:
            self._send_err('NO_PKG', '尚未載入 HLK 檔案', 409)
            return None
        if getattr(pkg, 'KIND', '') != 'project':
            self._send_err('NO_PROJECT', '只有 .hlkp 專案檔提供 Log 串流（.hlkx 請由側項看 Log）', 409)
            return None
        return pkg

    def _api_chunks(self):
        pkg = self._project_only()
        if pkg is None:
            return
        try:
            cs = pkg.chunks()
        except ValueError as e:
            return self._send_err('NO_STREAM', str(e), 409)
        except Exception as e:
            return self._send_err('CHUNK_SCAN_FAILED', '掃描 Log 串流失敗：%s' % e, 500)
        return self._send_json({'ok': True, 'result': {'chunks': cs}})

    def _api_pchunk(self, q):
        pkg = self._project_only()
        if pkg is None:
            return
        try:
            cid = int(q['c'][0])
        except (KeyError, IndexError, ValueError):
            return self._send_err('BAD_ARGS', '缺少 chunk id（?c=）', 400)
        try:
            data = pkg.read_chunk(cid)
        except Exception as e:
            return self._send_err('CHUNK_READ_FAILED', '讀取 chunk 失敗：%s' % e, 500)
        if data is None:
            return self._send_err('NO_CHUNK', '找不到指定的 Log chunk', 404)
        try:
            meta = next((c for c in pkg.chunks() if c['id'] == cid), {'kind': 'other'})
        except Exception:
            meta = {'kind': 'other'}            # 關檔 race: 不影響預覽, 只是少個類型標註
        if (q.get('dl', [''])[0] or '') == '1':      # 原始檔（.wtl/.xml/.bin）
            ext = {'wtl': '.wtl', 'comm': '.xml'}.get(meta.get('kind'), '.bin')
            return self._send_bytes(data, 'application/octet-stream', csp=CSP_VIEW,
                                    download_name='chunk-%d%s' % (cid, ext))
        title = 'Log chunk %d（%s）' % (cid, meta.get('kind', 'other'))
        try:
            if meta.get('kind') == 'wtl':
                ext, out = hlk_wtl.log_to_html('chunk-%d.wtl' % cid, data)
                if ext != '.html':
                    text = hlk_wtl.decode_any(data)  # 保險: .wtl 理論上恆轉 HTML
                    out = hlk_wtl.pre_html(title, text).encode('utf-8')
            else:
                out = hlk_wtl.pre_html(title, hlk_wtl.decode_any(data)).encode('utf-8')
        except Exception as e:
            return self._send_err('CHUNK_CONVERT_FAILED', '轉換 chunk 失敗：%s' % e, 500)
        if (q.get('dl', [''])[0] or '') == 'htm':    # 轉換後的 .htm（同單筆 Log 下載）
            return self._send_bytes(out, 'text/html; charset=utf-8', csp=CSP_VIEW,
                                    download_name='chunk-%d.htm' % cid)
        return self._send_bytes(out, 'text/html; charset=utf-8', csp=CSP_VIEW)

    # ---------------- endpoints
    def _api_open(self, body):
        global LOAD, WTL, PKG
        path = str(body.get('path') or '').strip().strip('"')
        if not path:
            return self._send_err('BAD_ARGS', '缺少 path', 400)
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            return self._send_err('NO_SUCH_FILE', '檔案不存在：%s' % path, 404)
        if not path.lower().endswith(OPEN_EXTS):
            return self._send_err('BAD_EXT', '請選擇 .hlk/.hlkx/.hlkp/.wtl 檔案', 400)
        if path.lower().endswith('.wtl'):        # 獨立 .wtl: 單檔模式, 不需背景載入
            try:
                size = os.path.getsize(path)
            except OSError as e:
                return self._send_err('NO_SUCH_FILE', '檔案不存在：%s' % e, 404)
            with STATE_LOCK:
                if LOAD['state'] == 'loading' or EXPORT.get('state') == 'running':
                    return self._send_err('BUSY', '載入／匯出進行中，請稍後', 409)
                old = PKG
                PKG = None
                WTL = {'path': path, 'name': os.path.basename(path), 'size': size}
                LOAD.update(state='ready', error='', path=path)
            if old is not None:
                close_pkg_later(old)
            return self._send_json({'ok': True, 'result': {'state': 'ready'}})
        with STATE_LOCK:
            if LOAD['state'] == 'loading' or EXPORT.get('state') == 'running':
                return self._send_err('BUSY', '載入／匯出進行中，請稍後', 409)
            WTL = None                    # 開封裝檔即退出 .wtl 單檔模式（載入失敗也不回復）
            LOAD.update(state='loading', error='', path=path)
        threading.Thread(target=loader_thread, args=(path,), daemon=True).start()
        return self._send_json({'ok': True, 'result': {'state': 'loading'}})

    def _api_wtl(self, q):
        """獨立 .wtl 單檔模式: 目前開啟的 .wtl 轉 Complete Report（dl=1 下載 .htm）"""
        with STATE_LOCK:
            wtl = dict(WTL) if WTL else None
        if wtl is None:
            return self._send_err('NO_WTL', '尚未載入 .wtl 檔案', 409)
        if wtl['size'] > WTL_PREVIEW_MAX:       # 轉換要吃進整份記憶體, 過大檔改請用 GUI
            return self._send_err('WTL_TOO_LARGE', '檔案超過預覽上限（%d MB），請改用 GUI「獨立 .wtl 轉單頁 .htm」'
                                  % (WTL_PREVIEW_MAX // (1024 * 1024)), 413)
        try:
            with open(wtl['path'], 'rb') as f:
                data = f.read()
            ext, out = hlk_wtl.log_to_html(wtl['name'], data)
            if ext != '.html':                   # 保險: 非 .wtl 副檔名理論不會走到這
                out = hlk_wtl.pre_html(wtl['name'], hlk_wtl.decode_any(data)).encode('utf-8')
        except OSError as e:                     # 檔案中途被移走/換掉
            return self._send_err('WTL_READ_FAILED', '讀取 .wtl 失敗：%s' % e, 500)
        except Exception as e:
            return self._send_err('WTL_CONVERT_FAILED', '轉換 .wtl 失敗：%s' % e, 500)
        dl_name = None
        if (q.get('dl', [''])[0] or '') == '1':
            dl_name = os.path.splitext(wtl['name'])[0] + '.htm'
        return self._send_bytes(out, 'text/html; charset=utf-8', csp=CSP_VIEW,
                                download_name=dl_name)

    def _api_log(self, q):
        dl = (q.get('dl', [''])[0] or '') == '1'    # dl=1: 下載轉換後的 .htm（非原始檔）
        with STATE_LOCK:
            pkg = PKG
        if pkg is None:
            return self._send_err('NO_PKG', '尚未載入 HLK 檔案', 409)
        if getattr(pkg, 'KIND', '') == 'project':
            return self._send_err('NO_LOGS', '.hlkp 專案檔不含逐項測試 log（結果在 HLK Controller 端）', 409)
        try:
            i = int(q['i'][0]); lid = int(q['l'][0])
            t = pkg.tests[i]
            log = next(l for l in t['logs'] if l['log_id'] == lid)
        except (KeyError, IndexError, StopIteration, ValueError):
            return self._send_err('BAD_ARGS', '找不到指定的 log', 404)
        try:
            data = pkg.read_log(lid)
            ext, out = hlk_wtl.log_to_html(log['name'], data)
        except Exception as e:            # 例如檔案中途被換掉/關閉
            return self._send_err('LOG_READ_FAILED', '讀取 log 失敗：%s' % e, 500)
        title = '%s / %s' % (t['name'], log['name'])
        # 下載檔名: 側項名稱 - log 主檔名.htm（中文由 RFC 5987 filename* 帶出）
        stem = os.path.splitext(os.path.basename(log['name']))[0]
        dl_name = '%s - %s.htm' % (re.sub(r'[<>:"/\\|?*]', '_', t['name']), stem) if dl else None
        if ext == '.html':
            return self._send_bytes(out, 'text/html; charset=utf-8', csp=CSP_VIEW,
                                    download_name=dl_name)
        if ext in hlk_wtl.TEXT_EXTS or ext == '':
            text = hlk_wtl.decode_any(out if ext else data)
            html = hlk_wtl.pre_html(title, text).encode('utf-8')
            return self._send_bytes(html, 'text/html; charset=utf-8', csp=CSP_VIEW,
                                    download_name=dl_name)
        # binary log: offer as download instead of preview
        safe = re.sub(r'[^A-Za-z0-9._-]', '_', log['name']) or 'log.bin'
        return self._send_bytes(data, 'application/octet-stream', csp=CSP_VIEW,
                                download_name=safe)

    def _api_export(self, body):
        global EXPORT
        with STATE_LOCK:
            pkg = PKG
            if LOAD['state'] != 'ready' or pkg is None:
                return self._send_err('NO_PKG', '請先載入 HLK 檔案', 409)
            if getattr(pkg, 'KIND', '') == 'project':
                return self._send_err('NO_LOGS', '.hlkp 專案檔不含可匯出的測試 log（結果在 HLK Controller 端）', 409)
            if EXPORT.get('state') == 'running':
                return self._send_err('BUSY', '匯出進行中', 409)
        mode = str(body.get('mode') or 'te')
        if mode not in ('te', 'all'):
            return self._send_err('BAD_ARGS', 'mode 必須是 te 或 all', 400)
        raw = body.get('items')
        if not isinstance(raw, list) or not raw:
            return self._send_err('BAD_ARGS', 'items 為空的（請勾選要匯出的項目）', 400)
        if len(raw) > 2000:
            return self._send_err('BAD_ARGS', '項目過多（上限 2000 筆）', 400)
        items = []
        for it in raw:
            try:
                i = int(it['i']); lid = int(it['l'])
                t = pkg.tests[i]
                log = next(l for l in t['logs'] if l['log_id'] == lid)
            except (KeyError, TypeError, IndexError, StopIteration, ValueError):
                return self._send_err('BAD_ARGS', 'items 含無法解析的項目', 400)
            ent = {'test_name': t['name'], 'test_status': t['rstatus'],
                   'log_name': log['name'], 'log_id': log['log_id'], 'task': log['task']}
            if mode == 'te':
                ent['out_name'] = t['name']
                ent['out_ext'] = '.htm'
            items.append(ent)
        outdir = str(body.get('outdir') or '').strip().strip('"')
        outdir = os.path.abspath(outdir) if outdir else default_export_dir()
        with STATE_LOCK:
            # 取鎖後再檢查一次並占位, 避免兩個並發 POST 都通過前面的檢查
            if EXPORT.get('state') == 'running':
                return self._send_err('BUSY', '匯出進行中', 409)
            EXPORT.clear()
            EXPORT.update(state='running', mode=mode, i=0, n=len(items),
                          current='', outdir=outdir, result=None, error='')
        try:
            threading.Thread(target=export_thread, args=(pkg, items, outdir), daemon=True).start()
        except Exception as e:            # 執行緒資源耗盡等極端情況: 不讓 EXPORT 永久卡 running
            with STATE_LOCK:
                EXPORT.update(state='error', error='無法啟動匯出執行緒：%s' % e)
            return self._send_err('START_FAILED', '無法啟動匯出執行緒：%s' % e, 500)
        return self._send_json({'ok': True, 'result': {'state': 'running',
                                                       'outdir': outdir,
                                                       'n': len(items)}})

    def _api_export_xlsx(self, body):
        """側項結果 Excel（對照 GUI「匯出側項結果 Excel」）: 依用戶端传来的可見側項順序
        （tests, 篩選在用戶端做）產生 .xlsx 到 reports\\<日期> 目錄, 回 /report/ 連結
        （不覆寫 EXPORT_DIR, 免得 HTML 匯出 job 的 /export/ 連結錯指向）。"""
        global REPORT_DIR
        with STATE_LOCK:
            pkg = PKG
            if LOAD['state'] != 'ready' or pkg is None:
                return self._send_err('NO_PKG', '請先載入 HLK 檔案', 409)
            if getattr(pkg, 'KIND', '') == 'project':
                return self._send_err('NO_LOGS', '.hlkp 專案檔無側項結果清單', 409)
        raw = body.get('tests')
        if raw is None:
            idxs = list(range(len(pkg.tests)))
        elif isinstance(raw, list):
            idxs = []
            for v in raw:
                try:
                    i = int(v)
                except (TypeError, ValueError):
                    return self._send_err('BAD_ARGS', 'tests 含無法解析的索引', 400)
                if 0 <= i < len(pkg.tests):
                    idxs.append(i)
            if not idxs:
                return self._send_err('BAD_ARGS', '目前篩選條件下沒有側項', 400)
        else:
            return self._send_err('BAD_ARGS', 'tests 必須是側項索引清單', 400)
        if len(idxs) > 20000:
            return self._send_err('BAD_ARGS', '項目過多（上限 20000 列）', 400)
        try:
            s = pkg.summary()
            info = {'source': pkg.name, 'project': pkg.project_name, 'total': s['total'],
                    'run': s['run'], 'pass': s['pass'], 'fail': s['fail'], 'notrun': s['notrun']}
            data = []
            for i in idxs:
                t = pkg.tests[i]
                run = t['rid'] is not None
                st = STATUS_TEXT.get(t['rstatus'] if run else t['tstatus'], '')
                data.append((st, t['name'], ', '.join(t['features']), t['machine'],
                             t['start'], t['end'], len(t['logs'])))
            outdir = default_report_dir()
            os.makedirs(outdir, exist_ok=True)
            base = re.sub(r'[<>:"/\\|?*]', '_',
                          pkg.project_name or pkg.name or 'HLK') + '_側項結果'
            fname = base + '.xlsx'             # 同日重複匯出: 加 -1/-2 後綴, 不靜默覆寫
            k = 0
            while os.path.exists(os.path.join(outdir, fname)) and k < 999:
                k += 1
                fname = '%s-%d.xlsx' % (base, k)
            hlk_xlsx.write_results_xlsx(os.path.join(outdir, fname), info, data)
        except OSError as e:
            return self._send_err('EXPORT_WRITE_FAILED',
                                  '寫入失敗（資料夾權限或磁碟空間）：%s' % e, 500)
        except Exception as e:
            return self._send_err('EXPORT_FAILED', '產生 Excel 失敗：%s' % e, 500)
        with STATE_LOCK:
            REPORT_DIR = outdir
        return self._send_json({'ok': True, 'result': {
            'file': fname, 'path': os.path.join(outdir, fname),
            'url': '/report/' + quote(fname), 'count': len(data)}})

    # ---------------- 檔案選取 / 拖曳上傳
    @staticmethod
    def _drive_roots():
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return ['%s:\\' % chr(ord('A') + i) for i in range(26) if (mask >> i) & 1]

    def _api_browse(self, q):
        """檔案選取視窗用（ui-kit tb-dirpicker 格式）: 列舉目錄 + .hlk/.hlkx/.hlkp/.wtl 檔;
        path='' 回磁碟機清單。回傳 {current, parent, items:[{name,path,hasGit,isFile?}], truncated}。"""
        raw = (q.get('path') or [''])[0]
        if not raw:
            items = [{'name': d, 'path': d, 'hasGit': False} for d in self._drive_roots()]
            return self._send_json({'ok': True, 'result': {
                'current': '', 'parent': None, 'items': items, 'truncated': False}})
        p = os.path.abspath(raw)
        if os.path.isfile(p):               # 路徑欄給的是檔案 -> 列舉其所在資料夾
            p = os.path.dirname(p)
        if not os.path.isdir(p):
            return self._send_err('NO_SUCH_DIR', '資料夾不存在：%s' % p, 404)
        try:
            entries = sorted(os.scandir(p), key=lambda e: e.name.lower())
        except OSError as exc:
            return self._send_err('DIR_DENIED', '無法列出資料夾：%s'
                                  % getattr(exc, 'strerror', exc), 403)
        items, truncated = [], False
        n_dirs = n_files = 0
        for e in entries:
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:                   # 權限/無效 reparse point: 跳過單項
                continue
            if is_dir:
                if n_dirs < BROWSE_CAP:
                    n_dirs += 1
                    items.append({'name': e.name, 'path': os.path.join(p, e.name),
                                  'hasGit': os.path.exists(os.path.join(p, e.name, '.git'))})
                else:
                    truncated = True
            elif e.name.lower().endswith(OPEN_EXTS):
                if n_files < BROWSE_CAP:
                    n_files += 1
                    items.append({'name': e.name, 'path': os.path.join(p, e.name),
                                  'hasGit': False, 'isFile': True})
                else:
                    truncated = True
        parent = os.path.dirname(p)
        if parent == p:                       # 磁碟機/共用根 -> 磁碟機清單
            parent = ''
        return self._send_json({'ok': True, 'result': {
            'current': p, 'parent': parent, 'items': items, 'truncated': truncated}})

    def _api_upload(self):
        """拖曳上傳: 瀏覽器拿不到完整路徑, 改為把檔案內容存到 dataDir/uploads 再開啟。"""
        if not self._host_ok():
            return self._send_err('BAD_HOST', 'Host 標頭不合法', 400)
        if self.headers.get('X-Toolbox-Request') != '1':
            return self._send_err('MISSING_TOOLBOX_HEADER', '缺少 X-Toolbox-Request 標頭', 403)
        if not self._origin_ok():
            return self._send_err('FORBIDDEN_ORIGIN', 'Origin 不接受', 403)
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return self._send_err('BAD_LENGTH', '上傳內容長度不合法', 400)
        if length > UPLOAD_MAX:
            return self._send_err('TOO_LARGE', '檔案過大（上限 %d MB）'
                                  % (UPLOAD_MAX // (1024 * 1024)), 413)
        name = unquote(self.headers.get('X-Filename') or '')
        name = os.path.basename(name.replace('\\', '/'))
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')
        ext = os.path.splitext(name)[1].lower()
        if ext not in OPEN_EXTS:
            return self._send_err('BAD_EXT', '僅接受 .hlk/.hlkx/.hlkp/.wtl 檔案', 400)
        if re.match(r'^(con|prn|aux|nul|com\d|lpt\d)(\.|$)', name, re.I):
            name = '_' + name                 # Windows 保留裝置名: 加底線前綴（比照 _export_file）
        if len(name) > 180:
            name = name[:180 - len(ext)] + ext
        up_dir = os.path.join(DATA_DIR, 'uploads')
        try:
            os.makedirs(up_dir, exist_ok=True)
        except OSError as exc:
            return self._send_err('SAVE_FAILED', '無法建立 uploads 資料夾：%s'
                                  % getattr(exc, 'strerror', exc), 500)
        stem = os.path.splitext(name)[0]
        dest, n = os.path.join(up_dir, name), 1
        while os.path.exists(dest):           # 同名不覆蓋: name-1.hlkx …
            dest = os.path.join(up_dir, '%s-%d%s' % (stem, n, ext))
            n += 1
        # 暫存檔名帶隨機後綴: 並發上傳同檔名時不會寫進同一 .part
        try:
            fd, part = tempfile.mkstemp(dir=up_dir, prefix=name + '.', suffix='.part')
            os.close(fd)
        except OSError as exc:
            return self._send_err('SAVE_FAILED', '無法建立暫存檔：%s'
                                  % getattr(exc, 'strerror', exc), 500)
        got = 0
        try:
            with open(part, 'wb') as out:
                while got < length:
                    chunk = self.rfile.read(min(1 << 20, length - got))
                    if not chunk:
                        break
                    out.write(chunk)
                    got += len(chunk)
            if got != length:                 # 連線中斷: 不留下半截檔案
                try:
                    os.remove(part)
                except OSError:
                    pass
                return self._send_err('PARTIAL', '上傳中斷（%d/%d bytes）' % (got, length), 400)
            os.replace(part, dest)
        except OSError as exc:
            try:
                os.remove(part)
            except OSError:
                pass
            return self._send_err('SAVE_FAILED', '儲存失敗：%s' % getattr(exc, 'strerror', exc), 500)
        return self._send_json({'ok': True, 'result': {'path': dest, 'size': got}})

    # ---------------- static
    def _export_file(self, name):
        with STATE_LOCK:
            d = EXPORT_DIR
        return self._serve_in_dir(d, name)

    def _report_file(self, name):
        with STATE_LOCK:
            d = REPORT_DIR
        return self._serve_in_dir(d, name)

    def _serve_in_dir(self, d, name):
        if (not d or not name or '/' in name or '\\' in name or ':' in name
                or name.startswith('.')
                or re.match(r'^(con|prn|aux|nul|com\d|lpt\d)(\.|$)', name, re.I)):
            return self._send_err('NOT_FOUND', '找不到檔案', 404)
        fp = os.path.join(d, name)
        base = os.path.normcase(os.path.realpath(d)) + os.sep
        if not os.path.normcase(os.path.realpath(fp)).startswith(base):
            return self._send_err('NOT_FOUND', '找不到檔案', 404)
        if not os.path.isfile(fp):
            return self._send_err('NOT_FOUND', '找不到檔案', 404)
        ext = os.path.splitext(name)[1].lower()
        ctype = {'.html': 'text/html; charset=utf-8', '.htm': 'text/html; charset=utf-8',
                 '.txt': 'text/plain; charset=utf-8', '.log': 'text/plain; charset=utf-8',
                 '.css': 'text/css; charset=utf-8'}.get(ext, 'application/octet-stream')
        with open(fp, 'rb') as f:
            self._send_bytes(f.read(), ctype, csp=CSP_VIEW if ext in ('.html', '.htm') else None)

    def _static(self, path):
        fn = UI_FILES.get(path)
        if not fn:
            return self._send_err('NOT_FOUND', '找不到頁面', 404)
        fp = os.path.join(UI_DIR, fn)
        if not os.path.isfile(fp):
            return self._send_err('MISSING_UI', 'ui/ 靜態檔缺失：%s' % fn, 500)
        ctype = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
                 '.css': 'text/css; charset=utf-8'}.get(os.path.splitext(fn)[1], 'text/plain')
        csp = CSP_PAGE if fn.endswith('.html') else None
        with open(fp, 'rb') as f:
            self._send_bytes(f.read(), ctype, csp=csp)


# ---------------------------------------------------------------- lifecycle
def _parent_alive(pid):
    STILL_ACTIVE = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)     # QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def watch_parent(pid):
    while True:
        time.sleep(1.0)
        if not _parent_alive(pid):
            print('Parent process exited, closing.', flush=True)
            sweep_uploads()                  # 父程序消失也要清上傳暫存（删不掉的跳過）
            os._exit(0)


def resolve_data_dir(override):
    # 優先序：--data-dir > DEVTOOLBOX_DATA\<id> > %LOCALAPPDATA%\DevToolbox\hlk-viewer
    if override:
        d = override
    elif os.environ.get('DEVTOOLBOX_DATA'):
        d = os.path.join(os.environ['DEVTOOLBOX_DATA'], TOOL_ID)
    else:
        d = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
                         'DevToolbox', TOOL_ID)
    os.makedirs(d, exist_ok=True)
    return d


def main(argv=None):
    global DATA_DIR, HTTPD
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description='HLK Viewer local web server (127.0.0.1 only)')
    ap.add_argument('--port', type=int, default=DEFAULT_PORT)
    ap.add_argument('--open-browser', action='store_true')
    ap.add_argument('--parent-pid', type=int, default=0)
    ap.add_argument('--data-dir', default=None)
    ap.add_argument('--hub-origin', default=None)
    args = ap.parse_args(argv)
    port_explicit = any(a == '--port' or a.startswith('--port=') for a in argv)

    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    DATA_DIR = resolve_data_dir(args.data_dir)
    sweep_uploads()                          # 收掉上次執行殘留的上傳暫存檔
    if args.parent_pid > 0 and not _parent_alive(args.parent_pid):
        print('parent process %d not running, exiting' % args.parent_pid, file=sys.stderr)
        return 1

    candidates = [args.port] if port_explicit else \
        list(range(args.port, args.port + MAX_PORT_SCAN + 1)) + [0]
    httpd = None
    last_error = None
    for port in candidates:
        try:
            httpd = ThreadingHTTPServer(('127.0.0.1', port), Handler)
            break
        except OSError as exc:
            last_error = exc
    if httpd is None:
        print('無法監聽 127.0.0.1:%s（%s）' % (args.port, last_error), file=sys.stderr)
        return 5

    Handler.port = httpd.server_address[1]
    HTTPD = httpd
    Handler.managed = bool(args.parent_pid)
    if args.hub_origin:
        m = re.match(r'^http://(127\.0\.0\.1|localhost):(\d{1,5})$', args.hub_origin.strip().lower())
        if m:
            Handler.hub_origins = ('http://127.0.0.1:%s' % m.group(2),
                                   'http://localhost:%s' % m.group(2))
    httpd.daemon_threads = True

    url = 'http://127.0.0.1:%d' % Handler.port
    print('READY %s' % url, flush=True)
    if args.open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url + '/')).start()
    if args.parent_pid > 0:
        threading.Thread(target=watch_parent, args=(args.parent_pid,), daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sweep_uploads()                      # Ctrl+C 退出也清上傳暫存
    return 0


if __name__ == '__main__':
    sys.exit(main())
