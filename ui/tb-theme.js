/* tb-theme 3.0.0 — 深淺色／跟隨系統 與 強調色。正本在 Dev-Toolbox/ui-kit。
 * 優先順序：網址參數（Hub 嵌入時帶 ?theme=&accent=）> localStorage > 預設（跟隨系統、藍色）。
 * 請在 <head> 內、CSS 之後同步載入，避免先閃一下錯的顏色。
 * 嵌入時：Hub 以 postMessage({ type: 'tb-theme', mode, accent }) 即時同步。
 * API：TbTheme.set('light'|'dark'|'system')、TbTheme.setAccent('blue'|'green'|'violet'|'orange'|'rose')
 *      TbTheme.get() → { mode, resolved, accent }；變更時 document 會發出 'tb-theme-change' 事件。
 */
(function () {
  'use strict';
  var MODES = ['light', 'dark', 'system'];
  var ACCENTS = ['blue', 'green', 'violet', 'orange', 'rose'];
  var root = document.documentElement;
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  var params = new URLSearchParams(location.search);
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* 無痕或被擋：只影響記憶 */ } }

  var state = {
    mode: pick(params.get('theme'), MODES) || pick(load('tb.theme'), MODES) || 'system',
    accent: pick(params.get('accent'), ACCENTS) || pick(load('tb.accent'), ACCENTS) || 'blue'
  };
  if (params.get('embedded') === '1') root.dataset.embedded = '1';

  function pick(v, list) { return list.indexOf(v) >= 0 ? v : null; }
  function resolved() { return state.mode === 'system' ? (mq && mq.matches ? 'dark' : 'light') : state.mode; }
  function apply() {
    root.dataset.theme = resolved();
    root.dataset.themeMode = state.mode;
    if (state.accent === 'blue') delete root.dataset.accent; else root.dataset.accent = state.accent;
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = resolved() === 'dark' ? '#0a0e19' : '#f3f5f9';
    document.dispatchEvent(new CustomEvent('tb-theme-change', { detail: api.get() }));
  }
  if (mq && mq.addEventListener) mq.addEventListener('change', function () { if (state.mode === 'system') apply(); });

  var api = {
    modes: MODES, accents: ACCENTS,
    get: function () { return { mode: state.mode, resolved: resolved(), accent: state.accent }; },
    set: function (m) { if (pick(m, MODES)) { state.mode = m; save('tb.theme', m); apply(); } },
    setAccent: function (a) { if (pick(a, ACCENTS)) { state.accent = a; save('tb.accent', a); apply(); } },
    /* 把目前主題接到網址上（Hub 開 iframe、新視窗時用） */
    query: function () { return 'theme=' + state.mode + '&accent=' + state.accent; }
  };
  window.TbTheme = api;
  /* Hub 切換主題時用 postMessage 通知嵌入的工具，不必重新載入 iframe（不寫入工具自己的 localStorage） */
  window.addEventListener('message', function (e) {
    if (window.parent === window || e.source !== window.parent) return;
    var d = e.data;
    if (!d || d.type !== 'tb-theme') return;
    if (pick(d.mode, MODES)) state.mode = d.mode;
    if (pick(d.accent, ACCENTS)) state.accent = d.accent;
    apply();
  });
  apply();
})();
