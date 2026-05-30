/**
 * SmartTrack — medicine reminder engine (server-driven, DB-backed retry scheduling).
 */
(function () {
  'use strict';

  var medReminders = [];
  var csrfToken = '';
  var popupVisible = false;
  var markingInProgress = false;
  var syncTimer = null;
  var wakeTimer = null;
  var SYNC_MS = 30000;
  var SYNC_ACTIVE_MS = 5000;

  function getCookie(name) {
    var match = document.cookie.match('(^|;) ?' + name + '=([^;]*)(;|$)');
    return match ? match[2] : null;
  }

  function getCsrf() {
    if (csrfToken) return csrfToken;
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    csrfToken = el ? el.value : (getCookie('csrftoken') || '');
    return csrfToken;
  }

  function showToastMsg(type, title, message) {
    if (typeof window.showToast === 'function') {
      window.showToast(type, title, message);
      return;
    }
    var toast = document.createElement('div');
    toast.className = 'fixed top-5 right-5 z-[10002] max-w-sm px-4 py-3 pr-12 rounded-2xl text-white text-sm font-semibold shadow-2xl ' +
      (type === 'success' ? 'bg-emerald-600' : type === 'warning' ? 'bg-amber-600' : 'bg-red-600');
    toast.innerHTML =
      '<div class="font-bold text-xs mb-0.5">' + title + '</div>' +
      '<div class="text-xs font-normal opacity-95">' + message + '</div>' +
      '<button type="button" aria-label="Dismiss" class="absolute top-2 right-2 w-7 h-7 rounded-lg bg-white/20 hover:bg-white/30 flex items-center justify-center">' +
      '<i class="fas fa-times text-xs"></i></button>';
    toast.querySelector('button').onclick = function () { toast.remove(); };
    document.body.appendChild(toast);
    setTimeout(function () { if (toast.parentNode) toast.remove(); }, 6000);
  }

  function refreshMedicineCardUI(medId, data) {
    if (!data || !data.success) return;

    var doseCount = document.getElementById('dose-count-' + medId);
    if (doseCount) {
      doseCount.textContent = data.taken_today + '/' + data.max_doses;
    }
    var bar = document.getElementById('dose-bar-' + medId);
    if (bar) {
      bar.style.width = Math.round((data.taken_today / data.max_doses) * 100) + '%';
      if (data.taken_today >= data.max_doses) {
        bar.classList.remove('bg-blue-500');
        bar.classList.add('bg-emerald-500');
      }
    }

    var actionArea = document.getElementById('action-area-' + medId);
    if (actionArea) {
      if (data.taken_today >= data.max_doses) {
        actionArea.innerHTML =
          '<div class="flex-1 px-4 py-2.5 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-xl text-sm font-semibold text-center flex items-center justify-center gap-2">' +
          '<i class="fas fa-check-double"></i> All doses taken today ✓</div>';
      } else {
        var nextDose = data.next_dose
          ? '<span class="text-xs font-normal text-emerald-600">Next dose: ' + data.next_dose + '</span>'
          : '';
        actionArea.innerHTML =
          '<div class="flex-1 px-4 py-2.5 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-xl text-sm font-semibold text-center flex flex-col items-center justify-center gap-0.5">' +
          '<span class="flex items-center gap-2"><i class="fas fa-check"></i> Dose Taken ✓</span>' + nextDose + '</div>';
      }
    }

    var markBtn = document.getElementById('mark-btn-' + medId);
    if (markBtn) {
      if (data.taken_today >= data.max_doses) {
        markBtn.outerHTML =
          '<span class="px-3 py-1.5 bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-semibold rounded-lg flex items-center gap-1">' +
          '<i class="fas fa-check-double"></i> Done</span>';
      } else {
        var nextLabel = data.next_dose ? ' · Next: ' + data.next_dose : '';
        markBtn.outerHTML =
          '<span class="px-3 py-1.5 bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-semibold rounded-lg flex items-center gap-1" title="Dose taken' + nextLabel + '">' +
          '<i class="fas fa-check"></i> Taken ✓</span>';
      }
    }
  }

  function markMedicineTakenFromPopup(item, btn) {
    if (!item || !item.med_id || markingInProgress) return;

    markingInProgress = true;
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<i class="fas fa-spinner fa-spin mr-1"></i> Saving...';
    }

    var body = 'action=taken';
    if (item.log_id) body += '&log_id=' + encodeURIComponent(item.log_id);

    fetch('/medicines/mark/' + item.med_id + '/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRFToken': getCsrf(),
      },
      body: body,
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.success) {
          closeMedicinePopup();
          showToastMsg(
            'success',
            '✓ Medicine marked as taken',
            (data.medicine_name || item.name || 'Medicine') + ' — stock updated (' + data.stock + ' remaining).'
          );
          refreshMedicineCardUI(item.med_id, data);
          syncMedicineReminders();
          return;
        }

        var errMsg = data.message || 'Could not mark medicine as taken.';
        var errType = 'error';
        var errTitle = 'Unable to mark dose';

        if (data.error === 'overdose' || data.error === 'already_taken') {
          errType = 'warning';
          errTitle = 'Overdose Warning';
          closeMedicinePopup();
          syncMedicineReminders();
        } else if (data.error === 'dose_expired') {
          errType = 'warning';
          errTitle = 'Dose Expired';
          errMsg = data.message || 'Dose window expired.';
          closeMedicinePopup();
          syncMedicineReminders();
        }
        showToastMsg(errType, errTitle, errMsg);

        if (btn) {
          btn.disabled = false;
          btn.innerHTML = 'Mark Taken';
        }
      })
      .catch(function () {
        showToastMsg('error', 'Network error', 'Please try again.');
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = 'Mark Taken';
        }
      })
      .finally(function () {
        markingInProgress = false;
      });
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
    if (!logId) return;
    fetch('/medicines/reminders/ack/' + logId + '/', {
      method: 'POST',
      headers: { 'X-CSRFToken': getCsrf() },
    }).catch(function () {});
  }

  function closeMedicinePopup() {
    var popup = document.getElementById('medicineReminderPopup');
    if (popup) popup.classList.add('hidden');
    popupVisible = false;
  }

  function isPopupCandidate(item) {
    if (!item || !item.popup_due) return false;
    if (item.taken || item.missed) return false;
    if (item.dose_status === 'TAKEN' || item.dose_status === 'MISSED') return false;
    if (item.dose_status === 'UPCOMING' || item.dose_status === 'NO_STOCK') return false;
    if (!item.can_take) return false;
    return true;
  }

  function showMedicinePopup(item) {
    if (!isPopupCandidate(item)) return;
    if (popupVisible) return;

    var popup = document.getElementById('medicineReminderPopup');
    if (!popup) return;

    popupVisible = true;
    item.popup_due = false;
    if (item.log_id) ackReminder(item.log_id);

    var nameEl = document.getElementById('popupMedName');
    var doseEl = document.getElementById('popupMedDosage');
    var schedEl = document.getElementById('popupMedScheduled');
    if (nameEl) nameEl.textContent = item.name;
    if (doseEl) doseEl.textContent = item.dosage;
    if (schedEl) schedEl.textContent = 'Scheduled: ' + (item.time_display || item.time || '—');
    var stockEl = document.getElementById('popupMedStock');
    if (stockEl) {
      if (item.stock_quantity != null && item.stock_quantity > 0) {
        stockEl.textContent = 'Stock: ' + item.stock_quantity + ' remaining';
        stockEl.classList.remove('hidden');
      } else {
        stockEl.classList.add('hidden');
      }
    }

    var markBtn = document.getElementById('popupMarkTakenBtn');
    if (markBtn) {
      markBtn.disabled = false;
      markBtn.innerHTML = 'Mark Taken';
      markBtn.onclick = function (e) {
        e.preventDefault();
        e.stopPropagation();
        markMedicineTakenFromPopup(item, markBtn);
      };
    }

    var snoozeBtn = document.getElementById('popupSnoozeMedBtn');
    if (snoozeBtn) {
      snoozeBtn.onclick = function () {
        snoozeMedicineReminder(item.log_id);
        closeMedicinePopup();
      };
    }

    popup.classList.remove('hidden');
    playSound();
  }

  function snoozeMedicineReminder(logId) {
    if (!logId) return;
    fetch('/medicines/reminders/snooze/' + logId + '/', {
      method: 'POST',
      headers: { 'X-CSRFToken': getCsrf() },
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.success && window.showToast) {
          window.showToast('Reminder snoozed for 10 minutes', 'success');
        }
        syncMedicineReminders();
      })
      .catch(function () {});
  }

  function formatSeconds(seconds) {
    if (seconds <= 0) return 'Due now';
    var h = Math.floor(seconds / 3600);
    var m = Math.floor((seconds % 3600) / 60);
    var s = Math.floor(seconds % 60);
    return (h > 0 ? h + 'h ' : '') + m + 'm ' + s.toString().padStart(2, '0') + 's';
  }

  function updateUpcomingList() {
    var list = document.getElementById('upcomingMedsList');
    var badge = document.getElementById('medMissedBadge');
    var badgeText = document.getElementById('medMissedBadgeText');
    if (!list) return;

    var pending = medReminders.filter(function (r) {
      return !r.taken && !r.missed;
    });

    var overdueCount = pending.filter(function (r) {
      return (r.dose_status === 'DUE_NOW' || r.dose_status === 'REMIND_LATER_ACTIVE') && r.is_overdue;
    }).length;

    if (badge && badgeText) {
      if (overdueCount > 0) {
        badge.classList.remove('hidden');
        badgeText.textContent = overdueCount + ' ' + (overdueCount > 1 ? 'medicines overdue' : 'medicine overdue');
      } else {
        badge.classList.add('hidden');
      }
    }

    if (pending.length === 0) {
      list.innerHTML =
        '<div class="flex flex-col items-center justify-center py-10 text-slate-400">' +
        '<i class="fas fa-pills text-2xl mb-2 opacity-40"></i>' +
        '<p class="text-sm">No medicines due today</p></div>';
      return;
    }

    var colorStyles = {
      blue: 'bg-blue-100 text-blue-600',
      green: 'bg-emerald-100 text-emerald-600',
      red: 'bg-red-100 text-red-600',
      purple: 'bg-violet-100 text-violet-600',
      amber: 'bg-amber-100 text-amber-600',
    };

    list.innerHTML = pending.slice(0, 8).map(function (r) {
      var style = colorStyles[r.color] || colorStyles.amber;
      var dueLabel;
      if (r.dose_status === 'UPCOMING') {
        dueLabel = 'Due in ' + formatSeconds(r.seconds_until);
      } else if (r.is_overdue && r.overdue_minutes) {
        dueLabel = 'Overdue by ' + r.overdue_minutes + ' min';
      } else if (r.dose_status === 'DUE_NOW' || r.dose_status === 'REMIND_LATER_ACTIVE') {
        dueLabel = 'Due now';
      } else {
        dueLabel = r.status_message || 'Due now';
      }
      var canMark = r.can_take;
      var timerId = 'upcoming-timer-' + r.med_id + '-' + (r.time || '').replace(':', '');
      return (
        '<div class="p-3 rounded-xl border border-slate-100 bg-slate-50/40 hover:border-emerald-100 transition" data-med-id="' + r.med_id + '">' +
        '<div class="flex items-start justify-between gap-2 mb-2">' +
        '<div class="flex items-center gap-2.5 min-w-0 flex-1">' +
        '<div class="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ' + style + '">' +
        '<i class="fas fa-capsules text-xs"></i></div>' +
        '<div class="min-w-0">' +
        '<div class="font-semibold text-slate-800 text-sm truncate">' + r.name + '</div>' +
        '<div class="text-xs text-slate-500">' + r.dosage + ' • <span id="' + timerId + '">' + dueLabel + '</span></div>' +
        '</div></div></div>' +
        '<div class="flex flex-wrap gap-1.5">' +
        '<button onclick="markMedicine(' + r.med_id + ', \'taken\', this)" ' +
        (canMark ? '' : 'disabled ') +
        'class="text-[11px] px-2.5 py-1 rounded-lg font-semibold transition ' +
        (canMark ? 'bg-emerald-600 text-white hover:bg-emerald-700' : 'bg-slate-100 text-slate-400 cursor-not-allowed') + '">' +
        '<i class="fas fa-check mr-0.5"></i>Mark Taken</button>' +
        '<button type="button" onclick="snoozeMedicineReminder(' + (r.log_id || 0) + ')" ' +
        (canMark && r.log_id ? '' : 'disabled ') +
        'class="text-[11px] px-2.5 py-1 rounded-lg bg-slate-100 text-slate-600 font-semibold hover:bg-slate-200 transition">' +
        'Remind Later</button></div></div>'
      );
    }).join('');
  }

  function updateCountdownBar() {
    var bar = document.getElementById('liveCountdownBar');
    if (!bar) return;

    var next = medReminders.find(function (r) {
      return !r.taken && !r.missed && r.seconds_until > 0;
    });
    if (!next) {
      bar.classList.add('hidden');
      return;
    }

    bar.classList.remove('hidden');
    var nameEl = document.getElementById('countdownMedName');
    var timeEl = document.getElementById('countdownMedTime');
    var timerEl = document.getElementById('countdownTimer');
    if (nameEl) nameEl.textContent = next.name;
    if (timeEl) timeEl.textContent = next.time;
    if (timerEl) {
      var sec = next.seconds_until;
      var h = Math.floor(sec / 3600);
      var m = Math.floor((sec % 3600) / 60);
      var s = Math.floor(sec % 60);
      timerEl.textContent =
        h.toString().padStart(2, '0') + ':' +
        m.toString().padStart(2, '0') + ':' +
        s.toString().padStart(2, '0');
    }
  }

  function updateTodayScheduleStatus() {
    medReminders.forEach(function (r) {
      var btn = document.getElementById('mark-btn-' + r.med_id);
      if (btn && r.taken) {
        btn.outerHTML =
          '<span class="px-3 py-1.5 bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-semibold rounded-lg flex items-center gap-1">' +
          '<i class="fas fa-check-double"></i> Done</span>';
      }
    });
  }

  function hasActiveReminders() {
    return medReminders.some(function (r) {
      return !r.taken && !r.missed &&
        (r.dose_status === 'DUE_NOW' || r.dose_status === 'REMIND_LATER_ACTIVE' || r.popup_due);
    });
  }

  function nearestPopupSeconds() {
    var min = 99999;
    medReminders.forEach(function (r) {
      if (r.taken || r.missed) return;
      if (r.popup_due) {
        min = Math.min(min, 0);
        return;
      }
      var s = secondsUntil(r.next_popup_at);
      if (s < min) min = s;
      if (r.seconds_until <= 0 && r.can_take) min = Math.min(min, 0);
    });
    return min;
  }

  function scheduleWake() {
    if (wakeTimer) clearTimeout(wakeTimer);
    var sec = nearestPopupSeconds();
    if (sec > 0 && sec < 7200) {
      wakeTimer = setTimeout(function () {
        syncMedicineReminders();
      }, Math.max(1000, sec * 1000 + 500));
    }
  }

  function getSyncInterval() {
    if (medReminders.some(function (r) { return r.popup_due; })) return SYNC_ACTIVE_MS;
    if (!hasActiveReminders()) return SYNC_MS;
    var sec = nearestPopupSeconds();
    if (sec <= 600) return SYNC_ACTIVE_MS;
    return SYNC_MS;
  }

  function scheduleSync() {
    if (syncTimer) clearInterval(syncTimer);
    syncTimer = setInterval(syncMedicineReminders, getSyncInterval());
    scheduleWake();
  }

  async function syncMedicineReminders() {
    try {
      var resp = await fetch('/medicines/reminders/');
      var data = await resp.json();
      if (!data.reminders) return;

      medReminders = data.reminders;
      window.currentReminders = medReminders;

      updateUpcomingList();
      updateCountdownBar();
      updateTodayScheduleStatus();

      if (!popupVisible) {
        var due = medReminders.find(isPopupCandidate);
        if (due) showMedicinePopup(due);
      }

      scheduleSync();
    } catch (e) {
      console.error('Medicine reminder sync failed', e);
    }
  }

  function shouldRun() {
    return !!document.getElementById('medicineReminderPopup');
  }

  function init() {
    if (!shouldRun()) return;
    syncMedicineReminders();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.syncMedicineReminders = syncMedicineReminders;
  window.closeMedicinePopup = closeMedicinePopup;
  window.snoozeMedicineReminder = snoozeMedicineReminder;
  window.currentReminders = medReminders;
})();
