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

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('error-modal-dismiss').addEventListener('click', () => hideModal('error-modal'));

  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', () => {
      fetch(logoutBtn.dataset.url, { method: 'POST' })
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

  document.querySelectorAll('button.delete-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!await confirmModal(btn.dataset.confirm)) return;
      fetch(btn.dataset.url, { method: 'POST' }).then(r => {
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

    btn.addEventListener('click', () => {
      if (panel.classList.contains('hidden')) {
        if (!loaded) {
          fetch(btn.dataset.url)
            .then(r => r.json())
            .then(data => {
              usernameEl.textContent = data.username || '-';
              passwordEl.textContent = data.password || '-';
              passwordEl.dataset.value = data.password || '';
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
      passwordEl.textContent = isHidden ? passwordEl.dataset.value || '-' : '••••••••';
      toggleBtn.innerHTML = isHidden
        ? '<i class="fa-solid fa-eye-slash"></i>'
        : '<i class="fa-solid fa-eye"></i>';
    });
  });
});
