(function() {
  const SITE_PASSWORD_KEY = 'gods_town_site_password';

  function getApiBaseUrl() {
    if (window.SORORITY_HOUSE_API_URL && !window.SORORITY_HOUSE_API_URL.includes('up.railway.app')) {
      return window.SORORITY_HOUSE_API_URL;
    }
    if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
      return 'http://127.0.0.1:8000';
    }
    return window.SORORITY_HOUSE_API_URL || window.API_BASE_URL || 'https://sorority-house-production-aeb5.up.railway.app';
  }

  // Override fetch to include X-Site-Password header automatically on all outgoing requests
  const _originalFetch = window.fetch;
  window.fetch = function(resource, init) {
    init = init || {};
    const headers = new Headers(init.headers || {});
    const pwd = localStorage.getItem(SITE_PASSWORD_KEY) || '';
    if (pwd && !headers.has('X-Site-Password')) {
      headers.set('X-Site-Password', pwd);
    }
    init.headers = headers;
    return _originalFetch.call(this, resource, init);
  };

  function injectStyles() {
    if (document.getElementById('site-gate-styles')) return;
    const style = document.createElement('style');
    style.id = 'site-gate-styles';
    style.textContent = `
      #site-gate-overlay {
        position: fixed;
        inset: 0;
        z-index: 999999;
        background: #151715;
        color: #E9E2D7;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        padding: 20px;
        box-sizing: border-box;
      }
      #site-gate-box {
        background: #1E211E;
        border: 1px solid rgba(233, 226, 215, 0.14);
        border-radius: 20px;
        padding: 36px 30px;
        width: min(400px, 100%);
        text-align: center;
        box-shadow: 0 22px 70px rgba(0, 0, 0, 0.55);
        box-sizing: border-box;
      }
      #site-gate-box h1 {
        font-family: Impact, Haettenschweiler, "Arial Narrow Bold", sans-serif;
        font-size: 2.2rem;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        margin: 0 0 6px;
        color: #E9E2D7;
      }
      #site-gate-box p {
        color: #8A7D6B;
        font-size: 0.92rem;
        margin: 0 0 22px;
        line-height: 1.4;
      }
      #site-gate-form {
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      #site-gate-input {
        width: 100%;
        padding: 12px 14px;
        border-radius: 12px;
        border: 1px solid rgba(233, 226, 215, 0.14);
        background: #151715;
        color: #E9E2D7;
        font: inherit;
        font-size: 1rem;
        box-sizing: border-box;
      }
      #site-gate-input:focus {
        outline: none;
        border-color: rgba(233, 226, 215, 0.4);
      }
      #site-gate-btn {
        background: #556357;
        color: #E9E2D7;
        border: 0;
        border-radius: 999px;
        padding: 12px 20px;
        font: inherit;
        font-weight: 700;
        cursor: pointer;
        font-size: 0.95rem;
        transition: filter .15s;
      }
      #site-gate-btn:hover {
        filter: brightness(1.1);
      }
      #site-gate-msg {
        min-height: 1.2em;
        font-size: 0.85rem;
        color: #f0a8a0;
        margin-top: 4px;
      }
      body.gate-locked > *:not(#site-gate-overlay) {
        display: none !important;
      }
    `;
    document.head.appendChild(style);
  }

  function showGateOverlay(errMsg) {
    injectStyles();
    document.body.classList.add('gate-locked');
    let overlay = document.getElementById('site-gate-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'site-gate-overlay';
      overlay.innerHTML = `
        <div id="site-gate-box">
          <h1>God's Town</h1>
          <p>This game is currently password protected.</p>
          <form id="site-gate-form" autocomplete="off">
            <input id="site-gate-input" type="password" placeholder="Enter password" required autofocus />
            <button id="site-gate-btn" type="submit">Enter Game</button>
            <div id="site-gate-msg"></div>
          </form>
        </div>
      `;
      document.body.appendChild(overlay);

      const form = document.getElementById('site-gate-form');
      form.addEventListener('submit', function(e) {
        e.preventDefault();
        const pwd = document.getElementById('site-gate-input').value.trim();
        if (!pwd) return;
        verifyPassword(pwd, false);
      });
    }
    const msgEl = document.getElementById('site-gate-msg');
    if (msgEl) msgEl.textContent = errMsg || '';
  }

  function removeGateOverlay() {
    document.body.classList.remove('gate-locked');
    const overlay = document.getElementById('site-gate-overlay');
    if (overlay) overlay.remove();
  }

  function verifyPassword(pwd, isSilent) {
    const btn = document.getElementById('site-gate-btn');
    if (btn) btn.disabled = true;
    const msgEl = document.getElementById('site-gate-msg');
    if (msgEl && !isSilent) msgEl.textContent = 'Verifying...';

    const apiUrl = getApiBaseUrl();
    _originalFetch(apiUrl + '/gate/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pwd })
    }).then(res => {
      if (res.ok) {
        localStorage.setItem(SITE_PASSWORD_KEY, pwd);
        removeGateOverlay();
        window.dispatchEvent(new CustomEvent('site_unlocked'));
      } else {
        localStorage.removeItem(SITE_PASSWORD_KEY);
        showGateOverlay('Incorrect password. Please try again.');
      }
    }).catch(() => {
      if (!isSilent) showGateOverlay('Could not verify password. Check your connection.');
    }).finally(() => {
      if (btn) btn.disabled = false;
    });
  }

  function checkGate() {
    const apiUrl = getApiBaseUrl();
    _originalFetch(apiUrl + '/gate/status', {
      headers: { 'X-Site-Password': localStorage.getItem(SITE_PASSWORD_KEY) || '' }
    }).then(res => res.json()).then(data => {
      if (!data.gate_active) {
        removeGateOverlay();
      } else {
        const stored = localStorage.getItem(SITE_PASSWORD_KEY) || '';
        if (stored) {
          verifyPassword(stored, true);
        } else {
          showGateOverlay();
        }
      }
    }).catch(() => {
      if (localStorage.getItem(SITE_PASSWORD_KEY)) {
        removeGateOverlay();
      } else {
        showGateOverlay();
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', checkGate);
  } else {
    checkGate();
  }
})();
