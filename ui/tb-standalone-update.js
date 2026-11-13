(() => {
  const button = document.getElementById('standalone-update');
  if (!button || new URLSearchParams(location.search).get('embedded') === '1') return;
  const bridge = button.dataset.updateBridge === 'pywebview';
  async function request(action, version) {
    if (bridge) {
      return action === 'check' ? window.pywebview.api.check_update() : window.pywebview.api.open_update(version);
    }
    const response = await fetch('/api/standalone-update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Toolbox-Request': '1' },
      body: JSON.stringify({ action, version }),
    });
    return response.json();
  }

  async function check() {
    try {
      const result = await request('check');
      const version = result?.ok && result.update?.version;
      if (!version) return;
      const label = `下載更新 v${version}`;
      button.title = label;
      button.setAttribute('aria-label', label);
      button.innerHTML = window.TbIcons?.svg('download') || '↓';
      button.hidden = false;
      button.classList.remove('tb-hidden');
      button.addEventListener('click', async () => {
        button.disabled = true;
        try {
          const opened = await request('open', version);
          if (!opened?.ok) throw new Error(opened?.error?.message || '無法開啟更新視窗。');
        } catch (error) {
          window.alert(error.message);
        } finally {
          button.disabled = false;
        }
      });
    } catch {
      // A failed check should leave the tool usable.
    }
  }

  if (bridge && !window.pywebview?.api?.check_update) {
    window.addEventListener('pywebviewready', check, { once: true });
  } else {
    check();
  }
})();
