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

// The error modal is shared, so every caller sets its heading - otherwise the
// previous caller's wording sticks around.
function showError(title, message) {
  document.getElementById('error-modal-title').textContent = title;
  document.getElementById('error-modal-message').textContent = message;
  showModal('error-modal');
}

// Renders the last-24h check rows into the history modal. Split out of the
// open-modal handler so the Clear button can re-render in place afterwards.
function loadHistory(url) {
  const tbody = document.getElementById('history-tbody');
  const empty = document.getElementById('history-empty');
  tbody.innerHTML = '';
  empty.classList.add('hidden');

  return fetch(url)
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

const HOST_COLLAPSE_PREFIX = 'host-collapsed:';

// Collapse state is applied from two places - the heading click handler and
// live search, which opens groups holding matches - so keep it in one helper.
function setGroupCollapsed(group, collapsed) {
  group.classList.toggle('is-collapsed', collapsed);
  const btn = group.querySelector('.host-toggle');
  if (btn) btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
}

function storedGroupCollapsed(group) {
  try {
    return localStorage.getItem(HOST_COLLAPSE_PREFIX + group.dataset.hostKey) === '1';
  } catch (e) {
    return false;
  }
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

// navigator.clipboard only exists in a secure context, and these dashboards are
// routinely served over plain HTTP on a LAN address, so fall back to the old
// execCommand path instead of leaving the copy button dead exactly where most
// installs run. Resolves to whether the copy actually happened.
function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text).then(() => true, () => false);
  }

  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.top = '-1000px';
  area.style.opacity = '0';
  document.body.appendChild(area);
  area.select();
  area.setSelectionRange(0, text.length); // iOS Safari ignores select() alone
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch (e) {
    ok = false;
  }
  area.remove();
  return Promise.resolve(ok);
}

// Swaps a button's icon for a tick or a cross, then puts it back.
function flashButtonResult(btn, originalHtml, originalTitle, ok) {
  clearTimeout(btn._flashTimer);
  btn.innerHTML = ok
    ? '<i class="fa-solid fa-check text-emerald-400"></i>'
    : '<i class="fa-solid fa-xmark text-rose-400"></i>';
  btn.title = ok ? 'Copied' : 'Copy failed';
  btn._flashTimer = setTimeout(() => {
    btn.innerHTML = originalHtml;
    btn.title = originalTitle;
  }, 1500);
}

// Ctrl+K (Cmd+K on a Mac) focuses the dashboard search from anywhere on the
// page. Bound whether or not live search is on - jumping to the box is useful
// either way.
function initSearchHotkey(form) {
  const input = form.querySelector('input[name="q"]');
  if (!input) return;

  const hint = document.getElementById('search-hotkey-hint');
  if (hint && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)) {
    hint.textContent = '⌘ K';
  }

  document.addEventListener('keydown', e => {
    if (!e.key || e.key.toLowerCase() !== 'k' || e.altKey) return;
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    input.focus();
    input.select();
  });

  input.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    // First Escape clears the filter, a second one gets you out of the field.
    if (input.value) {
      input.value = '';
      // Live search listens for this; with the setting off it is a no-op.
      input.dispatchEvent(new Event('input', { bubbles: true }));
    } else {
      input.blur();
    }
  });
}

// Live search filters the dashboard cards already on the page instead of
// round-tripping the search form. The route skips its own filtering while this
// is on and renders every service, so the full set is always here to match
// against - including after a reload of a filtered URL. Matching is a
// case-insensitive substring over data-search, the same five fields and the
// same semantics as the server's ILIKE query, so results are identical whether
// the setting is on or off.
function initLiveSearch(form) {
  const input = form.querySelector('input[name="q"]');
  const hostSelect = form.querySelector('select[name="host_id"]');
  const categorySelect = form.querySelector('select[name="category_id"]');
  if (!input || !hostSelect || !categorySelect) return;

  const cards = [...document.querySelectorAll('.service-card')];
  const groups = [...document.querySelectorAll('.host-group')];
  const emptyState = document.getElementById('live-search-empty');
  const countLabel = document.getElementById('live-search-count');
  const resetBtn = document.getElementById('search-reset-btn');

  // Enter in the text field would otherwise submit and reload the page.
  form.addEventListener('submit', e => e.preventDefault());

  let wasFiltered = false;
  let urlTimer = null;

  // Rewriting the URL keeps a reload or a bookmark on the current filter, but
  // browsers rate-limit replaceState, so it trails the keystrokes.
  const syncUrl = (term, hostId, categoryId) => {
    clearTimeout(urlTimer);
    urlTimer = setTimeout(() => {
      const params = new URLSearchParams();
      if (term) params.set('q', term);
      if (hostId) params.set('host_id', hostId);
      if (categoryId) params.set('category_id', categoryId);
      const query = params.toString();
      history.replaceState(null, '', query ? location.pathname + '?' + query : location.pathname);
    }, 300);
  };

  const apply = (updateUrl) => {
    const term = input.value.trim();
    const needle = term.toLowerCase();
    const hostId = hostSelect.value;
    const categoryId = categorySelect.value;
    const filtered = !!(needle || hostId || categoryId);
    let visible = 0;

    cards.forEach(card => {
      const match =
        (!needle || card.dataset.search.includes(needle)) &&
        (!hostId || card.dataset.hostId === hostId) &&
        (!categoryId || card.dataset.categoryIds.split(' ').includes(categoryId));
      card.classList.toggle('hidden', !match);
      if (match) visible += 1;
    });

    groups.forEach(group => {
      const wasHidden = group.classList.contains('hidden');
      const shown = group.querySelectorAll('.service-card:not(.hidden)').length;
      group.classList.toggle('hidden', shown === 0);

      const count = group.querySelector('.host-count');
      if (count) count.textContent = filtered ? shown : count.dataset.total;

      if (!filtered) {
        // Filter cleared - hand the group back to whatever the user last chose.
        setGroupCollapsed(group, storedGroupCollapsed(group));
      } else if (shown && (wasHidden || !wasFiltered)) {
        // A collapsed group hides its own matches, so open it as it comes into
        // view. Only on that transition: collapsing a group mid-search is a
        // deliberate act and must survive the next keystroke.
        setGroupCollapsed(group, false);
      }
    });

    if (emptyState) emptyState.classList.toggle('hidden', visible > 0 || cards.length === 0);
    if (countLabel) {
      countLabel.textContent = visible + ' of ' + cards.length + ' services';
      countLabel.classList.toggle('hidden', !filtered);
    }

    wasFiltered = filtered;
    if (updateUrl) syncUrl(term, hostId, categoryId);
  };

  input.addEventListener('input', () => apply(true));
  hostSelect.addEventListener('change', () => apply(true));
  categorySelect.addEventListener('change', () => apply(true));

  if (resetBtn) {
    resetBtn.addEventListener('click', e => {
      e.preventDefault();
      input.value = '';
      hostSelect.value = '';
      categorySelect.value = '';
      apply(true);
      input.focus();
    });
  }

  // The page may already be filtered server-side via query params; re-running
  // the same filter here is a no-op that just primes the counts and labels.
  apply(false);
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

    if (storedGroupCollapsed(group)) setGroupCollapsed(group, true);

    btn.addEventListener('click', () => {
      const collapsed = !group.classList.contains('is-collapsed');
      setGroupCollapsed(group, collapsed);
      try {
        localStorage.setItem(HOST_COLLAPSE_PREFIX + group.dataset.hostKey, collapsed ? '1' : '0');
      } catch (e) { /* ignore */ }
    });
  });

  const searchForm = document.getElementById('search-form');
  if (searchForm) {
    initSearchHotkey(searchForm);
    if (searchForm.dataset.liveSearch) initLiveSearch(searchForm);
  }

  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', () => {
      fetch(logoutBtn.dataset.url, { method: 'POST', headers: csrfHeaders() })
        .then(() => { location.href = logoutBtn.dataset.redirect; });
    });
  }

  // Login/setup forms: a page left open long enough can outlive the session
  // its embedded CSRF token was bound to (browser restart drops the session
  // cookie, another tab rotates it). Swap in a token for the current session
  // right before submitting, so the first attempt succeeds instead of bouncing
  // through "Your session expired. Please try again."
  document.querySelectorAll('form[data-refresh-csrf]').forEach(form => {
    form.addEventListener('submit', e => {
      e.preventDefault();
      if (form.dataset.submitting) return;
      form.dataset.submitting = '1';
      fetch(form.dataset.refreshCsrf, { cache: 'no-store' })
        .then(r => r.json())
        .then(data => {
          const field = form.querySelector('input[name="csrf_token"]');
          if (field && data.csrf_token) field.value = data.csrf_token;
        })
        .catch(() => {}) // offline etc. - submit with the existing token
        .finally(() => form.submit());
    });
  });

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
          r.json().then(data => showError('Cannot Delete', data.error));
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

  const historyClearBtn = document.getElementById('history-clear-btn');

  document.querySelectorAll('button.history-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.getElementById('history-modal-title').textContent = btn.dataset.name + ' -Last 24h';
      // The modal is shared by every card, so point the Clear button at the
      // service being opened right now.
      historyClearBtn.dataset.url = btn.dataset.clearUrl;
      historyClearBtn.dataset.reloadUrl = btn.dataset.url;
      historyClearBtn.dataset.name = btn.dataset.name;
      showModal('history-modal');
      loadHistory(btn.dataset.url);
    });
  });

  if (historyClearBtn) {
    historyClearBtn.addEventListener('click', async () => {
      const message = `Clear all health check history for "${historyClearBtn.dataset.name}"? This cannot be undone.`;
      if (!await confirmModal(message)) return;
      historyClearBtn.disabled = true;
      fetch(historyClearBtn.dataset.url, { method: 'POST', headers: csrfHeaders() })
        .then(r => {
          if (!r.ok) {
            showError('Cannot Clear History', 'The history could not be cleared. Please try again.');
            return;
          }
          return loadHistory(historyClearBtn.dataset.reloadUrl);
        })
        .finally(() => { historyClearBtn.disabled = false; });
    });
  }

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
    const errorEl = panel.querySelector('.credentials-error');
    const toggleBtn = panel.querySelector('.toggle-password-btn');
    const copyBtn = panel.querySelector('.copy-password-btn');
    const copyBtnHtml = copyBtn.innerHTML;
    let request = null;
    let plainPassword = '';
    let revealed = false;

    // Cached, so the copy button awaits the fetch the reveal button already
    // started rather than racing it or issuing a second request.
    const loadCredentials = () => {
      if (!request) {
        request = fetch(btn.dataset.url, { method: 'POST', headers: csrfHeaders() })
          .then(r => r.json())
          .then(data => {
            plainPassword = data.password || '';
            usernameEl.textContent = data.username || '-';
            passwordEl.textContent = plainPassword ? '••••••••' : '-';

            if (data.decrypt_failed) {
              errorEl.textContent = 'Stored password could not be decrypted. This usually means '
                + 'SECRET_KEY changed since it was saved (set APP_CREDENTIALS_KEY to keep the two '
                + 'independent). Re-enter the password on the service to fix it.';
              errorEl.classList.remove('hidden');
            }
            // Nothing to reveal or copy if the password is missing or unreadable.
            if (!plainPassword) {
              toggleBtn.classList.add('hidden');
              copyBtn.classList.add('hidden');
            }
            return data;
          });
      }
      return request;
    };

    btn.addEventListener('click', () => {
      if (panel.classList.contains('hidden')) {
        loadCredentials();
        panel.classList.remove('hidden');
        btn.innerHTML = '<i class="fa-solid fa-key mr-1"></i>Hide credentials';
      } else {
        panel.classList.add('hidden');
        btn.innerHTML = '<i class="fa-solid fa-key mr-1"></i>Show credentials';
      }
    });

    copyBtn.addEventListener('click', () => {
      loadCredentials().then(() => {
        if (!plainPassword) return;
        copyToClipboard(plainPassword).then(
          ok => flashButtonResult(copyBtn, copyBtnHtml, 'Copy password', ok));
      });
    });

    toggleBtn.addEventListener('click', () => {
      revealed = !revealed;
      passwordEl.textContent = revealed ? plainPassword : '••••••••';
      toggleBtn.title = revealed ? 'Hide password' : 'Show password';
      toggleBtn.setAttribute('aria-label', toggleBtn.title);
      toggleBtn.innerHTML = revealed
        ? '<i class="fa-solid fa-eye-slash"></i>'
        : '<i class="fa-solid fa-eye"></i>';
    });
  });
});
