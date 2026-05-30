/**
 * SmartTrack — activity reminder engine (server-driven, DB-backed retry scheduling).
 */
(function () {
  'use strict';

  var actReminders = [];
  var csrfToken = '';
  var popupVisible = false;
  var syncTimer = null;
  var wakeTimer = null;
  var pendingStartLogId = null;
  var SYNC_MS = 30000;
  var SYNC_ACTIVE_MS = 10000;
  var backgroundTickTimer = null;
  var activeSessionCompleteNotified = {};
  var currentBackgroundSession = null;

  function getCsrf() {
    if (csrfToken) return csrfToken;
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    csrfToken = el ? el.value : '';
    return csrfToken;
  }

  function playSound() {
    var audio = document.getElementById('reminderSound');
    if (audio) audio.play().catch(function () {});
  }

  function secondsUntil(iso) {
    if (!iso) return 99999;
    return (new Date(iso).getTime() - Date.now()) / 1000;
  }

  function ackReminder(logId) {
    fetch('/medicines/activities/ack-reminder/' + logId + '/', {
      method: 'POST',
      headers: { 'X-CSRFToken': getCsrf() },
    }).catch(function () {});
  }

  function ensureActivityPopup() {
    if (document.getElementById('activityReminderPopup')) return;
    document.body.insertAdjacentHTML('beforeend', `
<div id="activityReminderPopup" class="fixed inset-0 bg-slate-900/80 backdrop-blur-sm z-[10002] hidden flex items-center justify-center p-4">
  <div class="bg-white w-full max-w-md rounded-3xl shadow-2xl overflow-hidden animate-slide-in">
    <div class="bg-gradient-to-r from-blue-600 to-violet-600 px-6 py-5 text-white text-center">
      <div class="w-14 h-14 bg-white/20 rounded-full flex items-center justify-center mx-auto mb-3">
        <i class="fas fa-bell text-2xl"></i>
      </div>
      <h3 class="text-xl font-bold">Activity Reminder</h3>
      <p class="text-blue-100 text-sm">It's time for your scheduled activity.</p>
    </div>
    <div class="p-6">
      <div id="popupActTitle" class="text-lg font-bold text-slate-800 text-center mb-1"></div>
      <div id="popupActMeta" class="text-sm text-slate-500 text-center mb-1"></div>
      <div id="popupActSchedule" class="text-xs text-slate-400 text-center mb-4"></div>
      <div id="popupActDesc" class="text-sm text-slate-600 bg-slate-50 rounded-xl p-3 mb-5 hidden"></div>
      <div class="flex flex-col gap-2.5">
        <button id="popupStartActBtn" class="w-full py-3 bg-blue-600 text-white rounded-xl font-bold hover:bg-blue-700 transition">
          Yes, I'm Starting
        </button>
        <button id="popupSnoozeActBtn" class="w-full py-3 bg-slate-100 text-slate-700 rounded-xl font-semibold hover:bg-slate-200 transition">
          Remind Me Later
        </button>
      </div>
    </div>
  </div>
</div>`);
  }

  function ensureStartProofModal() {
    if (document.getElementById('activityStartProofModal')) return;
    document.body.insertAdjacentHTML('beforeend', `
<div id="activityStartProofModal" class="fixed inset-0 bg-slate-900/80 backdrop-blur-sm z-[10003] hidden flex items-center justify-center p-4">
  <div class="bg-white w-full max-w-md rounded-3xl shadow-2xl overflow-hidden">
    <div class="bg-gradient-to-r from-emerald-600 to-teal-600 px-6 py-5 text-white">
      <h3 class="text-lg font-bold">Confirm Activity Start</h3>
      <p class="text-emerald-100 text-sm mt-1">Please upload proof before starting your activity.</p>
    </div>
    <div class="p-6 space-y-4">
      <p class="text-xs text-slate-500">Accepted: image, video, PDF, or document (e.g. walking selfie, gym photo, hospital slip).</p>
      <input type="file" id="startProofFile" accept="image/*,video/*,.pdf,.doc,.docx"
             class="w-full text-sm text-slate-600 file:mr-3 file:py-2.5 file:px-4 file:rounded-xl file:border-0 file:bg-emerald-50 file:text-emerald-700 file:font-semibold">
      <p id="startProofError" class="text-xs text-red-600 hidden"></p>
      <div class="flex flex-col gap-2">
        <button id="confirmStartProofBtn" class="w-full py-3 bg-emerald-600 text-white rounded-xl font-bold hover:bg-emerald-700 transition">
          Upload &amp; Start
        </button>
        <button id="cancelStartProofBtn" class="w-full py-3 bg-slate-100 text-slate-700 rounded-xl font-semibold hover:bg-slate-200 transition">
          Cancel
        </button>
      </div>
    </div>
  </div>
</div>`);

    document.getElementById('cancelStartProofBtn').onclick = function () {
      document.getElementById('activityStartProofModal').classList.add('hidden');
      pendingStartLogId = null;
    };

    document.getElementById('confirmStartProofBtn').onclick = function () {
      var fileInput = document.getElementById('startProofFile');
      var errEl = document.getElementById('startProofError');
      if (!fileInput.files || !fileInput.files[0]) {
        errEl.textContent = 'Proof upload is required to start.';
        errEl.classList.remove('hidden');
        return;
      }
      errEl.classList.add('hidden');
      submitStartWithProof(pendingStartLogId, fileInput.files[0]);
    };
  }

  function openStartProofModal(logId) {
    pendingStartLogId = logId;
    ensureStartProofModal();
    document.getElementById('startProofFile').value = '';
    document.getElementById('startProofError').classList.add('hidden');
    document.getElementById('activityStartProofModal').classList.remove('hidden');
  }

  function submitStartWithProof(logId, proofFile) {
    if (!logId) return;
    var btn = document.getElementById('confirmStartProofBtn');
    btn.disabled = true;
    btn.textContent = 'Starting…';

    var fd = new FormData();
    fd.append('start_proof', proofFile);

    fetch('/medicines/activities/start/' + logId + '/', {
      method: 'POST',
      headers: { 'X-CSRFToken': getCsrf() },
      body: fd,
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        btn.disabled = false;
        btn.textContent = 'Upload & Start';
        if (d.success) {
          document.getElementById('activityStartProofModal').classList.add('hidden');
          window.location.href = d.redirect;
        } else {
          var errEl = document.getElementById('startProofError');
          errEl.textContent = d.message || d.error || 'Could not start activity';
          errEl.classList.remove('hidden');
        }
      })
      .catch(function () {
        btn.disabled = false;
        btn.textContent = 'Upload & Start';
        if (window.showToast) showToast('error', 'Error', 'Could not start activity');
      });
  }

  function staticStatusLabel(r) {
    if (r.status_label) return r.status_label;
    if (r.status === 'completed') return 'Completed';
    if (r.status === 'missed') return 'Missed';
    if (r.status === 'in_progress') return 'In Progress';
    if (r.is_upcoming) return 'Scheduled';
    if (r.can_start) return 'Due now';
    return 'Scheduled';
  }

  function showActivityPopup(item) {
    if (!item || !item.popup_due) return;
    if (popupVisible) return;
    if (item.status === 'in_progress' || item.status === 'completed' || item.status === 'missed' || item.status === 'skipped') {
      return;
    }

    popupVisible = true;
    item.popup_due = false;
    ackReminder(item.log_id);
    ensureActivityPopup();

    document.getElementById('popupActTitle').textContent = item.title;
    document.getElementById('popupActMeta').textContent = item.duration_minutes + ' Minutes';
    document.getElementById('popupActSchedule').textContent =
      'Scheduled: ' + (item.time_display || item.time);
    var descEl = document.getElementById('popupActDesc');
    if (item.description) {
      descEl.textContent = item.description;
      descEl.classList.remove('hidden');
    } else {
      descEl.classList.add('hidden');
    }

    var popup = document.getElementById('activityReminderPopup');
    popup.classList.remove('hidden');
    playSound();

    document.getElementById('popupStartActBtn').onclick = function () {
      closeActivityPopup();
      openStartProofModal(item.log_id);
    };
    document.getElementById('popupSnoozeActBtn').onclick = function () {
      snoozeActivity(item.log_id);
      closeActivityPopup();
      if (window.showToast) showToast('info', 'Reminder Snoozed', 'We will remind you again in 10 minutes.');
    };
  }

  function closeActivityPopup() {
    var p = document.getElementById('activityReminderPopup');
    if (p) p.classList.add('hidden');
    popupVisible = false;
  }

  window.startActivity = function (logId) {
    openStartProofModal(logId);
  };

  function snoozeActivity(logId) {
    fetch('/medicines/activities/snooze/' + logId + '/', {
      method: 'POST',
      headers: { 'X-CSRFToken': getCsrf() },
    }).then(function () {
      syncActivityReminders();
    });
  }
  window.snoozeActivity = snoozeActivity;

  function renderDashboardActivityItem(r) {
    var statusClass = r.status === 'missed' ? 'bg-red-100 text-red-700'
      : r.status === 'completed' ? 'bg-emerald-100 text-emerald-700'
      : r.status === 'in_progress' ? 'bg-amber-100 text-amber-700'
      : r.is_upcoming ? 'bg-slate-100 text-slate-600'
      : 'bg-blue-100 text-blue-700';
    var label = staticStatusLabel(r);
    var buttons = '';
    var meta = (r.time_display || r.time) + ' • ' + r.duration_minutes + ' min';

    if (r.status === 'completed') {
      meta = r.duration_minutes + ' Minutes';
      if (r.started_at_display && r.completed_at_display) {
        meta += ' · Started: ' + r.started_at_display + ' · Finished: ' + r.completed_at_display;
      }
    }

    if (r.status !== 'completed' && r.status !== 'missed') {
      if (r.in_progress) {
        buttons += '<a href="/medicines/activities/session/' + r.log_id + '/" class="text-[11px] px-2.5 py-1 rounded-lg bg-amber-500 text-white font-semibold">Continue Session</a>';
      } else if (r.can_start) {
        buttons += '<button type="button" onclick="startActivity(' + r.log_id + ')" class="text-[11px] px-2.5 py-1 rounded-lg bg-blue-600 text-white font-semibold">Start</button>';
        buttons += '<button type="button" onclick="snoozeActivity(' + r.log_id + ')" class="text-[11px] px-2.5 py-1 rounded-lg bg-slate-100 text-slate-600 font-semibold">Remind Later</button>';
      } else if (r.is_upcoming) {
        buttons += '<span class="text-[11px] px-2.5 py-1 rounded-lg bg-slate-100 text-slate-500">Scheduled</span>';
      }
    }

    return '<div class="p-3 rounded-xl border border-slate-100 bg-slate-50/40 hover:border-blue-100 transition">' +
      '<div class="flex items-start justify-between gap-2 mb-2">' +
      '<div class="min-w-0 flex-1"><div class="font-semibold text-slate-800 text-sm truncate">' + r.title + '</div>' +
      '<div class="text-xs text-slate-500">' + meta + '</div></div>' +
      '<span class="text-[10px] px-2 py-0.5 rounded-full font-semibold whitespace-nowrap ' + statusClass + '">' + label + '</span></div>' +
      (buttons ? '<div class="flex flex-wrap gap-1.5">' + buttons + '</div>' : '') +
      '</div>';
  }

  function updateActivityDashboardList() {
    var list = document.getElementById('upcomingActsList');
    if (!list) return;
    var items = actReminders.filter(function (r) {
      return r.status !== 'skipped';
    });
    if (!items.length) return;
    list.innerHTML = items.map(renderDashboardActivityItem).join('');
  }

  function isOnActivitySessionPage() {
    return window.location.pathname.indexOf('/activities/session/') !== -1;
  }

  function getActiveInProgressSession(reminders) {
    return reminders.find(function (r) {
      return r.status === 'in_progress' && r.session_url;
    }) || null;
  }

  function formatRemainingLabel(seconds) {
    var sec = Math.max(0, Math.floor(seconds));
    if (sec <= 0) return 'Ready to complete';
    var mins = Math.ceil(sec / 60);
    return mins + ' min left';
  }

  function ensureActivityBackgroundWidget() {
    if (document.getElementById('activityBackgroundWidget')) return;
    document.body.insertAdjacentHTML('beforeend', `
<div id="activityBackgroundWidget" class="hidden fixed bottom-5 right-5 z-[10001] w-72 max-w-[calc(100vw-2rem)]">
  <div class="bg-white rounded-2xl shadow-2xl border border-emerald-200 overflow-hidden">
    <div class="bg-gradient-to-r from-emerald-600 to-teal-600 px-4 py-2.5 flex items-center gap-2 text-white">
      <span class="w-2 h-2 rounded-full bg-lime-300 animate-pulse flex-shrink-0"></span>
      <span id="activityWidgetStatus" class="text-xs font-bold uppercase tracking-wide">Activity Running</span>
    </div>
    <div class="p-4 space-y-3">
      <div>
        <div id="activityWidgetTitle" class="font-bold text-slate-800 text-sm truncate"></div>
        <div id="activityWidgetMeta" class="text-xs text-slate-500 mt-0.5"></div>
      </div>
      <a id="activityWidgetOpenBtn" href="#" class="block w-full text-center py-2.5 rounded-xl bg-emerald-600 text-white text-sm font-bold hover:bg-emerald-700 transition">
        Resume Activity
      </a>
    </div>
  </div>
</div>`);
  }

  function ensureActivityCompleteToast() {
    if (document.getElementById('activityCompleteToast')) return;
    document.body.insertAdjacentHTML('beforeend', `
<div id="activityCompleteToast" class="hidden fixed bottom-24 right-5 z-[10002] w-80 max-w-[calc(100vw-2rem)]">
  <div class="bg-white rounded-2xl shadow-2xl border border-blue-200 overflow-hidden">
    <div class="bg-gradient-to-r from-blue-600 to-violet-600 px-4 py-3 text-white">
      <div class="font-bold text-sm">Activity Complete</div>
      <p class="text-blue-100 text-xs mt-0.5">You can now mark activity as completed.</p>
    </div>
    <div class="p-4">
      <p id="activityCompleteToastTitle" class="text-sm font-semibold text-slate-800 mb-3"></p>
      <a id="activityCompleteOpenBtn" href="#" class="block w-full text-center py-2.5 rounded-xl bg-blue-600 text-white text-sm font-bold hover:bg-blue-700 transition">
        Open Activity
      </a>
    </div>
  </div>
</div>`);
  }

  function hideActivityBackgroundWidget() {
    var widget = document.getElementById('activityBackgroundWidget');
    if (widget) widget.classList.add('hidden');
    currentBackgroundSession = null;
    if (backgroundTickTimer) {
      clearInterval(backgroundTickTimer);
      backgroundTickTimer = null;
    }
  }

  function updateBackgroundWidgetDisplay(session) {
    if (!session) return;
    var AT = window.ActivityTimer;
    var remaining = AT
      ? AT.secondsRemaining(session.started_at_iso, session.duration_seconds)
      : (session.remaining_seconds || 0);
    var titleEl = document.getElementById('activityWidgetTitle');
    var metaEl = document.getElementById('activityWidgetMeta');
    var statusEl = document.getElementById('activityWidgetStatus');
    var openBtn = document.getElementById('activityWidgetOpenBtn');
    if (!titleEl || !metaEl || !openBtn) return;

    titleEl.textContent = session.title;
    metaEl.textContent = (session.activity_type_display || 'Activity') + ' • ' + formatRemainingLabel(remaining);
    openBtn.href = session.session_url;
    openBtn.textContent = remaining <= 0 ? 'Mark Done' : 'Resume Activity';

    if (statusEl) {
      statusEl.textContent = remaining <= 0 ? 'Activity Complete' : 'Activity In Progress';
    }
  }

  function showActivityCompleteNotification(session) {
    if (!session || activeSessionCompleteNotified[session.log_id]) return;
    activeSessionCompleteNotified[session.log_id] = true;

    ensureActivityCompleteToast();
    var toast = document.getElementById('activityCompleteToast');
    var titleEl = document.getElementById('activityCompleteToastTitle');
    var openBtn = document.getElementById('activityCompleteOpenBtn');
    if (titleEl) titleEl.textContent = session.title;
    if (openBtn) openBtn.href = session.session_url;
    if (toast) toast.classList.remove('hidden');

    if (window.showToast) {
      showToast('success', 'Activity Complete', 'You can now mark "' + session.title + '" as completed.');
    }
    playSound();
  }

  function updateActivityBackgroundMode(reminders) {
    var active = getActiveInProgressSession(reminders);

    if (!active) {
      hideActivityBackgroundWidget();
      var toast = document.getElementById('activityCompleteToast');
      if (toast) toast.classList.add('hidden');
      return;
    }

    if (isOnActivitySessionPage()) {
      hideActivityBackgroundWidget();
      return;
    }

    ensureActivityBackgroundWidget();
    currentBackgroundSession = active;

    var widget = document.getElementById('activityBackgroundWidget');
    if (widget) widget.classList.remove('hidden');

    updateBackgroundWidgetDisplay(active);

    var AT = window.ActivityTimer;
    var remaining = AT
      ? AT.secondsRemaining(active.started_at_iso, active.duration_seconds)
      : (active.remaining_seconds || 0);
    if (remaining <= 0 || active.can_complete) {
      showActivityCompleteNotification(active);
    }

    if (!backgroundTickTimer) {
      backgroundTickTimer = setInterval(function () {
        if (!currentBackgroundSession) return;
        updateBackgroundWidgetDisplay(currentBackgroundSession);
        var AT2 = window.ActivityTimer;
        if (!AT2) return;
        var rem = AT2.secondsRemaining(
          currentBackgroundSession.started_at_iso,
          currentBackgroundSession.duration_seconds
        );
        if (rem <= 0) {
          showActivityCompleteNotification(currentBackgroundSession);
        }
      }, 1000);
    }
  }

  function hasActiveReminders() {
    return actReminders.some(function (r) {
      return r.status === 'scheduled' &&
        (r.tracking_status === 'pending' || r.tracking_status === 'snoozed');
    }) || actReminders.some(function (r) {
      return r.status === 'in_progress';
    });
  }

  function nearestPopupSeconds() {
    var min = 99999;
    actReminders.forEach(function (r) {
      if (r.status !== 'scheduled') return;
      var s = secondsUntil(r.next_popup_at);
      if (s < min) min = s;
    });
    return min;
  }

  function scheduleWake() {
    if (wakeTimer) clearTimeout(wakeTimer);
    var sec = nearestPopupSeconds();
    if (sec > 0 && sec < 7200) {
      wakeTimer = setTimeout(function () {
        syncActivityReminders();
      }, Math.max(1000, sec * 1000 + 500));
    }
  }

  function getSyncInterval() {
    if (!hasActiveReminders()) return SYNC_MS;
    var sec = nearestPopupSeconds();
    if (sec <= 120 || actReminders.some(function (r) { return r.popup_due; })) {
      return SYNC_ACTIVE_MS;
    }
    return SYNC_MS;
  }

  function scheduleSync() {
    if (syncTimer) clearInterval(syncTimer);
    syncTimer = setInterval(syncActivityReminders, getSyncInterval());
    scheduleWake();
  }

  async function syncActivityReminders() {
    try {
      var resp = await fetch('/medicines/activities/reminders/');
      var data = await resp.json();
      if (!data.reminders) return;
      actReminders = data.reminders;
      updateActivityBackgroundMode(actReminders);

      if (!popupVisible) {
        var due = actReminders.find(function (r) {
          return r.popup_due && r.status === 'scheduled';
        });
        if (due) showActivityPopup(due);
      }

      updateActivityDashboardList();
      scheduleSync();
    } catch (e) {
      console.error('Activity reminder sync failed', e);
    }
  }

  function shouldRun() {
    return true;
  }

  function init() {
    if (!shouldRun()) return;
    syncActivityReminders();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.syncActivityReminders = syncActivityReminders;
  window.closeActivityPopup = closeActivityPopup;
  window.openStartProofModal = openStartProofModal;
})();
