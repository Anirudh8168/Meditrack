/**
 * Low-stock medicine alerts — dashboard cards, popup modal, quick refill.
 */
(function () {
  'use strict';

  var POLL_MS = 90000;
  var SNOOZE_MINUTES = 360;
  var SNOOZE_MS = SNOOZE_MINUTES * 60 * 1000;
  var REFILL_OPEN_MS = 24 * 60 * 60 * 1000;
  var shownIds = {};
  var modalEl = null;
  var quickModalEl = null;
  var pendingQuickRefill = null;

  var PHARMACY_FINDER_CONFIG = {
    backdropId: 'pharmacyFinderBackdrop',
    panelId: 'pharmacyFinderPanel',
    listId: 'pharmacyList',
    mapId: 'pharmacyMap',
    btnMaximizeId: 'pharmacyFinderMaximize',
    btnMinimizeId: 'pharmacyFinderMinimize',
    btnCloseId: 'pharmacyFinderClose',
    placeType: 'pharmacy',
    placeLabel: 'pharmacies',
    resultsKey: 'pharmacies',
    locationDeniedMessage:
      'Live location access is required to find nearby pharmacies. SmartTrack cannot use a saved or default address.',
    buildApiUrl: function (lat, lng) {
      return '/medicines/find-pharmacies/?lat=' + lat + '&lng=' + lng + '&fast=1';
    },
  };

  function openNearbyPharmacies(e) {
    if (e && e.preventDefault) e.preventDefault();
    if (!window.SmartTrackNearbyPlaces) {
      showToast('Pharmacy finder failed to load. Please refresh the page.', 'error');
      return;
    }
    if (!document.getElementById('pharmacyFinderBackdrop')) {
      showToast('Pharmacy finder is not available on this page.', 'error');
      return;
    }
    window.SmartTrackNearbyPlaces.open(PHARMACY_FINDER_CONFIG);
  }

  function csrfToken() {
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    return el ? el.value : '';
  }

  function isRefillPage() {
    return /\/medicines\/refill\/\d+\/?/.test(window.location.pathname);
  }

  function storageKey(type, medId) {
    return 'st_low_stock_' + type + '_' + medId;
  }

  function isClientSuppressed(medId) {
    var now = Date.now();
    var refillUntil = parseInt(sessionStorage.getItem(storageKey('refill', medId)) || '0', 10);
    var snoozeUntil = parseInt(sessionStorage.getItem(storageKey('snooze', medId)) || '0', 10);
    return now < refillUntil || now < snoozeUntil;
  }

  function markSeenOnDashboard(medId) {
    sessionStorage.setItem(storageKey('seen', medId), '1');
  }

  function wasSeenOnDashboard(medId) {
    return sessionStorage.getItem(storageKey('seen', medId)) === '1';
  }

  function clearSeen(medId) {
    sessionStorage.removeItem(storageKey('seen', medId));
  }

  function suppressRefillOpen(medId) {
    sessionStorage.setItem(storageKey('refill', medId), String(Date.now() + REFILL_OPEN_MS));
  }

  function suppressSnooze(medId, minutes) {
    var ms = (minutes || SNOOZE_MINUTES) * 60 * 1000;
    sessionStorage.setItem(storageKey('snooze', medId), String(Date.now() + ms));
  }

  function hasDashboardCard(medId) {
    return !!document.getElementById('stockAlertCard-' + medId);
  }

  function removeDashboardCard(medId) {
    var card = document.getElementById('stockAlertCard-' + medId);
    if (card) card.remove();
    var wrap = document.getElementById('stockAlertCards');
    if (wrap && !wrap.querySelector('.stock-alert-card')) {
      wrap.remove();
    }
  }

  function showToast(msg, type) {
    if (typeof window.showToast === 'function') {
      window.showToast(msg, type || 'success');
      return;
    }
    var toast = document.createElement('div');
    toast.className =
      'fixed top-5 right-5 z-[10002] px-6 py-3 rounded-2xl text-white text-sm font-semibold shadow-2xl ' +
      (type === 'error' ? 'bg-red-600' : type === 'warning' ? 'bg-amber-600' : 'bg-emerald-600');
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(function () { toast.remove(); }, 4000);
  }

  function postDismiss(medId, action, minutes) {
    var payload = { action: action };
    if (minutes) payload.minutes = minutes;
    return fetch('/medicines/inventory-dismiss/' + medId + '/', {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken(),
        'Content-Type': 'application/json',
      },
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    }).catch(function () {});
  }

  function severityStyles(severity) {
    var map = {
      emergency: {
        header: 'from-red-600 to-red-700',
        icon: 'bg-red-500/30',
        title: 'Emergency — Out of Stock',
      },
      critical: {
        header: 'from-red-500 to-rose-600',
        icon: 'bg-red-500/30',
        title: 'Critical Medicine Stock',
      },
      high: {
        header: 'from-orange-500 to-orange-600',
        icon: 'bg-orange-500/30',
        title: 'High Priority — Low Stock',
      },
      warning: {
        header: 'from-amber-500 to-orange-500',
        icon: 'bg-white/20',
        title: 'Medicine Stock Running Low',
      },
    };
    return map[severity] || map.warning;
  }

  function escapeHtml(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function ensureModal() {
    if (modalEl) return modalEl;
    var wrap = document.createElement('div');
    wrap.id = 'inventoryLowStockModal';
    wrap.className = 'fixed inset-0 bg-black/60 z-[60] hidden flex items-center justify-center p-4';
    wrap.innerHTML =
      '<div class="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden">' +
        '<div id="inventoryAlertHeader" class="px-6 py-4 text-white">' +
          '<div class="flex items-center gap-3">' +
            '<div class="w-10 h-10 rounded-xl flex items-center justify-center" id="inventoryAlertIcon"><i class="fas fa-exclamation-triangle"></i></div>' +
            '<div><h3 class="font-bold text-lg" id="inventoryAlertTitle">Medicine Stock Running Low</h3></div>' +
          '</div>' +
        '</div>' +
        '<div class="p-6" id="inventoryAlertBody"></div>' +
        '<div class="px-6 pb-6 flex flex-col gap-2" id="inventoryAlertActions"></div>' +
      '</div>';
    document.body.appendChild(wrap);
    modalEl = wrap;
    return modalEl;
  }

  function ensureQuickModal() {
    if (quickModalEl) return quickModalEl;
    var wrap = document.createElement('div');
    wrap.id = 'inventoryQuickRefillModal';
    wrap.className = 'fixed inset-0 bg-black/60 z-[61] hidden flex items-center justify-center p-4';
    wrap.innerHTML =
      '<div class="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden max-h-[90vh] flex flex-col">' +
        '<div class="bg-gradient-to-r from-emerald-600 to-teal-600 px-6 py-4 text-white flex-shrink-0">' +
          '<h3 class="font-bold text-lg" id="quickRefillModalTitle"><i class="fas fa-shopping-cart mr-2"></i>Add Medicine Purchase</h3>' +
          '<p class="text-emerald-100 text-xs mt-1">Tell us you bought this medicine — no bill upload needed.</p>' +
        '</div>' +
        '<div class="p-6 overflow-y-auto flex-1 space-y-4">' +
          '<div>' +
            '<label class="block text-xs font-medium text-slate-500 mb-1">Medicine Name</label>' +
            '<input type="text" id="quickRefillMedNameInput" readonly class="w-full px-4 py-2.5 border border-slate-200 rounded-xl bg-slate-50 text-sm font-semibold text-slate-800">' +
          '</div>' +
          '<p id="quickRefillPrescribedHint" class="text-xs text-slate-500 -mt-2 hidden"></p>' +
          '<div>' +
            '<label class="block text-sm font-medium text-slate-700 mb-1.5">Purchased Quantity <span class="text-red-500">*</span></label>' +
            '<input type="number" id="quickRefillQty" min="1" placeholder="e.g. 10" class="w-full px-4 py-2.5 border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 text-sm">' +
          '</div>' +
          '<div>' +
            '<label class="block text-sm font-medium text-slate-700 mb-1.5">Purchase Date <span class="text-red-500">*</span></label>' +
            '<input type="date" id="quickRefillDate" class="w-full px-4 py-2.5 border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 text-sm">' +
          '</div>' +
          '<div>' +
            '<label class="block text-sm font-medium text-slate-700 mb-1.5">Pharmacy Name <span class="text-slate-400 text-xs">(optional)</span></label>' +
            '<input type="text" id="quickRefillPharmacy" placeholder="e.g. Apollo Pharmacy" class="w-full px-4 py-2.5 border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 text-sm">' +
          '</div>' +
          '<div>' +
            '<label class="block text-sm font-medium text-slate-700 mb-1.5">Notes <span class="text-slate-400 text-xs">(optional)</span></label>' +
            '<textarea id="quickRefillNotes" rows="2" placeholder="Optional notes about this purchase" class="w-full px-4 py-2.5 border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 text-sm resize-none"></textarea>' +
          '</div>' +
        '</div>' +
        '<div class="px-6 pb-6 flex gap-3 flex-shrink-0 border-t border-slate-100 pt-4">' +
          '<button type="button" id="quickRefillConfirm" class="flex-1 px-4 py-3 bg-emerald-600 text-white rounded-xl font-bold hover:bg-emerald-700 transition text-sm">Save Purchase</button>' +
          '<button type="button" id="quickRefillCancel" class="px-4 py-3 bg-slate-100 text-slate-700 rounded-xl font-semibold hover:bg-slate-200 transition text-sm">Cancel</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(wrap);
    quickModalEl = wrap;

    document.getElementById('quickRefillCancel').addEventListener('click', function () {
      quickModalEl.classList.add('hidden');
      pendingQuickRefill = null;
    });

    document.getElementById('quickRefillConfirm').addEventListener('click', submitQuickRefill);

    return quickModalEl;
  }

  function openQuickRefill(medId, medName, prescribedQty) {
    pendingQuickRefill = { medId: medId, medName: medName };
    var modal = ensureQuickModal();
    var nameInput = document.getElementById('quickRefillMedNameInput');
    if (nameInput) nameInput.value = medName || 'Medicine';
    var hint = document.getElementById('quickRefillPrescribedHint');
    if (hint) {
      if (prescribedQty && prescribedQty > 0) {
        hint.textContent = 'Doctor prescribed ' + prescribedQty + ' doses total — enter how many you bought now.';
        hint.classList.remove('hidden');
      } else {
        hint.classList.add('hidden');
      }
    }
    document.getElementById('quickRefillQty').value = '';
    document.getElementById('quickRefillDate').value = new Date().toISOString().slice(0, 10);
    var pharmacy = document.getElementById('quickRefillPharmacy');
    var notes = document.getElementById('quickRefillNotes');
    if (pharmacy) pharmacy.value = '';
    if (notes) notes.value = '';
    var title = document.getElementById('quickRefillModalTitle');
    if (title) title.innerHTML = '<i class="fas fa-shopping-cart mr-2"></i>Add Medicine Purchase';
    modal.classList.remove('hidden');
    setTimeout(function () {
      document.getElementById('quickRefillQty').focus();
    }, 100);
  }

  function submitQuickRefill() {
    if (!pendingQuickRefill) return;
    var qty = parseInt(document.getElementById('quickRefillQty').value, 10);
    if (!qty || qty < 1) {
      showToast('Please enter a valid quantity.', 'error');
      return;
    }
    var purchaseDate = document.getElementById('quickRefillDate').value;
    if (!purchaseDate) {
      showToast('Please select a purchase date.', 'error');
      return;
    }
    var pharmacy = document.getElementById('quickRefillPharmacy');
    var notesEl = document.getElementById('quickRefillNotes');
    var medId = pendingQuickRefill.medId;
    var btn = document.getElementById('quickRefillConfirm');
    btn.disabled = true;
    btn.textContent = 'Saving…';

    fetch('/medicines/quick-refill/' + medId + '/', {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken(),
        'Content-Type': 'application/json',
      },
      credentials: 'same-origin',
      body: JSON.stringify({
        quantity_purchased: qty,
        purchase_date: purchaseDate,
        pharmacy_name: pharmacy ? pharmacy.value.trim() : '',
        notes: notesEl ? notesEl.value.trim() : '',
      }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        btn.disabled = false;
        btn.textContent = 'Save Purchase';
        if (!data.success) {
          showToast(data.error || 'Purchase failed.', 'error');
          return;
        }
        quickModalEl.classList.add('hidden');
        if (modalEl) modalEl.classList.add('hidden');
        shownIds[medId] = true;
        suppressRefillOpen(medId);
        removeDashboardCard(medId);
        clearSeen(medId);
        showToast(
          '✓ Purchase saved — stock: ' + data.new_stock + ' doses' +
            (data.purchased_total ? ' (' + data.purchased_total + '/' + data.prescribed_total + ' purchased)' : ''),
          'success'
        );
        pendingQuickRefill = null;
        setTimeout(function () { window.location.reload(); }, 1200);
      })
      .catch(function () {
        btn.disabled = false;
        btn.textContent = 'Confirm Refill';
        showToast('Network error. Please try again.', 'error');
      });
  }

  function handleRefillNow(medId, medName, prescribedQty) {
    suppressRefillOpen(medId);
    postDismiss(medId, 'refill_opened');
    openQuickRefill(medId, medName, prescribedQty || 0);
  }

  function handleSnooze(medId) {
    suppressSnooze(medId, SNOOZE_MINUTES);
    postDismiss(medId, 'snooze', SNOOZE_MINUTES);
    removeDashboardCard(medId);
    if (modalEl) modalEl.classList.add('hidden');
    showToast('Reminder snoozed for 6 hours', 'success');
  }

  function bindDashboardCards() {
    document.querySelectorAll('.st-inv-refill-now').forEach(function (btn) {
      btn.addEventListener('click', function () {
        handleRefillNow(
          parseInt(btn.getAttribute('data-med-id'), 10),
          btn.getAttribute('data-med-name') || '',
          parseInt(btn.getAttribute('data-prescribed') || '0', 10)
        );
      });
    });
    document.querySelectorAll('.st-inv-find-pharmacy').forEach(function (btn) {
      btn.addEventListener('click', openNearbyPharmacies);
    });
    document.querySelectorAll('.st-inv-quick-refill').forEach(function (btn) {
      btn.addEventListener('click', function () {
        openQuickRefill(
          parseInt(btn.getAttribute('data-med-id'), 10),
          btn.getAttribute('data-med-name'),
          parseInt(btn.getAttribute('data-prescribed') || '0', 10)
        );
      });
    });
    document.querySelectorAll('.st-inv-snooze').forEach(function (btn) {
      btn.addEventListener('click', function () {
        handleSnooze(parseInt(btn.getAttribute('data-med-id'), 10));
      });
    });
    document.querySelectorAll('.stock-alert-card').forEach(function (card) {
      var medId = card.getAttribute('data-med-id');
      shownIds[medId] = true;
      markSeenOnDashboard(medId);
    });
  }

  function showAlert(alert) {
    var medId = alert.medicine_id;
    if (shownIds[medId] || isClientSuppressed(medId)) return;
    if (hasDashboardCard(medId) && !alert.is_priority) return;

    shownIds[medId] = true;
    var styles = severityStyles(alert.severity);
    var modal = ensureModal();

    var header = document.getElementById('inventoryAlertHeader');
    header.className = 'bg-gradient-to-r ' + styles.header + ' px-6 py-4 text-white';
    document.getElementById('inventoryAlertIcon').className =
      'w-10 h-10 rounded-xl flex items-center justify-center ' + styles.icon;
    document.getElementById('inventoryAlertTitle').textContent = styles.title;

    document.getElementById('inventoryAlertBody').innerHTML =
      '<p class="font-bold text-slate-800 text-lg mb-1">' + escapeHtml(alert.name) + '</p>' +
      '<p class="text-sm text-slate-600 mb-2">Only <strong>' + alert.remaining_stock + '</strong> dose' +
        (alert.remaining_stock === 1 ? '' : 's') + ' remaining.</p>' +
      '<p class="text-sm text-slate-500">Refill medicine to avoid interruption in treatment.</p>';

    var actions = document.getElementById('inventoryAlertActions');
    actions.innerHTML =
      '<button type="button" class="refill-inv w-full px-4 py-3 bg-emerald-600 text-white rounded-xl font-semibold hover:bg-emerald-700 transition text-sm">' +
        '<i class="fas fa-shopping-bag mr-1"></i> Refill Now</button>' +
      '<button type="button" class="find-pharmacy-inv w-full px-4 py-3 bg-blue-600 text-white rounded-xl font-semibold hover:bg-blue-700 transition text-sm">' +
        '<i class="fas fa-map-marker-alt mr-1"></i> Find Nearby Pharmacies</button>' +
      '<button type="button" class="quick-refill-inv w-full px-4 py-3 bg-violet-600 text-white rounded-xl font-semibold hover:bg-violet-700 transition text-sm">' +
        '<i class="fas fa-check-circle mr-1"></i> Already Refilled</button>' +
      '<button type="button" class="dismiss-inv w-full px-4 py-3 bg-slate-100 text-slate-700 rounded-xl font-semibold hover:bg-slate-200 transition text-sm">' +
        'Remind Me Later</button>';

    modal.classList.remove('hidden');

    actions.querySelector('.refill-inv').addEventListener('click', function () {
      modal.classList.add('hidden');
      handleRefillNow(medId, alert.name, alert.prescribed_quantity || 0);
    });

    actions.querySelector('.find-pharmacy-inv').addEventListener('click', function () {
      modal.classList.add('hidden');
      openNearbyPharmacies();
    });

    actions.querySelector('.quick-refill-inv').addEventListener('click', function () {
      modal.classList.add('hidden');
      openQuickRefill(medId, alert.name, alert.prescribed_quantity || 0);
    });

    actions.querySelector('.dismiss-inv').addEventListener('click', function () {
      handleSnooze(medId);
    });

    fetch('/medicines/inventory-dismiss/' + medId + '/', {
      method: 'POST',
      headers: { 'X-CSRFToken': csrfToken(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'shown' }),
      credentials: 'same-origin',
    }).catch(function () {});
  }

  function poll() {
    if (isRefillPage()) return;

    fetch('/medicines/inventory-alerts/', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.success || !data.alerts || !data.alerts.length) return;
        var alert = data.alerts.find(function (a) {
          if (isClientSuppressed(a.medicine_id)) return false;
          if (hasDashboardCard(a.medicine_id) && !a.is_priority) return false;
          if (wasSeenOnDashboard(a.medicine_id) && !a.is_priority) return false;
          return !shownIds[a.medicine_id];
        });
        if (alert) showAlert(alert);
      })
      .catch(function () {});
  }

  function init() {
    bindDashboardCards();
    if (isRefillPage()) return;
    poll();
    setInterval(poll, POLL_MS);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.openQuickRefillModal = openQuickRefill;
  window.openNearbyPharmacies = openNearbyPharmacies;
  window.findNearbyPharmacies = openNearbyPharmacies;
})();
