/**
 * SmartTrack — Global toast notifications & confirmation modals.
 * Replaces alert(), confirm(), and prompt() across the app.
 */
(function () {
  'use strict';

  var TOAST_ICONS = {
    success: 'fa-circle-check',
    error: 'fa-circle-xmark',
    warning: 'fa-triangle-exclamation',
    info: 'fa-circle-info',
  };

  var TOAST_STYLES = {
    success: 'st-toast-success',
    error: 'st-toast-error',
    warning: 'st-toast-warning',
    info: 'st-toast-info',
  };

  function ensureContainers() {
    if (!document.getElementById('stToastContainer')) {
      var tc = document.createElement('div');
      tc.id = 'stToastContainer';
      tc.className = 'st-toast-container';
      tc.setAttribute('aria-live', 'polite');
      document.body.appendChild(tc);
    }
    if (!document.getElementById('stConfirmModal')) {
      document.body.insertAdjacentHTML('beforeend', `
<div id="stConfirmModal" class="st-modal hidden" aria-hidden="true" role="dialog" aria-modal="true">
  <div class="st-modal-backdrop" data-st-modal-close></div>
  <div class="st-modal-dialog">
    <div id="stConfirmIcon" class="st-modal-icon st-modal-icon-warning"><i class="fas fa-exclamation-triangle"></i></div>
    <h3 id="stConfirmTitle" class="st-modal-title">Confirm Action</h3>
    <p id="stConfirmMessage" class="st-modal-message"></p>
    <div id="stConfirmInputWrap" class="st-modal-input-wrap hidden">
      <label id="stConfirmInputLabel" class="st-modal-input-label"></label>
      <textarea id="stConfirmInput" class="st-modal-input" rows="3" placeholder=""></textarea>
    </div>
    <p id="stConfirmNote" class="st-modal-note hidden"></p>
    <div class="st-modal-actions">
      <button type="button" id="stConfirmCancel" class="st-btn-cancel">Cancel</button>
      <button type="button" id="stConfirmOk" class="st-btn-confirm">Confirm</button>
    </div>
  </div>
</div>`);
    }
  }

  /**
   * showToast(type, title, message, duration?)
   * showToast(message, type) — legacy
   */
  function showToast(arg1, arg2, arg3, arg4) {
    ensureContainers();
    var type, title, message, duration;
    var types = ['success', 'error', 'warning', 'info'];

    if (typeof arg2 === 'string' && types.indexOf(arg2) !== -1 && arg3 === undefined) {
      message = arg1;
      type = arg2;
      title = null;
      duration = typeof arg4 === 'number' ? arg4 : 4000;
    } else if (types.indexOf(arg1) !== -1) {
      type = arg1;
      title = arg2 || null;
      message = arg3 || '';
      duration = typeof arg4 === 'number' ? arg4 : 4000;
    } else {
      message = arg1;
      type = arg2 || 'info';
      title = null;
      duration = 4000;
    }

    type = types.indexOf(type) !== -1 ? type : 'info';
    duration = duration || (type === 'error' ? 5000 : 4000);

    var container = document.getElementById('stToastContainer');
    var toast = document.createElement('div');
    toast.className = 'st-toast ' + (TOAST_STYLES[type] || TOAST_STYLES.info);
    toast.innerHTML =
      '<div class="st-toast-icon"><i class="fas ' + (TOAST_ICONS[type] || TOAST_ICONS.info) + '"></i></div>' +
      '<div class="st-toast-body">' +
        (title ? '<div class="st-toast-title">' + escapeHtml(title) + '</div>' : '') +
        '<div class="st-toast-msg">' + escapeHtml(message) + '</div>' +
      '</div>' +
      '<button type="button" class="st-toast-close" aria-label="Dismiss"><i class="fas fa-times"></i></button>';

    toast.querySelector('.st-toast-close').addEventListener('click', function () { dismissToast(toast); });
    container.appendChild(toast);
    requestAnimationFrame(function () { toast.classList.add('st-toast-visible'); });

    var timer = setTimeout(function () { dismissToast(toast); }, duration);
    toast._timer = timer;
  }

  function dismissToast(toast) {
    if (!toast || toast._dismissed) return;
    toast._dismissed = true;
    clearTimeout(toast._timer);
    toast.classList.remove('st-toast-visible');
    setTimeout(function () { toast.remove(); }, 280);
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  var confirmResolve = null;

  /**
   * @param {Object} opts
   * @returns {Promise<boolean|string>} true/false, or input string if requireInput
   */
  function showConfirmModal(opts) {
    ensureContainers();
    opts = opts || {};
    var modal = document.getElementById('stConfirmModal');
    var titleEl = document.getElementById('stConfirmTitle');
    var msgEl = document.getElementById('stConfirmMessage');
    var noteEl = document.getElementById('stConfirmNote');
    var inputWrap = document.getElementById('stConfirmInputWrap');
    var inputLabel = document.getElementById('stConfirmInputLabel');
    var inputEl = document.getElementById('stConfirmInput');
    var okBtn = document.getElementById('stConfirmOk');
    var cancelBtn = document.getElementById('stConfirmCancel');
    var iconEl = document.getElementById('stConfirmIcon');

    titleEl.textContent = opts.title || 'Confirm Action';
    msgEl.innerHTML = opts.message || opts.body || 'Are you sure you want to continue?';

    if (opts.note) {
      noteEl.textContent = opts.note;
      noteEl.classList.remove('hidden');
    } else {
      noteEl.classList.add('hidden');
    }

    var variant = opts.variant || 'warning';
    iconEl.className = 'st-modal-icon st-modal-icon-' + variant;
    iconEl.innerHTML = '<i class="fas ' + (
      variant === 'danger' ? 'fa-trash-can' :
      variant === 'info' ? 'fa-circle-info' : 'fa-exclamation-triangle'
    ) + '"></i>';

    okBtn.textContent = opts.confirmText || opts.confirmLabel || 'Confirm';
    cancelBtn.textContent = opts.cancelText || opts.cancelLabel || 'Cancel';
    okBtn.className = 'st-btn-confirm' + (variant === 'danger' ? ' st-btn-danger' : '');

    if (opts.requireInput) {
      inputWrap.classList.remove('hidden');
      inputLabel.textContent = opts.inputLabel || 'Reason (required)';
      inputEl.placeholder = opts.inputPlaceholder || '';
      inputEl.value = opts.inputDefault || '';
    } else {
      inputWrap.classList.add('hidden');
      inputEl.value = '';
    }

    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';

    return new Promise(function (resolve) {
      confirmResolve = resolve;

      function close(result) {
        modal.classList.add('hidden');
        modal.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
        confirmResolve = null;
        resolve(result);
      }

      function onOk() {
        if (opts.requireInput) {
          var val = inputEl.value.trim();
          if (!val) {
            showToast('warning', 'Required', opts.inputRequiredMessage || 'Please provide a reason.');
            inputEl.focus();
            return;
          }
          close(val);
          return;
        }
        close(true);
      }

      function onCancel() { close(false); }

      okBtn.onclick = onOk;
      cancelBtn.onclick = onCancel;
      modal.querySelectorAll('[data-st-modal-close]').forEach(function (el) {
        el.onclick = onCancel;
      });

      function onKey(e) {
        if (e.key === 'Escape') { onCancel(); document.removeEventListener('keydown', onKey); }
      }
      document.addEventListener('keydown', onKey);

      setTimeout(function () {
        if (opts.requireInput) inputEl.focus();
        else okBtn.focus();
      }, 50);
    });
  }

  /** Legacy confirm() replacement — returns Promise<boolean> */
  function smartConfirm(message, title) {
    return showConfirmModal({ title: title || 'Confirm', message: message, variant: 'warning' });
  }

  function bindConfirmForms() {
    document.querySelectorAll('form[data-st-confirm]').forEach(function (form) {
      if (form.dataset.stBound) return;
      form.dataset.stBound = '1';
      form.addEventListener('submit', function (e) {
        if (form.dataset.stConfirmed === '1') {
          delete form.dataset.stConfirmed;
          return;
        }
        e.preventDefault();
        showConfirmModal({
          title: form.dataset.stConfirmTitle || 'Confirm Action',
          message: form.getAttribute('data-st-confirm') || 'Are you sure?',
          note: form.dataset.stConfirmNote || '',
          variant: form.dataset.stConfirmVariant || 'warning',
          confirmText: form.dataset.stConfirmOk || 'Confirm',
        }).then(function (ok) {
          if (ok) {
            form.dataset.stConfirmed = '1';
            form.requestSubmit ? form.requestSubmit() : form.submit();
          }
        });
      });
    });

    document.querySelectorAll('[data-st-confirm-click]').forEach(function (el) {
      if (el.dataset.stBound) return;
      el.dataset.stBound = '1';
      el.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var form = el.closest('form');
        showConfirmModal({
          title: el.dataset.stConfirmTitle || 'Confirm Action',
          message: el.getAttribute('data-st-confirm-click') || 'Are you sure?',
          variant: el.dataset.stConfirmVariant || 'warning',
          confirmText: el.dataset.stConfirmOk || 'Confirm',
        }).then(function (ok) {
          if (ok && form) {
            form.dataset.stConfirmed = '1';
            form.requestSubmit ? form.requestSubmit() : form.submit();
          }
        });
      });
    });
  }

  document.addEventListener('DOMContentLoaded', bindConfirmForms);

  window.showToast = showToast;
  window.showConfirmModal = showConfirmModal;
  window.smartConfirm = smartConfirm;
  window.SmartTrackUI = { showToast: showToast, showConfirmModal: showConfirmModal, smartConfirm: smartConfirm };
})();
