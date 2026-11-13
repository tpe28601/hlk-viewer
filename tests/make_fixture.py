# -*- coding: utf-8 -*-
"""鑄最小測試 fixture（結構對照 hlk_core.py 的解析邏輯）。

用法:
    py -3 tests/make_fixture.py [輸出路徑]      預設 tests/sample.hlkx

內含 4 個測試項: PASS×2 / FAIL×1 / 未執行×1, log 含 Te.wtl(WTT-Logger
UTF-16 XML)、文字檔與一個二進位檔, 並安排 Deployment 也有 Te.wtl 以驗證
pick_te 優先取 Run Test。coredata 前頭放一個非 SQLite 的 2022 decoy,
驗證 _extract_sqlite 會按 magic 跳過。

同目錄另產生（v1.2.7 起, 供 Web 單檔模式／chunk 預覽測試）:
    sample.hlkp  OPC + telemetry JSONL + streamdata Chunk(wtl/comm/other)
    sample.wtl   獨立單檔（/api/wtl 預覽與 convert_wtl_file 測試用）
"""

import os
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))

RELS = """<?xml version="1.0" encoding="utf-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="PackageInfo" Type="http://schemas.microsoft.com/Windows/2010/03/ResultPackage/packageinfo"
    Target="hck/data/PackageInfo.xml"/>
  <Relationship Id="Core2022" Type="http://schemas.microsoft.com/Windows/2010/03/ResultPackage/coredata"
    Target="Content/Package_Data_0000_00000002.edb"/>
  <Relationship Id="Core" Type="http://schemas.microsoft.com/Windows/2010/03/ResultPackage/coredata"
    Target="hck/data/Package_Data_0000_00000000.sqlite"/>
  <Relationship Id="Stream" Type="http://schemas.microsoft.com/Windows/2010/03/ResultPackage/streamdata"
    Target="hck/data/Package_Data_0000_00000001.sqlite"/>
</Relationships>"""

CONTENT_TYPES = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="sqlite" ContentType="application/octet-stream"/>
</Types>"""

PACKAGE_INFO = """<?xml version="1.0" encoding="utf-8"?>
<PackageInfo xmlns="http://schemas.microsoft.com/Windows/2010/03/ResultPackage"
    Name="Fixture Results" Created="2026-11-10T10:00:00+08:00" PackageVersion="10.0.0.0">
  <Project Name="PlatformA High HLK Run (Fixture)">
    <Target Name="PLATA-H-01" TargetType="Device"/>
    <Target Name="PLATB-H-02" TargetType="Device"/>
    <TestRollup Passed="2" Failed="1" NotRun="1"/>
  </Project>
</PackageInfo>"""


# ---------------------------------------------------------------- log 內容
def wtl_bytes(title, machine, fail=False):
    """WTT-Logger 風格 .wtl (UTF-16 XML), 節點對照 hlk_wtl.wtl_to_html。"""
    root = ET.Element('WTT-Logger')

    def stamp(el, ms):
        r = ET.SubElement(el, 'rti', {'id': '1'})
        d = ET.SubElement(el, 'Data')
        ET.SubElement(d, 'WexTraceInfo', {'TimeStamp': str(ms * 10000), 'ThreadId': '5031',
                                          'ProcessId': '4020'})
        return el

    ET.SubElement(root, 'RTI', {'ID': '1', 'BaseTime': '2026:11:10 1:0:0:0',
                                'Frequency': '10000000', 'Machine': machine,
                                'ProcessName': 'TAEF.exe', 'ProcessID': '4020',
                                'ThreadID': '5031'})
    stamp(ET.SubElement(root, 'Machine', {'OS': 'Windows 11 Pro', 'Version': '10.0',
          'Platform': 'x64', 'Language': 'zh-TW', 'Build': '26100',
          'BuildLab': 'ge_release', 'BuildDate': '20261001', 'Config': 'UEFI'}), 0)
    stamp(ET.SubElement(root, 'StartTest', {'Title': title}), 0)
    stamp(ET.SubElement(root, 'Msg', {'UserText': 'Preparing test environment ...'}), 1200)
    stamp(ET.SubElement(root, 'Msg', {'UserText': 'Executing test sequence (%s)' % title}), 3000)
    if fail:
        stamp(ET.SubElement(root, 'Msg', {'UserText': 'Assertion failed on step 7'}), 9500)
        e = stamp(ET.SubElement(root, 'Error', {'File': 'VerifyOutput.cpp', 'Line': '123',
                  'ErrCode': '0x80070005', 'ErrType': 'Win32',
                  'ErrorText': 'Access is denied.', 'UserText': 'Check failed'}), 9600)
        d = e.find('Data')
        res = ET.SubElement(d, 'Result', {'Reason': 'step 7 assertion'})
        res.text = 'Fail'
    ET.SubElement(root, 'PFRollup', {'Total': '1', 'Passed': '0' if fail else '1',
                                     'Failed': '1' if fail else '0', 'Blocked': '0',
                                     'Warned': '0', 'Skipped': '0'})
    stamp(ET.SubElement(root, 'EndTest', {'Title': title, 'Result': 'Fail' if fail else 'Pass'}),
         12000)
    return ET.tostring(root, encoding='utf-16', xml_declaration=True)


def text_bytes(s):
    return s.encode('utf-8')


# 每個 log: (log_id, name, task, result_id, data)
def build_logs():
    return [
        (101, 'Te.wtl', 'Run Test', 11, wtl_bytes('Device Fundamentals - Reboot', 'PLATA-H-01')),
        (102, 'Results.txt', 'Run Test', 11,
         text_bytes('RESULT: PASS\r\nReboot cycles completed: 50\r\nErrors: 0\r\n')),
        (103, 'Deploy_9001.log', 'Deployment', 11,
         text_bytes('Deployment started 09:00:02\nImage applied OK\nAgent version 10.0.26100\n')),
        (104, 'Te.wtl', 'Run Test', 12,
         wtl_bytes('Media Fundamentals - HD Playback', 'PLATA-H-01', fail=True)),
        (105, 'error.txt', 'Run Test', 12,
         text_bytes('Playback dropped 137 frames.\nAssertion failed on step 7 '
                    '(Access is denied. 0x80070005)\n')),
        # Deployment 也有 Te.wtl: pick_te 必須取 Run Test 的 104
        (106, 'Te.wtl', 'Deployment', 12,
         wtl_bytes('Deployment - Media Fundamentals - HD Playback', 'PLATA-H-01')),
        (107, 'shot.bin', 'Deployment', 12, bytes(range(256)) * 8),
        (108, 'Te.wtl', 'Run Test', 13,
         wtl_bytes('Battery Energy Model', 'PLATB-H-02')),
    ]


def build_coredata(logs):
    fd, path = tempfile.mkstemp(suffix='.sqlite')
    os.close(fd)
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE Test(Id INTEGER PRIMARY KEY, Name TEXT, Status INT,
                      TestClassification TEXT, Description TEXT, IsDeactivated INT DEFAULT 0);
    CREATE TABLE Result(Id INTEGER PRIMARY KEY, Status INT, StartTime TEXT, CompletionTime TEXT);
    CREATE TABLE Machine(Id INTEGER PRIMARY KEY, Name TEXT);
    CREATE TABLE Feature(Id INTEGER PRIMARY KEY, FullName TEXT);
    CREATE TABLE Task(Id INTEGER PRIMARY KEY, Name TEXT);
    CREATE TABLE Log(Id INTEGER PRIMARY KEY, Name TEXT);
    CREATE TABLE Stream(Id INTEGER PRIMARY KEY, Length INT);
    CREATE TABLE Relationship(Parent INT, Child INT, ParentType TEXT, ChildType TEXT);
    CREATE TABLE StreamMapping(StreamId INT, ChunkId INT, Position INT);
    """)
    db.executemany('INSERT INTO Test VALUES(?,?,?,?,?,0)', [
        (1, 'Device Fundamentals - Reboot', 1, 'Required', 'Reboot stress'),
        (2, 'Media Fundamentals - HD Playback', 2, 'Required', '1080p playback'),
        (3, 'Battery Energy Model', 1, 'Recommended', 'Energy model run'),
        (4, 'MultiMonitor Durability', 0, 'Recommended', 'Not executed'),
    ])
    db.executemany('INSERT INTO Result VALUES(?,?,?,?)', [
        (11, 1, '2026-11-10T09:00:00.0000000+08:00', '2026-11-10T09:31:12.0000000+08:00'),
        (12, 2, '2026-11-10T10:02:00.0000000+08:00', '2026-11-10T10:25:40.0000000+08:00'),
        (13, 1, '2026-11-10T14:10:00.0000000+08:00', '2026-11-10T15:41:03.0000000+08:00'),
    ])
    db.executemany('INSERT INTO Machine VALUES(?,?)',
                   [(1, 'PLATA-H-01'), (2, 'PLATB-H-02')])
    db.executemany('INSERT INTO Feature VALUES(?,?)', [
        (1, 'Devices and Printers'), (2, 'Media Playback'),
        (3, 'Power Management'), (4, 'Display')])
    db.executemany('INSERT INTO Task VALUES(?,?)', [
        (21, 'Run Test'), (22, 'Deployment'), (23, 'Run Test'),
        (24, 'Deployment'), (25, 'Run Test')])
    db.executemany('INSERT INTO Log VALUES(?,?)',
                   [(lid, name) for lid, name, _t, _r, _d in logs])
    db.executemany('INSERT INTO Stream VALUES(?,?)',
                   [(lid, len(data)) for lid, _n, _t, _r, data in logs])
    # Task -> Log 對應（由 logs 清單反推）
    task_of_rid = {11: {'Run Test': 21, 'Deployment': 22},
                   12: {'Run Test': 23, 'Deployment': 24},
                   13: {'Run Test': 25}}
    rel = []
    for lid, _name, task, rid, _d in logs:
        rel.append((task_of_rid[rid][task], lid, 'PackageTask', 'PackageTestLog'))
        rel.append((lid, lid, 'PackageTestLog', 'Stream'))
        db.execute('INSERT INTO StreamMapping VALUES(?,?,0)', (lid, lid))
    rel += [
        # Result -> Test
        (1, 11, 'PackageTest', 'PackageTestResult'),
        (2, 12, 'PackageTest', 'PackageTestResult'),
        (3, 13, 'PackageTest', 'PackageTestResult'),
        # Result -> Machine
        (11, 1, 'PackageTestResult', 'PackageMachine'),
        (12, 1, 'PackageTestResult', 'PackageMachine'),
        (13, 2, 'PackageTestResult', 'PackageMachine'),
        # Test -> Feature
        (1, 1, 'PackageTest', 'PackageFeature'),
        (2, 2, 'PackageTest', 'PackageFeature'),
        (3, 3, 'PackageTest', 'PackageFeature'),
        (4, 4, 'PackageTest', 'PackageFeature'),
        # Result -> Task
        (11, 21, 'PackageTestResult', 'PackageTask'),
        (11, 22, 'PackageTestResult', 'PackageTask'),
        (12, 23, 'PackageTestResult', 'PackageTask'),
        (12, 24, 'PackageTestResult', 'PackageTask'),
        (13, 25, 'PackageTestResult', 'PackageTask'),
    ]
    db.executemany('INSERT INTO Relationship VALUES(?,?,?,?)', rel)
    db.commit()
    db.close()
    with open(path, 'rb') as f:
        return f.read()


def build_streamdata(logs):
    fd, path = tempfile.mkstemp(suffix='.sqlite')
    os.close(fd)
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE Chunk(Id INTEGER PRIMARY KEY, Data BLOB)')
    db.executemany('INSERT INTO Chunk VALUES(?,?)',
                   [(lid, data) for lid, _n, _t, _r, data in logs])
    db.commit()
    db.close()
    with open(path, 'rb') as f:
        return f.read()


# ---------------------------------------------------------------- .hlkp 專案檔
RELS_HLKP = """<?xml version="1.0" encoding="utf-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="PackageInfo" Type="http://schemas.microsoft.com/Windows/2010/03/ResultPackage/packageinfo"
    Target="hck/data/PackageInfo.xml"/>
  <Relationship Id="TeleDone" Type="http://schemas.microsoft.com/Windows/2010/03/ResultPackage/telemetry"
    Target="hck/telemetry/TestCompletedDataPoint_0.txt"/>
  <Relationship Id="TeleErr" Type="http://schemas.microsoft.com/Windows/2010/03/ResultPackage/telemetry"
    Target="hck/telemetry/Error_0.txt"/>
  <Relationship Id="TeleSched" Type="http://schemas.microsoft.com/Windows/2010/03/ResultPackage/telemetry"
    Target="hck/telemetry/TestScheduledDataPoint_0.txt"/>
  <Relationship Id="Stream" Type="http://schemas.microsoft.com/Windows/2010/03/ResultPackage/streamdata"
    Target="hck/data/Project_Data_0000_00000001.sqlite"/>
</Relationships>"""

EPOCH_1601 = datetime(1601, 1, 1)


def _ticks(y, mo, d, h=0, mi=0, s=0):
    """本機時間 → 1601 起算的 100ns ticks（TimeTicks 欄位格式）"""
    return int((datetime(y, mo, d, h, mi, s) - EPOCH_1601).total_seconds() * 1e7)


def build_hlkp_telemetry():
    done = [
        {'TimeTicks': _ticks(2026, 11, 10, 9, 31, 12), 'JobName': 'Job-101',
         'TestResultStatus': 'Passed', 'TargetName': 'PLATA-H-01', 'DurationInSecs': 1872},
        {'TimeTicks': _ticks(2026, 11, 10, 10, 25, 40), 'JobName': 'Job-102',
         'TestResultStatus': 'Failed', 'TargetName': 'PLATA-H-01', 'DurationInSecs': 1420,
         'BugcheckCode': 221, 'BugcheckCodeName': 'LIVE_DUMP_EVENT_INFO_UNAVAILABLE'},
    ]
    errors = [
        {'TimeTicks': _ticks(2026, 11, 10, 10, 24, 31), 'MachineId': 'PLATA-H-01',
         'Message': 'Test: Job-102\nPreparing to run test: Media Fundamentals - HD Playback\n'
                    'Error: dropped frames exceeded threshold'},
    ]
    sched = [{'TimeTicks': _ticks(2026, 11, 10, 8, 50, 0)}]

    def jsonl(rows):
        import json
        return '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n'
    return jsonl(done), jsonl(errors), jsonl(sched)


def build_project_streamdata(logs):
    fd, path = tempfile.mkstemp(suffix='.sqlite')
    os.close(fd)
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE Chunk(Id INTEGER PRIMARY KEY, Data BLOB)')
    wtl = logs[0][4]                                     # 與封裝內相同的 WTL chunk
    comm = ('<CommMessage><Log Share="\\\\CTRL\\logs"/><Entry>chunk received</Entry>'
            '</CommMessage>').encode('utf-16')
    db.executemany('INSERT INTO Chunk VALUES(?,?)', [
        (1, wtl), (2, comm), (3, b'plain controller text chunk')])
    db.commit()
    db.close()
    with open(path, 'rb') as f:
        return f.read()


def build_hlkp(logs, out):
    done, errs, sched = build_hlkp_telemetry()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', CONTENT_TYPES)
        z.writestr('_rels/.rels', RELS_HLKP)
        z.writestr('hck/data/PackageInfo.xml', PACKAGE_INFO)
        z.writestr('hck/telemetry/TestCompletedDataPoint_0.txt', done)
        z.writestr('hck/telemetry/Error_0.txt', errs)
        z.writestr('hck/telemetry/TestScheduledDataPoint_0.txt', sched)
        z.writestr('hck/data/Project_Data_0000_00000001.sqlite',
                   build_project_streamdata(logs))
    print('fixture 已產生: %s (%d bytes)' % (out, os.path.getsize(out)))


def main(argv):
    out = argv[0] if argv else os.path.join(HERE, 'sample.hlkx')
    logs = build_logs()
    core = build_coredata(logs)
    stream = build_streamdata(logs)
    # 2022 decoy: 非 SQLite magic, _extract_sqlite 應跳過
    decoy = b'\x00\x00\x01\x00Jet4.0 decoy database' + b'\x00' * 64
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', CONTENT_TYPES)
        z.writestr('_rels/.rels', RELS)
        z.writestr('hck/data/PackageInfo.xml', PACKAGE_INFO)
        z.writestr('Content/Package_Data_0000_00000002.edb', decoy)
        z.writestr('hck/data/Package_Data_0000_00000000.sqlite', core)
        z.writestr('hck/data/Package_Data_0000_00000001.sqlite', stream)
    print('fixture 已產生: %s (%d bytes)' % (out, os.path.getsize(out)))
    d = os.path.dirname(os.path.abspath(out))
    build_hlkp(logs, os.path.join(d, 'sample.hlkp'))
    wtl_path = os.path.join(d, 'sample.wtl')             # 獨立單檔（/api/wtl 測試用）
    with open(wtl_path, 'wb') as f:
        f.write(logs[0][4])
    print('fixture 已產生: %s (%d bytes)' % (wtl_path, os.path.getsize(wtl_path)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
