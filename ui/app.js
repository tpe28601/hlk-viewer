/* HLK Viewer web UI — 對接 hlk_web.py（/api/pkg, /api/log, /api/export）。 */
'use strict';
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var state = {
    pkg: null,           // /api/pkg result（results: tests／project: runs+errors）
    sel: {},             // i -> true（選取要匯出 Te.wtl 的側項）
    sort: { key: 'name', dir: 1 },
    exporting: false,
    exTimer: null,
    loadTimer: null,
    rowTest: null,       // 彈窗目前測試項列
    ptab: 'runs',        // project 模式分頁: runs | errors | chunks
    projRows: null,      // project 模式目前顯示列（供 data-k 索引）
    chunkData: null,     // .hlkp Log 串流清單（lazy: 首次切分頁才 fetch /api/chunks）
    chunkLoading: false, // /api/chunks 進行中
    chunkErr: '',        // /api/chunks 失敗訊息（列表顯示重試按鈕）
    pkgSeq: 0,           // 封裝世代號: 異步回調比對, 丟棄換檔後的舊回應
    uploading: false,    // 拖曳上傳進行中
    rmScroll: 0,         // 單項 Log 清單捲動位置（進預覽再返回時還原）
    adSel: {},           // 所有類型 Log 匯出彈窗: 'i:l' -> true
    noticeTimer: null    // 通知卡自動關閉計時器
  };

  // ---------------------------------------------------------------- 通訊
  function getJson(url) {
    return fetch(url).then(function (r) { return r.json(); });
  }
  function postJson(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Toolbox-Request': '1' },
      body: JSON.stringify(body || {})
    }).then(function (r) { return r.json(); });
  }
  function fail(res) {
    var msg = res && res.error ? (res.error.message || res.error.code) : '不明錯誤';
    toast(msg);
    return Promise.reject(msg);
  }
  var toastTimer = null;
  function toast(msg, ok) {
    var el = $('toast');
    el.textContent = msg;
    el.classList.toggle('hlk-toast--ok', !!ok);
    el.classList.remove('hidden');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.add('hidden'); }, ok ? 2500 : 6000);
  }

  // 右下角通知卡: kind='load'|'ok'|'err'; ttl>0 自動消失, ttl=0 留到 hideNotice（載入中用）
  var NT_ICON = {
    load: '<svg class="hlk-spin" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M21 12a9 9 0 1 1-8.5-9" stroke-linecap="round"/></svg>',
    ok: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="9"/><path d="m8.5 12.2 2.4 2.4 4.6-5"/></svg>',
    err: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5"/><circle cx="12" cy="16.4" r="0.4" fill="currentColor"/></svg>'
  };
  function notice(title, sub, kind, ttl) {
    clearTimeout(state.noticeTimer);
    kind = kind || 'load';
    $('nt-icon').innerHTML = NT_ICON[kind] || NT_ICON.load;
    $('nt-title').textContent = title || '';
    $('nt-sub').textContent = sub || '';
    var card = $('nt-card');
    card.classList.remove('hidden');
    card.classList.toggle('hlk-notice--ok', kind === 'ok');
    card.classList.toggle('hlk-notice--err', kind === 'err');
    state.noticeTimer = ttl > 0 ? setTimeout(hideNotice, ttl) : null;
  }
  function hideNotice() {
    clearTimeout(state.noticeTimer);
    state.noticeTimer = null;
    $('nt-card').classList.add('hidden');
  }

  // ---------------------------------------------------------------- 開檔／關檔
  function setOpenUi(busy, ready) {
    $('btn-open').disabled = busy;
    $('btn-close').disabled = busy;
    $('btn-open').classList.toggle('tb-btn--primary', !busy);
    $('btn-close').classList.toggle('hidden', !ready && !busy);
    setBadge(busy ? '載入中…' : (ready ? '已載入' : '尚未載入'),
             busy ? 'warn' : (ready ? 'ok' : ''));
  }
  function setBadge(text, kind) {
    var b = $('state-badge');
    b.textContent = text;
    b.className = 'tb-badge' + (kind ? ' tb-badge--' + kind : '');
  }
  function openPkg() {
    var path = $('path-input').value.trim().replace(/^"|"$/g, '');
    if (!path) { toast('請輸入或以「瀏覽」選擇 .hlk/.hlkx/.hlkp/.wtl 檔案'); return; }
    setOpenUi(true, false);
    postJson('/api/open', { path: path }).then(function (res) {
      if (!res.ok) { setOpenUi(false, false); notice('開啟失敗', res.error && res.error.message, 'err', 12000); return fail(res); }
      notice('正在載入 HLK 檔案…', path.replace(/.*[\\/]/, ''), 'load', 0);
      pollPkg();
    }, function (e) { setOpenUi(false, false); notice('連不上伺服器', String(e), 'err', 12000); toast('連不上伺服器：' + e); });
  }
  function pollPkg() {
    clearTimeout(state.loadTimer);
    state.loadTimer = setTimeout(function () {
      getJson('/api/pkg').then(function (res) {
        var r = res.result || {};
        if (r.state === 'loading') { setOpenUi(true, false); pollPkg(); return; }
        if (r.state === 'error') {
          setOpenUi(false, false);
          $('wtl-card').classList.add('hidden');   // 開封裝檔失敗: 不殘留 .wtl 單檔卡片
          notice('載入失敗', String(r.error || '').split('\n')[0], 'err', 12000);
          toast('載入失敗：' + String(r.error || '').split('\n')[0]);
          return;
        }
        if (r.state === 'ready') {
          notice('載入完成', r.path && r.path.replace(/.*[\\/]/, ''), 'ok', 2500);
          applyPkg(r);
          return;
        }
        setOpenUi(false, !!state.pkg);      // idle
        hideNotice();
      }, function () { setOpenUi(false, false); notice('連線中斷', '輪詢載入狀態失敗', 'err', 12000); });
    }, 600);
  }
  function closePkg() {
    postJson('/api/close', {}).then(function (res) {
      if (!res.ok) return fail(res);
      state.pkg = null; state.sel = {}; state.projRows = null; state.chunkData = null;
      state.pkgSeq++; state.chunkLoading = false; state.chunkErr = '';
      hideNotice();
      closePc();
      $('ad-mask').classList.add('hidden');
      $('list-card').classList.add('hidden');
      $('wtl-card').classList.add('hidden');
      $('chips').classList.add('hidden');
      $('btn-close').classList.add('hidden');
      $('file-label').textContent = '開啟 .hlk/.hlkx/.hlkp 以檢視側項與 Log（單一 .wtl 可直開預覽）';
      $('empty').classList.remove('hidden');
      setBadge('尚未載入', '');
      state.ptab = 'runs';
      syncPTabUi();
      setModeUi();
    });
  }
  function applyPkg(r) {
    closeRow();                              // 換檔時收掉舊 Log/錯誤彈窗, 避免打到已換掉的封裝
    closePc();
    $('ms-mask').classList.add('hidden');
    $('ad-mask').classList.add('hidden');
    state.pkg = r; state.sel = {}; state.projRows = null; state.chunkData = null;
    state.pkgSeq++;                            // 作廢進行中的 /api/chunks 回應
    state.chunkLoading = false; state.chunkErr = '';
    setOpenUi(false, true);
    $('empty').classList.add('hidden');
    $('list-card').classList.remove('hidden');
    $('btn-close').classList.remove('hidden');
    $('file-label').textContent = r.path;
    if (r.kind === 'wtl') {                    // 獨立 .wtl 單檔模式（v1.2.7）
      $('list-card').classList.add('hidden');
      $('chips').classList.add('hidden');
      $('wtl-label').textContent = r.path + '（' + humanSize(r.size || 0) + '）';
      $('wtl-dl').href = '/api/wtl?dl=1';
      $('wtl-card').classList.remove('hidden');
      setModeUi();
      openWtlPc();                             // 開檔即直接預覽
      return;
    }
    $('wtl-card').classList.add('hidden');
    var s = r.summary || {};
    var chips;
    if (r.kind === 'project') {
      state.ptab = 'runs';
      syncPTabUi();
      state.sort = { key: 'time', dir: -1 };
      var info = r.info || {}, pi = info.package || {}, targets = info.targets || [];
      chips = [
        ['專案', r.project || r.name, 'accent'],
        ['Package', (pi.type || '?') + (pi.kit ? ' · Kit ' + pi.kit : ''), ''],
        ['Target', targets.map(function (t) { return t.name; }).join(', ') || '—', ''],
        ['執行次數', s.run, ''],
        ['Passed', s.pass, 'ok'],
        ['Failed', s.fail, s.fail ? 'danger' : ''],
        ['錯誤', s.errors, s.errors ? 'warn' : '']
      ];
      (info.instances || []).forEach(function (inst, k) {
        if (!inst.status) return;
        chips.push(['Instance ' + (k + 1), inst.status + '（Features ' + inst.features.length + '）',
                    inst.status === 'Fail' ? 'danger' : (inst.status === 'Pass' ? 'ok' : '')]);
      });
    } else {
      if (state.ptab !== 'runs') { state.ptab = 'runs'; syncPTabUi(); }   // .hlkp 殘留的錯誤/串流視圖不適用於測試計畫檔
      if (['status', 'name', 'feature', 'machine', 'start', 'end', 'logs'].indexOf(state.sort.key) < 0)
        state.sort = { key: 'name', dir: 1 };   // project 殘留的 sort key 對 results 無效
      chips = [
        ['專案', r.project || r.name, 'accent'],
        ['測試項', s.total, ''],
        ['已執行', s.run, ''],
        ['PASS', s.pass, 'ok'],
        ['FAIL', s.fail, s.fail ? 'danger' : ''],
        ['未執行', s.notrun, ''],
        ['Log', s.nlogs, '']
      ];
    }
    $('chips').innerHTML = chips.map(function (c) {
      return '<span class="tb-badge' + (c[2] ? ' tb-badge--' + c[2] : '') + '">' +
             esc(c[0]) + '：' + esc(String(c[1] == null ? '-' : c[1])) + '</span>';
    }).join('');
    $('chips').classList.remove('hidden');
    setModeUi();
    if (r.kind !== 'project') {
      getJson('/api/export').then(function (res) {
        if (res.ok && res.result && res.result.defaultOutdir)
          $('outdir-input').placeholder = res.result.defaultOutdir;
      });
    }
    render();
  }

  // ---------------------------------------------------------------- 結果／專案模式切換
  function setModeUi() {
    var prj = !!(state.pkg && state.pkg.kind === 'project');
    // 「錯誤／Log 串流」分頁只對 .hlkp 專案檔有意義（原 tb-seg 三選一改為分頁列）
    $('ptab-errors').classList.toggle('hidden', !prj);
    $('ptab-chunks').classList.toggle('hidden', !prj);
    $('f-run-label').classList.toggle('hidden', prj);
    $('tb-export-row').classList.toggle('hidden', prj);
    $('thead-res').classList.toggle('hidden', prj);
    $('thead-prj').classList.toggle('hidden', !prj || state.ptab !== 'runs');
    $('thead-err').classList.toggle('hidden', !prj || state.ptab !== 'errors');
    $('thead-chunk').classList.toggle('hidden', !prj || state.ptab !== 'chunks');
    $('f-search').placeholder = prj
      ? (state.ptab === 'chunks' ? '搜尋來源／機器／時間…' : '搜尋測試項／機器／訊息…')
      : '搜尋側項名稱／機器／功能…';
    setStatusOptions();
  }
  function setStatusOptions() {
    var sel = $('f-status');
    var prj = !!(state.pkg && state.pkg.kind === 'project');
    if (prj && state.ptab === 'runs') {
      sel.innerHTML = '<option value="">全部狀態</option>' +
                      '<option value="Passed">Passed</option>' +
                      '<option value="Failed">Failed</option>';
    } else if (prj && state.ptab === 'errors') {
      sel.innerHTML = '<option value="">全部類型</option>' +
                      '<option value="Error">Error</option>' +
                      '<option value="Failure">Failure</option>';
    } else if (prj) {
      sel.innerHTML = '<option value="">全部類型</option>' +
                      '<option value="wtl">測試 Log（WTL）</option>' +
                      '<option value="comm">通訊訊息</option>' +
                      '<option value="other">其他</option>';
    } else {
      sel.innerHTML = '<option value="">全部狀態</option><option value="1">PASS</option>' +
                      '<option value="2">FAIL</option><option value="0">未執行</option>';
    }
    sel.value = '';
  }
  function setPTab(p) {
    if (state.ptab === p) return;
    state.ptab = p;
    syncPTabUi();
    state.sort = { key: p === 'chunks' ? 'id' : 'time', dir: -1 };
    setModeUi();
    if (p === 'chunks' && !state.chunkData && !state.chunkLoading) loadChunks();
    render();
  }
  // 分頁列（tb-tab）與 state.ptab 同步（與 Build Runner／Git Ref Manager 同用 is-active）
  function syncPTabUi() {
    var p = state.ptab;
    $('ptab-runs').classList.toggle('is-active', p === 'runs');
    $('ptab-errors').classList.toggle('is-active', p === 'errors');
    $('ptab-chunks').classList.toggle('is-active', p === 'chunks');
  }
  function runBadge(st) {
    if (st === 'Passed') return '<span class="tb-badge tb-badge--ok">Passed</span>';
    if (st === 'Failed' || st === 'Fail') return '<span class="tb-badge tb-badge--danger">' + esc(st) + '</span>';
    return '<span class="tb-badge tb-badge--warn">' + esc(st || '?') + '</span>';
  }
  function fmtDur(sec) {
    sec = +sec || 0;
    if (sec < 60) return sec + 's';
    if (sec < 3600) return Math.floor(sec / 60) + 'm' + (sec % 60 ? (sec % 60) + 's' : '');
    return Math.floor(sec / 3600) + 'h' + Math.floor((sec % 3600) / 60) + 'm';
  }
  function filteredProj() {
    var isRuns = state.ptab === 'runs';
    var src = (isRuns ? state.pkg.runs : state.pkg.errors) || [];
    var st = $('f-status').value;
    var q = $('f-search').value.trim().toLowerCase();
    var rows = src.filter(function (r) {
      if (st) {
        if (isRuns) {
          // runBadge/summary 相容 'Fail', 篩選也一併接受
          var ok = st === 'Failed' ? (r.status === 'Failed' || r.status === 'Fail')
                                   : r.status === st;
          if (!ok) return false;
        } else if (r.type !== st) {
          return false;
        }
      }
      if (q) {
        var hay = (isRuns ? r.job + ' ' + r.target + ' ' + r.status
                          : r.type + ' ' + r.message + ' ' + (r.source || '') + ' ' +
                            (r.machine || '') + ' ' + (r.job || '')).toLowerCase();
        if (hay.indexOf(q) < 0) return false;
      }
      return true;
    });
    var k = state.sort.key, d = state.sort.dir;
    rows.sort(function (a, b) {
      var x = a[k], y = b[k];
      if (typeof x !== 'number' || typeof y !== 'number') {
        x = String(x == null ? '' : x).toLowerCase();
        y = String(y == null ? '' : y).toLowerCase();
      }
      return (x < y ? -1 : x > y ? 1 : 0) * d;
    });
    return rows;
  }
  function renderProject() {
    if (state.ptab === 'chunks') { renderChunks(); return; }
    var rows = filteredProj();
    state.projRows = rows;
    var isRuns = state.ptab === 'runs';
    var html = rows.map(function (r, idx) {
      if (isRuns) {
        return '<tr data-k="' + idx + '">' +
          '<td class="tb-mono tb-small">' + esc(r.time || '—') + '</td>' +
          '<td>' + runBadge(r.status) + '</td>' +
          '<td class="hlk-name" title="' + esc(r.job) + '">' + esc(r.job) + '</td>' +
          '<td>' + esc(r.target || '—') + '</td>' +
          '<td class="hnum tb-small">' + fmtDur(r.duration) + '</td>' +
          '<td>' + (r.bugcheck ? '<span class="tb-badge tb-badge--danger">' + esc(r.bugcheck) + '</span>' : '—') + '</td>' +
          '</tr>';
      }
      return '<tr class="hlk-errrow" data-k="' + idx + '" title="點擊看完整訊息">' +
        '<td class="tb-mono tb-small">' + esc(r.time || '—') + '</td>' +
        '<td><span class="tb-badge tb-badge--' + (r.type === 'Failure' ? 'warn' : 'danger') + '">' +
        esc(r.type) + '</span></td>' +
        '<td class="tb-small">' + (r.source ? '<span class="tb-badge">' + esc(r.source) + '</span> ' : '') +
        '<span class="tb-muted">' + esc(r.machine || '—') + '</span></td>' +
        '<td class="hlk-errmsg">' + esc(r.message) + '</td>' +
        '</tr>';
    }).join('');
    var total = ((isRuns ? state.pkg.runs : state.pkg.errors) || []).length;
    $('tbody').innerHTML = html ||
      '<tr><td colspan="' + (isRuns ? 6 : 4) + '" class="tb-muted" style="text-align:center;padding:18px">（無符合篩選條件的資料）</td></tr>';
    $('row-count').textContent = rows.length + ' / ' + total + ' 筆';
    document.querySelectorAll('th.sortable').forEach(function (th) {
      th.classList.toggle('sorted', th.dataset.sort === state.sort.key);
      th.dataset.dir = th.dataset.sort === state.sort.key ? (state.sort.dir > 0 ? 'asc' : 'desc') : '';
    });
  }
  // ---------------------------------------------------------------- Log 串流（.hlkp streamdata chunks）
  function loadChunks() {
    var seq = state.pkgSeq;                    // 綁定封裝世代: 換檔／關檔後的舊回應一律丟棄
    state.chunkLoading = true; state.chunkErr = '';
    getJson('/api/chunks').then(function (res) {
      if (seq !== state.pkgSeq) return;
      state.chunkLoading = false;
      if (!res.ok)
        state.chunkErr = (res.error && (res.error.message || res.error.code)) || '不明錯誤';
      else
        state.chunkData = (res.result && res.result.chunks) || [];
      if (state.pkg && state.ptab === 'chunks') render();
    }, function () {
      if (seq !== state.pkgSeq) return;
      state.chunkLoading = false;
      state.chunkErr = '連不上伺服器';
      if (state.pkg && state.ptab === 'chunks') render();
    });
  }
  function filteredChunks() {
    var rows = (state.chunkData || []).filter(function (c) {
      var st = $('f-status').value;
      if (st && c.kind !== st) return false;
      var q = $('f-search').value.trim().toLowerCase();
      if (q && (c.exe + ' ' + c.machine + ' ' + c.time).toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
    var k = state.sort.key, d = state.sort.dir;
    rows.sort(function (a, b) {
      var x = a[k], y = b[k];
      if (typeof x !== 'number' || typeof y !== 'number') {
        x = String(x == null ? '' : x).toLowerCase();
        y = String(y == null ? '' : y).toLowerCase();
      }
      return (x < y ? -1 : x > y ? 1 : 0) * d;
    });
    return rows;
  }
  var CHUNK_KIND = {
    wtl: ['WTL', 'accent', 'WTT-Logger 測試 log（同 Te.wtl 格式）'],
    comm: ['Comm', 'warn', 'Controller 通訊訊息（含 Log 分享路徑）'],
    other: ['其他', '', '']
  };
  function renderChunks() {
    var head = '<tr><td colspan="6" class="tb-muted" style="text-align:center;padding:18px">';
    if (state.chunkErr) {
      $('tbody').innerHTML = head + '掃描 Log 串流失敗：' + esc(state.chunkErr) +
        '　<button class="tb-btn tb-btn--sm tb-btn--ghost btn-chunk-retry">重試</button></td></tr>';
      $('row-count').textContent = '';
      return;
    }
    if (!state.chunkData) {
      $('tbody').innerHTML = head + (state.chunkLoading ? '掃描 Log 串流中…' : '') + '</td></tr>';
      $('row-count').textContent = '';
      if (!state.chunkLoading) loadChunks();
      return;
    }
    var rows = filteredChunks();
    var html = rows.map(function (c) {
      var k = CHUNK_KIND[c.kind] || CHUNK_KIND.other;
      var srcTxt = (c.exe || '') + (c.machine ? (c.exe ? ' @ ' : '') + c.machine : '');
      return '<tr data-c="' + esc(c.id) + '" title="' + esc(k[2] || '點擊預覽') + '">' +
        '<td class="hnum tb-mono tb-small">' + esc(c.id) + '</td>' +
        '<td><span class="tb-badge' + (k[1] ? ' tb-badge--' + k[1] : '') + '">' + k[0] + '</span></td>' +
        '<td class="hlk-name" title="' + esc(srcTxt) + '">' + (srcTxt ? esc(srcTxt) : '—') + '</td>' +
        '<td class="tb-mono tb-small">' + esc(c.time || '—') + '</td>' +
        '<td class="hnum tb-small">' + humanSize(c.size) + '</td>' +
        '<td><button class="tb-btn tb-btn--sm tb-btn--ghost btn-chunk-pv" data-c="' + esc(c.id) + '">預覽</button></td>' +
        '</tr>';
    }).join('');
    $('tbody').innerHTML = html || head + '（無符合篩選條件的資料）</td></tr>';
    $('row-count').textContent = rows.length + ' / ' + state.chunkData.length + ' 條';
    document.querySelectorAll('th.sortable').forEach(function (th) {
      th.classList.toggle('sorted', th.dataset.sort === state.sort.key);
      th.dataset.dir = th.dataset.sort === state.sort.key ? (state.sort.dir > 0 ? 'asc' : 'desc') : '';
    });
  }
  function openPc(cid) {
    var c = (state.chunkData || []).filter(function (g) { return g.id === cid; })[0] || {};
    $('pc-title').textContent = 'Log chunk ' + cid + '（' + (c.kind || '?') + '）';
    $('pc-frame').src = '/api/pchunk?c=' + cid;
    $('pc-dl').href = '/api/pchunk?c=' + cid + '&dl=1';
    $('pc-dl').classList.remove('hidden');
    $('pc-dl-htm').href = '/api/pchunk?c=' + cid + '&dl=htm';
    $('pc-note').textContent =
      [c.exe, c.machine, c.time, humanSize(c.size || 0)].filter(Boolean).join('　·　');
    $('pc-mask').classList.remove('hidden');
  }
  // 獨立 .wtl 單檔模式：同一個預覽彈窗, 但來源是 /api/wtl（原始檔在使用者手上, 不收原始檔）
  function openWtlPc() {
    $('pc-title').textContent = 'WTL 預覽：' + (state.pkg ? state.pkg.name : '');
    $('pc-frame').src = '/api/wtl';
    $('pc-dl').classList.add('hidden');
    $('pc-dl-htm').href = '/api/wtl?dl=1';
    $('pc-note').textContent = '獨立 .wtl（無 test config 脈絡, 為 Complete Test Log 單頁）';
    $('pc-mask').classList.remove('hidden');
  }
  function closePc() {
    $('pc-mask').classList.add('hidden');
    $('pc-frame').src = 'about:blank';
  }

  function showError(r) {
    $('ms-title').textContent = (r.type || 'Error') + '　';
    $('ms-title').insertAdjacentHTML('beforeend',
      '<span class="tb-badge tb-badge--danger">' + esc(r.time || '') + '</span>');
    var meta = [];
    if (r.source) meta.push('來源：' + r.source);
    if (r.machine) meta.push('機器：' + r.machine);
    if (r.job) meta.push('工作：' + r.job);
    $('ms-meta').textContent = meta.join('　·　');
    $('ms-meta').classList.toggle('hidden', !meta.length);
    $('ms-body').textContent = r.message || '（無訊息）';
    $('ms-note').textContent = '時間：' + (r.time || '—');
    $('ms-mask').classList.remove('hidden');
  }

  // ---------------------------------------------------------------- 清單
  function filtered() {
    if (!state.pkg || state.pkg.kind !== 'results') return [];
    var st = $('f-status').value;
    var q = $('f-search').value.trim().toLowerCase();
    var runOnly = $('f-run').checked;
    var rows = state.pkg.tests.filter(function (t) {
      if (runOnly && !t.run) return false;
      if (st === '0' && t.run) return false;
      if (st === '1' && !(t.run && t.status === 1)) return false;
      if (st === '2' && !(t.run && t.status === 2)) return false;
      if (q) {
        var hay = (t.name + ' ' + t.machine + ' ' + t.features.join(' ')).toLowerCase();
        if (hay.indexOf(q) < 0) return false;
      }
      return true;
    });
    var k = state.sort.key, d = state.sort.dir;
    rows.sort(function (a, b) {
      var x, y;
      if (k === 'status') { x = a.run ? a.status : -1; y = b.run ? b.status : -1; }
      else if (k === 'logs') { x = a.logs.length; y = b.logs.length; }
      else if (k === 'feature') { x = a.features.join(','); y = b.features.join(','); }
      else { x = a[k] || ''; y = b[k] || ''; }
      return (x < y ? -1 : x > y ? 1 : 0) * d || (a.name < b.name ? -1 : 1);
    });
    return rows;
  }
  function statusBadge(t) {
    if (!t.run) return '<span class="tb-badge">未執行</span>';
    if (t.status === 1) return '<span class="tb-badge tb-badge--ok">PASS</span>';
    if (t.status === 2) return '<span class="tb-badge tb-badge--danger">FAIL</span>';
    return '<span class="tb-badge">' + esc(t.statusText || '?') + '</span>';
  }
  function render() {
    if (!state.pkg) return;
    if (state.pkg.kind === 'wtl') return;      // 單檔模式無清單可畫
    if (state.pkg.kind === 'project') { renderProject(); return; }
    var rows = filtered();
    var html = rows.map(function (t) {
      var ck = t.run && t.te
        ? '<input type="checkbox" class="ck-row" data-i="' + t.i + '"' + (state.sel[t.i] ? ' checked' : '') + '>'
        : '<input type="checkbox" disabled title="無 Te.wtl 或未執行">';
      return '<tr data-i="' + t.i + '"' + (state.sel[t.i] ? ' class="hlk-sel"' : '') + '>' +
        '<td class="hck">' + ck + '</td>' +
        '<td>' + statusBadge(t) + '</td>' +
        '<td class="hlk-name" title="' + esc(t.name) + '">' + esc(t.name) + '</td>' +
        '<td class="tb-muted hlk-feat" title="' + esc(t.features.join(', ')) + '">' + esc(t.features.join(', ') || '—') + '</td>' +
        '<td>' + esc(t.machine || '—') + '</td>' +
        '<td class="tb-mono tb-small">' + esc(t.start || '—') + '</td>' +
        '<td class="tb-mono tb-small">' + esc(t.end || '—') + '</td>' +
        '<td class="hnum">' + (t.run ? t.logs.length : '—') + '</td>' +
        '<td>' + (t.te ? '<button class="tb-btn tb-btn--sm tb-btn--ghost btn-te" data-i="' + t.i + '">預覽</button>' : '') + '</td>' +
        '</tr>';
    }).join('');
    $('tbody').innerHTML = html || '<tr><td colspan="9" class="tb-muted" style="text-align:center;padding:18px">（無符合篩選條件的測試項）</td></tr>';
    $('row-count').textContent = rows.length + ' / ' + state.pkg.tests.length + ' 項';
    updateSelCount();
    document.querySelectorAll('th.sortable').forEach(function (th) {
      th.classList.toggle('sorted', th.dataset.sort === state.sort.key);
      th.dataset.dir = th.dataset.sort === state.sort.key ? (state.sort.dir > 0 ? 'asc' : 'desc') : '';
    });
  }
  function updateSelCount() {
    var n = Object.keys(state.sel).length;
    $('sel-count').textContent = n;
    $('btn-export').disabled = !n || state.exporting;
  }
  function selectVisible(pred, replace) {
    if (replace) state.sel = {};
    filtered().forEach(function (t) {
      if (t.run && t.te && (!pred || pred(t))) state.sel[t.i] = true;
    });
    render();
  }

  // ---------------------------------------------------------------- 匯出
  function startExport(mode, items) {
    var outdir = $('outdir-input').value.trim().replace(/^"|"$/g, '');
    state.exporting = true;
    $('btn-export').disabled = true;
    $('ex-mask').classList.remove('hidden');
    $('ex-running').classList.remove('hidden');
    $('ex-done').classList.add('hidden');
    $('ex-index').classList.add('hidden');
    $('ex-bar').style.width = '0%';
    $('ex-count').textContent = '0 / ' + items.length;
    $('ex-current').textContent = '';
    postJson('/api/export', { mode: mode, items: items, outdir: outdir || undefined })
      .then(function (res) {
        if (!res.ok) {
          state.exporting = false;
          updateSelCount();
          $('ex-mask').classList.add('hidden');
          return fail(res);
        }
        pollExport();
      }, function () {
        state.exporting = false;
        updateSelCount();
        $('ex-mask').classList.add('hidden');
        toast('連不上伺服器（匯出未開始）');
      });
  }
  function pollExport() {
    clearInterval(state.exTimer);
    state.exTimer = setInterval(function () {
      getJson('/api/export').then(function (res) {
        var j = res.result || {};
        if (j.state === 'running') {
          var pct = j.n ? Math.round(100 * j.i / j.n) : 0;
          $('ex-bar').style.width = pct + '%';
          $('ex-count').textContent = j.i + ' / ' + j.n;
          $('ex-current').textContent = j.current || '';
          return;
        }
        clearInterval(state.exTimer);
        state.exporting = false;
        updateSelCount();
        $('ex-running').classList.add('hidden');
        $('ex-done').classList.remove('hidden');
        $('ex-dir').textContent = j.outdir || '';
        if (j.state === 'done') {
          var r = j.result || {};
          $('ex-result').textContent = '完成';
          $('ex-result').className = 'tb-badge tb-badge--ok';
          $('ex-summary').textContent = '已匯出 ' + r.count + ' 個 Log' +
            (r.errors && r.errors.length ? '，' + r.errors.length + ' 筆失敗' : '');
          var errs = $('ex-errors');
          errs.innerHTML = (r.errors || []).map(function (e) {
            return '<li class="tb-small">' + esc(typeof e === 'string' ? e : (e.name + '：' + e.error)) + '</li>';
          }).join('');
          errs.classList.toggle('hidden', !(r.errors || []).length);
          if (r.indexUrl) {
            $('ex-index').href = r.indexUrl;
            $('ex-index').classList.remove('hidden');
          }
          toast('匯出完成', true);
        } else {
          $('ex-result').textContent = '失敗';
          $('ex-result').className = 'tb-badge tb-badge--danger';
          $('ex-summary').textContent = j.error || '匯出發生錯誤';
        }
      }, function () {
        // 一次網路錯誤不重試：明確結束, 免得匯出狀態永久卡住
        clearInterval(state.exTimer);
        state.exporting = false;
        updateSelCount();
        $('ex-running').classList.add('hidden');
        $('ex-done').classList.remove('hidden');
        $('ex-result').textContent = '失敗';
        $('ex-result').className = 'tb-badge tb-badge--danger';
        $('ex-summary').textContent = '輪詢匯出狀態失敗（伺服器可能已重啟）';
      });
    }, 500);
  }

  // ------------------------------------------------ 所有類型 Log 匯出（跨側項, 對照 GUI「Log→進階」）
  var AD_RENDER_CAP = 3000;   // 彈窗 DOM 顯示上限（極大封裝防卡頓; 匯出上限另由伺服器把關 2000）
  var adItems = {};           // 'i:l' -> {i, l, name}（給「只選 .wtl/.html」判斷副檔名）
  function buildAdList() {
    var q = $('ad-search').value.trim().toLowerCase();
    var html = [], n = 0, trunc = false;
    adItems = {};
    filtered().forEach(function (t) {
      if (trunc) return;
      var logs = t.logs.filter(function (l) {
        if (!q) return true;
        return (t.name + ' ' + l.name + ' ' + (l.task || '')).toLowerCase().indexOf(q) >= 0;
      });
      if (!logs.length) return;
      html.push('<div class="hlk-ad-group">' + esc(t.name) + '</div>');
      logs.forEach(function (l) {
        if (n >= AD_RENDER_CAP) { trunc = true; return; }
        var k = t.i + ':' + l.l;
        n++;
        adItems[k] = { i: t.i, l: l.l, name: l.name };
        html.push('<label class="hlk-ad-item"><input type="checkbox" class="ad-ck" data-k="' + k +
          '"' + (state.adSel[k] ? ' checked' : '') + '>' +
          '<span class="hlk-ad-name" title="' + esc(l.name) + '">' + esc(l.name) + '</span>' +
          '<span class="tb-muted tb-small">' + esc(l.task || '—') + ' · ' + humanSize(l.size) + '</span></label>');
      });
    });
    $('ad-list').innerHTML = html.join('') ||
      '<p class="tb-muted" style="text-align:center;padding:16px">（無符合條件的 Log）</p>';
    var tr = $('ad-trunc');
    tr.textContent = trunc ? 'Log 超過顯示上限 ' + AD_RENDER_CAP + ' 筆，請用上方過濾縮小範圍' : '';
    tr.classList.toggle('hidden', !trunc);
    updateAdCount();
  }
  function updateAdCount() {
    var n = Object.keys(state.adSel).length;
    $('ad-count').textContent = n;
    $('ad-export').disabled = !n;
  }
  // 預設勾選集只作用「目前已顯示」項目; 被過濾掉的既有勾選保留（所見≠所送的隱藏項仍會匯出）。
  function adSetChecks(pred) {                    // pred(entry)->bool; 無 pred = 顯示項目全選
    $('ad-list').querySelectorAll('.ad-ck').forEach(function (c) {
      var k = c.dataset.k;
      var on = !pred || !!pred(adItems[k] || {});
      c.checked = on;
      if (on) state.adSel[k] = true; else delete state.adSel[k];
    });
    updateAdCount();
  }
  function openAd() {
    if (!state.pkg || state.pkg.kind !== 'results') return;
    state.adSel = {};
    $('ad-search').value = '';
    buildAdList();
    $('ad-mask').classList.remove('hidden');
  }
  function closeAd() { $('ad-mask').classList.add('hidden'); }
  function adSubmit() {
    var items = Object.keys(state.adSel).map(function (k) {
      var p = k.split(':');
      return { i: +p[0], l: +p[1] };
    });
    if (!items.length) return;
    if (items.length > 2000) { toast('項目超過 2000 筆，請縮小勾選範圍'); return; }
    closeAd();
    startExport('all', items);
  }

  // ---------------------------------------------------------------- 單項彈窗
  function openRow(i) {
    var t = state.pkg.tests[i];
    if (!t) return;
    state.rowTest = t;
    state.rmScroll = 0;                        // 新側項從頭看
    $('rm-title').textContent = t.name + '　';
    $('rm-title').insertAdjacentHTML('beforeend', statusBadge(t));
    $('rm-tbody').innerHTML = t.logs.map(function (l) {
      var btn = l.pv
        ? '<button class="tb-btn tb-btn--sm btn-preview" data-l="' + l.l + '">預覽</button>'
        : '<button class="tb-btn tb-btn--sm tb-btn--ghost btn-dl" data-l="' + l.l + '" title="二進位檔：下載">下載</button>';
      return '<tr><td class="hlk-name" title="' + esc(l.name) + '">' + esc(l.name) + '</td>' +
        '<td class="tb-muted" title="' + esc(l.task || '') + '">' + esc(l.task || '—') +
        '</td><td class="hnum tb-small">' + humanSize(l.size) + '</td>' +
        '<td>' + btn + '</td></tr>';
    }).join('') || '<tr><td colspan="4" class="tb-muted" style="text-align:center;padding:14px">（無 Log）</td></tr>';
    showRowList();
    $('rm-export').disabled = !t.logs.length;
    $('row-mask').classList.remove('hidden');
  }
  function humanSize(n) {
    if (!n) return '0 B';
    var u = ['B', 'KB', 'MB', 'GB'], k = 0;
    while (n >= 1024 && k < 3) { n /= 1024; k++; }
    return (k === 0 ? n : n.toFixed(1)) + ' ' + u[k];
  }
  function showRowList() {
    var body = document.querySelector('#row-mask .hlk-modal__body');
    $('rm-list').classList.remove('hidden');
    body.scrollTop = state.rmScroll;           // 還原清單捲動位置（隱藏時會被歸零）
    $('rm-preview').classList.add('hidden');
    $('rm-back').classList.add('hidden');
    $('rm-frame').src = 'about:blank';
    $('rm-note').textContent = '';
    $('rm-dl').classList.add('hidden');
  }
  function previewLog(l) {
    var t = state.rowTest;
    var url = '/api/log?i=' + t.i + '&l=' + l;
    var log = t.logs.filter(function (g) { return g.l === +l; })[0] || {};
    if (!log.pv) { window.open(url, '_blank'); return; }   // 二進位: 伺服端回 attachment
    state.rmScroll = document.querySelector('#row-mask .hlk-modal__body').scrollTop;
    $('rm-list').classList.add('hidden');
    $('rm-preview').classList.remove('hidden');
    $('rm-back').classList.remove('hidden');
    $('rm-frame').src = url;
    $('rm-note').textContent = log.name || '';
    var dl = $('rm-dl');
    dl.href = url + '&dl=1';                               // 下載轉換後的 .htm
    dl.classList.remove('hidden');
  }
  function closeRow() {
    $('row-mask').classList.add('hidden');
    $('rm-frame').src = 'about:blank';
  }

  // ---------------------------------------------------------------- 檔案挑選（ui-kit tb-dirpicker／/api/browse）
  function bdOpen() {
    var p = $('path-input').value.trim().replace(/^"|"$/g, '');
    TbDirPicker.open({
      title: '瀏覽 HLK 檔案',
      mode: 'file',
      extensions: ['.hlk', '.hlkx', '.hlkp', '.wtl'],
      start: p,
      fetchDir: function (path) {
        return getJson('/api/browse?path=' + encodeURIComponent(path || '')).then(function (res) {
          if (!res.ok) {
            throw new Error((res.error && (res.error.message || res.error.code)) || '瀏覽失敗');
          }
          return res.result || {};
        });
      },
    }).then(function (picked) {
      if (!picked) return;
      $('path-input').value = picked;
      openPkg();
    });
  }

  // ---------------------------------------------------------------- 拖曳上傳（/api/upload）
  function hasFiles(e) {
    return e.dataTransfer &&
           Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') >= 0;
  }
  function uploadFile(f) {
    if (!/\.(hlk|hlkx|hlkp|wtl)$/i.test(f.name || '')) {
      $('drop-mask').classList.add('hidden');
      toast('僅接受 .hlk/.hlkx/.hlkp/.wtl 檔案（拖曳的是：' + (f.name || '未知檔案') + '）');
      return;
    }
    if (f.size > 4 * 1024 * 1024 * 1024 || f.size <= 0) {   // 與伺服器 UPLOAD_MAX 一致
      $('drop-mask').classList.add('hidden');
      toast('檔案大小不合法（需 0 < size ≤ 4 GB）：' + f.name);
      return;
    }
    state.uploading = true;
    $('drop-text').textContent = '上傳中：' + f.name + '（' + humanSize(f.size) + '）';
    $('drop-prog-wrap').classList.remove('hidden');
    $('drop-bar').style.width = '0%';
    $('drop-note').textContent = '';
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload');
    xhr.setRequestHeader('X-Toolbox-Request', '1');
    xhr.setRequestHeader('X-Filename', encodeURIComponent(f.name));
    xhr.upload.onprogress = function (ev) {
      if (!ev.lengthComputable) return;
      $('drop-bar').style.width = Math.round(100 * ev.loaded / ev.total) + '%';
      $('drop-note').textContent = humanSize(ev.loaded) + ' / ' + humanSize(ev.total);
    };
    xhr.onload = function () {
      state.uploading = false;
      var res = {};
      try { res = JSON.parse(xhr.responseText); } catch (err) {}
      $('drop-mask').classList.add('hidden');
      if (xhr.status === 200 && res.ok && res.result) {
        $('path-input').value = res.result.path;
        notice('上傳完成，開始分析…', f.name + '（' + humanSize(f.size) + '）', 'ok', 2000);
        openPkg();
      } else {
        var emsg = (res.error && (res.error.message || res.error.code)) || ('HTTP ' + xhr.status);
        notice('上傳失敗', emsg, 'err', 12000);
        toast('上傳失敗：' + emsg);
      }
    };
    xhr.onerror = function () {
      state.uploading = false;
      $('drop-mask').classList.add('hidden');
      notice('上傳失敗', '連線中斷', 'err', 12000);
      toast('上傳失敗：連線中斷');
    };
    xhr.send(f);
  }

  // ---------------------------------------------------------------- misc
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // ---------------------------------------------------------------- 事件綁定
  $('btn-open').addEventListener('click', openPkg);
  $('path-input').addEventListener('keydown', function (e) { if (e.key === 'Enter') openPkg(); });
  $('btn-browse').addEventListener('click', bdOpen);
  $('wtl-preview').addEventListener('click', openWtlPc);
  $('btn-close').addEventListener('click', closePkg);
  ['f-status', 'f-search', 'f-run'].forEach(function (id) {
    $(id).addEventListener('input', render);
  });
  $('sel-all').addEventListener('click', function () { selectVisible(null, true); });
  $('sel-fail').addEventListener('click', function () { selectVisible(function (t) { return t.run && t.status === 2; }, true); });
  $('sel-pass').addEventListener('click', function () { selectVisible(function (t) { return t.run && t.status === 1; }, true); });
  $('sel-none').addEventListener('click', function () { state.sel = {}; render(); });
  $('ck-head').addEventListener('change', function () {
    var on = this.checked;
    filtered().forEach(function (t) {
      if (t.run && t.te) { if (on) state.sel[t.i] = true; else delete state.sel[t.i]; }
    });
    render();
  });
  $('btn-export').addEventListener('click', function () {
    var items = Object.keys(state.sel).map(function (i) {
      return { i: +i, l: state.pkg.tests[i].te };
    });
    if (items.length) startExport('te', items);
  });
  // 所有類型 Log 匯出彈窗
  $('btn-adv').addEventListener('click', openAd);
  $('ad-close').addEventListener('click', closeAd);
  $('ad-cancel').addEventListener('click', closeAd);
  $('ad-mask').addEventListener('click', function (e) { if (e.target === this) closeAd(); });
  $('ad-search').addEventListener('input', buildAdList);
  $('ad-all').addEventListener('click', function () { adSetChecks(null); });
  $('ad-wtl').addEventListener('click', function () {
    adSetChecks(function (e) { return /\.(wtl|html?)$/i.test(e.name || ''); });
  });
  $('ad-none').addEventListener('click', function () {   // 清空＝全清（含被過濾掉的勾選）
    state.adSel = {};
    $('ad-list').querySelectorAll('.ad-ck').forEach(function (c) { c.checked = false; });
    updateAdCount();
  });
  $('ad-list').addEventListener('change', function (e) {
    var c = e.target.closest ? e.target.closest('.ad-ck') : null;
    if (!c) return;
    if (c.checked) state.adSel[c.dataset.k] = true; else delete state.adSel[c.dataset.k];
    updateAdCount();
  });
  $('ad-export').addEventListener('click', adSubmit);
  // Excel 側項結果報表（對照 GUI「匯出側項結果 Excel」, 範圍＝目前篩選/排序）
  $('btn-xlsx').addEventListener('click', function () {
    if (!state.pkg || state.pkg.kind !== 'results') return;
    var rows = filtered();
    if (!rows.length) { toast('目前篩選條件下沒有側項'); return; }
    var btn = $('btn-xlsx');
    btn.disabled = true;
    postJson('/api/export-xlsx', { tests: rows.map(function (t) { return t.i; }) })
      .then(function (res) {
        btn.disabled = false;
        if (!res.ok) return fail(res);
        var a = document.createElement('a');
        a.href = res.result.url;
        a.download = res.result.file;
        document.body.appendChild(a); a.click(); a.remove();
        notice('Excel 已產生', res.result.count + ' 列：' + res.result.path, 'ok', 9000);
      }, function () {
        btn.disabled = false;
        toast('連不上伺服器（Excel 匯出失敗）');
      });
  });
  $('tbody').addEventListener('click', function (e) {
    if (state.pkg && state.pkg.kind === 'project') {
      if (state.ptab === 'chunks') {
        if (e.target.closest('.btn-chunk-retry')) { loadChunks(); render(); return; }
        var cr = e.target.closest('tr[data-c]');
        if (cr) openPc(+cr.dataset.c);
        return;
      }
      var er = e.target.closest('tr.hlk-errrow');
      if (er && state.projRows) {
        var r = state.projRows[+er.dataset.k];
        if (r) showError(r);
      }
      return;
    }
    var tr = e.target.closest('tr[data-i]');
    if (!tr) return;
    var i = +tr.dataset.i;
    if (e.target.classList.contains('ck-row')) {
      if (e.target.checked) state.sel[i] = true; else delete state.sel[i];
      render();
      return;
    }
    openRow(i);
  });
  document.querySelectorAll('th.sortable').forEach(function (th) {
    th.addEventListener('click', function () {
      var k = th.dataset.sort;
      if (state.sort.key === k) state.sort.dir = -state.sort.dir;
      else { state.sort.key = k; state.sort.dir = 1; }
      render();
    });
  });
  $('rm-close').addEventListener('click', closeRow);
  $('rm-back').addEventListener('click', showRowList);
  $('row-mask').addEventListener('click', function (e) { if (e.target === this) closeRow(); });
  $('rm-tbody').addEventListener('click', function (e) {
    var b = e.target.closest('.btn-preview') || e.target.closest('.btn-dl');
    if (b) previewLog(b.dataset.l);
  });
  $('rm-export').addEventListener('click', function () {
    var t = state.rowTest;
    if (!t || !t.logs.length) return;
    var items = t.logs.map(function (l) { return { i: t.i, l: l.l }; });
    closeRow();
    startExport('all', items);
  });
  $('ex-close').addEventListener('click', function () { $('ex-mask').classList.add('hidden'); });
  // project 分頁
  $('ptab-runs').addEventListener('click', function () { setPTab('runs'); });
  $('ptab-errors').addEventListener('click', function () { setPTab('errors'); });
  $('ptab-chunks').addEventListener('click', function () { setPTab('chunks'); });
  // Log 串流 chunk 預覽彈窗
  $('pc-close').addEventListener('click', closePc);
  $('pc-mask').addEventListener('click', function (e) { if (e.target === this) closePc(); });
  $('nt-x').addEventListener('click', hideNotice);
  // 錯誤訊息彈窗
  $('ms-close').addEventListener('click', function () { $('ms-mask').classList.add('hidden'); });
  $('ms-ok').addEventListener('click', function () { $('ms-mask').classList.add('hidden'); });
  $('ms-mask').addEventListener('click', function (e) { if (e.target === this) $('ms-mask').classList.add('hidden'); });
  // 拖曳檔案上傳（瀏覽器拿不到完整路徑, 改為上傳內容）
  var dragDepth = 0;
  document.addEventListener('dragenter', function (e) {
    if (!hasFiles(e) || state.uploading) return;
    e.preventDefault();
    dragDepth++;
    $('drop-text').textContent = '放開以上傳並分析 .hlk／.hlkx／.hlkp／.wtl';
    $('drop-prog-wrap').classList.add('hidden');
    $('drop-note').textContent = '';
    $('drop-mask').classList.remove('hidden');
  });
  document.addEventListener('dragover', function (e) {
    if (hasFiles(e)) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; }
  });
  document.addEventListener('dragleave', function (e) {
    if (!hasFiles(e)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth && !state.uploading) $('drop-mask').classList.add('hidden');
  });
  document.addEventListener('dragcancel', function () {   // 拖曳被取消時的保險（部分瀏覽器不補 dragleave）
    dragDepth = 0;
    if (!state.uploading) $('drop-mask').classList.add('hidden');
  });
  document.addEventListener('drop', function (e) {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth = 0;
    if (state.uploading) return;
    var f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (!f) { $('drop-mask').classList.add('hidden'); return; }
    uploadFile(f);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      if (!$('row-mask').classList.contains('hidden')) closeRow();
      else if (!$('pc-mask').classList.contains('hidden')) closePc();
      else if (!$('ad-mask').classList.contains('hidden')) closeAd();
      else if (!$('ex-mask').classList.contains('hidden')) $('ex-mask').classList.add('hidden');
      else if (!$('ms-mask').classList.contains('hidden')) $('ms-mask').classList.add('hidden');
    }
  });
  // 主題鈕：依目前模式重繪圖示與提示（對齊 Build Runner／Git Ref Manager）
  var THEME_LABELS = { light: '淺色', dark: '深色', system: '跟隨系統' };
  var THEME_ICONS = { light: 'sun', dark: 'moon', system: 'monitor' };
  function renderThemeButton() {
    var mode = TbTheme.get().mode;
    var btn = $('theme-toggle');
    btn.innerHTML = TbIcons.svg(THEME_ICONS[mode], { anim: 'wiggle' });
    var label = '主題：' + THEME_LABELS[mode] + '（點一下切換）';
    btn.title = label;
    btn.setAttribute('aria-label', label);
  }
  document.addEventListener('tb-theme-change', renderThemeButton);
  $('theme-toggle').addEventListener('click', function () {
    var modes = TbTheme.modes;
    var m = TbTheme.get().mode;
    TbTheme.set(modes[(modes.indexOf(m) + 1) % modes.length]);
  });
  renderThemeButton();

  // ---------------------------------------------------------------- 啟動
  // 伺服器連線狀態徽章＋port（與 Build Runner／Git Ref Manager 一致的頂部列行為）；
  // 檔案載入狀態另行顯示在開檔卡列頭的 #state-badge。
  function pollServer() {
    getJson('/api/health').then(function (res) {
      var b = $('server-state');
      if (res && res.ok) {
        if (b.textContent !== '連線正常') b.textContent = '連線正常';
        b.className = 'tb-badge tb-badge--ok';
        if (res.port) {
          var pt = '本機服務 port ' + res.port;
          if ($('server-port').textContent !== pt) $('server-port').textContent = pt;
        }
        var title = res.version ? 'HLK Viewer ' + res.version : 'HLK Viewer';
        if (document.title !== title) document.title = title;
      } else {
        if (b.textContent !== '伺服器未回應') b.textContent = '伺服器未回應';
        b.className = 'tb-badge tb-badge--danger';
      }
    }, function () {
      var b = $('server-state');
      if (b.textContent !== '伺服器未回應') b.textContent = '伺服器未回應';
      b.className = 'tb-badge tb-badge--danger';
    });
  }
  // Hub 嵌入時頂部列已被 .tb-hide-embedded 隱藏，跳過輪詢（與 Build Runner 一致）
  if (document.documentElement.dataset.embedded !== '1') {
    setInterval(pollServer, 3000);
    pollServer();
  }
  getJson('/api/pkg').then(function (res) {
    var r = res.result || {};
    if (r.state === 'ready') applyPkg(r);
    else if (r.state === 'loading') { setOpenUi(true, false); pollPkg(); }
  });
})();
