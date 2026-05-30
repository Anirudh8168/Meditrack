/**
 * SmartTrack notification drawer + real-time polling.
 */
(function () {
  let lastNotifId = 0;
  let pollTimer = null;
  let drawerOpen = false;

  function csrf() {
    const el = document.querySelector('[name=csrfmiddlewaretoken]');
    return el ? el.value : getCookie('csrftoken');
  }

  function getCookie(name) {
    const m = document.cookie.match('(^|;) ?' + name + '=([^;]*)(;|$)');
    return m ? m[2] : null;
  }

  function iconForType(type) {
    const map = {
      medicine: 'fa-pills text-emerald-600',
      appointment: 'fa-calendar-check text-violet-600',
      connection: 'fa-user-plus text-blue-600',
      report: 'fa-file-medical text-rose-600',
      alert: 'fa-exclamation-triangle text-red-600',
      message: 'fa-comment text-emerald-600',
    };
    return map[type] || 'fa-bell text-slate-600';
  }

  function bgForType(type) {
    const map = {
      medicine: 'bg-emerald-100',
      appointment: 'bg-violet-100',
      connection: 'bg-blue-100',
      report: 'bg-rose-100',
      alert: 'bg-red-100',
      message: 'bg-emerald-100',
    };
    return map[type] || 'bg-slate-100';
  }

  function updateBadge(count) {
    document.querySelectorAll('.notif-badge').forEach((badge) => {
      if (count > 0) {
        badge.textContent = count > 99 ? '99+' : count;
        badge.classList.remove('hidden');
      } else {
        badge.classList.add('hidden');
      }
    });
  }

  function renderDrawerList(notifications) {
    const content = document.getElementById('notifContent');
    if (!content) return;
    if (!notifications || !notifications.length) {
      content.innerHTML = `
        <div class="flex flex-col items-center justify-center py-16 px-4 text-center text-slate-400">
          <i class="fas fa-bell-slash text-4xl mb-3 opacity-30"></i>
          <p class="text-sm font-medium text-slate-600">No notifications for today.</p>
          <p class="text-xs mt-1"><a href="/notifications/" class="text-blue-600 hover:underline">View all notifications</a> to browse older alerts.</p>
        </div>`;
      return;
    }
    content.innerHTML = notifications
      .map(
        (n) => `
      <div class="notif-item rounded-xl border border-slate-100 p-3 flex gap-3 ${n.is_read ? 'bg-white' : 'bg-blue-50/60 border-blue-100'}" data-id="${n.id}">
        <div class="w-10 h-10 rounded-xl ${bgForType(n.type)} flex items-center justify-center flex-shrink-0">
          <i class="fas ${iconForType(n.type)} text-sm"></i>
        </div>
        <div class="flex-1 min-w-0">
          <div class="flex items-start justify-between gap-2">
            <h4 class="font-semibold text-sm text-slate-800 leading-tight">${escapeHtml(n.title)}</h4>
            <span class="text-[10px] text-slate-400 flex-shrink-0 whitespace-nowrap">${escapeHtml(n.time_ago)}</span>
          </div>
          <p class="text-xs text-slate-600 mt-0.5 line-clamp-3">${escapeHtml(n.message)}</p>
          <div class="flex items-center gap-2 mt-2">
            <span class="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded ${
              n.priority === 'high'
                ? 'bg-red-100 text-red-700'
                : n.priority === 'medium'
                  ? 'bg-amber-100 text-amber-700'
                  : 'bg-slate-100 text-slate-600'
            }">${n.type}</span>
            ${
              !n.is_read
                ? `<button type="button" class="mark-read-btn text-[10px] text-blue-600 font-semibold hover:underline" data-id="${n.id}">Mark read</button>`
                : ''
            }
          </div>
        </div>
      </div>`
      )
      .join('');

    content.querySelectorAll('.mark-read-btn').forEach((btn) => {
      btn.addEventListener('click', () => markNotificationRead(btn.dataset.id));
    });
  }

  function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
  }

  async function loadNotifications() {
    const content = document.getElementById('notifContent');
    if (!content) return;
    content.innerHTML =
      '<div class="flex items-center justify-center py-12 text-slate-400"><i class="fas fa-spinner fa-spin mr-2"></i> Loading…</div>';
    try {
      const resp = await fetch('/notifications/feed/?limit=25&preset=today');
      const data = await resp.json();
      if (!data.success && data.notifications === undefined) throw new Error('Failed');
      renderDrawerList(data.notifications);
      updateBadge(data.unread_count);
      if (data.latest_id) lastNotifId = data.latest_id;
    } catch (e) {
      content.innerHTML =
        '<div class="text-center py-8 text-red-500 text-sm">Could not load notifications.</div>';
    }
  }

  async function markNotificationRead(id) {
    try {
      const resp = await fetch(`/notifications/mark-read/${id}/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrf() },
      });
      const data = await resp.json();
      if (data.success) {
        const item = document.querySelector(`.notif-item[data-id="${id}"]`);
        if (item) {
          item.classList.remove('bg-blue-50/60', 'border-blue-100');
          item.classList.add('bg-white');
          const btn = item.querySelector('.mark-read-btn');
          if (btn) btn.remove();
        }
        updateBadge(data.unread_count);
        if (data.latest_id) lastNotifId = data.latest_id;
      }
    } catch (e) {
      console.error(e);
    }
  }

  window.markNotificationRead = markNotificationRead;

  function toggleNotifDrawer() {
    const drawer = document.getElementById('notifDrawer');
    const backdrop = document.getElementById('notifBackdrop');
    if (!drawer || !backdrop) return;
    const opening = drawer.classList.contains('translate-x-full');
    if (opening) {
      drawer.classList.remove('translate-x-full');
      backdrop.classList.remove('hidden');
      document.body.classList.add('overflow-hidden');
      drawerOpen = true;
      loadNotifications();
    } else {
      drawer.classList.add('translate-x-full');
      backdrop.classList.add('hidden');
      document.body.classList.remove('overflow-hidden');
      drawerOpen = false;
    }
  }

  window.toggleNotifDrawer = toggleNotifDrawer;

  async function markAllNotificationsRead() {
    const resp = await fetch('/notifications/mark-all-read/', {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf() },
    });
    const data = await resp.json();
    if (data.success) {
      updateBadge(0);
      loadNotifications();
    }
  }

  window.markAllNotificationsRead = markAllNotificationsRead;

  function showNotifPopup(n) {
    if (n.is_health_risk || (n.category && n.category.indexOf('health_risk_') === 0)) {
      showHealthRiskPopup(n);
      return;
    }
    if (typeof window.showToast === 'function') {
      window.showToast(`${n.title}: ${n.message}`, n.priority === 'high' ? 'error' : 'info');
      return;
    }
    const popup = document.createElement('div');
    popup.className =
      'fixed top-20 right-4 z-[200] bg-white border border-slate-200 shadow-2xl rounded-xl p-4 w-80 max-w-[calc(100vw-2rem)]';
    popup.innerHTML = `<div class="font-semibold text-sm text-slate-800">${escapeHtml(n.title)}</div>
      <div class="text-xs text-slate-500 mt-1 line-clamp-2">${escapeHtml(n.message)}</div>`;
    document.body.appendChild(popup);
    setTimeout(() => popup.remove(), 5000);
  }

  function showHealthRiskPopup(n) {
    const existing = document.getElementById('healthRiskLivePopup');
    if (existing) existing.remove();

    const isEmergency = n.title && n.title.indexOf('EMERGENCY') !== -1;
    const popup = document.createElement('div');
    popup.id = 'healthRiskLivePopup';
    popup.className = 'fixed inset-0 bg-slate-900/70 backdrop-blur-sm z-[10005] flex items-center justify-center p-4';
    popup.innerHTML = `
      <div class="bg-white w-full max-w-md rounded-3xl shadow-2xl overflow-hidden animate-slide-in">
        <div class="px-6 py-4 ${isEmergency ? 'bg-red-600' : 'bg-gradient-to-r from-rose-600 to-red-600'} text-white">
          <div class="flex items-center gap-2 mb-1">
            <i class="fas fa-exclamation-triangle"></i>
            <span class="font-bold">${escapeHtml(n.title || 'High Risk Alert')}</span>
          </div>
          <span class="text-[10px] px-2 py-0.5 rounded-full bg-white/20 font-bold uppercase">CRITICAL</span>
        </div>
        <div class="p-5">
          <p class="text-sm text-slate-700 whitespace-pre-line mb-4">${escapeHtml(n.message)}</p>
          <div class="flex flex-col gap-2">
            <button type="button" id="hrViewDetails" class="w-full py-2.5 bg-slate-800 text-white rounded-xl text-sm font-semibold">View Details</button>
            <button type="button" id="hrDismiss" class="w-full py-2.5 bg-slate-100 text-slate-700 rounded-xl text-sm font-semibold">Dismiss</button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(popup);
    popup.querySelector('#hrDismiss').onclick = function () { popup.remove(); };
    popup.querySelector('#hrViewDetails').onclick = function () {
      popup.remove();
      if (typeof toggleNotifDrawer === 'function') toggleNotifDrawer();
      else window.location.href = '/notifications/';
    };
    if (typeof window.playSound === 'function') window.playSound();
    setTimeout(function () {
      const el = document.getElementById('healthRiskLivePopup');
      if (el) el.remove();
    }, 30000);
  }

  async function pollForUpdates() {
    try {
      const resp = await fetch(`/notifications/poll/?since=${lastNotifId}`);
      const data = await resp.json();
      updateBadge(data.unread_count);
      const msgBadge = document.querySelector('.msg-badge');
      if (msgBadge) {
        if (data.unread_messages > 0) {
          msgBadge.textContent = data.unread_messages;
          msgBadge.classList.remove('hidden');
        } else {
          msgBadge.classList.add('hidden');
        }
      }
      if (data.notifications && data.notifications.length) {
        data.notifications.forEach((n) => {
          if (n.id > lastNotifId) showNotifPopup(n);
        });
      }
      if (data.latest_id && data.latest_id > lastNotifId) {
        lastNotifId = data.latest_id;
      }
      if (drawerOpen && data.notifications && data.notifications.length) {
        loadNotifications();
      }
    } catch (e) {
      /* silent */
    }
  }

  function init() {
    const initEl = document.getElementById('notif-init-data');
    if (initEl) {
      lastNotifId = parseInt(initEl.dataset.latestId || '0', 10) || 0;
      updateBadge(parseInt(initEl.dataset.unread || '0', 10) || 0);
    }
    const bell = document.getElementById('notifBell');
    if (bell) bell.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleNotifDrawer();
    });
    const markAllBtn = document.getElementById('notifMarkAllRead');
    if (markAllBtn) markAllBtn.addEventListener('click', markAllNotificationsRead);
    pollForUpdates();
    pollTimer = setInterval(pollForUpdates, 8000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
