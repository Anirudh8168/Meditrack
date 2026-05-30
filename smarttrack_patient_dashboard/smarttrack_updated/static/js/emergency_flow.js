/**
 * Emergency video: 5-minute wait — fixed non-dismissible modal, server-synced timer.
 */
(function () {
  const STORAGE_KEY = 'smarttrack_active_emergency';
  const DISMISS_KEY = 'smarttrack_emergency_wait_dismissed';

  let activeEmergencyAptId = null;
  let emergencyWaitingActive = false;
  let emergencyWaitDismissed = false;
  let waitPollTimer = null;
  let countdownTimer = null;
  let remainingSeconds = 300;
  let doctorDisplayName = '';

  function csrf() {
    const el = document.querySelector('[name=csrfmiddlewaretoken]');
    return el ? el.value : '';
  }

  function formatCountdown(sec) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  function showModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('hidden');
  }

  function hideModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add('hidden');
  }

  function persistEmergencyState() {
    if (emergencyWaitingActive && activeEmergencyAptId) {
      try {
        localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({ aptId: activeEmergencyAptId, ts: Date.now() })
        );
      } catch (e) {
        /* ignore */
      }
    } else {
      try {
        localStorage.removeItem(STORAGE_KEY);
      } catch (e) {
        /* ignore */
      }
    }
  }

  function updateReopenBar() {
    const bar = document.getElementById('emergencyReopenBar');
    if (!bar) return;
    const visible = emergencyWaitingActive && emergencyWaitDismissed;
    bar.classList.toggle('hidden', !visible);
  }

  function clearDismissedFlag() {
    try {
      sessionStorage.removeItem(DISMISS_KEY);
    } catch (e) {
      /* ignore */
    }
  }

  function setDismissedFlag(aptId) {
    try {
      sessionStorage.setItem(DISMISS_KEY, String(aptId));
    } catch (e) {
      /* ignore */
    }
  }

  function isDismissedForApt(aptId) {
    try {
      return sessionStorage.getItem(DISMISS_KEY) === String(aptId);
    } catch (e) {
      return false;
    }
  }

  function clearEmergencySession() {
    emergencyWaitingActive = false;
    emergencyWaitDismissed = false;
    activeEmergencyAptId = null;
    doctorDisplayName = '';
    stopWaitTimers();
    hideModal('emergencyWaitingModal');
    persistEmergencyState();
    clearDismissedFlag();
    updateReopenBar();
  }

  function stopWaitTimers() {
    if (waitPollTimer) {
      clearInterval(waitPollTimer);
      waitPollTimer = null;
    }
    if (countdownTimer) {
      clearInterval(countdownTimer);
      countdownTimer = null;
    }
  }

  async function logEvent(eventType, extra) {
    if (!activeEmergencyAptId) return;
    const body = new URLSearchParams({ event_type: eventType });
    if (extra && extra.clinic_name) body.set('clinic_name', extra.clinic_name);
    try {
      await fetch(`/appointments/emergency-log/${activeEmergencyAptId}/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrf(), 'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString(),
      });
    } catch (e) {
      console.warn('emergency log failed', e);
    }
  }

  function updateDoctorLabels() {
    const label = doctorDisplayName ? `Dr. ${doctorDisplayName} contacted` : 'Doctor contacted';
    const waitDoc = document.getElementById('emergencyWaitDoctor');
    if (waitDoc) waitDoc.textContent = label;
  }

  function updateCountdownDisplay() {
    const text = formatCountdown(remainingSeconds);
    const el = document.getElementById('emergencyCountdown');
    if (el) el.textContent = text;

    const statusEl = document.getElementById('emergencyWaitStatus');
    const statusText =
      remainingSeconds > 0
        ? 'Doctor is being contacted. Waiting for response…'
        : 'Checking doctor availability…';
    if (statusEl) statusEl.textContent = statusText;
    updateReopenBar();
  }

  function startCountdown(initialSeconds) {
    remainingSeconds = Math.max(0, initialSeconds || 300);
    updateCountdownDisplay();
    if (countdownTimer) clearInterval(countdownTimer);
    countdownTimer = setInterval(() => {
      if (remainingSeconds > 0) {
        remainingSeconds -= 1;
        updateCountdownDisplay();
      }
    }, 1000);
  }

  function openWaitingModal() {
    if (!emergencyWaitingActive) return;
    emergencyWaitDismissed = false;
    clearDismissedFlag();
    showModal('emergencyWaitingModal');
    updateCountdownDisplay();
    updateDoctorLabels();
    updateReopenBar();
  }

  async function closeWaitingModalManually() {
    if (!emergencyWaitingActive) return;
    const ok = typeof showConfirmModal === 'function'
      ? await showConfirmModal({
          title: 'Hide Waiting Screen?',
          message: 'Your emergency request stays active until the doctor responds or the 5-minute timer ends.',
          note: 'You can reopen the status from the Appointments page.',
          confirmText: 'Hide Screen',
          variant: 'warning',
        })
      : true;
    if (!ok) return;
    emergencyWaitDismissed = true;
    if (activeEmergencyAptId) setDismissedFlag(activeEmergencyAptId);
    hideModal('emergencyWaitingModal');
    updateReopenBar();
  }

  async function pollEmergencyStatus() {
    if (!activeEmergencyAptId) return;
    try {
      const resp = await fetch(`/appointments/timeout-check/${activeEmergencyAptId}/`);
      const data = await resp.json();
      if (!data.success) return;

      if (data.doctor_name) {
        doctorDisplayName = data.doctor_name.replace(/^Dr\.\s*/i, '');
        updateDoctorLabels();
      }

      if (typeof data.remaining_seconds === 'number' && data.remaining_seconds >= 0) {
        remainingSeconds = data.remaining_seconds;
        updateCountdownDisplay();
      }

      if (data.status === 'confirmed') {
        clearEmergencySession();
        if (typeof showToast === 'function') {
          showToast('Doctor accepted! You can join the video call.', 'success');
        }
        setTimeout(() => location.reload(), 1500);
        return;
      }

      if (data.status === 'timeout' || data.status === 'rejected' || data.show_fallback) {
        clearEmergencySession();
        showDoctorUnavailable(data.rejection_reason || '');
      }
    } catch (e) {
      console.error('Emergency poll error', e);
    }
  }

  function showDoctorUnavailable(reason) {
    const reasonEl = document.getElementById('doctorUnavailableReason');
    if (reasonEl) {
      reasonEl.textContent = reason
        ? `Reason: ${reason}`
        : 'Doctor is currently unavailable. Please visit a nearby clinic or hospital immediately.';
    }
    showModal('doctorUnavailableModal');
  }

  function beginEmergencyWaiting(aptId, timeoutSeconds, doctorName) {
    activeEmergencyAptId = aptId;
    emergencyWaitingActive = true;
    emergencyWaitDismissed = isDismissedForApt(aptId);
    if (doctorName) {
      doctorDisplayName = String(doctorName).replace(/^Dr\.\s*/i, '');
    }
    stopWaitTimers();
    persistEmergencyState();
    if (emergencyWaitDismissed) {
      hideModal('emergencyWaitingModal');
      updateReopenBar();
    } else {
      openWaitingModal();
    }
    startCountdown(timeoutSeconds || 300);
    pollEmergencyStatus();
    waitPollTimer = setInterval(pollEmergencyStatus, 3000);
  }

  window.startEmergencyWaiting = function (aptId, timeoutSeconds, doctorName) {
    beginEmergencyWaiting(aptId, timeoutSeconds, doctorName);
  };

  window.showDoctorUnavailableModal = showDoctorUnavailable;

  window.setEmergencyAptId = function (id) {
    activeEmergencyAptId = id;
  };

  window.reopenEmergencyWaitingModal = function () {
    openWaitingModal();
  };

  window.openClinicFinder = function () {
    hideModal('doctorUnavailableModal');
    if (!window.SmartTrackNearbyPlaces) {
      window.location.href = '/appointments/';
      return;
    }
    window.SmartTrackNearbyPlaces.open({
      backdropId: 'clinicFinderBackdrop',
      panelId: 'clinicFinderPanel',
      listId: 'clinicList',
      mapId: 'clinicMap',
      btnMaximizeId: 'clinicFinderMaximize',
      btnMinimizeId: 'clinicFinderMinimize',
      btnCloseId: 'clinicFinderClose',
      placeType: 'clinic',
      placeLabel: 'clinics and hospitals',
      resultsKey: 'clinics',
      locationDeniedMessage:
        'Live location access is required to find nearby clinics. SmartTrack cannot use a saved or default address.',
      buildApiUrl(lat, lng) {
        const q = new URLSearchParams({ lat, lng, fast: '1', emergency: '1' });
        if (activeEmergencyAptId) q.set('apt_id', activeEmergencyAptId);
        return `/appointments/find-nearby-clinics/?${q}`;
      },
      onSelect({ name }) {
        logEvent('clinic_selected', { clinic_name: name });
      },
    });
  };

  window.closeClinicFinder = function () {
    window.SmartTrackNearbyPlaces?.close();
  };

  window.retryEmergencyCall = function () {
    hideModal('doctorUnavailableModal');
    const em = document.getElementById('emergencyModal');
    if (em) {
      em.classList.remove('hidden');
    } else {
      window.location.href = '/appointments/';
    }
  };

  window.requestEmergency = function () {
    const notesEl = document.getElementById('emergencyNotes');
    const notes = notesEl ? notesEl.value : '';
    const btn = document.querySelector('#emergencyModal button[data-emergency-submit]');
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Requesting...';
    }
    fetch('/appointments/emergency-video/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRFToken': csrf(),
      },
      body: `notes=${encodeURIComponent(notes)}`,
    })
      .then((r) => r.json())
      .then((data) => {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<i class="fas fa-bolt mr-2"></i>Request Emergency';
        }
        if (data.success) {
          hideModal('emergencyModal');
          if (typeof showToast === 'function') {
            showToast('Emergency request sent. Doctor alerted.', 'success');
          }
          window.startEmergencyWaiting(
            data.apt_id,
            data.timeout_seconds || 300,
            data.doctor_name || ''
          );
        } else if (typeof showToast === 'function') {
          showToast(data.error || 'Could not request emergency consultation', 'error');
        }
      })
      .catch(() => {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<i class="fas fa-bolt mr-2"></i>Request Emergency';
        }
      });
  };

  function setupEmergencyWaitGuards() {
    const modal = document.getElementById('emergencyWaitingModal');
    if (!modal) return;

    modal.addEventListener(
      'click',
      (e) => {
        if (!emergencyWaitingActive) return;
        if (e.target === modal) {
          e.preventDefault();
          e.stopPropagation();
        }
      },
      true
    );

    const panel = modal.querySelector('[data-emergency-wait-panel]');
    if (panel) {
      panel.addEventListener('click', (e) => e.stopPropagation());
    }

    document.addEventListener(
      'keydown',
      (e) => {
        if (e.key !== 'Escape' || !emergencyWaitingActive || emergencyWaitDismissed) return;
        if (modal.classList.contains('hidden')) return;
        e.preventDefault();
        e.stopPropagation();
      },
      true
    );

    document.getElementById('emergencyCloseWaitBtn')?.addEventListener('click', closeWaitingModalManually);
    document.getElementById('emergencyReopenStatusBtn')?.addEventListener('click', openWaitingModal);

    const observer = new MutationObserver(() => {
      if (!emergencyWaitingActive || emergencyWaitDismissed) return;
      const m = document.getElementById('emergencyWaitingModal');
      if (m && m.classList.contains('hidden')) {
        m.classList.remove('hidden');
      }
    });
    observer.observe(modal, { attributes: true, attributeFilter: ['class'] });
  }

  function setupGenericBackdropClose() {
    const allowCloseIds = [
      'videoModal',
      'emergencyModal',
      'rejectModal',
      'rejectEmergencyModal',
      'doctorUnavailableModal',
    ];
    allowCloseIds.forEach((id) => {
      const modal = document.getElementById(id);
      if (!modal) return;
      modal.addEventListener('click', function (e) {
        if (e.target === this) this.classList.add('hidden');
      });
    });
  }

  async function restoreActiveEmergencyFromServer() {
    try {
      const resp = await fetch('/appointments/patient-active-emergency/');
      const data = await resp.json();
      if (!data.success) return;

      if (data.active && data.apt_id) {
        beginEmergencyWaiting(
          data.apt_id,
          data.remaining_seconds ?? data.timeout_seconds ?? 300,
          data.doctor_name || ''
        );
        return;
      }

      if (data.show_fallback && data.apt_id) {
        activeEmergencyAptId = data.apt_id;
        showDoctorUnavailable(data.rejection_reason || '');
      }
    } catch (e) {
      console.warn('Could not restore emergency state', e);
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    setupEmergencyWaitGuards();
    setupGenericBackdropClose();
    restoreActiveEmergencyFromServer();
  });
})();
