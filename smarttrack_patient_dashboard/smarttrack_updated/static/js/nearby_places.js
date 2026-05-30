/**
 * Nearby finder: live GPS, list-first, in-app map + routes.
 */
(function (global) {
  const PAGE_SIZE = 100;
  const LOCATION_CACHE_MS = 10 * 60 * 1000;
  const SEARCH_CACHE_MS = 10 * 60 * 1000;
  const LOC_STORAGE_KEY = 'st_nearby_location';
  const SEARCH_STORAGE_PREFIX = 'st_nearby_search_';
  const NP_DEBUG = true;

  const state = {
    map: null,
    markers: [],
    placeMarkerMap: new Map(),
    routeLayer: null,
    userPosition: null,
    config: null,
    maximized: false,
    allPlaces: [],
    visibleCount: PAGE_SIZE,
    activePlaceId: null,
    searchMeta: null,
    fetchController: null,
    searchGeneration: 0,
    activeFilter: 'nearest',
    rawPlaces: [],
  };

  function logDebug(label, data) {
    if (NP_DEBUG && typeof console !== 'undefined' && console.log) {
      console.log(`[Nearby] ${label}`, data);
    }
  }

  function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
  }

  function placeKey(p) {
    return p.id || `${p.lat}_${p.lng}_${(p.name || '').toLowerCase().replace(/\s+/g, '_').slice(0, 48)}`;
  }

  function formatDistance(km) {
    if (km == null || Number.isNaN(km)) return '';
    if (km < 0.1) return `${Math.max(1, Math.round(km * 1000))} m`;
    return `${Number(km).toFixed(1)} km`;
  }

  function roundCoord(n) {
    return Math.round(n * 1000) / 1000;
  }

  function isValidCoords(lat, lng) {
    if (lat == null || lng == null || Number.isNaN(lat) || Number.isNaN(lng)) return false;
    if (Math.abs(lat) > 90 || Math.abs(lng) > 180) return false;
    if (Math.abs(lat) < 0.01 && Math.abs(lng) < 0.01) return false;
    return true;
  }

  function getCachedLocation() {
    try {
      const raw = sessionStorage.getItem(LOC_STORAGE_KEY);
      if (!raw) return null;
      const data = JSON.parse(raw);
      if (Date.now() - data.ts > LOCATION_CACHE_MS) return null;
      const c = data.coords;
      if (!isValidCoords(c.latitude, c.longitude)) return null;
      return c;
    } catch (e) {
      return null;
    }
  }

  function setCachedLocation(coords) {
    if (!isValidCoords(coords.latitude, coords.longitude)) return;
    try {
      sessionStorage.setItem(
        LOC_STORAGE_KEY,
        JSON.stringify({
          ts: Date.now(),
          coords: {
            latitude: coords.latitude,
            longitude: coords.longitude,
            accuracy: coords.accuracy,
          },
        })
      );
    } catch (e) {
      /* ignore */
    }
  }

  function searchCacheKey(lat, lng, type) {
    return `${SEARCH_STORAGE_PREFIX}${type}:${roundCoord(lat)}:${roundCoord(lng)}`;
  }

  function clearSearchCache(lat, lng) {
    try {
      const type = state.config?.placeType || 'place';
      sessionStorage.removeItem(searchCacheKey(lat, lng, type));
    } catch (e) {
      /* ignore */
    }
  }

  function getCachedSearch(lat, lng) {
    try {
      const type = state.config?.placeType || 'place';
      const raw = sessionStorage.getItem(searchCacheKey(lat, lng, type));
      if (!raw) return null;
      const data = JSON.parse(raw);
      if (Date.now() - data.ts > SEARCH_CACHE_MS) return null;
      if (!data.payload?.places?.length) return null;
      return data.payload;
    } catch (e) {
      return null;
    }
  }

  function setCachedSearch(lat, lng, payload) {
    if (!payload?.places?.length) return;
    try {
      const type = state.config?.placeType || 'place';
      sessionStorage.setItem(
        searchCacheKey(lat, lng, type),
        JSON.stringify({ ts: Date.now(), payload })
      );
    } catch (e) {
      /* ignore */
    }
  }

  function getBackdrop() {
    return document.getElementById(state.config?.backdropId);
  }

  function getPanel() {
    return document.getElementById(state.config?.panelId);
  }

  function getListEl() {
    return document.getElementById(state.config?.listId);
  }

  function getMapEl() {
    return document.getElementById(state.config?.mapId);
  }

  function requestLiveLocation(forceFresh) {
    return new Promise((resolve, reject) => {
      if (!forceFresh) {
        const cached = getCachedLocation();
        if (cached) {
          logDebug('GPS (session cache)', cached);
          resolve({ coords: cached });
          return;
        }
      }
      if (!navigator.geolocation) {
        reject({ code: 'unsupported', message: 'Geolocation is not supported by your browser.' });
        return;
      }
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          if (!isValidCoords(pos.coords.latitude, pos.coords.longitude)) {
            reject({ code: 'invalid', message: 'Invalid GPS coordinates received.' });
            return;
          }
          setCachedLocation(pos.coords);
          logDebug('GPS captured', {
            latitude: pos.coords.latitude,
            longitude: pos.coords.longitude,
            accuracy: pos.coords.accuracy,
          });
          resolve(pos);
        },
        (err) => {
          const code =
            err.code === 1 ? 'denied' : err.code === 2 ? 'unavailable' : err.code === 3 ? 'timeout' : 'error';
          reject({ code, message: err.message, raw: err });
        },
        { enableHighAccuracy: true, timeout: 15000, maximumAge: forceFresh ? 0 : 60000 }
      );
    });
  }

  function skeletonListHtml(count) {
    return Array.from({ length: count }, () => `
      <div class="nearby-places-skeleton">
        <div class="np-sk-line med"></div>
        <div class="np-sk-line"></div>
        <div class="np-sk-line short"></div>
      </div>`).join('');
  }

  function showMapPlaceholder() {
    const mapParent = getMapEl()?.parentElement;
    if (!mapParent) return;
    mapParent.innerHTML = `<div id="${state.config.mapId}" class="nearby-places-map nearby-places-map-loading"><i class="fas fa-map"></i> Map loading…</div>`;
    state.map = null;
  }

  function locationGateHtml(message, placeLabel) {
    return `
      <div class="nearby-places-location-gate">
        <div class="w-16 h-16 rounded-full bg-amber-100 flex items-center justify-center mb-4">
          <i class="fas fa-location-crosshairs text-amber-600 text-2xl"></i>
        </div>
        <h4 class="font-bold text-slate-800 text-base mb-2">Allow SmartTrack to access your live location?</h4>
        <p class="text-sm text-slate-600 max-w-sm mb-6">${escapeHtml(message)}</p>
        <p class="text-xs text-slate-400 mb-4">We only use your <strong>current GPS position</strong> to find nearby ${escapeHtml(placeLabel)} — not your profile or saved address.</p>
        <div class="flex flex-col sm:flex-row gap-2 w-full max-w-xs">
          <button type="button" class="np-enable-location flex-1 px-4 py-3 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700">
            <i class="fas fa-crosshairs mr-2"></i>Allow Location
          </button>
          <button type="button" class="np-cancel-location flex-1 px-4 py-3 bg-slate-100 text-slate-700 rounded-xl text-sm font-semibold hover:bg-slate-200">Cancel</button>
        </div>
      </div>`;
  }

  function showLocationGate() {
    const list = getListEl();
    if (!list) return;
    const msg =
      state.config.locationDeniedMessage ||
      'Live location is required to find nearby pharmacies and clinics.';
    list.innerHTML = locationGateHtml(msg, state.config.placeLabel || 'places');
    showMapPlaceholder();
    list.querySelector('.np-enable-location')?.addEventListener('click', () =>
      runSearch({ forceGps: true })
    );
    list.querySelector('.np-cancel-location')?.addEventListener('click', close);
  }

  function clearMapLayers() {
    if (!state.map) return;
    state.markers.forEach((m) => {
      try {
        state.map.removeLayer(m);
      } catch (e) {
        /* ignore */
      }
    });
    state.markers = [];
    state.placeMarkerMap.clear();
    if (state.routeLayer) {
      state.map.removeLayer(state.routeLayer);
      state.routeLayer = null;
    }
  }

  function initMap(lat, lng) {
    const mapParent = getMapEl()?.parentElement;
    if (mapParent && !document.getElementById(state.config.mapId)) {
      mapParent.innerHTML = `<div id="${state.config.mapId}" class="nearby-places-map"></div>`;
    }
    const mapEl = getMapEl();
    if (!mapEl || typeof L === 'undefined') return;
    if (state.map) {
      state.map.setView([lat, lng], 14);
      clearMapLayers();
    } else {
      state.map = L.map(mapEl, { scrollWheelZoom: true, zoomControl: true }).setView([lat, lng], 14);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap',
      }).addTo(state.map);
    }
    const userMarker = L.circleMarker([lat, lng], {
      color: '#2563eb',
      fillColor: '#2563eb',
      fillOpacity: 0.9,
      radius: 10,
    })
      .addTo(state.map)
      .bindPopup('<b>Your live location</b>');
    state.markers.push(userMarker);
  }

  async function drawRoute(destLat, destLng) {
    if (!state.map || !state.userPosition) return;
    const { latitude, longitude } = state.userPosition;
    const url = `https://router.project-osrm.org/route/v1/driving/${longitude},${latitude};${destLng},${destLat}?overview=full&geometries=geojson`;
    try {
      const resp = await fetch(url);
      const data = await resp.json();
      if (data.routes?.[0]) {
        const coords = data.routes[0].geometry.coordinates.map((c) => [c[1], c[0]]);
        if (state.routeLayer) state.map.removeLayer(state.routeLayer);
        state.routeLayer = L.polyline(coords, { color: '#dc2626', weight: 5, opacity: 0.9 }).addTo(state.map);
        state.map.fitBounds(state.routeLayer.getBounds(), { padding: [56, 56] });
      }
    } catch (e) {
      console.warn('Route failed', e);
    }
  }

  function is24_7(p) {
    return !!(p.is_24_7 || /24\s*[\/x×]\s*7/i.test(p.opening_hours || ''));
  }

  function sortPlaces(places, filter) {
    var arr = places.slice();
    if (filter === 'open_now') {
      arr.sort(function (a, b) {
        var ao = a.open === true ? 0 : a.open === false ? 2 : 1;
        var bo = b.open === true ? 0 : b.open === false ? 2 : 1;
        if (ao !== bo) return ao - bo;
        return (a.distance_km || 999) - (b.distance_km || 999);
      });
    } else if (filter === '24_7') {
      arr.sort(function (a, b) {
        var a24 = is24_7(a) ? 0 : 1;
        var b24 = is24_7(b) ? 0 : 1;
        if (a24 !== b24) return a24 - b24;
        return (a.distance_km || 999) - (b.distance_km || 999);
      });
    } else if (filter === 'highest_rated') {
      arr.sort(function (a, b) {
        var ar = a.rating != null ? a.rating : -1;
        var br = b.rating != null ? b.rating : -1;
        if (br !== ar) return br - ar;
        return (a.distance_km || 999) - (b.distance_km || 999);
      });
    } else {
      arr.sort(function (a, b) {
        return (a.distance_km || 999) - (b.distance_km || 999);
      });
    }
    return arr;
  }

  function googleMapsDirectionsUrl(lat, lng) {
    return 'https://www.google.com/maps/dir/?api=1&destination=' + encodeURIComponent(lat + ',' + lng);
  }

  function ensureFilterBar() {
    var listWrap = getListEl()?.parentElement;
    if (!listWrap || document.getElementById('npFilterBar')) return;
    var bar = document.createElement('div');
    bar.id = 'npFilterBar';
    bar.className = 'np-filter-bar flex flex-wrap gap-1.5 p-3 border-b border-slate-100 bg-slate-50/80';
    bar.innerHTML = [
      { id: 'nearest', label: 'Nearest' },
      { id: 'open_now', label: 'Open now' },
      { id: '24_7', label: '24×7' },
      { id: 'highest_rated', label: 'Highest rated' },
    ].map(function (f) {
      return '<button type="button" class="np-filter-btn px-3 py-1.5 rounded-lg text-xs font-semibold border transition ' +
        (state.activeFilter === f.id ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-100') +
        '" data-filter="' + f.id + '">' + f.label + '</button>';
    }).join('');
    listWrap.insertBefore(bar, getListEl());
    bar.querySelectorAll('.np-filter-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        state.activeFilter = btn.getAttribute('data-filter') || 'nearest';
        bar.querySelectorAll('.np-filter-btn').forEach(function (b) {
          var active = b.getAttribute('data-filter') === state.activeFilter;
          b.className = 'np-filter-btn px-3 py-1.5 rounded-lg text-xs font-semibold border transition ' +
            (active ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-100');
        });
        state.allPlaces = sortPlaces(state.rawPlaces, state.activeFilter);
        state.visibleCount = state.allPlaces.length;
        state.activePlaceId = null;
        renderListSlice();
        if (state.map && state.userPosition) {
          addPlaceMarkers(state.allPlaces, state.userPosition.latitude, state.userPosition.longitude);
        }
      });
    });
  }

  function openStatusHtml(p) {
    if (p.open === true) {
      return '<span class="inline-flex items-center text-emerald-600 font-semibold text-xs"><span class="inline-block w-2 h-2 rounded-full bg-emerald-500 mr-1"></span>Open now</span>';
    }
    if (p.open === false) {
      return '<span class="inline-flex items-center text-amber-600 font-semibold text-xs"><span class="inline-block w-2 h-2 rounded-full bg-amber-500 mr-1"></span>Closed</span>';
    }
    return '<span class="text-slate-500 text-xs">Hours unknown</span>';
  }

  function buildCardHtml(p, type) {
    var icon = type === 'pharmacy' ? '💊' : '🏥';
    var phone = (p.phone || '').trim();
    var dist = formatDistance(p.distance_km);
    var safeName = escapeHtml(p.name);
    var pid = placeKey(p);
    var safePid = escapeHtml(pid);
    var addr = p.address && p.address.trim() ? p.address : 'Address unavailable';
    var ratingHtml = p.rating != null
      ? '<span class="text-amber-500 font-semibold text-xs"><i class="fas fa-star mr-0.5"></i>' + Number(p.rating).toFixed(1) + '</span>'
      : '';
    var badge24 = is24_7(p)
      ? '<span class="text-[10px] bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-bold">24×7</span>'
      : '';
    var gmapsUrl = googleMapsDirectionsUrl(p.lat, p.lng);
    var tel = phone ? phone.replace(/[\s-]/g, '') : '';

    return (
      '<div class="nearby-places-card" data-place-id="' + safePid + '" data-lat="' + p.lat + '" data-lng="' + p.lng + '" data-name="' + safeName + '">' +
        '<div class="flex justify-between gap-2 mb-1 items-start">' +
          '<div class="font-bold text-slate-800 text-sm">' + icon + ' ' + safeName + '</div>' +
          '<div class="flex flex-wrap gap-1 justify-end">' + badge24 + ratingHtml + '</div>' +
        '</div>' +
        '<div class="flex flex-wrap items-center gap-2 text-xs mb-2">' +
          (dist ? '<span class="text-slate-700 font-semibold"><i class="fas fa-route mr-1 text-blue-500"></i>' + dist + ' away</span>' : '') +
          openStatusHtml(p) +
        '</div>' +
        '<div class="text-xs text-slate-600 mb-2 leading-relaxed"><i class="fas fa-map-marker-alt text-red-400 mr-1"></i>' + escapeHtml(addr) + '</div>' +
        (phone ? '<div class="text-xs text-slate-600 mb-2"><i class="fas fa-phone mr-1 text-emerald-500"></i>Phone: <span class="font-semibold">' + escapeHtml(phone) + '</span></div>' : '') +
        '<div class="flex gap-2 flex-wrap mt-2">' +
          '<a href="' + gmapsUrl + '" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 bg-blue-600 text-white text-xs rounded-lg font-semibold hover:bg-blue-700 inline-flex items-center gap-1"><i class="fas fa-directions"></i> Directions</a>' +
          (tel ? '<a href="tel:' + tel + '" class="px-3 py-1.5 bg-emerald-600 text-white text-xs rounded-lg font-semibold hover:bg-emerald-700 inline-flex items-center gap-1"><i class="fas fa-phone"></i> Call</a>' : '') +
          '<button type="button" class="np-route-btn px-3 py-1.5 bg-slate-100 text-slate-700 text-xs rounded-lg font-semibold hover:bg-slate-200">View Route</button>' +
        '</div>' +
      '</div>'
    );
  }

  function wireCardEvents() {
    const list = getListEl();
    if (!list) return;

    list.querySelectorAll('.nearby-places-card').forEach((card) => {
      const lat = parseFloat(card.dataset.lat);
      const lng = parseFloat(card.dataset.lng);
      const name = card.dataset.name;
      const pid = card.dataset.placeId;

      card.querySelector('.np-route-btn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        state.config.onSelect?.({ name, lat, lng });
        highlightPlace(pid, lat, lng, name, true);
      });
      card.addEventListener('click', () => highlightPlace(pid, lat, lng, name, false));
    });

    list.querySelector('.np-load-more')?.addEventListener('click', () => {
      state.visibleCount = Math.min(state.visibleCount + PAGE_SIZE, state.allPlaces.length);
      renderListSlice();
    });
  }

  function setActiveCard(pid) {
    const list = getListEl();
    if (!list) return;
    list.querySelectorAll('.nearby-places-card').forEach((c) => c.classList.remove('is-active'));
    const escaped = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(pid) : pid.replace(/"/g, '\\"');
    const card = list.querySelector(`[data-place-id="${escaped}"]`);
    if (card) {
      card.classList.add('is-active');
      card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  function highlightPlace(pid, lat, lng, name, drawRouteLine) {
    if (!state.map) return;
    state.activePlaceId = pid;
    state.map.flyTo([lat, lng], 16, { duration: 0.6 });
    const marker = state.placeMarkerMap.get(pid);
    if (marker) marker.openPopup();
    setActiveCard(pid);
    if (drawRouteLine) drawRoute(lat, lng);
  }

  function renderListSlice() {
    const list = getListEl();
    if (!list) return;
    const type = state.config.placeType || 'place';
    const visible = state.allPlaces.slice(0, state.visibleCount);
    const hasMore = state.visibleCount < state.allPlaces.length;

    if (!state.allPlaces.length) {
      list.innerHTML = `<div class="text-center py-10 text-slate-500 text-sm">No ${escapeHtml(state.config.placeLabel || 'places')} found within search radius.<br><button type="button" class="np-retry-search mt-3 px-4 py-2 bg-slate-100 rounded-xl text-xs font-semibold">Search again</button></div>`;
      list.querySelector('.np-retry-search')?.addEventListener('click', () => runSearch({ forceGps: true, skipCache: true }));
      return;
    }

    const meta = document.getElementById('npResultsMeta');
    if (meta && state.searchMeta) {
      meta.textContent = `${state.allPlaces.length} found · within ${(state.searchMeta.search_radius_m / 1000).toFixed(0)} km`;
    }

    list.innerHTML =
      visible.map((p) => buildCardHtml(p, type)).join('') +
      (hasMore
        ? `<button type="button" class="np-load-more w-full py-3 mt-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-sm font-semibold">Load more (${state.allPlaces.length - state.visibleCount} remaining)</button>`
        : '');

    wireCardEvents();
    logDebug('rendered', { final: visible.length, total: state.allPlaces.length });
    if (state.activePlaceId) setActiveCard(state.activePlaceId);
  }

  function applySearchResults(places, latitude, longitude, meta, generation) {
    if (generation !== state.searchGeneration) return;

    state.searchMeta = meta;
    ensureResultsMeta();
    const metaEl = document.getElementById('npResultsMeta');
    if (metaEl) {
      metaEl.textContent = `${places.length} found · within ${((meta?.search_radius_m || 5000) / 1000).toFixed(0)} km`;
    }

    state.rawPlaces = Array.isArray(places) ? places.slice() : [];
    state.allPlaces = sortPlaces(state.rawPlaces, state.activeFilter);
    state.visibleCount = state.allPlaces.length;
    state.activePlaceId = null;
    ensureFilterBar();
    logDebug('render pipeline', {
      filtered: state.allPlaces.length,
      final: state.allPlaces.length,
    });
    renderListSlice();

    window.requestAnimationFrame(() => {
      if (generation !== state.searchGeneration) return;
      initMap(latitude, longitude);
      addPlaceMarkers(state.allPlaces, latitude, longitude);
    });
  }

  function addPlaceMarkers(places, userLat, userLng) {
    if (!state.map) return;
    clearMapLayers();
    places.forEach((p) => {
      if (p.lat == null || p.lng == null) return;
      const pid = placeKey(p);
      const m = L.marker([p.lat, p.lng])
        .addTo(state.map)
        .bindPopup(
          `<b>${escapeHtml(p.name)}</b><br>${escapeHtml(p.address || '')}<br>${formatDistance(p.distance_km)}`
        );
      m.on('click', () => {
        highlightPlace(pid, p.lat, p.lng, p.name, false);
        state.config.onSelect?.({ name: p.name, lat: p.lat, lng: p.lng });
      });
      state.markers.push(m);
      state.placeMarkerMap.set(pid, m);
    });

    if (places.length) {
      const bounds = L.latLngBounds([[userLat, userLng]]);
      places.forEach((p) => bounds.extend([p.lat, p.lng]));
      state.map.fitBounds(bounds, { padding: [48, 48] });
    }
    setTimeout(() => state.map?.invalidateSize(), 200);
  }

  function ensureResultsMeta() {
    const header = getPanel()?.querySelector('.nearby-places-header > div');
    if (!header || document.getElementById('npResultsMeta')) return;
    const meta = document.createElement('p');
    meta.id = 'npResultsMeta';
    meta.className = 'text-xs text-slate-400 mt-0.5';
    header.appendChild(meta);
  }

  async function fetchPlaces(latitude, longitude) {
    const url = state.config.buildApiUrl(latitude, longitude);
    const sep = url.includes('?') ? '&' : '?';
    const fetchUrl = `${url}${sep}debug=1`;

    state.fetchController = new AbortController();
    const timeoutMs = 50000;
    const timeoutId = setTimeout(() => state.fetchController?.abort(), timeoutMs);
    let resp;
    try {
      resp = await fetch(fetchUrl, {
        signal: state.fetchController.signal,
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      });
    } finally {
      clearTimeout(timeoutId);
    }

    let data;
    try {
      data = await resp.json();
    } catch (e) {
      throw new Error('Invalid response from server. Please sign in and try again.');
    }

    if (!resp.ok || !data.success) {
      throw new Error(data.error || `Search failed (${resp.status})`);
    }

    const key =
      state.config.resultsKey || (state.config.placeType === 'pharmacy' ? 'pharmacies' : 'clinics');
    const places = data[key] || [];

    const filtered = places.filter(
      (p) => p && p.lat != null && p.lng != null && (p.name || '').trim()
    );
    const meta = {
      search_radius_m: data.search_radius_m,
      total: data.total ?? filtered.length,
    };
    logDebug('API response', {
      apiCount: places.length,
      filteredCount: filtered.length,
      radius_m: data.search_radius_m,
      debug: data.debug,
    });
    return { places: filtered, meta };
  }

  async function runSearch(options = {}) {
    const list = getListEl();
    const forceGps = options.forceGps === true;
    const skipCache = options.skipCache === true;
    const generation = ++state.searchGeneration;

    if (list) list.innerHTML = skeletonListHtml(4);
    showMapPlaceholder();
    ensureResultsMeta();
    const metaEl = document.getElementById('npResultsMeta');
    if (metaEl) metaEl.textContent = 'Finding nearby places…';

    let pos;
    try {
      if (forceGps) sessionStorage.removeItem(LOC_STORAGE_KEY);
      pos = await requestLiveLocation(forceGps);
    } catch (err) {
      showLocationGate();
      return;
    }

    state.userPosition = pos.coords;
    const latitude = pos.coords.latitude;
    const longitude = pos.coords.longitude;

    if (!isValidCoords(latitude, longitude)) {
      showLocationGate();
      return;
    }

    if (!skipCache) {
      const cached = getCachedSearch(latitude, longitude);
      if (cached?.places?.length) {
        logDebug('cache hit', { count: cached.places.length });
        applySearchResults(cached.places, latitude, longitude, cached.meta, generation);
      }
    }

    try {
      const { places, meta } = await fetchPlaces(latitude, longitude);
      if (generation !== state.searchGeneration) return;

      logDebug('filtered final', { count: places.length });

      if (places.length) {
        setCachedSearch(latitude, longitude, { places, meta });
      } else {
        clearSearchCache(latitude, longitude);
      }

      applySearchResults(places, latitude, longitude, meta, generation);
    } catch (err) {
      if (err.name === 'AbortError') {
        if (generation !== state.searchGeneration) return;
        if (list) {
          list.innerHTML = `<div class="text-center py-10 text-amber-700 text-sm">Search is taking longer than expected. Please try again.<br><button type="button" class="np-retry-search mt-3 px-4 py-2 bg-slate-100 rounded-xl text-xs font-semibold">Retry</button></div>`;
          list.querySelector('.np-retry-search')?.addEventListener('click', () =>
            runSearch({ forceGps: true, skipCache: true })
          );
        }
        return;
      }
      logDebug('error', err.message);
      if (generation !== state.searchGeneration) return;
      if (list) {
        list.innerHTML = `<div class="text-center py-10 text-red-600 text-sm">${escapeHtml(err.message)}<br><button type="button" class="np-retry-search mt-3 px-4 py-2 bg-slate-100 rounded-xl text-xs font-semibold">Retry</button></div>`;
        list.querySelector('.np-retry-search')?.addEventListener('click', () =>
          runSearch({ forceGps: true, skipCache: true })
        );
      }
    }
  }

  function setMaximized(on) {
    const panel = getPanel();
    const backdrop = getBackdrop();
    if (!panel) return;
    state.maximized = on;
    panel.classList.toggle('is-maximized', on);
    panel.classList.toggle('is-minimized', !on);
    if (backdrop) backdrop.style.padding = on ? '0' : '';
    setTimeout(() => state.map?.invalidateSize(), 350);
  }

  function wirePanelControls() {
    document.getElementById(state.config.btnMaximizeId)?.addEventListener('click', () => setMaximized(true));
    document.getElementById(state.config.btnMinimizeId)?.addEventListener('click', () => setMaximized(false));
    document.getElementById(state.config.btnCloseId)?.addEventListener('click', close);
    getBackdrop()?.addEventListener('click', (e) => {
      if (e.target === getBackdrop()) close();
    });
  }

  function open(config) {
    state.config = config;
    state.userPosition = null;
    state.map = null;
    state.markers = [];
    state.placeMarkerMap = new Map();
    state.routeLayer = null;
    state.maximized = false;
    state.allPlaces = [];
    state.visibleCount = PAGE_SIZE;
    state.searchMeta = null;
    state.activeFilter = 'nearest';
    state.rawPlaces = [];
    state.searchGeneration++;

    const backdrop = getBackdrop();
    const panel = getPanel();
    if (!backdrop || !panel) return;

    document.getElementById('npFilterBar')?.remove();

    panel.classList.remove('is-maximized');
    panel.classList.add('is-minimized');
    backdrop.classList.add('is-open');
    document.body.classList.add('overflow-hidden');

    document.getElementById('npResultsMeta')?.remove();

    if (!panel.dataset.controlsWired) {
      wirePanelControls();
      panel.dataset.controlsWired = '1';
    }
    runSearch({ forceGps: true });
  }

  function close() {
    state.searchGeneration++;
    if (state.fetchController) {
      state.fetchController.abort();
      state.fetchController = null;
    }
    const backdrop = getBackdrop();
    if (backdrop) backdrop.classList.remove('is-open');
    document.body.classList.remove('overflow-hidden');
    clearMapLayers();
    state.map = null;
    setMaximized(false);
    document.getElementById('npResultsMeta')?.remove();
  }

  global.SmartTrackNearbyPlaces = {
    open,
    close,
    requestLiveLocation: (force) => requestLiveLocation(!!force),
    runSearch,
  };
})(window);
