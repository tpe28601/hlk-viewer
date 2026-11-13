# -*- coding: utf-8 -*-
"""免第三方套件的 XLSX 產生器：HLK 側項結果報表（含 PASS/FAIL 填色、凍結窗格、自動篩選）。"""

import re
import zipfile
from datetime import datetime

_SHEET = '側項結果'
_CTL = 'http://schemas.openxmlformats.org/package/2006/content-types'
_REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
_RNS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

# cellXfs 樣式索引
ST_DEFAULT, ST_TITLE, ST_HEADER, ST_PASS, ST_FAIL, ST_BOLD, ST_NOTRUN = range(7)

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="%(_NS)s">
<fonts count="7">
<font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><name val="Calibri"/></font>
<font><b/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
<font><color rgb="FF006100"/><name val="Calibri"/></font>
<font><color rgb="FF9C0006"/><name val="Calibri"/></font>
<font><color rgb="FF7F7F7F"/><name val="Calibri"/></font>
<font><b/><sz val="16"/><name val="Calibri"/></font>
</fonts>
<fills count="5">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF4A6CB8"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFC6EFCE"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFC7CE"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="7">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="6" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="2" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="0" fontId="3" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="0" fontId="4" fillId="4" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="5" fillId="0" borderId="0" xfId="0" applyFont="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>""" % {'_NS': _NS}


def esc(s):
    s = '' if s is None else str(s)
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)
    return (s.replace('&', '&amp;').replace('<', '&lt;')
             .replace('>', '&gt;').replace('"', '&quot;'))


def _col(i):
    s = ''
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(row, col, value, style=ST_DEFAULT, num=False):
    ref = '%s%d' % (_col(col), row)
    st = ' s="%d"' % style if style else ''
    if num:
        return '<c r="%s"%s><v>%s</v></c>' % (ref, st, value)
    return ('<c r="%s"%s t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
            % (ref, st, esc(value)))


def write_results_xlsx(path, info, rows):
    """info: dict(source/project/total/run/pass/fail/notrun)
    rows: [(結果, 側項名稱, Feature, 機器, 開始, 結束, log數)]"""
    HDR = 6                                     # 標題列所在列
    out = []
    out.append('<row r="1">%s</row>' % _cell(1, 1, 'HLK 側項結果報表', ST_TITLE))
    out.append('<row r="2">%s</row>' % _cell(2, 1, '來源檔案：%s' % info.get('source', '')))
    out.append('<row r="3">%s</row>' % _cell(
        3, 1, '專案：%s　產生時間：%s' % (info.get('project', ''),
                                          datetime.now().strftime('%Y-%m-%d %H:%M:%S'))))
    out.append('<row r="4">%s%s%s%s%s%s%s%s%s%s</row>' % (
        _cell(4, 1, '側項總計', ST_BOLD), _cell(4, 2, info.get('total', 0), ST_BOLD, num=True),
        _cell(4, 3, '已執行', ST_BOLD), _cell(4, 4, info.get('run', 0), ST_BOLD, num=True),
        _cell(4, 5, 'PASS', ST_PASS), _cell(4, 6, info.get('pass', 0), ST_PASS, num=True),
        _cell(4, 7, 'FAIL', ST_FAIL), _cell(4, 8, info.get('fail', 0), ST_FAIL, num=True),
        _cell(4, 9, '未執行', ST_BOLD), _cell(4, 10, info.get('notrun', 0), ST_BOLD, num=True)))
    heads = ('結果', '測試側項', '所屬功能 (Feature)', '測試機器', '開始時間', '結束時間', 'Log 數')
    out.append('<row r="%d">%s</row>' % (
        HDR, ''.join(_cell(HDR, i + 1, h, ST_HEADER) for i, h in enumerate(heads))))
    r = HDR
    for rec in rows:
        r += 1
        st = rec[0]
        style = ST_PASS if st == 'PASS' else (ST_FAIL if st == 'FAIL' else ST_NOTRUN)
        cells = [_cell(r, 1, rec[0], style)]
        for i in range(1, 6):
            cells.append(_cell(r, i + 1, rec[i], style))
        cells.append(_cell(r, 7, rec[6], style, num=True))
        out.append('<row r="%d">%s</row>' % (r, ''.join(cells)))
    last = max(r, HDR)

    cols = ''.join('<col min="%d" max="%d" width="%s" customWidth="1"/>' % w
                   for w in ((1, 1, '9'), (2, 2, '62'), (3, 3, '40'), (4, 4, '18'),
                             (5, 5, '20'), (6, 6, '20'), (7, 7, '8')))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="%s">'
             '<sheetViews><sheetView workbookViewId="0">'
             '<pane ySplit="%d" topLeftCell="A%d" activePane="bottomLeft" state="frozen"/>'
             '</sheetView></sheetViews>'
             '<sheetFormatPr defaultRowHeight="15"/>'
             '<cols>%s</cols>'
             '<sheetData>%s</sheetData>'
             '<autoFilter ref="A%d:G%d"/>'
             '</worksheet>') % (_NS, HDR, HDR + 1, cols, ''.join(out), HDR, last)

    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="%s">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
          '</Types>') % _CTL
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="%s">'
            '<Relationship Id="rId1" Type="%s/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>') % (_REL, _RNS)
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook xmlns="%s" xmlns:r="%s">'
          '<sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets>'
          '</workbook>') % (_NS, _RNS, _SHEET)
    wbrels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Relationships xmlns="%s">'
              '<Relationship Id="rId1" Type="%s/worksheet" Target="worksheets/sheet1.xml"/>'
              '<Relationship Id="rId2" Type="%s/styles" Target="styles.xml"/>'
              '</Relationships>') % (_REL, _RNS, _RNS)

    tmp = path + '.tmp'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', ct)
        z.writestr('_rels/.rels', rels)
        z.writestr('xl/workbook.xml', wb)
        z.writestr('xl/_rels/workbook.xml.rels', wbrels)
        z.writestr('xl/styles.xml', _STYLES)
        z.writestr('xl/worksheets/sheet1.xml', sheet)
    import os
    if os.path.exists(path):
        os.remove(path)                       # Excel 佔用時會拋 OSError, 由呼叫端提示
    os.replace(tmp, path)
