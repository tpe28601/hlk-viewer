# -*- coding: utf-8 -*-
"""HLK .hlk/.hlkx 離線結果封裝解析（OPC/ZIP + SQLite）與 .hlkp 專案檔解析。

封裝結構:
  _rels/.rels                 關係檔, 指向 PackageInfo / coredata / streamdata
  hck/data/PackageInfo.xml    專案名稱、TestRollup (Passed/Failed/NotRun)
  coredata  (SQLite)          Test / Result / Task / Log / Stream / Relationship
  streamdata(SQLite)          Chunk(Id, Data) = log 檔的位元組內容(.wtl 為 UTF-16 XML)

狀態碼（已與 PackageInfo 的 TestRollup 交叉驗證）:
  Status: 0=未執行, 1=Pass, 2=Fail

.hlkp（HLK Studio 專案檔, 見 HlkProject）: 同為 OPC 容器, 但測試結果存在
HLK Controller 端, 封裝內只有 PackageInfo + hck/telemetry/*.txt 遙測。
"""

import bisect
import datetime
import json
import os
import re
import sqlite3
import hashlib
import tempfile
import threading
import zipfile
from xml.etree import ElementTree as ET

SQLITE_MAGIC = b'SQLite format 3\x00'

STATUS_TEXT = {0: '未執行', 1: 'PASS', 2: 'FAIL'}


def _fmt_time(s):
    """'2027-11-06T16:21:21.2500000+08:00' -> '2027-11-06 16:21:21'"""
    if not s:
        return ''
    m = re.match(r'(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})', s)
    return (m.group(1) + ' ' + m.group(2)) if m else s


def _cache_dir_for(path):
    """依 path|size|mtime 產生可重用的解壓縮快取目錄（.hlkx coredata / .hlkp streamdata 共用）。"""
    st = os.stat(path)
    key = hashlib.sha1(('%s|%d|%d' % (path, st.st_size, int(st.st_mtime))).encode('utf-8')).hexdigest()[:16]
    d = os.path.join(tempfile.gettempdir(), 'HLK_Viewer_Cache', key)
    os.makedirs(d, exist_ok=True)
    return d


class HlkPackage(object):
    """載入一个 .hlk/.hlkx 檔, 提供側項(測試)清單、log 清單與 log 內容讀取。"""

    def __init__(self, path, progress=None):
        self.path = path
        self.name = os.path.basename(path)
        self.project_name = ''
        self.rollup = {}          # {'Passed':..,'Failed':..,'NotRun':..}
        self.targets = []         # [(name, type)]
        self.tests = []           # [{test_id, name, tstatus, cls, desc, rid, rstatus, start, end, machine, features:[..], logs:[..]}]
        self._progress = progress or (lambda s: None)

        zf = zipfile.ZipFile(path)
        self._zip = zf
        rels = self._parse_rels(zf)

        self._parse_packageinfo(rels)

        cache = self._cache_dir()
        core_path = self._extract_sqlite(rels, 'coredata', cache, 'coredata.db')
        stream_path = self._extract_sqlite(rels, 'streamdata', cache, 'streamdata.db')
        # check_same_thread=False：匯出/預覽在背景執行緒讀 log
        self._core = sqlite3.connect(core_path, check_same_thread=False)
        self._core.row_factory = sqlite3.Row
        self._stream = sqlite3.connect(stream_path, check_same_thread=False)
        self._lock = threading.Lock()
        try:
            self._build_model()
        except Exception:
            self.close()                       # 開檔失敗不要泄漏 zip/sqlite 句柄（Windows 檔鎖）
            raise

    # ------------------------------------------------------------------ 載入
    def _cache_dir(self):
        return _cache_dir_for(self.path)

    @staticmethod
    def _parse_rels(zf):
        root = ET.fromstring(zf.read('_rels/.rels'))
        ns = '{http://schemas.openxmlformats.org/package/2006/relationships}'
        return [(r.get('Type'), r.get('Target')) for r in root.findall(ns + 'Relationship')]

    @staticmethod
    def _find_members(rels, kind):
        out = []
        for typ, target in rels:
            if typ.rstrip('/').endswith(kind):
                out.append(target.replace('\\', '/').lstrip('/'))
        return out

    def _parse_packageinfo(self, rels):
        members = self._find_members(rels, 'packageinfo')
        if not members:
            return
        try:
            root = ET.fromstring(self._zip.read(members[0]))
        except Exception:
            return
        # PackageInfo 可能自訂命名空間, 子節點需一併加上
        ns = root.tag[:root.tag.rfind('}') + 1] if root.tag.startswith('{') else ''
        proj = root.find(ns + 'Project')
        if proj is not None:
            self.project_name = proj.get('Name', '')
            for t in proj.iter(ns + 'Target'):
                self.targets.append((t.get('Name', ''), t.get('TargetType', '')))
        roll = proj.find(ns + 'TestRollup') if proj is not None else None
        if roll is not None:
            self.rollup = {k: int(roll.get(k, 0)) for k in ('Passed', 'Failed', 'NotRun')}

    def _extract_sqlite(self, rels, kind, cache, fname):
        """從封裝解出指定角色的 SQLite 檔 (coredata 有 2010/2022 兩種, 取 SQLite 那份)。"""
        dest = os.path.join(cache, fname)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            return dest
        cand = self._find_members(rels, kind)
        # 沒有 rels 時退回掃描
        if not cand:
            cand = [n for n in self._zip.namelist() if n.startswith('hck/data/') and '-' in os.path.basename(n)]
        for member in cand:
            with self._zip.open(member) as f:
                magic = f.read(16)
            if magic != SQLITE_MAGIC:
                continue
            self._progress('解壓縮 %s …（檔較大，約需數秒）' % kind)
            tmp = dest + '.tmp'
            with self._zip.open(member) as src, open(tmp, 'wb') as dst:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    dst.write(chunk)
            os.replace(tmp, dest)
            return dest
        raise ValueError('封裝中找不到 %s 的 SQLite 資料庫' % kind)

    # ------------------------------------------------------------------ 模型
    def _build_model(self):
        c = self._core
        tests = {}
        try:
            cur = c.execute('SELECT Id, Name, Status, TestClassification, Description, IsDeactivated FROM Test')
            rows = cur.fetchall()
        except sqlite3.OperationalError:
            raise ValueError('封裝的 coredata 沒有 Test 表：這可能是 .hlkp 專案檔, '
                             '請改用 .hlkp 副檔名開啟')
        for r in rows:
            tests[r['Id']] = {
                'test_id': r['Id'], 'name': r['Name'],
                'tstatus': int(r['Status'] or 0),
                'cls': r['TestClassification'] or '', 'desc': r['Description'] or '',
                'rid': None, 'rstatus': None, 'start': '', 'end': '',
                'machine': '', 'features': [], 'logs': [],
            }
        # 每次執行(Result) 對應到測試；同一測試有多次執行時保留最新一次
        runs = {}
        for r in c.execute("""
            SELECT r.Id rid, r.Status rstatus, r.StartTime, r.CompletionTime, rel.Parent test_id
            FROM Result r JOIN Relationship rel
              ON rel.Child=r.Id AND rel.ChildType='PackageTestResult' AND rel.ParentType='PackageTest'"""):
            t = tests.get(r['test_id'])
            if t is None:
                continue
            runs[r['rid']] = r['test_id']
            if t['rid'] is None or (r['StartTime'] or '') >= (t.get('start_raw') or ''):
                t['rid'] = r['rid']
                t['rstatus'] = int(r['rstatus'])
                t['start_raw'] = r['StartTime']
                t['start'] = _fmt_time(r['StartTime'])
                t['end'] = _fmt_time(r['CompletionTime'])
        # 機器
        for r in c.execute("""
            SELECT rel.Parent rid, m.Name FROM Relationship rel JOIN Machine m ON m.Id=rel.Child
            WHERE rel.ChildType='PackageMachine' AND rel.ParentType='PackageTestResult'"""):
            tid = runs.get(r['rid'])
            if tid is not None and tests[tid]['rid'] == r['rid']:
                tests[tid]['machine'] = r['Name']
        # 功能(Feature)
        for r in c.execute("""
            SELECT rel.Parent test_id, f.FullName FROM Relationship rel JOIN Feature f ON f.Id=rel.Child
            WHERE rel.ChildType='PackageFeature' AND rel.ParentType='PackageTest'"""):
            tests[r['test_id']]['features'].append(r['FullName'])
        # log: 直接掛在 Result 或掛在 Result 的 Task 上（雙向關係都取）
        sql = """
        SELECT x.rid, x.logid, x.taskname, l.Name lname,
               (SELECT COALESCE(SUM(st.Length),0) FROM Relationship sr JOIN Stream st
                  ON st.Id=sr.Child WHERE sr.Parent=l.Id
                  AND sr.ChildType='Stream' AND sr.ParentType='PackageTestLog') size
        FROM (
          SELECT rel.Parent rid, rel.Child logid, '' taskname FROM Relationship rel
           WHERE rel.ChildType='PackageTestLog' AND rel.ParentType='PackageTestResult'
          UNION
          SELECT rp.Parent rid, tl.Child logid, tk.Name taskname FROM Relationship tl
            JOIN Relationship rp ON rp.Child=tl.Parent
              AND rp.ChildType='PackageTask' AND rp.ParentType='PackageTestResult'
            JOIN Task tk ON tk.Id=tl.Parent
           WHERE tl.ChildType='PackageTestLog' AND tl.ParentType='PackageTask'
          UNION
          SELECT rp.Child rid, tl.Child logid, tk.Name taskname FROM Relationship tl
            JOIN Relationship rp ON rp.Parent=tl.Parent
              AND rp.ChildType='PackageTestResult' AND rp.ParentType='PackageTask'
            JOIN Task tk ON tk.Id=tl.Parent
           WHERE tl.ChildType='PackageTestLog' AND tl.ParentType='PackageTask'
        ) x JOIN Log l ON l.Id=x.logid"""
        for r in c.execute(sql):
            tid = runs.get(r['rid'])
            if tid is None:
                continue
            t = tests[tid]
            if t['rid'] != r['rid']:
                continue
            t['logs'].append({'log_id': r['logid'], 'name': r['lname'],
                              'task': r['taskname'] or '', 'size': r['size'] or 0})
        # 排序
        for t in tests.values():
            t['logs'].sort(key=lambda g: (g['task'], g['name']))
        self.tests = sorted(tests.values(), key=lambda t: (t['name'] or '').lower())

    # ------------------------------------------------------------------ log
    def close(self):
        """釋放 zip 檔句柄與兩個 SQLite 連線（Web 模式重複開/關檔用）。
        db.close() 需與 read_log 互斥, 否則進行中的預覽會操作到已關閉的連線。"""
        with self._lock:
            for db in (self._core, self._stream):
                try:
                    db.close()
                except Exception:
                    pass
        try:
            self._zip.close()
        except Exception:
            pass

    def read_log(self, log_id):
        """讀出 log 的原始位元組（.wtl 為 UTF-16 XML）。可在背景執行緒呼叫。"""
        data = b''
        with self._lock:
            rows = self._core.execute(
                """SELECT sm.Position, sm.ChunkId FROM Relationship rel JOIN StreamMapping sm
                     ON sm.StreamId=rel.Child
                   WHERE rel.Parent=? AND rel.ChildType='Stream' AND rel.ParentType='PackageTestLog'
                   ORDER BY sm.Position""", (log_id,)).fetchall()
            for r in rows:
                blob = self._stream.execute('SELECT Data FROM Chunk WHERE Id=?', (r['ChunkId'],)).fetchone()
                if blob and blob[0]:
                    data += blob[0]
        return data

    def summary(self):
        n_all = len(self.tests)
        runs = [t for t in self.tests if t['rid'] is not None]
        npass = sum(1 for t in runs if t['rstatus'] == 1)
        nfail = sum(1 for t in runs if t['rstatus'] == 2)
        return {'total': n_all, 'run': len(runs), 'pass': npass, 'fail': nfail,
                'notrun': n_all - len(runs),
                'nlogs': sum(len(t['logs']) for t in runs)}


# ---------------------------------------------------------------------- .hlkp
_DOTNET_EPOCH = datetime.datetime(1, 1, 1)


def _ticks_to_time(ts):
    """.NET DateTime ticks（epoch 0001-01-01, 控制端記錄的原生時間）-> 'YYYY-MM-DD HH:MM:SS'。"""
    try:
        return (_DOTNET_EPOCH + datetime.timedelta(microseconds=int(ts) / 10)).strftime('%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError, OverflowError, OSError):
        return ''


def _norm_time(s):
    """WTT BaseTime '2026:10:30 6:21:21:709' 或 '10/30/2026 6:58:17:386' → 'YYYY-MM-DD HH:MM:SS'。"""
    s = (s or '').strip()
    m = re.match(r'(\d{4})[/:](\d{1,2})[/:](\d{1,2})\s+(\d{1,2}:\d{2}:\d{2})', s)
    if m:
        return '%s-%02d-%02d %s' % (m.group(1), int(m.group(2)), int(m.group(3)), m.group(4))
    m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}:\d{2}:\d{2})', s)
    if m:
        return '%s-%02d-%02d %s' % (m.group(3), int(m.group(1)), int(m.group(2)), m.group(4))
    return s[:24]


def _read_jsonl(zf, member):
    """telemetry 檔為 JSON lines（UTF-16 或 UTF-8 BOM 開頭）, 逐行 yield dict。"""
    raw = zf.read(member)
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        text = raw.decode('utf-16', 'replace')
    else:
        text = raw.decode('utf-8-sig', 'replace')
    for line in text.splitlines():
        line = line.strip()
        if line:
            try:
                yield json.loads(line)
            except ValueError:
                continue


class HlkProject(object):
    """載入一個 .hlkp（HLK Studio 專案檔）, 提供專案資訊與 telemetry 執行紀錄/錯誤。

    .hlkp 與 .hlk/.hlkx 同為 OPC 容器但角色不同: coredata 只有空的 AssessmentData,
    逐項測試結果與 log 存在 HLK Controller 端。本類別改讀:
      hck/data/PackageInfo.xml          專案/Target/ProductInstance(Status, Features)/TestRollup
      hck/telemetry/TestCompleted*.txt  每次測試執行（JobName/TestResultStatus/Target/Duration/Bugcheck）
      hck/telemetry/Error_*.txt         錯誤與 Message（堆疊）
      hck/telemetry/TestScheduled*.txt  排程紀錄（僅計數）
    Streamdata（HLK Studio 自身 log 的 Chunk 表）本版不支援。
    """

    KIND = 'project'
    CAP_RUNS = 20000
    CAP_ERRORS = 5000
    ERR_MSG_MAX = 4000

    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        try:
            self._zip = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as exc:
            raise ValueError('無法讀取（不是有效的 .hlkp ZIP 容器）：%s' % exc)
        try:
            rels = HlkPackage._parse_rels(self._zip)
        except Exception as exc:
            self._zip.close()
            raise ValueError('無法解析 _rels/.rels：%s' % exc)
        self._rels = rels
        members = HlkPackage._find_members(rels, 'packageinfo')
        if not members:
            self._zip.close()
            raise ValueError('找不到 packageinfo 關係（請確認這是 .hlkp 專案檔而非結果檔）')
        self._pkginfo_member = members[0]
        self._tele = {}                          # kind -> [member, ...]
        names = set(self._zip.namelist())
        for typ, target in rels:
            if typ.rstrip('/').endswith('telemetry'):
                member = target.replace('\\', '/').lstrip('/')
                if member in names:
                    kind = os.path.basename(member).split('_', 1)[0]
                    self._tele.setdefault(kind, []).append(member)
        if not self._tele:
            self._zip.close()
            raise ValueError('封裝內沒有 telemetry 資料：這可能是 .hlk/.hlkx 結果檔, '
                             '請改用 .hlk/.hlkx 副檔名開啟')
        self.info = self._parse_info()
        self._runs_cache = None
        self._errors_cache = None
        self._chunks_cache = None
        self._stream = None                    # streamdata SQLite（lazy, 首次 chunks() 才解壓）
        self._slock = threading.Lock()
        self._closed = False

    def close(self):
        with self._slock:
            self._closed = True
            if self._stream is not None:
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
        try:
            self._zip.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ 專案資訊
    def _parse_info(self):
        info = {'package': {}, 'project': {}, 'instances': [], 'targets': [], 'rollup': {}}
        try:
            root = ET.fromstring(self._zip.read(self._pkginfo_member))
        except Exception:
            return info
        ns = root.tag[:root.tag.rfind('}') + 1] if root.tag.startswith('{') else ''
        info['package'] = {'type': root.get('Type', ''), 'kit': root.get('KitVersion', ''),
                           'created': root.get('CreationDate', ''),
                           'build': root.get('FullBuildName', '')}
        proj = root.find(ns + 'Project')
        if proj is not None:
            info['project'] = {'name': proj.get('Name', ''),
                               'created': proj.get('CreationDate', '')}
            roll = proj.find(ns + 'TestRollup')
            if roll is not None:
                info['rollup'] = {k: int(roll.get(k, 0) or 0)
                                  for k in ('Passed', 'Failed', 'NotRun')}
            for t in proj.iter(ns + 'Target'):
                info['targets'].append({'name': t.get('Name', ''),
                                        'type': t.get('TargetType', ''),
                                        'driver': t.get('DriverStatus', '')})
        for inst in root.iter(ns + 'ProductInstance'):
            info['instances'].append({
                'status': inst.get('Status', ''),
                'codes': [c.get('Name', '') for c in inst.iter(ns + 'Code')],
                'features': [f.get('FullName', '') for f in inst.iter(ns + 'Feature')]})
        return info

    # ------------------------------------------------------------------ telemetry
    def _iter_tele(self, kind):
        for member in self._tele.get(kind, []):
            try:
                for d in _read_jsonl(self._zip, member):
                    yield d
            except Exception:
                continue                        # 單一 telemetry 檔損毀不影響其餘

    @staticmethod
    def _bugcheck(d):
        name = d.get('BugcheckCodeName') or ''
        code = d.get('BugcheckCode')
        if not name and code:
            try:
                name = '0x%08X' % int(code)
            except (TypeError, ValueError):
                name = str(code)
        return name

    def runs(self):
        """TestCompletedDataPoint -> [{time, job, status, target, duration, bugcheck}], 新→舊。

        先全數收集再排序, 超過 CAP 時保留最新的 CAP 筆（truncated 表示有捨棄）。
        """
        if self._runs_cache is None:
            out = []
            for d in self._iter_tele('TestCompletedDataPoint'):
                try:
                    dur = int(d.get('DurationInSecs') or 0)
                except (TypeError, ValueError):
                    dur = 0
                out.append({'time': _ticks_to_time(d.get('TimeTicks')),
                            'job': d.get('JobName') or '',
                            'status': d.get('TestResultStatus') or '',
                            'target': d.get('TargetName') or '',
                            'duration': dur,
                            'bugcheck': self._bugcheck(d)})
            out.sort(key=lambda r: r['time'], reverse=True)
            truncated = len(out) > self.CAP_RUNS
            self._runs_cache = (out[:self.CAP_RUNS], truncated)
        return self._runs_cache

    ERR_SRC_RE = re.compile(r'^([A-Z][A-Za-z0-9_]{2,24})\s+:')   # 'Machine :' 風格: 詞≥3 且冒號前有空白, 避開 'C:\' 路徑與 'Warning:' 散文
    ERR_JOB_RE = re.compile(r'(?:Preparing to run|Running) test:\s*(.+)', re.I)
    ERR_MACHINE_RES = (re.compile(r'on machine \(([A-Za-z0-9._-]{1,64})\)'),
                       re.compile(r"Machine '([^'\r\n]{1,64})'"),
                       re.compile(r'Machine\s*:\s*\[([A-Za-z0-9._-]{1,64})\]'))
    ERR_MSG_SCAN = 1500      # message 機器名只掃前段, 避開深層 stack trace 誤匹配

    def _machine_map(self):
        """MachineId -> [(TimeTicks, TargetName)] 由舊到新（機器可能隨時間改名的 target）。"""
        best = {}
        for d in self._iter_tele('TestCompletedDataPoint'):
            mid = d.get('MachineId') or ''
            tgt = d.get('TargetName') or ''
            if not (mid and tgt):
                continue
            try:
                ts = int(d.get('TimeTicks') or 0)
            except (TypeError, ValueError):
                ts = 0
            best.setdefault(mid, {})[ts] = tgt      # 同 ts 後者覆蓋
        return {mid: sorted(m.items()) for mid, m in best.items()}

    @staticmethod
    def _machine_at(mmap, mid, err_ts):
        """取 MachineId 在 err_ts 當時（之前最近一筆 run）的 TargetName。"""
        seq = mmap.get(mid)
        if not seq:
            return ''
        i = bisect.bisect_right([t for t, _ in seq], err_ts)
        return (seq[i - 1][1] if i else seq[0][1])

    def errors(self):
        """Error -> [{time, type, source, machine, job, message}], 新→舊; message 截破到 ERR_MSG_MAX。

        Error telemetry 沒有任務欄位; 來源（Machine/MachinePool/Project/Test/LogoManager）
        取自 message 首行前綴, 測試任務由 "Preparing to run test: X" 提取,
        機器名優先由 MachineId→TargetName 對應表（有 Error 才建置）, 查不到時退回
        message 內文的機器名寫法。
        """
        if self._errors_cache is None:
            out = []
            for d in self._iter_tele('Error'):
                raw = (d.get('Message') or '').strip()
                msg = raw
                if len(msg) > self.ERR_MSG_MAX:
                    msg = msg[:self.ERR_MSG_MAX] + ' …（已截斷）'
                first = raw.split('\n', 1)[0].split('\r', 1)[0]
                ms = self.ERR_SRC_RE.match(first)
                source = ms.group(1) if ms else ''
                mj = self.ERR_JOB_RE.search(raw)
                job = mj.group(1).strip()[:120] if mj else ''
                msg_machine = ''
                for rx in self.ERR_MACHINE_RES:
                    mm = rx.search(raw[:self.ERR_MSG_SCAN])
                    if mm:
                        msg_machine = mm.group(1)
                        break
                out.append({'_mid': d.get('MachineId') or '', '_msgm': msg_machine,
                            '_ts': d.get('TimeTicks') or 0,
                            'time': _ticks_to_time(d.get('TimeTicks')),
                            'type': d.get('ErrorType') or 'Error',
                            'source': source, 'machine': '', 'job': job,
                            'message': msg})
            if out:                              # 完全沒有 Error 時不多掃一輪 runs
                mmap = self._machine_map()
                for e in out:
                    try:
                        ets = int(e['_ts'])
                    except (TypeError, ValueError):
                        ets = 0
                    e['machine'] = self._machine_at(mmap, e['_mid'], ets) or e['_msgm']
            for e in out:
                e.pop('_mid', None)
                e.pop('_msgm', None)
                e.pop('_ts', None)
            out.sort(key=lambda r: r['time'], reverse=True)
            truncated = len(out) > self.CAP_ERRORS
            self._errors_cache = (out[:self.CAP_ERRORS], truncated)
        return self._errors_cache

    # ------------------------------------------------------------------ log 串流（streamdata）
    def _open_stream_locked(self):
        """開啟 streamdata SQLite（呼叫端必須已持有 _slock）。lazy 從 zip 解到快取。"""
        if self._stream is None:
            if self._closed:
                raise ValueError('封裝已關閉')
            dest = os.path.join(_cache_dir_for(self.path), 'project_streamdata.db')
            if not (os.path.exists(dest) and os.path.getsize(dest) > 0):
                found = False
                for member in HlkPackage._find_members(self._rels, 'streamdata'):
                    with self._zip.open(member) as f:
                        if f.read(16) != SQLITE_MAGIC:
                            continue
                    tmp = dest + '.tmp'
                    with self._zip.open(member) as src, open(tmp, 'wb') as dst:
                        while True:
                            blk = src.read(1 << 20)
                            if not blk:
                                break
                            dst.write(blk)
                    os.replace(tmp, dest)
                    found = True
                    break
                if not found:
                    raise ValueError('封裝中沒有 SQLite 格式的 streamdata')
            self._stream = sqlite3.connect(dest, check_same_thread=False)
        return self._stream

    def _stream_query(self, sql, params=()):
        """在 _slock 內開連線並執行查詢（與 close() 互斥, 不會用到已關閉的連線）。"""
        with self._slock:
            return self._open_stream_locked().execute(sql, params).fetchall()

    def chunks(self):
        """Chunk(Id, Data) -> [{id, kind, exe, machine, time, size}], 依 id; 結果快取。

        kind: 'wtl'（WTT-Logger 測試 log, 同 Te.wtl 格式）/ 'comm'（Controller 通訊訊息）/ 'other'。
        """
        if self._chunks_cache is None:
            rows = self._stream_query(
                'SELECT Id, LENGTH(Data), substr(Data, 1, 4096) FROM Chunk ORDER BY Id')
            out = []
            for rid, size, head_blob in rows:
                try:
                    rid = int(rid)     # 抵擋非整數 Id（前端直接插入屬性）
                except (TypeError, ValueError):
                    continue
                if head_blob[:2] in (b'\xff\xfe', b'\xfe\xff'):
                    head = head_blob.decode('utf-16', 'replace')
                else:
                    head = head_blob.decode('utf-8', 'replace')
                if 'WTT-Logger' in head or '<RTI ' in head or '<Msg' in head:
                    kind = 'wtl'
                elif 'CommMessage' in head:
                    kind = 'comm'
                else:
                    kind = 'other'
                m = re.search(r'ProcessName="[^"]*?([A-Za-z0-9_.-]+\.exe)"', head, re.I)
                mm = re.search(r'(?:Machine|MachineName)="([^"]+)"', head)
                mt = re.search(r'(?:BaseTime|StartTime)="([^"]+)"', head)
                out.append({'id': rid, 'kind': kind, 'size': size or 0,
                            'exe': m.group(1) if m else '',
                            'machine': (mm.group(1) if mm else '')[:64],
                            'time': _norm_time(mt.group(1)) if mt else ''})
            self._chunks_cache = out
        return self._chunks_cache

    def read_chunk(self, chunk_id):
        """讀單條 chunk 原始位元組; 找不到回 None。可在背景執行緒呼叫。"""
        try:
            rows = self._stream_query('SELECT Data FROM Chunk WHERE Id=?', (chunk_id,))
        except ValueError:
            return None
        row = rows[0] if rows else None
        return row[0] if row and row[0] else None

    # ------------------------------------------------------------------ 彙總
    def summary(self):
        runs, r_trunc = self.runs()
        errors, e_trunc = self.errors()
        npass = sum(1 for r in runs if r['status'] == 'Passed')
        nfail = sum(1 for r in runs if r['status'] in ('Failed', 'Fail'))
        return {'kind': 'project', 'total': len(runs), 'run': len(runs),
                'pass': npass, 'fail': nfail, 'other': len(runs) - npass - nfail,
                'errors': len(errors), 'truncated': bool(r_trunc or e_trunc)}
