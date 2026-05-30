(function () {
  'use strict';

  function getCsrfToken() {
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    if (el) return el.value;
    var match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function closeDeleteModal(modal) {
    modal.classList.add('hidden');
    modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
  }

  function openDeleteModal(opts) {
    var modal = document.getElementById('activityDeleteModal');
    if (!modal) return;

    document.getElementById('activityDeleteTitle').textContent = opts.title || '';
    document.getElementById('activityDeleteSchedule').textContent = opts.schedule || '';
    document.getElementById('activityDeleteId').value = opts.activityId || '';
    document.getElementById('activityDeleteReason').value = '';
    document.getElementById('activityDeleteEffectiveDate').value = opts.effectiveDate || '';
    modal.dataset.redirect = opts.redirect || '';

    var scopeWrap = document.getElementById('activityDeleteScopeWrap');
    if (opts.isRecurring) {
      scopeWrap.classList.remove('hidden');
      var radios = scopeWrap.querySelectorAll('input[name=delete_scope]');
      radios.forEach(function (r) { r.checked = r.value === 'entire'; });
    } else {
      scopeWrap.classList.add('hidden');
    }

    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    document.getElementById('activityDeleteReason').focus();
  }

  function bindMenus() {
    document.querySelectorAll('[data-activity-menu-toggle]').forEach(function (btn) {
      if (btn.dataset.bound) return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var wrap = btn.closest('[data-activity-menu-wrap]');
        var menu = wrap.querySelector('[data-activity-menu-dropdown]');
        document.querySelectorAll('[data-activity-menu-dropdown]').forEach(function (m) {
          if (m !== menu) m.classList.add('hidden');
        });
        menu.classList.toggle('hidden');
      });
    });

    document.addEventListener('click', function () {
      document.querySelectorAll('[data-activity-menu-dropdown]').forEach(function (m) {
        m.classList.add('hidden');
      });
    });
  }

  function bindDeleteButtons() {
    document.querySelectorAll('[data-delete-activity]').forEach(function (btn) {
      if (btn.dataset.bound) return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var menu = btn.closest('[data-activity-menu-dropdown]');
        if (menu) menu.classList.add('hidden');
        openDeleteModal({
          activityId: btn.dataset.activityId,
          title: btn.dataset.activityTitle,
          schedule: btn.dataset.scheduleLabel,
          isRecurring: btn.dataset.isRecurring === '1',
          effectiveDate: btn.dataset.effectiveDate || '',
          redirect: btn.dataset.redirect || '',
        });
      });
    });
  }

  function bindDeleteModal() {
    var modal = document.getElementById('activityDeleteModal');
    if (!modal || modal.dataset.bound) return;
    modal.dataset.bound = '1';

    modal.querySelectorAll('[data-activity-delete-close]').forEach(function (el) {
      el.addEventListener('click', function () { closeDeleteModal(modal); });
    });

    document.getElementById('activityDeleteConfirm').addEventListener('click', function () {
      var reason = document.getElementById('activityDeleteReason').value.trim();
      if (!reason) {
        if (window.showToast) {
          showToast('warning', 'Required', 'Please provide a reason for deletion.');
        }
        document.getElementById('activityDeleteReason').focus();
        return;
      }

      var activityId = document.getElementById('activityDeleteId').value;
      var scopeEl = modal.querySelector('input[name=delete_scope]:checked');
      var scope = scopeEl ? scopeEl.value : 'entire';
      var effectiveDate = document.getElementById('activityDeleteEffectiveDate').value;

      var formData = new FormData();
      formData.append('reason', reason);
      formData.append('scope', scope);
      if (effectiveDate) formData.append('effective_date', effectiveDate);
      if (modal.dataset.redirect) formData.append('redirect', modal.dataset.redirect);

      var confirmBtn = document.getElementById('activityDeleteConfirm');
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Deleting…';

      fetch('/medicines/activities/' + activityId + '/delete/', {
        method: 'POST',
        headers: { 'X-CSRFToken': getCsrfToken() },
        body: formData,
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          confirmBtn.disabled = false;
          confirmBtn.textContent = 'Delete Activity';
          if (data.success) {
            closeDeleteModal(modal);
            if (window.showToast) showToast('success', 'Deleted', data.message || 'Activity removed.');
            window.location.href = data.redirect || modal.dataset.redirect || '/medicines/activities/';
          } else {
            if (window.showToast) showToast('error', 'Error', data.error || 'Could not delete activity.');
          }
        })
        .catch(function () {
          confirmBtn.disabled = false;
          confirmBtn.textContent = 'Delete Activity';
          if (window.showToast) showToast('error', 'Error', 'Network error. Please try again.');
        });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindMenus();
    bindDeleteButtons();
    bindDeleteModal();
  });
})();
