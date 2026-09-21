(function () {
  const STORAGE_KEY = 'gods_town_site_password';

  // Override fetch to automatically include X-Site-Password header
  const originalFetch = window.fetch;
  window.fetch = function (resource, options) {
    options = options || {};
    options.headers = options.headers || {};
    const pwd = localStorage.getItem(STORAGE_KEY) || '';
    if (pwd) {
      if (options.headers instanceof Headers) {
        options.headers.set('X-Site-Password', pwd);
      } else if (Array.isArray(options.headers)) {
        options.headers.push(['X-Site-Password', pwd]);
      } else {
        options.headers['X-Site-Password'] = pwd;
      }
    }
    return originalFetch(resource, options).then((response) => {
      if (response.status === 401) {
        response.clone().json().then((data) => {
          if (data && data.gate_active) {
            localStorage.removeItem(STORAGE_KEY);
            showGateOverlay();
          }
        }).catch(() => {});
      }
      return response;
    });
  };

  function getApiBase() {
    if (window.SORORITY_HOUSE_API_URL) return window.SORORITY_HOUSE_API_URL;
    if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
      return window.location.origin;
    }
    return 'https://sorority-house-production-aeb5.up.railway.app';
  }

  function showGateOverlay() {
    if (document.getElementById('site-gate-overlay')) return;

    const overlay = document.createElement('div');
    overlay.id = 'site-gate-overlay';
    overlay.style.cssText = `
      position: fixed;
      inset: 0;
      z-index: 999999;
      background: #151715;
      color: #E9E2D7;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      font-family: Inter, system-ui, sans-serif;
      padding: 20px;
      text-align: center;
    `;

    overlay.innerHTML = `
      <div style="max-width: 360px; width: 100%; background: #1E211E; border: 1px solid rgba(233, 226, 215, 0.14); padding: 32px 24px; border-radius: 18px; box-shadow: 0 20px 50px rgba(0,0,0,0.6);">
        <h2 style="margin: 0 0 8px 0; color: #E9E2D7; font-size: 1.5rem; letter-spacing: 0.05em; text-transform: uppercase;">God's Town</h2>
        <p style="margin: 0 0 20px 0; color: #8A7D6B; font-size: 0.9rem;">This site is password protected.</p>
        <form id="site-gate-form" style="display: flex; flex-direction: column; gap: 12px;">
          <input type="password" id="site-gate-input" placeholder="Password" required style="width: 100%; padding: 12px 14px; border-radius: 10px; background: #151715; border: 1px solid rgba(233, 226, 215, 0.2); color: #E9E2D7; font-size: 1rem; box-sizing: border-box; outline: none;" />
          <button type="submit" style="padding: 12px; border-radius: 999px; background: #556357; color: #E9E2D7; border: 0; font-weight: 700; font-size: 0.95rem; cursor: pointer;">Enter</button>
          <div id="site-gate-err" style="color: #e06c75; font-size: 0.85rem; min-height: 1.2em;"></div>
        </form>
      </div>
    `;

    const mountOverlay = () => {
      if (document.body) {
        document.body.appendChild(overlay);
        const form = document.getElementById('site-gate-form');
        const input = document.getElementById('site-gate-input');
        const errDiv = document.getElementById('site-gate-err');
        input.focus();

        form.addEventListener('submit', async (e) => {
          e.preventDefault();
          const pwd = input.value.trim();
          if (!pwd) return;
          errDiv.textContent = 'Verifying...';

          try {
            const res = await originalFetch(getApiBase() + '/gate/verify', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-Site-Password': pwd
              },
              body: JSON.stringify({ password: pwd })
            });

            if (res.ok) {
              localStorage.setItem(STORAGE_KEY, pwd);
              overlay.remove();
              location.reload();
            } else {
              errDiv.textContent = 'Incorrect password.';
            }
          } catch (err) {
            errDiv.textContent = 'Connection error. Try again.';
          }
        });
      } else {
        setTimeout(mountOverlay, 10);
      }
    };
    mountOverlay();
  }

  async function checkGate() {
    try {
      const res = await originalFetch(getApiBase() + '/gate/status');
      if (!res.ok) return;
      const data = await res.json();
      if (data && data.gate_active) {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (!saved) {
          showGateOverlay();
        } else {
          const verifyRes = await originalFetch(getApiBase() + '/gate/verify', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-Site-Password': saved
            },
            body: JSON.stringify({ password: saved })
          });
          if (!verifyRes.ok) {
            localStorage.removeItem(STORAGE_KEY);
            showGateOverlay();
          }
        }
      }
    } catch (e) {
      // Backend unavailable or network error
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', checkGate);
  } else {
    checkGate();
  }
})();
