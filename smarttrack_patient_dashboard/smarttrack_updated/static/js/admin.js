(function () {
  'use strict';

  function initSidebar() {
    var toggle = document.getElementById('adminSidebarToggle');
    var sidebar = document.getElementById('adminSidebar');
    var overlay = document.getElementById('adminOverlay');
    if (!toggle || !sidebar) return;

    function openSidebar() {
      sidebar.classList.add('open');
      if (overlay) overlay.classList.add('open');
      document.body.style.overflow = 'hidden';
    }

    function closeSidebar() {
      sidebar.classList.remove('open');
      if (overlay) overlay.classList.remove('open');
      document.body.style.overflow = '';
    }

    toggle.addEventListener('click', function () {
      if (sidebar.classList.contains('open')) {
        closeSidebar();
      } else {
        openSidebar();
      }
    });

    if (overlay) {
      overlay.addEventListener('click', closeSidebar);
    }

    sidebar.querySelectorAll('.admin-nav-link').forEach(function (link) {
      link.addEventListener('click', function () {
        if (window.innerWidth < 1024) closeSidebar();
      });
    });
  }

  function initNavGroups() {
    document.querySelectorAll('[data-nav-group]').forEach(function (btn) {
      var targetId = btn.getAttribute('data-nav-group');
      var target = document.getElementById(targetId);
      if (!target) return;

      var storageKey = 'admin_nav_' + targetId;
      var isOpen = localStorage.getItem(storageKey);
      if (isOpen === 'true' || btn.classList.contains('open')) {
        target.classList.remove('hidden');
        btn.classList.add('open');
      }

      btn.addEventListener('click', function () {
        var expanded = !target.classList.contains('hidden');
        if (expanded) {
          target.classList.add('hidden');
          btn.classList.remove('open');
          localStorage.setItem(storageKey, 'false');
        } else {
          target.classList.remove('hidden');
          btn.classList.add('open');
          localStorage.setItem(storageKey, 'true');
        }
      });
    });
  }

  function initDeleteModal() {
    var modal = document.getElementById('adminDeleteModal');
    var form = document.getElementById('adminDeleteForm');
    var titleEl = document.getElementById('adminDeleteModalTitle');
    var messageEl = document.getElementById('adminDeleteModalMessage');
    var warningEl = document.getElementById('adminDeleteModalWarning');
    if (!modal || !form) return;

    function closeModal() {
      modal.classList.add('hidden');
      modal.setAttribute('aria-hidden', 'true');
      document.body.style.overflow = '';
    }

    function openModal(url, name, warning) {
      form.action = url;
      titleEl.textContent = 'Delete Record?';
      messageEl.innerHTML = 'Are you sure you want to remove <strong>' + name + '</strong>?';
      if (warning) {
        warningEl.textContent = warning;
        warningEl.classList.remove('hidden');
      } else {
        warningEl.textContent = '';
        warningEl.classList.add('hidden');
      }
      modal.classList.remove('hidden');
      modal.setAttribute('aria-hidden', 'false');
      document.body.style.overflow = 'hidden';
    }

    document.querySelectorAll('[data-delete-url]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        openModal(
          btn.getAttribute('data-delete-url'),
          btn.getAttribute('data-delete-name') || 'this record',
          btn.getAttribute('data-delete-warning') || ''
        );
      });
    });

    modal.querySelectorAll('[data-modal-close]').forEach(function (el) {
      el.addEventListener('click', closeModal);
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
        closeModal();
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initSidebar();
    initNavGroups();
    initDeleteModal();
  });
})();
