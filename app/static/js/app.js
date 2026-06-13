// Copyright 2026 nullata/webui-manager
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

function csrfHeaders() {
  const token = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
  return { 'X-CSRFToken': token };
}

function showModal(id) {
  const m = document.getElementById(id);
  m.classList.remove('hidden');
  m.classList.add('flex');
}

function hideModal(id) {
  const m = document.getElementById(id);
  m.classList.add('hidden');
  m.classList.remove('flex');
}

function confirmModal(message) {
  return new Promise(resolve => {
    document.getElementById('confirm-modal-message').textContent = message;
    showModal('confirm-modal');
    const ok = document.getElementById('confirm-modal-ok');
    const cancel = document.getElementById('confirm-modal-cancel');
    function cleanup(result) {
      hideModal('confirm-modal');
      ok.removeEventListener('click', onOk);
      cancel.removeEventListener('click', onCancel);
      resolve(result);
    }
    function onOk() { cleanup(true); }
    function onCancel() { cleanup(false); }
    ok.addEventListener('click', onOk);
    cancel.addEventListener('click', onCancel);
  });
}

function syncToggleState(toggle, input) {
  const checked = !!input.checked;
  toggle.dataset.checked = checked ? 'true' : 'false';
  toggle.setAttribute('aria-checked', checked ? 'true' : 'false');
}

function dismissToast(toast) {
  toast.classList.add('toast-dismissed');
  setTimeout(() => toast.remove(), 300);
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.toast').forEach(toast => {
    const timer = setTimeout(() => dismissToast(toast), 4500);
    toast.querySelector('.toast-close').addEventListener('click', () => {
      clearTimeout(timer);
      dismissToast(toast);
    });
  });

  document.getElementById('error-modal-dismiss').addEventListener('click', () => hideModal('error-modal'));

  const scrollTopBtn = document.getElementById('scroll-top-btn');
  if (scrollTopBtn) {
    const toggleScrollTop = () => scrollTopBtn.classList.toggle('is-visible', window.scrollY > 300);
    toggleScrollTop();
    window.addEventListener('scroll', toggleScrollTop, { passive: true });
    scrollTopBtn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  }

  document.querySelectorAll('.host-toggle').forEach(btn => {
    const group = btn.closest('.host-group');
    const storageKey = 'host-collapsed:' + group.dataset.hostKey;

    const setCollapsed = (collapsed, persist) => {
      group.classList.toggle('is-collapsed', collapsed);
      btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      if (persist) {
        try { localStorage.setItem(storageKey, collapsed ? '1' : '0'); } catch (e) { /* ignore */ }
      }
    };

    let stored = null;
    try { stored = localStorage.getItem(storageKey); } catch (e) { /* ignore */ }
    if (stored === '1') setCollapsed(true, false);

    btn.addEventListener('click', () => setCollapsed(!group.classList.contains('is-collapsed'), true));
  });

  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', () => {
      fetch(logoutBtn.dataset.url, { method: 'POST', headers: csrfHeaders() })
        .then(() => { location.href = logoutBtn.dataset.redirect; });
    });
  }

  document.querySelectorAll('img[data-fallback]').forEach(img => {
    img.addEventListener('error', () => {
      const icon = document.createElement('i');
      icon.className = 'fa-solid fa-globe text-cyan-300';
      img.replaceWith(icon);
    });
  });

  document.querySelectorAll('[data-toggle-control]').forEach(toggle => {
    const input = document.getElementById(toggle.dataset.toggleInput);
    if (!input) return;

    syncToggleState(toggle, input);

    toggle.addEventListener('click', () => {
      input.checked = !input.checked;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      syncToggleState(toggle, input);
    });

    input.addEventListener('change', () => {
      syncToggleState(toggle, input);
    });
  });

  document.querySelectorAll('button.delete-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!await confirmModal(btn.dataset.confirm)) return;
      fetch(btn.dataset.url, { method: 'POST', headers: csrfHeaders() }).then(r => {
        if (r.ok) {
          location.reload();
        } else {
          r.json().then(data => {
            document.getElementById('error-modal-message').textContent = data.error;
            showModal('error-modal');
          });
        }
      });
    });
  });

  const testEmailBtn = document.getElementById('test-email-btn');
  if (testEmailBtn) {
    testEmailBtn.addEventListener('click', () => {
      const status = document.getElementById('test-email-status');
      testEmailBtn.disabled = true;
      status.textContent = 'Sending...';
      status.style.color = '';
      fetch(testEmailBtn.dataset.url, { method: 'POST', headers: csrfHeaders() })
        .then(r => r.json())
        .then(data => {
          status.textContent = data.ok ? 'Sent successfully!' : (data.error || 'Failed to send.');
          status.className = data.ok ? 'status-ok' : 'status-fail';
        })
        .catch(() => {
          status.textContent = 'Request failed.';
          status.className = 'status-fail';
        })
        .finally(() => { testEmailBtn.disabled = false; });
    });
  }

  document.querySelectorAll('button.history-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.getElementById('history-modal-title').textContent = btn.dataset.name + ' -Last 24h';
      showModal('history-modal');

      const tbody = document.getElementById('history-tbody');
      const empty = document.getElementById('history-empty');
      tbody.innerHTML = '';
      empty.classList.add('hidden');

      fetch(btn.dataset.url)
        .then(r => r.json())
        .then(logs => {
          if (!logs.length) {
            empty.classList.remove('hidden');
            return;
          }

          [...logs].reverse().forEach((log, i) => {
            const ts = new Date(log.checked_at).toISOString().replace('T', ' ').slice(0, 19);
            const isOk = log.is_ok;
            const tr = document.createElement('tr');
            tr.className = i % 2 === 0 ? '' : 'history-row-alt';
            tr.innerHTML = `
              <td class="px-3 py-2 font-mono text-xs text-slate-300">${ts}</td>
              <td class="px-3 py-2">
                <span class="history-status">
                  <span class="history-dot ${isOk ? 'history-dot-ok' : 'history-dot-fail'}"></span>
                  <span class="${isOk ? 'history-text-ok' : 'history-text-fail'}">${isOk ? 'Online' : 'Offline'} - ${log.status_text}</span>
                </span>
              </td>`;
            tbody.appendChild(tr);
          });
        });
    });
  });

  const historyClose = document.getElementById('history-modal-close');
  if (historyClose) {
    historyClose.addEventListener('click', () => hideModal('history-modal'));
  }

  document.querySelectorAll('button.edit-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.edit-card');
      const display = card.querySelector('.host-display, .category-display');
      const form = card.querySelector('.edit-form');
      display.classList.add('hidden');
      form.classList.remove('hidden');
    });
  });

  document.querySelectorAll('button.edit-cancel').forEach(btn => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.edit-card');
      const display = card.querySelector('.host-display, .category-display');
      const form = card.querySelector('.edit-form');
      form.classList.add('hidden');
      display.classList.remove('hidden');
    });
  });

  document.querySelectorAll('button.credentials-btn').forEach(btn => {
    const article = btn.closest('article');
    const panel = article.querySelector('.credentials-panel');
    const usernameEl = panel.querySelector('.credentials-username');
    const passwordEl = panel.querySelector('.credentials-password');
    const toggleBtn = panel.querySelector('.toggle-password-btn');
    let loaded = false;
    let plainPassword = '';

    btn.addEventListener('click', () => {
      if (panel.classList.contains('hidden')) {
        if (!loaded) {
          fetch(btn.dataset.url, { method: 'POST', headers: csrfHeaders() })
            .then(r => r.json())
            .then(data => {
              usernameEl.textContent = data.username || '-';
              plainPassword = data.password || '';
              passwordEl.textContent = '••••••••';
              loaded = true;
            });
        }
        panel.classList.remove('hidden');
        btn.innerHTML = '<i class="fa-solid fa-key mr-1"></i>Hide credentials';
      } else {
        panel.classList.add('hidden');
        btn.innerHTML = '<i class="fa-solid fa-key mr-1"></i>Show credentials';
      }
    });

    toggleBtn.addEventListener('click', () => {
      const isHidden = passwordEl.textContent === '••••••••';
      passwordEl.textContent = isHidden ? plainPassword || '-' : '••••••••';
      toggleBtn.innerHTML = isHidden
        ? '<i class="fa-solid fa-eye-slash"></i>'
        : '<i class="fa-solid fa-eye"></i>';
    });
  });
});
