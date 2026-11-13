# -*- coding: utf-8 -*-
"""HLK 側項檢視 / Log 匯出工具 (GUI 主程式)

用法:
    hlk_viewer.pyw [檔案.hlkx|檔案.wtl]              啟動 GUI（可直接帶檔; .wtl 轉單頁 .htm）
    hlk_viewer.pyw --cli-export-all <hlkx> <輸出資料夾>   全部 log 匯出成 HTML（無視窗）
"""

import os
import queue
import re
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import hlk_core
import hlk_wtl
import hlk_xlsx
from hlk_core import STATUS_TEXT
from standalone_update import check_update, open_update


def human_size(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return '%.0f %s' % (n, unit) if unit == 'B' else '%.1f %s' % (n, unit)
        n /= 1024.0


class ExportDialog(tk.Toplevel):
    """選擇要匯出的 log（按測試項分組, 可單選/全選/只選 FAIL）, 匯出成 HTML。"""

    def __init__(self, master, pkg, only_test=None, te_mode=True):
        super().__init__(master)
        self.pkg = pkg
        self.te_mode = te_mode      # True: 只列每個側項 Run Test 的 Te.wtl（檔名=側項名稱）
        self.title('選擇要匯出的 Log（Run Test 的 Te.wtl → .htm）' if te_mode
                   else '選擇要匯出的 Log（所有類型 → HTML）')
        self.geometry('1000x640')
        self.transient(master)
        self.checked = set()        # te_mode: {test_idx};  all: {(test_idx, log_id)}
        self.running = False
        self._result = None
        self._msg = tk.StringVar(value='')
        self._te = {}               # te_mode: test_idx -> Te.wtl log dict

        runs = [(i, t) for i, t in enumerate(pkg.tests) if t['rid'] is not None]
        if only_test is not None:
            runs = [(i, t) for i, t in runs if i == only_test]

        frm = ttk.Frame(self, padding=6)
        frm.pack(fill='both', expand=True)
        bar = ttk.Frame(frm)
        bar.pack(fill='x')
        presets = [('全選', lambda: self._set_all(True)),
                   ('取消全選', lambda: self._set_all(False)),
                   ('只選 FAIL 側項', lambda: self._preset(lambda t: t['rstatus'] == 2)),
                   ('只選 PASS 側項', lambda: self._preset(lambda t: t['rstatus'] == 1))]
        if not te_mode:
            presets.append(('只選 .wtl / .html',
                            lambda: self._preset(lambda t: True, ext_only=('.wtl', '.html'))))
        for text, cmd in presets:
            ttk.Button(bar, text=text, command=cmd).pack(side='left', padx=2)
        ttk.Label(bar, textvariable=self._msg).pack(side='right', padx=6)

        wrap = ttk.Frame(frm)
        wrap.pack(fill='both', expand=True, pady=4)
        cols = ('status', 'machine', 'task', 'size') if te_mode else ('task', 'size', 'type')
        self.tree = ttk.Treeview(wrap, columns=cols, selectmode='browse')
        self.tree.heading('#0', text='側項（核取＝匯出 Run Test 的 Te.wtl，輸出檔名＝側項名稱.htm）'
                          if te_mode else '測試項目 / Log（點擊核取方塊選取）')
        for cid, txt, w in (('status', '結果', 70), ('machine', '測試機器', 150),
                            ('task', '所屬任務/階段', 200), ('size', '大小', 80),
                            ('type', '格式', 60)):
            if cid not in cols:
                continue
            self.tree.heading(cid, text=txt)
            self.tree.column(cid, width=w, anchor='w', stretch=(cid == 'task'))
        vs = ttk.Scrollbar(wrap, orient='vertical', command=self.tree.yview)
        hs = ttk.Scrollbar(wrap, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vs.grid(row=0, column=1, sticky='ns')
        hs.grid(row=1, column=0, sticky='ew')
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.tree.tag_configure('pass', foreground='#1a7f37')
        self.tree.tag_configure('fail', foreground='#c62828')
        self.tree.bind('<Button-1>', self._on_click)

        bottom = ttk.Frame(frm)
        bottom.pack(fill='x')
        ttk.Button(bottom, text='轉換成 .htm 並匯出 …', command=self._export).pack(side='left', padx=2)
        ttk.Button(bottom, text='關閉', command=self.destroy).pack(side='right', padx=2)

        self._ids = {}        # tree item id -> ('test', idx) | ('log', idx, log_dict)
        rows_added = 0
        for idx, t in runs:
            st = STATUS_TEXT.get(t['rstatus'], '')
            tag = 'pass' if t['rstatus'] == 1 else ('fail' if t['rstatus'] == 2 else '')
            if self.te_mode:
                te = self._pick_te(t)
                if te is None:
                    continue
                self._te[idx] = te
                tid = self.tree.insert('', 'end', text='☐  %s' % t['name'], tags=(tag,),
                                       values=(st, t['machine'], te['task'] or 'Run Test',
                                               human_size(te['size'])))
                self._ids[tid] = ('test', idx)
                if only_test is not None:
                    self._toggle(tid, True)
            else:
                tid = self.tree.insert('', 'end', text='☐  %s' % t['name'], open=(len(runs) <= 3),
                                       tags=(tag,), values=(st, len(t['logs']), ''))
                self._ids[tid] = ('test', idx)
                for l in t['logs']:
                    lid = self.tree.insert(tid, 'end', text='☐  %s' % l['name'],
                                           values=(l['task'], human_size(l['size']),
                                                   os.path.splitext(l['name'])[1].lstrip('.').lower() or '?'))
                    self._ids[lid] = ('log', idx, l)
                    if only_test is not None:
                        self._toggle(lid, True)
            rows_added += 1
        if not rows_added:
            self.tree.insert('', 'end', text='（沒有含 Run Test Te.wtl 的側項）' if te_mode
                             else '（沒有已執行的測試側項）')

    @staticmethod
    def _pick_te(t):
        """取該側項 Run Test 任務的 Te.wtl；沒有則退回任何名為 Te.wtl 的 log。"""
        cands = [l for l in t['logs'] if l['name'].lower() == 'te.wtl']
        for l in cands:
            if l['task'] == 'Run Test':
                return l
        return cands[0] if cands else None

    # --------------------------------------------------------------- 勾選
    def _toggle(self, iid, val=None):
        item = self._ids.get(iid)
        if item is None:
            return
        text = self.tree.item(iid, 'text')
        cur = text.startswith('☑')
        new = (not cur) if val is None else val
        self.tree.item(iid, text=('☑' if new else '☐') + text[1:])
        if item[0] == 'test':
            if self.te_mode:
                if new:
                    self.checked.add(item[1])
                else:
                    self.checked.discard(item[1])
            for k in self.tree.get_children(iid):
                self._toggle(k, new)
        else:
            key = (item[1], item[2]['log_id'])
            if new:
                self.checked.add(key)
            else:
                self.checked.discard(key)

    def _on_click(self, ev):
        if self.tree.identify('region', ev.x, ev.y) != 'tree':
            return
        iid = self.tree.identify_row(ev.y)
        if iid:
            self._toggle(iid)

    def _set_all(self, val):
        for top in self.tree.get_children(''):
            self._toggle(top, val)

    def _preset(self, test_pred, ext_only=None):
        self._set_all(False)
        for top in self.tree.get_children(''):
            item = self._ids.get(top)
            if not item or not test_pred(self.pkg.tests[item[1]]):
                continue
            if self.te_mode:
                self._toggle(top, True)
                continue
            for k in self.tree.get_children(top):
                lk = self._ids.get(k)
                if lk and (ext_only is None or
                           os.path.splitext(lk[2]['name'])[1].lower() in ext_only):
                    self._toggle(k, True)

    # --------------------------------------------------------------- 動作
    def _items(self):
        out = []
        if self.te_mode:
            for idx in sorted(self.checked):
                t = self.pkg.tests[idx]
                l = self._te[idx]
                out.append({'test_name': t['name'], 'test_status': t['rstatus'],
                            'log_name': l['name'], 'log_id': l['log_id'], 'task': l['task'],
                            'out_name': t['name'], 'out_ext': '.htm'})
            return out
        for idx, t in enumerate(self.pkg.tests):
            for l in t['logs']:
                if (idx, l['log_id']) in self.checked:
                    out.append({'test_name': t['name'], 'test_status': t['rstatus'],
                                'log_name': l['name'], 'log_id': l['log_id'], 'task': l['task']})
        return out

    def _export(self):
        if self.running:
            return
        items = self._items()
        if not items:
            messagebox.showinfo('匯出', '請先勾選要匯出的 log', parent=self)
            return
        outdir = filedialog.askdirectory(title='選擇 HTML 輸出資料夾', parent=self)
        if not outdir:
            return
        self.running = True
        self._result = None
        self._msg_val = ''

        def worker():
            try:
                def prog(i, n, nm):
                    self._msg_val = '%d/%d　%s' % (i, n, nm)
                n, errs, idx = hlk_wtl.export_logs(self.pkg, items, outdir, progress=prog)
                self._result = (n, errs, idx, outdir)
            except Exception as e:
                self._result = ('ERR', e, traceback.format_exc(), outdir)
            finally:
                self.running = False
        threading.Thread(target=worker, daemon=True).start()
        self.after(200, self._poll)

    def _poll(self):
        if self.running:
            v = getattr(self, '_msg_val', '')
            if v:
                self._msg.set('匯出中 ' + v)
            self.after(200, self._poll)
            return
        if self._result is None:
            return
        res, self._result = self._result, None
        if res[0] == 'ERR':
            self._msg.set('匯出失敗')
            messagebox.showerror('匯出失敗', str(res[1]), parent=self)
            return
        n, errs, idx, outdir = res
        self._msg.set('完成 %d 份 → %s' % (n, outdir))
        msg = '已轉換完成 %s 份 .htm。\n輸出資料夾：%s\n索引頁：%s' % (n, outdir, idx)
        if errs:
            msg += '\n\n有 %d 個失敗：\n%s' % (len(errs), '\n'.join(errs[:5]))
        if messagebox.askyesno('轉換完成', msg + '\n\n是否開啟索引頁？', parent=self):
            webbrowser.open('file:///' + idx.replace('\\', '/'))


class App(tk.Tk):
    COLS = ('status', 'name', 'features', 'machine', 'start', 'end', 'logs')

    def __init__(self):
        super().__init__()
        self.title('HLK 側項檢視 / Log 匯出工具')
        self.geometry('1220x680')
        self.pkg = None
        self._result = None
        self.status = tk.StringVar(value='請開啟 .hlk / .hlkx 檔案')

        men = tk.Menu(self)
        m1 = tk.Menu(men, tearoff=0)
        m1.add_command(label='開啟 HLK 檔案…', accelerator='Ctrl+O', command=self.open_dialog)
        m1.add_separator()
        m1.add_command(label='結束', command=self.destroy)
        men.add_cascade(label='檔案', menu=m1)
        m2 = tk.Menu(men, tearoff=0)
        m2.add_command(label='選擇側項 Te.wtl 轉換成 .htm…', command=lambda: self.export_dialog())
        m2.add_command(label='獨立 .wtl 轉單頁 .htm…', command=self.open_wtl_dialog)
        m2.add_command(label='進階：選擇所有類型 Log 匯出…', command=lambda: self.export_dialog(te_mode=False))
        men.add_cascade(label='Log', menu=m2)
        m3 = tk.Menu(men, tearoff=0)
        m3.add_command(label='匯出側項結果 Excel (.xlsx)…', command=self.export_excel)
        men.add_cascade(label='報表', menu=m3)
        self.config(menu=men)
        self.bind('<Control-o>', lambda e: self.open_dialog())

        bar = ttk.Frame(self, padding=(8, 6))
        bar.pack(fill='x')
        ttk.Button(bar, text='開啟 HLK 檔案…', command=self.open_dialog).pack(side='left')
        ttk.Button(bar, text='Te.wtl → .htm 匯出…', command=lambda: self.export_dialog()).pack(side='left', padx=8)
        ttk.Button(bar, text='匯出側項結果 Excel…', command=self.export_excel).pack(side='left')
        self.update_button = ttk.Button(bar, text='↓', width=4)
        self.update_results = queue.Queue()
        self.after_idle(self.check_update)
        ttk.Label(bar, textvariable=self.status).pack(side='right')

        f2 = ttk.Frame(self, padding=(8, 0))
        f2.pack(fill='x')
        ttk.Label(f2, text='結果篩選').pack(side='left')
        self.f_status = ttk.Combobox(f2, values=('全部', 'PASS', 'FAIL', '未執行'), width=8, state='readonly')
        self.f_status.set('全部')
        self.f_status.pack(side='left', padx=4)
        self.f_status.bind('<<ComboboxSelected>>', lambda e: self._populate())
        ttk.Label(f2, text='搜尋').pack(side='left', padx=(14, 2))
        self.f_search = ttk.Entry(f2, width=28)
        self.f_search.pack(side='left')
        self.f_search.bind('<KeyRelease>', lambda e: self._populate())
        self.f_only_run = tk.BooleanVar(value=True)
        ttk.Checkbutton(f2, text='只顯示已執行的側項', variable=self.f_only_run,
                        command=self._populate).pack(side='left', padx=12)
        self.lbl_sum = ttk.Label(f2, text='')
        self.lbl_sum.pack(side='right')

        wrap = ttk.Frame(self, padding=8)
        wrap.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(wrap, columns=self.COLS, show='headings', selectmode='browse')
        widths = {'status': 70, 'name': 460, 'features': 240, 'machine': 130,
                  'start': 145, 'end': 145, 'logs': 60}
        heads = {'status': '結果', 'name': '測試側項', 'features': '所屬功能 (Feature)', 'machine': '測試機器',
                 'start': '開始時間', 'end': '結束時間', 'logs': 'Log 數'}
        for c in self.COLS:
            self.tree.heading(c, text=heads[c], command=lambda c=c: self._sort_by(c))
            self.tree.column(c, width=widths[c], anchor='w', stretch=(c in ('name', 'features')))
        vs = ttk.Scrollbar(wrap, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side='left', fill='both', expand=True)
        vs.pack(side='left', fill='y')
        self.tree.tag_configure('pass', background='#E8F5E9', foreground='#0d5016')
        self.tree.tag_configure('fail', background='#FDECEA', foreground='#a01414')
        self.tree.tag_configure('notrun', foreground='#888888')
        self.tree.bind('<Double-1>', self._on_dbl)
        self.tree.bind('<Return>', lambda e: self.export_dialog(self._test_index_from_row(self.tree.focus())))
        self._sort_state = {}

        self.lbl_hint = ttk.Label(self, padding=(8, 2, 8, 6), foreground='#555',
                                  text='提示：按兩下側項（或選取後按 Enter）→ 該側項 Run Test 的 Te.wtl 已勾選，選資料夾後即轉成「側項名稱.htm」；工具列「Te.wtl → .htm 匯出…」可批次多選（全選/只選 FAIL）。')
        self.lbl_hint.pack(fill='x')

    # --------------------------------------------------------------- 開啟
    def check_update(self):
        root = Path(__file__).resolve().parent
        threading.Thread(target=lambda: self.update_results.put(check_update(root)), daemon=True).start()
        self.after(150, self.show_available_update)

    def show_available_update(self):
        try:
            result = self.update_results.get_nowait()
        except queue.Empty:
            self.after(150, self.show_available_update)
            return
        version = (result.get('update') or {}).get('version')
        if version:
            self.update_button.configure(command=lambda: self.install_update(version))
            self.update_button.pack(side='left', padx=8)

    def install_update(self, version):
        result = open_update(Path(__file__).resolve().parent, version)
        if not result['ok']:
            messagebox.showerror('HLK Viewer 更新', result['error']['message'], parent=self)

    def open_dialog(self):
        fp = filedialog.askopenfilename(
            title='選擇 HLK 檔案', parent=self, initialdir=os.path.expanduser('~\\Desktop'),
            filetypes=[('HLK 檔案', '*.hlk;*.hlkx'), ('WTL log（單檔轉 .htm）', '*.wtl'),
                       ('所有檔案', '*.*')])
        if fp:
            if fp.lower().endswith('.wtl'):
                self.convert_wtl(fp)
            else:
                self.load_async(fp)

    def open_wtl_dialog(self):
        """獨立的 .wtl 檔（不在封裝內）→ 單頁 .htm"""
        fp = filedialog.askopenfilename(
            title='選擇 .wtl 檔案', parent=self, initialdir=os.path.expanduser('~\\Desktop'),
            filetypes=[('WTL log', '*.wtl'), ('所有檔案', '*.*')])
        if fp:
            self.convert_wtl(fp)

    def convert_wtl(self, fp):
        """選輸出資料夾後把單一 .wtl 轉成「主檔名.htm」（與匯出同一條 hlk_wtl 管線）"""
        outdir = filedialog.askdirectory(title='選擇 .htm 輸出資料夾', parent=self,
                                         initialdir=os.path.dirname(fp) or None)
        if not outdir:
            return
        try:
            dst = hlk_wtl.convert_wtl_file(fp, outdir)
        except Exception as e:
            messagebox.showerror('轉換失敗', '%s\n%s' % (e, traceback.format_exc()[:600]),
                                 parent=self)
            return
        self.status.set('已轉換：%s' % dst)
        if messagebox.askyesno('轉換完成',
                               '已轉換成單頁報表：\n%s\n\n是否開啟？' % dst, parent=self):
            try:
                os.startfile(dst)
            except Exception:
                pass

    def load_async(self, fp):
        self.status.set('載入中：%s …' % os.path.basename(fp))
        self._result = None

        def worker():
            try:
                pkg = hlk_core.HlkPackage(fp)
                self._result = ('ok', pkg)
            except Exception as e:
                self._result = ('err', e, traceback.format_exc())
        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_load)

    def _poll_load(self):
        if self._result is None:
            self.after(100, self._poll_load)
            return
        res, self._result = self._result, None
        if res[0] == 'err':
            self.status.set('載入失敗')
            messagebox.showerror('載入失敗', '%s\n\n%s' % (res[1], res[2][:1200]))
            return
        self.pkg = res[1]
        s = self.pkg.summary()
        self.title('HLK 側項檢視 / Log 匯出工具　—　%s (%s)' % (self.pkg.project_name or self.pkg.name, self.pkg.name))
        self.lbl_sum.config(text='側項總計 %d　已執行 %d（PASS %d / FAIL %d）　未執行 %d　Log %d 個'
                            % (s['total'], s['run'], s['pass'], s['fail'], s['notrun'], s['nlogs']))
        self.status.set('已載入：%s' % self.pkg.name)
        self._populate()

    # --------------------------------------------------------------- 列表
    def _filtered_sorted_rows(self):
        """依目前篩選 / 搜尋 / 排序條件, 回傳 [(tag, test, 狀態字串)]"""
        fs = self.f_status.get()
        kw = self.f_search.get().strip().lower()
        rows = []
        for i, t in enumerate(self.pkg.tests):
            run = t['rid'] is not None
            if self.f_only_run.get() and not run:
                continue
            st = STATUS_TEXT.get(t['rstatus'] if run else t['tstatus'], '')
            if fs == 'PASS' and st != 'PASS':
                continue
            if fs == 'FAIL' and st != 'FAIL':
                continue
            if fs == '未執行' and st != '未執行':
                continue
            if kw and kw not in (t['name'] + ' ' + ' '.join(t['features'])).lower():
                continue
            tag = 'pass' if st == 'PASS' else ('fail' if st == 'FAIL' else 'notrun')
            rows.append((tag, t, st))
        key = self._sort_state.get('col', 'name')

        def sortkey(r):
            t, st = r[1], r[2]
            if key == 'status':
                return st
            if key == 'logs':
                return len(t['logs'])
            if key == 'features':
                return ', '.join(t['features'])
            return str(t.get(key) or '')

        rows.sort(key=sortkey, reverse=self._sort_state.get('rev', False))
        return rows

    def _populate(self):
        tree = self.tree
        tree.delete(*tree.get_children())
        if not self.pkg:
            return
        for tag, t, st in self._filtered_sorted_rows():
            tree.insert('', 'end', tags=(tag,), values=(
                st, t['name'], ', '.join(t['features'][:2]) + ('…' if len(t['features']) > 2 else ''),
                t['machine'], t['start'], t['end'], len(t['logs'])))

    def _sort_by(self, col):
        rev = not self._sort_state.get('rev', False) if self._sort_state.get('col') == col else False
        self._sort_state = {'col': col, 'rev': rev}
        self._populate()

    def _test_index_from_row(self, iid):
        vals = self.tree.item(iid, 'values')
        if not vals:
            return None
        name = vals[1]
        for i, t in enumerate(self.pkg.tests):
            if t['name'] == name and t['rid'] is not None:
                return i
        return None

    def _on_dbl(self, ev):
        iid = self.tree.identify_row(ev.y)
        if iid:
            self.export_dialog(self._test_index_from_row(iid))

    # --------------------------------------------------------------- 匯出
    def export_dialog(self, only_test=None, te_mode=True):
        if not self.pkg:
            messagebox.showinfo('尚未載入', '請先開啟 .hlk / .hlkx 檔案')
            return
        ExportDialog(self, self.pkg, only_test=only_test, te_mode=te_mode)

    def export_excel(self):
        """把「目前篩選條件」下的側項結果清單匯出成 Excel (.xlsx)"""
        if not self.pkg:
            messagebox.showinfo('尚未載入', '請先開啟 .hlk / .hlkx 檔案')
            return
        rows = self._filtered_sorted_rows()
        if not rows:
            messagebox.showinfo('匯出 Excel', '目前篩選條件下沒有側項')
            return
        s = self.pkg.summary()
        default = '%s_側項結果.xlsx' % re.sub(r'[<>:"/\\|?*]', '_',
                                              self.pkg.project_name or 'HLK')
        fp = filedialog.asksaveasfilename(
            title='匯出側項結果 Excel', parent=self, defaultextension='.xlsx',
            initialfile=default, initialdir=os.path.expanduser('~\\Desktop'),
            filetypes=[('Excel 活頁簿', '*.xlsx')])
        if not fp:
            return
        info = {'source': self.pkg.name, 'project': self.pkg.project_name,
                'total': s['total'], 'run': s['run'], 'pass': s['pass'],
                'fail': s['fail'], 'notrun': s['notrun']}
        data = [(st, t['name'], ', '.join(t['features']), t['machine'],
                 t['start'], t['end'], len(t['logs'])) for tag, t, st in rows]
        try:
            hlk_xlsx.write_results_xlsx(fp, info, data)
        except OSError as e:
            messagebox.showerror('匯出失敗', '寫入失敗（檔案是否正在 Excel 中開啟？）\n%s' % e,
                                 parent=self)
            return
        except Exception as e:
            messagebox.showerror('匯出失敗', '%s\n%s' % (e, traceback.format_exc()[:600]),
                                 parent=self)
            return
        self.status.set('已匯出 Excel：%s（%d 列）' % (os.path.basename(fp), len(data)))
        if messagebox.askyesno('Excel 已產生',
                               '已依目前篩選條件匯出 %d 列側項結果：\n%s\n\n是否開啟檔案？'
                               % (len(data), fp), parent=self):
            try:
                os.startfile(fp)
            except Exception:
                pass


def main():
    args = sys.argv[1:]
    if args and args[0] in ('--cli-export-all', '--cli-export-all-logs'):
        inpath, outdir = args[1], args[2]
        all_logs = args[0] == '--cli-export-all-logs'
        pkg = hlk_core.HlkPackage(inpath)
        items = []
        for t in pkg.tests:
            if t['rid'] is None:
                continue
            if all_logs:
                for l in t['logs']:
                    items.append({'test_name': t['name'], 'test_status': t['rstatus'],
                                  'log_name': l['name'], 'log_id': l['log_id'], 'task': l['task']})
            else:
                l = ExportDialog._pick_te(t)
                if l:
                    items.append({'test_name': t['name'], 'test_status': t['rstatus'],
                                  'log_name': l['name'], 'log_id': l['log_id'], 'task': l['task'],
                                  'out_name': t['name'], 'out_ext': '.htm'})
        def prog(i, n, nm):
            if i % 25 == 0 or i == n:
                print('%d/%d %s' % (i, n, nm))
        n, errs, idx = hlk_wtl.export_logs(pkg, items, outdir, progress=prog)
        print('匯出 %d 份 → %s' % (n, idx))
        for e in errs[:10]:
            print('錯誤:', e)
        return
    app = App()
    if args and os.path.isfile(args[0]):
        if args[0].lower().endswith('.wtl'):
            app.after(400, lambda: app.convert_wtl(args[0]))
        else:
            app.load_async(args[0])
    app.mainloop()


if __name__ == '__main__':
    main()
