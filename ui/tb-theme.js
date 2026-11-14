/* tb-theme 3.4.0 — 深淺色、強調色與 Hub 嵌入風格。正本在 Dev-Toolbox/ui-kit。
 * 優先順序：網址參數 > localStorage > 預設（跟隨系統、藍色）。
 * 請在 <head> 內、CSS 之後同步載入，避免先閃一下錯的顏色。
 * 嵌入時：Hub 以 postMessage({ type: 'tb-theme', mode, accent, bg }) 即時同步。
 * API：TbTheme.set('light'|'dark'|'system')、TbTheme.setAccent('blue'|'green'|'violet'|'orange'|'rose')
 *      TbTheme.get() → { mode, resolved, accent }；變更時 document 會發出 'tb-theme-change' 事件。
 */
(function () {
  'use strict';
  var MODES = ['light', 'dark', 'system'];
  var ACCENTS = ['blue', 'green', 'violet', 'orange', 'rose'];
  var STYLES = ['plain', 'graphite', 'warm', 'nord', 'contrast', 'black', 'liquid', 'glass', 'frost', 'metal', 'pearl',
    'glow', 'grid', 'dots', 'dusk', 'forest', 'mono', 'cyber'];
  var root = document.documentElement;
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  var params = new URLSearchParams(location.search);
  var toolPage = document.currentScript?.hasAttribute('data-tb-tool');
  var embedRequested = params.get('embedded') === '1';
  var embedded = embedRequested && window.parent !== window;
  var useQuery = !embedRequested || embedded;
  var hubOrigin = embedded && params.get('hubOrigin');
  var hubStylesheet = /^http:\/\/(127\.0\.0\.1|localhost):[0-9]{1,5}$/.test(hubOrigin || '');
  if (!hubStylesheet) hubOrigin = null;
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* 無痕或被擋：只影響記憶 */ } }

  var state = {
    mode: (useQuery && pick(params.get('theme'), MODES)) || pick(load('tb.theme'), MODES) || 'system',
    accent: (useQuery && pick(params.get('accent'), ACCENTS)) || pick(load('tb.accent'), ACCENTS) || 'blue',
    bg: embedded && pick(params.get('bg'), STYLES)
  };
  if (embedded) root.dataset.embedded = '1';
  else if (toolPage) root.dataset.hubBg = 'graphite';

  function pick(v, list) { return list.indexOf(v) >= 0 ? v : null; }
  function resolved() { return state.mode === 'system' ? (mq && mq.matches ? 'dark' : 'light') : state.mode; }
  function apply() {
    root.dataset.theme = resolved();
    root.dataset.themeMode = state.mode;
    if (embedded) {
      if (state.bg && state.bg !== 'plain') root.dataset.hubBg = hubStylesheet ? state.bg : 'graphite';
      else delete root.dataset.hubBg;
    }
    if (state.accent === 'blue') delete root.dataset.accent; else root.dataset.accent = state.accent;
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = resolved() === 'dark' ? '#0a0e19' : '#f3f5f9';
    document.dispatchEvent(new CustomEvent('tb-theme-change', { detail: api.get() }));
  }
  if (mq && mq.addEventListener) mq.addEventListener('change', function () { if (state.mode === 'system') apply(); });

  var api = {
    modes: MODES, accents: ACCENTS,
    get: function () { return { mode: state.mode, resolved: resolved(), accent: state.accent }; },
    set: function (m) { if (!embedded && pick(m, MODES)) { state.mode = m; save('tb.theme', m); apply(); } },
    setAccent: function (a) { if (!embedded && pick(a, ACCENTS)) { state.accent = a; save('tb.accent', a); apply(); } },
    /* 把目前主題接到 iframe 網址上，避免首次繪製閃色 */
    query: function () { return 'theme=' + state.mode + '&accent=' + state.accent; }
  };
  window.TbTheme = api;
  if (hubStylesheet) {
    var link = document.createElement('link');
    link.rel = 'stylesheet';
    link.setAttribute('blocking', 'render');
    link.href = hubOrigin + '/tool-theme.css';
    link.addEventListener('error', function () { hubStylesheet = false; apply(); });
    document.head.appendChild(link);
  }
  /* Hub 切換主題時用 postMessage 通知嵌入的工具，不必重新載入 iframe（不寫入工具自己的 localStorage） */
  window.addEventListener('message', function (e) {
    if (!embedded || e.source !== window.parent || (hubOrigin && e.origin !== hubOrigin)) return;
    var d = e.data;
    if (!d || d.type !== 'tb-theme') return;
    if (pick(d.mode, MODES)) state.mode = d.mode;
    if (pick(d.accent, ACCENTS)) state.accent = d.accent;
    if (pick(d.bg, STYLES)) state.bg = d.bg;
    apply();
  });
  apply();
})();
