/* ui-kit 3.2.0 tb-dirpicker - shared folder/file picker dialog.
   正本在 Dev-Toolbox/ui-kit，請勿直接修改工具內的複本（Sync-UiKit.ps1 分發）。

   以 Git Ref Manager 的資料夾瀏覽器為基準：上層／掃描此處 Git Repo／磁碟清單、
   GIT badge、掃描結果清單、「選取這個資料夾」。後端由呼叫端注入 fetchDir，
   統一回傳格式（GitRef /api/browse 形）：
     { current, parent, items: [{ name, path, hasGit, isFile? }], truncated, repos?: [{ path }] }

   用法：
     const path = await TbDirPicker.open({
       title: '選擇資料夾',            // 標題（預設「選擇資料夾」）
       start: 'D:\\Work',              // 起始路徑；空字串 = 磁碟清單
       mode: 'dir',                    // 'dir' 或 'file'
       extensions: ['.zip'],           // file mode 副檔名過濾（小寫含點）；空 = 全部檔案
       dirsOnly: false,                // true：GIT badge 只標示，雙擊不直接選取
       fetchDir(path, opts) -> Promise<上>   // opts: { scan, depth, limit, files, extensions }
     });                               // 選取回傳路徑；取消/關閉回傳 null
   需要 tb-icons.js（TbIcons）提供圖示。 */
(function () {
  'use strict';

  var SCAN_DEPTH = 2, SCAN_LIMIT = 50;
  var current = null;   // 單例：同時只開一個挑選器

  function ic(name, size) {
    if (window.TbIcons) return window.TbIcons.svg(name, { size: size || 15 });
    return '';
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function build(opt) {
    var host = document.createElement('div');
    host.className = 'tb-dp';
    host.setAttribute('role', 'dialog');
    host.setAttribute('aria-modal', 'true');
    host.innerHTML =
      '<div class="tb-dp__box">' +
      '  <div class="tb-dp__head">' +
      '    <span class="tb-dp__title">' + esc(opt.title || '選擇資料夾') + '</span>' +
      '    <button type="button" class="tb-btn tb-dp__close" title="關閉">' + ic('x') + '</button>' +
      '  </div>' +
      '  <div class="tb-dp__toolbar">' +
      '    <button type="button" class="tb-btn tb-dp__up">' + ic('chevron-up') + ' 上層</button>' +
      '    <button type="button" class="tb-btn tb-dp__scan">' + ic('search') + ' 掃描此處 Git Repo</button>' +
      '    <button type="button" class="tb-btn tb-dp__drives">' + ic('hard-drive') + ' 磁碟</button>' +
      '  </div>' +
      '  <div class="tb-dp__pathrow"><input type="text" class="tb-dp__path" spellcheck="false" aria-label="目前路徑"></div>' +
      '  <div class="tb-dp__list" tabindex="0"></div>' +
      '  <div class="tb-dp__foot">' +
      '    <span class="tb-dp__hint"></span>' +
      '    <button type="button" class="tb-btn tb-dp__cancel">取消</button>' +
      '    <button type="button" class="tb-btn tb-btn--primary tb-dp__ok">選取這個資料夾</button>' +
      '  </div>' +
      '</div>';
    document.body.appendChild(host);
    return {
      host: host,
      list: host.querySelector('.tb-dp__list'),
      pathInput: host.querySelector('.tb-dp__path'),
      up: host.querySelector('.tb-dp__up'),
      ok: host.querySelector('.tb-dp__ok'),
      hint: host.querySelector('.tb-dp__hint')
    };
  }

  function open(opt) {
    opt = opt || {};
    if (current) { current.close(null); }   // 重複呼叫：關舊開新
    var mode = opt.mode === 'file' ? 'file' : 'dir';
    var exts = (opt.extensions || []).map(function (e) { return String(e).toLowerCase(); });
    var ui = build(opt);
    var state = { path: null, parent: null };
    var version = 0;   // 避免慢回應覆蓋新目錄
    var resolve;
    var promise = new Promise(function (res) { resolve = res; });

    if (mode === 'file') {
      ui.ok.style.display = 'none';   // 檔案用點擊/雙擊選
      ui.host.querySelector('.tb-dp__scan').style.display = 'none';   // 檔案挑選不需要找 Git Repo
    }
    ui.pathInput.placeholder = '輸入路徑後按 Enter 前往（清空 = 磁碟清單）';

    function close(value) {
      if (state.closed) return;
      state.closed = true;
      document.removeEventListener('keydown', onKey, true);
      ui.host.remove();
      if (current && current.host === ui.host) current = null;
      resolve(value);
    }
    function onKey(ev) {
      if (ev.key === 'Escape') { ev.stopPropagation(); close(null); }
    }
    document.addEventListener('keydown', onKey, true);

    function select(path) { close(path); }

    function setPathInput(text) {
      ui.pathInput.value = text || '';
    }

    function renderItems(data) {
      var html = '';
      var items = data.items || [];
      items.forEach(function (it, i) {
        if (it.isFile) {
          html += '<div class="tb-dp__item tb-dp__item--file" data-i="' + i + '">' +
            ic('file-code') + '<span>' + esc(it.name) + '</span></div>';
        } else {
          html += '<div class="tb-dp__item' + (it.hasGit ? ' tb-dp__item--repo' : '') + '" data-i="' + i + '">' +
            ic(it.hasGit ? 'folder-open' : 'folder') + '<span>' + esc(it.name) + '</span>' +
            (it.hasGit ? '<span class="tb-dp__tag">GIT</span>' : '') + '</div>';
        }
      });
      if (!items.length) html = '<div class="tb-dp__empty">（沒有可顯示的項目）</div>';
      else if (data.truncated) html += '<div class="tb-dp__empty">（項目過多，僅顯示前面部分）</div>';
      ui.list.innerHTML = html;
      ui.list.querySelectorAll('.tb-dp__item').forEach(function (el) {
        var it = items[+el.getAttribute('data-i')];
        el.addEventListener('click', function () {
          if (it.isFile) select(it.path);
          else load(it.path);
        });
        if (!it.isFile && it.hasGit && !opt.dirsOnly) {
          el.addEventListener('dblclick', function () { select(it.path); });
        }
      });
    }

    function renderRepos(repos) {
      if (!repos.length) {
        ui.list.innerHTML = '<div class="tb-dp__empty">此處 ' + SCAN_DEPTH + ' 層內找不到 Git Repo</div>';
        return;
      }
      ui.list.innerHTML = repos.map(function (rp, i) {
        return '<div class="tb-dp__item tb-dp__item--repo" data-p="' + esc(rp.path) + '" data-i="' + i + '">' +
          ic('git-branch') + '<span>' + esc(rp.path) + '</span><span class="tb-dp__tag">Git Repo</span></div>';
      }).join('');
      var seen = repos;
      ui.list.querySelectorAll('.tb-dp__item').forEach(function (el) {
        el.addEventListener('click', function () { select(seen[+el.getAttribute('data-i')].path); });
      });
    }

    function load(path, scan) {
      var v = ++version;
      ui.list.innerHTML = '<div class="tb-dp__empty">讀取中…</div>';
      ui.hint.textContent = '';
      var opts = scan
        ? { scan: true, depth: SCAN_DEPTH, limit: SCAN_LIMIT }
        : (mode === 'file' ? { files: true, extensions: exts } : {});
      Promise.resolve(opt.fetchDir(path || '', opts)).then(function (data) {
        if (v !== version || state.closed) return;
        if (!data || data.error) {
          ui.list.innerHTML = '<div class="tb-dp__empty">' + esc((data && data.error) || '無法讀取這個資料夾') + '</div>';
          return;
        }
        if (scan) { renderRepos(data.repos || []); return; }
        state.path = data.current || null;
        state.parent = data.parent || null;
        ui.up.disabled = !state.parent;
        ui.ok.disabled = !state.path;
        setPathInput(state.path || '');
        renderItems(data);
      }, function (err) {
        if (v !== version || state.closed) return;
        ui.list.innerHTML = '<div class="tb-dp__empty">' + esc((err && err.message) || '讀取失敗') + '</div>';
      });
    }

    ui.up.addEventListener('click', function () { if (state.parent) load(state.parent); });
    ui.host.querySelector('.tb-dp__drives').addEventListener('click', function () { load(''); });
    ui.host.querySelector('.tb-dp__scan').addEventListener('click', function () {
      if (!state.path) { ui.hint.textContent = '請先進入一個資料夾'; return; }
      load(state.path, true);
    });
    ui.host.querySelector('.tb-dp__cancel').addEventListener('click', function () { close(null); });
    ui.host.querySelector('.tb-dp__close').addEventListener('click', function () { close(null); });
    ui.ok.addEventListener('click', function () {
      if (!state.path) { ui.hint.textContent = '請先進入一個資料夾'; return; }
      select(state.path);
    });
    ui.pathInput.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); load(ui.pathInput.value.trim()); }
    });
    ui.host.addEventListener('mousedown', function (ev) { if (ev.target === ui.host) close(null); });

    ui.ok.disabled = true;
    current = { host: ui.host, close: close };
    load(opt.start || '');
    return promise;
  }

  window.TbDirPicker = { open: open, SCAN_DEPTH: SCAN_DEPTH, SCAN_LIMIT: SCAN_LIMIT };
})();
