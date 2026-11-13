# -*- coding: utf-8 -*-
"""將 HLK 的 log（.wtl = WTT-Logger XML 等）轉換成 HTML 報表並匯出。

.wtl 報表樣式模仿 HLK Manager 的「Test Log Report - Complete Report」：
  Report Summary / Test Results (PFRollup)
  Machine, Process, and OS Information
  Report Details → Complete Test Log (Runtime / Context / Message / Computer / Error ...)
"""

import os
import re
import html as H
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

TEXT_EXTS = {'.xml', '.txt', '.log', '.csv', '.json', '.ini', '.tsv', '.md'}

_CSS = """
body{font-family:'Segoe UI','Microsoft JhengHei',sans-serif;margin:16px;background:#fff;color:#000}
h1{font-size:26px;font-weight:bold;font-style:italic;text-align:center;margin:10px 0 18px}
table{border-collapse:collapse;width:100%;margin:0 0 4px}
td,th{border:1px solid #9aa7c7;padding:3px 8px;font-size:13px;vertical-align:top;word-break:break-word}
th{background:#4a6cb8;color:#fff;font-style:italic;text-align:center}
.bar{background:#294f9c;color:#fff;font-weight:bold;font-style:italic;text-align:center;font-size:15px;padding:5px}
.bar2{background:#3a5fae;color:#fff;font-weight:bold;font-style:italic;text-align:center;font-size:14px;padding:4px}
.lblbar{background:#294f9c;color:#fff;font-weight:bold;white-space:nowrap}
.barval{background:#5b7fd0;color:#fff;font-weight:bold;white-space:nowrap}
.errbar{background:#a02020;color:#fff}
.lbl{background:#ececec;font-weight:bold;width:170px;white-space:nowrap}
.msglbl{background:#dcdcdc;font-weight:bold;text-align:center;width:170px;white-space:nowrap}
.tm{color:#2c4f9e;font-weight:bold;width:185px;white-space:nowrap}
.val{background:#fff}
.kv{background:#fff}
.errv{color:#8b0000;background:#fdecea;font-weight:bold}
.tot{background:#f2f2f2;font-weight:bold}
.okv{color:#145a1e;font-weight:bold}
.badv{color:#b00000;font-weight:bold}
.note{color:#777;font-size:12px;margin:2px 0 10px;text-align:center}
a{color:#06c}
pre{background:#fff;border:1px solid #ccc;padding:10px;overflow:auto;font-size:12px;white-space:pre-wrap;word-break:break-all}
"""


def _page(title, body):
    return ('<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            '<title>%s</title><style>%s</style></head><body>%s</body></html>'
            % (H.escape(title), _CSS, body))


def esc(s):
    if s is None:
        return ''
    if not isinstance(s, str):
        s = str(s)
    return H.escape(s)


def decode_any(data):
    if data[:2] in (b'\xff\xfe', b'\xfe\xff'):
        try:
            return data.decode('utf-16')
        except Exception:
            pass
    for enc in ('utf-8-sig', 'utf-8', 'cp950', 'cp1252'):
        try:
            return data.decode(enc)
        except Exception:
            pass
    return data.decode('latin-1', 'replace')


def _parse_base(s):
    """RTI BaseTime '2027:11:6 8:21:21:709'（UTC, 最後是毫秒）→ aware UTC datetime"""
    m = re.match(r'(\d{4}):(\d{1,2}):(\d{1,2}) (\d{1,2}):(\d{2}):(\d{2}):(\d{1,7})', s or '')
    if not m:
        return None
    y, mo, d, h, mi, se, frac = m.groups()
    try:
        dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(se),
                      int(frac[:3]) * 1000, tzinfo=timezone.utc)
    except ValueError:
        return None
    return dt


def _fmt_dt(dt):
    """HLK 風格: 11/6/2027 4:13:24.344 PM"""
    if dt is None:
        return ''
    try:
        dt = dt.astimezone()          # 轉本機時區
    except Exception:
        pass
    h12 = dt.hour % 12 or 12
    ampm = 'AM' if dt.hour < 12 else 'PM'
    return '%d/%d/%d %d:%02d:%02d.%03d %s' % (
        dt.month, dt.day, dt.year, h12, dt.minute, dt.second, dt.microsecond // 1000, ampm)


# ---------------------------------------------------------------- 報表小節渲染
def _bar(label, time='', err=False):
    c1 = 'lblbar errbar' if err else 'lblbar'
    c2 = 'barval errbar' if err else 'barval'
    return '<tr><td class="%s">%s</td><td class="%s" colspan="2">%s</td></tr>' % (
        c1, esc(label), c2, esc(time))


def _kv(k, v, err=False, ok=None):
    cv = 'errv' if err else 'val'
    if ok is True:
        cv = 'okv'
    elif ok is False:
        cv = 'badv'
    return '<tr><td class="lbl">%s</td><td class="%s" colspan="2">%s</td></tr>' % (
        esc(k), cv, esc(v))


def _msg(time, label, text, err=False):
    c = 'errv' if err else 'val'
    return '<tr><td class="msglbl">%s</td><td class="tm">%s</td><td class="%s">%s</td></tr>' % (
        esc(label), esc(time), c, esc(text))


def pre_html(title, text, note=''):
    body = '<h1 style="text-align:left">%s</h1><div class="note" style="text-align:left">%s產生時間 %s</div><pre>%s</pre>' % (
        esc(title), (esc(note) + '　') if note else '',
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'), esc(text))
    return _page(title, body)


# ---------------------------------------------------------------- 主轉換
def wtl_to_html(title, data):
    """WTT-Logger .wtl → HLK Complete Report 風格 HTML; 解析失敗退回純文字。"""
    text = decode_any(data)
    root = None
    try:
        root = ET.fromstring(data)          # .wtl 為 UTF-16 XML
    except Exception:
        try:
            root = ET.fromstring(re.sub(r'<\?xml[^>]*\?>', '', text.lstrip('\ufeff'), count=1).encode('utf-8'))
        except Exception:
            root = None
    if root is None or not root.tag.lower().endswith('wtt-logger'):
        return pre_html(title, text, '（非預期格式, 以純文字顯示）')

    rti_map = {}
    details = []
    rollups = []
    mach_rows = []
    mach_seen = set()

    def _add_rti(el):
        base = _parse_base(el.get('BaseTime'))
        try:
            freq = float(el.get('Frequency') or 1e7)
        except ValueError:
            freq = 1e7
        rti_map[el.get('ID')] = (base, freq, el.get('Machine') or '',
                                 el.get('ProcessName') or '', el.get('ProcessID') or '',
                                 el.get('ThreadID') or '')

    # 先建全 RTI 對照表: 條目可能引用「尚未出現」的 RTI, 單次遍歷會漏時間
    for el in root:
        if el.tag == 'RTI':
            _add_rti(el)

    def entry_dt(el):
        """由 Data/WexTraceInfo + rti 引用算出顯示時間; 無 TraceInfo 時用 RTI BaseTime"""
        r = el.find('rti')
        if r is None:
            return None
        info = rti_map.get(r.get('id'))
        if not info or info[0] is None:
            return None
        data_el = el.find('Data')
        wti = data_el.find('WexTraceInfo') if data_el is not None else None
        if wti is None:                       # PFRollup 等只有 rti 引用 → BaseTime
            return info[0]
        try:
            return info[0] + timedelta(seconds=int(wti.get('TimeStamp', '0')) / (info[1] or 1e7))
        except ValueError:
            return info[0]

    for el in root:
        tag = el.tag

        if tag == 'RTI':
            _add_rti(el)                            # 對照表已預建, 此處同步刷新
            info = rti_map[el.get('ID')]
            details.append(_bar('Runtime', _fmt_dt(info[0])))
            details.append(_kv('Runtime Index:', el.get('ID')))
            details.append(_kv('Machine:', info[2]))
            details.append(_kv('Process Name:', info[3]))
            details.append(_kv('Process ID:', info[4]))
            details.append(_kv('Thread ID:', info[5]))

        elif tag == 'CTX':
            details.append(_bar('Context', ''))
            details.append(_kv('Context Index:', el.get('ID')))
            details.append(_kv('Current:', el.get('Current')))
            details.append(_kv('Parent:', el.get('Parent')))

        elif tag == 'Msg':
            user = el.get('UserText') or ''
            extra = ''
            ctx = ''
            data_el = el.find('Data')
            if data_el is not None:
                wec = data_el.find('WexContext')
                if wec is not None and wec.text:
                    ctx = wec.text.strip()
                eg = data_el.find('EndGroup')
                if eg is not None:
                    r = eg.get('Result') or ''
                    extra = '　<EndGroup: %s>' % r if r else ''
                sg = data_el.find('StartGroup')
                if sg is not None:
                    extra = '　<StartGroup>'
            if not user and not extra:
                continue
            line = user + extra
            if ctx and user.startswith('Device string'):
                pass
            details.append(_msg(_fmt_dt(entry_dt(el)), 'Message', line))

        elif tag == 'Machine':
            t = _fmt_dt(entry_dt(el))
            r = el.find('rti')
            info = rti_map.get(r.get('id')) if r is not None else None
            mach = info[2] if info else ''
            key = (mach, el.get('OS'), el.get('Build'), el.get('BuildDate'))
            if key not in mach_seen:
                mach_seen.add(key)
                mach_rows.append((mach, el))
            details.append(_msg(t, 'Computer', ''))
            details.append(_kv('OS:', el.get('OS')))
            details.append(_kv('Version:', '%s %s' % (el.get('Version') or '', el.get('Platform') or '')))
            details.append(_kv('Language:', el.get('Language')))
            details.append(_kv('Build String:', '%s-%s' % (el.get('BuildLab') or '', el.get('BuildDate') or '')))
            details.append(_kv('Configuration:', el.get('Config')))

        elif tag == 'MetadataRef':
            t = _fmt_dt(entry_dt(el))
            data_el = el.find('Data')
            wti = data_el.find('WexTraceInfo') if data_el is not None else None
            ctx = ''
            if data_el is not None:
                wec = data_el.find('WexContext')
                if wec is not None and wec.text:
                    ctx = wec.text.strip()
            left = ''
            right = ''
            if wti is not None:
                left = 'WexTraceInfo ThreadId=%s' % (wti.get('ThreadId') or wti.get('ProcessId') or '')
                right = '　　ProcessId=%s TimeStamp=%s' % (wti.get('ProcessId'), wti.get('TimeStamp'))
            details.append(_msg(t, 'MetadataRef', '%s　WexContext  %s%s' % (left, ctx, right)))
            if el.get('AttributeName'):
                details.append(_msg('', 'MetadataRef', '%s = %s' % (el.get('AttributeName'), el.get('AttributeValue'))))

        elif tag == 'StartTest':
            details.append(_bar('StartTest', _fmt_dt(entry_dt(el))))
            details.append(_kv('Test:', el.get('Title')))

        elif tag == 'EndTest':
            res = el.get('Result') or ''
            ok = res.lower() in ('pass', 'passed')
            err = res.lower() in ('fail', 'failed')
            details.append(_bar('EndTest (%s)' % res, _fmt_dt(entry_dt(el)), err=err))
            details.append(_kv('Test:', el.get('Title'), ok=ok if res else None, err=err))

        elif tag == 'Error':
            t = _fmt_dt(entry_dt(el))
            details.append(_bar('Error', t, err=True))
            if el.get('File'):
                details.append(_kv('File:', el.get('File'), err=True))
            if el.get('Line') not in (None, '', '-1'):
                details.append(_kv('Line:', el.get('Line'), err=True))
            if el.get('ErrCode'):
                details.append(_kv('Err Code:', '%s %s' % (el.get('ErrCode'), el.get('ErrType') or ''), err=True))
            if el.get('ErrorText'):
                details.append(_kv('Error Text:', el.get('ErrorText'), err=True))
            user = el.get('UserText')
            if user:
                details.append(_kv('Message:', user, err=True))
            data_el = el.find('Data')
            if data_el is not None:
                res_el = data_el.find('Result')
                if res_el is not None and res_el.text:
                    reason = ' (%s)' % res_el.get('Reason') if res_el.get('Reason') else ''
                    details.append(_kv('Result:', res_el.text.strip() + reason, err=True))

        elif tag == 'PFRollup':
            t = _fmt_dt(entry_dt(el))
            rollups.append({k: el.get(k) or '0' for k in
                            ('Total', 'Passed', 'Failed', 'Blocked', 'Warned', 'Skipped')})
            rollups[-1]['_time'] = t
            details.append(_bar('PFRollup', t))
            details.append(_kv('Total:', el.get('Total')))
            details.append(_kv('Passed:', el.get('Passed')))
            details.append(_kv('Failed:', el.get('Failed')))

    # ------------------------------------------------------------- 組合頁面
    parts = ['<h1>Test Log Report - Complete Report</h1>']

    # Report Summary / Test Results（仿 HLK Manager: Sum 列在上, 各 PFRollup 以
    # TimeStamp 當 Description 列在「TimeStamp」子表頭之下, 含 Blocked/Skipped/Pass Rate）
    tot = {k: sum(int(r[k]) for r in rollups) for k in
           ('Total', 'Passed', 'Failed', 'Blocked', 'Warned', 'Skipped')} if rollups else None

    def _pct(passed, total):
        return '%.2f%%' % (passed * 100.0 / total) if total else ''

    _HDRS = ('Total', 'Pass', 'Fail', 'Warning', 'Blocked', 'Skipped', 'Pass Rate')
    parts.append('<table><tr><td class="bar" colspan="8">Report Summary</td></tr>'
                 '<tr><td class="bar2" colspan="8">Test Results</td></tr>'
                 '<tr><th style="text-align:left">Description</th>%s</tr>'
                 % ''.join('<th>%s</th>' % h for h in _HDRS))
    if tot:
        parts.append('<tr class="tot"><td>+ Sum of all PFRollups</td><td>%d</td>'
                     '<td class="okv">%d</td><td class="%s">%d</td><td>%d</td><td>%d</td>'
                     '<td>%d</td><td>%s</td></tr>'
                     % (tot['Total'], tot['Passed'],
                        'badv' if tot['Failed'] else 'okv', tot['Failed'],
                        tot['Warned'], tot['Blocked'], tot['Skipped'],
                        _pct(tot['Passed'], tot['Total'])))
    parts.append('<tr><th style="text-align:left">TimeStamp</th>%s</tr>'
                 % ''.join('<th>%s</th>' % h for h in _HDRS))
    for r in rollups:
        try:
            rt, rp = int(r['Total'] or 0), int(r['Passed'] or 0)
        except ValueError:
            rt = rp = 0
        parts.append('<tr><td>%s</td><td>%s</td><td>%s</td>'
                     '<td class="%s">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                     % (esc(r.get('_time') or ''), esc(r['Total']), esc(r['Passed']),
                        'badv' if rt and rp != rt else '', esc(r['Failed']),
                        esc(r['Warned']), esc(r['Blocked']), esc(r['Skipped']),
                        _pct(rp, rt)))
    if not rollups:
        parts.append('<tr class="tot"><td>+ Sum of all PFRollups</td>'
                     '<td colspan="7">（無 PFRollup）</td></tr>')
    parts.append('</table>')

    # Machine, Process, and OS Information
    parts.append('<table><tr><td class="bar" colspan="12">Machine, Process, and OS Information</td></tr>'
                 '<tr><th>Machine Name</th><th>OS</th><th>Version</th><th>Build</th><th>BuildLab</th>'
                 '<th>BuildDate</th><th>Platform</th><th>Language</th></tr>')
    for mach, m in mach_rows:
        parts.append('<tr><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                     '<td>%s</td><td>%s</td></tr>' % (
                         esc(mach), esc(m.get('OS')), esc(m.get('Version')), esc(m.get('Build')),
                         esc(m.get('BuildLab')), esc(m.get('BuildDate')), esc(m.get('Platform')),
                         esc(m.get('Language'))))
    if not mach_rows:
        parts.append('<tr><td colspan="8">（無機器資訊）</td></tr>')
    parts.append('</table>')

    # Report Details / Complete Test Log
    parts.append('<table><tr><td class="bar" colspan="3">Report Details</td></tr>'
                 '<tr><td class="bar2" colspan="3">Complete Test Log</td></tr>')
    parts.extend(details)
    parts.append('</table>')
    parts.append('<div class="note">來源：%s　轉換時間：%s　（本頁由 HLK-Viewer 自 .wtl 產生, 樣式仿 HLK Manager Complete Report）</div>'
                 % (esc(title), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    return _page('Te.wtl - Report', ''.join(parts))


# ---------------------------------------------------------------- 匯出
def _sanitize(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', name).strip(' ._')
    return (name or 'log')[:120]


def log_to_html(log_name, data):
    """依副檔名決定輸出; 回傳 (副檔名, bytes)。非文字檔原樣複製。"""
    ext = os.path.splitext(log_name)[1].lower()
    if ext == '.wtl':
        return '.html', wtl_to_html(log_name, data).encode('utf-8')
    if ext == '.html':
        return '.html', data
    if ext in TEXT_EXTS:
        return '.html', pre_html(log_name, decode_any(data)).encode('utf-8')
    return ext or '.bin', data


def convert_wtl_file(src, outdir):
    """獨立 .wtl 檔 → 單頁 .htm（檔名＝主檔名.htm, 重複自動加 (2)、(3)…）。

    與封裝內 log_to_html 同一條轉換管線; 無 test config 脈絡, Report Summary
    僅列 WTL 自身資訊。回傳輸出檔完整路徑。
    """
    with open(src, 'rb') as f:
        data = f.read()
    name = os.path.basename(src)
    ext, out = log_to_html(name, data)
    if ext != '.html':
        out = pre_html(name, decode_any(data)).encode('utf-8')
    os.makedirs(outdir, exist_ok=True)
    stem = re.sub(r'[<>:"/\\|?*]', '_', os.path.splitext(name)[0])
    dst = os.path.join(outdir, stem + '.htm')
    k = 1
    while os.path.exists(dst):
        k += 1
        if k > 999:
            raise OSError('同名檔案過多, 請改用空白資料夾')
        dst = os.path.join(outdir, '%s(%d).htm' % (stem, k))
    tmp = dst + '.tmp'
    try:
        with open(tmp, 'wb') as f:
            f.write(out)
        os.replace(tmp, dst)
    except OSError:
        try:                                # 寫入/搬移失敗: 不把半截 .tmp 留在輸出資料夾
            os.remove(tmp)
        except OSError:
            pass
        raise
    return dst


def export_logs(pkg, items, outdir, progress=None):
    """items: [{test_name, test_status, log_name, log_id, task, out_name?, out_ext?}]
    回傳 (成功數, 錯誤清單, index.html 路徑)"""
    os.makedirs(outdir, exist_ok=True)
    used = set()
    rows = []
    errors = []
    done = 0
    for i, it in enumerate(items, 1):
        if progress:
            progress(i, len(items), it['log_name'])
        try:
            data = pkg.read_log(it['log_id'])
            ext, out = log_to_html(it['log_name'], data)
            if it.get('out_ext') and ext == '.html':
                ext = it['out_ext']
            if it.get('out_name'):
                base = _sanitize(it['out_name'])
            else:
                base = '%03d_%s__%s' % (i, _sanitize(it['test_name']), _sanitize(it['log_name']))
            fname = base + ext
            n = 2
            while fname in used:
                fname = '%s (%d)%s' % (base, n, ext)
                n += 1
            used.add(fname)
            with open(os.path.join(outdir, fname), 'wb') as f:
                f.write(out)
            conv = 'HTML' if ext in ('.html', '.htm') else '原始檔'
            st = it.get('test_status')
            badge = ('<span style="color:#145a1e;font-weight:bold">PASS</span>' if st == 1 else
                     '<span style="color:#b00000;font-weight:bold">FAIL</span>' if st == 2 else '—')
            rows.append('<tr><td>%s</td><td><a href="%s">%s</a></td><td>%s</td><td>%s</td></tr>' % (
                badge, H.escape(fname), H.escape(fname),
                H.escape(it['test_name']), len(data)))
            done += 1
        except Exception as e:
            errors.append('%s: %s' % (it.get('test_name'), e))
    idx = ['<h1 style="text-align:left">HLK Log 匯出索引 (Te.wtl → HTML)</h1>'
           '<div class="note" style="text-align:left">來源：%s　產生：%s　共 %d 份</div>'
           '<table><tr><th>結果</th><th>輸出檔案</th><th>測試側項</th><th>原始大小(B)</th></tr>%s</table>'
           % (esc(pkg.name), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), done, ''.join(rows))]
    index_path = os.path.join(outdir, 'index.html')
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(_page('HLK Log 匯出索引', ''.join(idx)))
    return done, errors, index_path
