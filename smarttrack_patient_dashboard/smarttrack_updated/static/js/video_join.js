/**
 * SmartTrack video consultation — join overlay + load call UI + WebRTC bootstrap.
 * Loaded from base_dashboard.html (before page content) so Join always works.
 */
(function () {
  'use strict';

  function normalizeVideoCallUrl(url) {
    if (!url) return '';
    return String(url)
      .replace(/\\u002D/gi, '-')
      .replace(/\\\//g, '/')
      .trim();
  }

  function notify(msg, type, title) {
    if (typeof window.showToast === 'function') {
      window.showToast(type || 'error', title || null, msg);
    }
  }

  function showVideoCallOverlay() {
    const overlay = document.getElementById('videoCallOverlay');
    if (!overlay) return null;
    overlay.classList.remove('hidden');
    overlay.style.display = 'flex';
    overlay.style.position = 'fixed';
    overlay.style.inset = '0';
    overlay.style.zIndex = '99999';
    overlay.style.background = '#0f172a';
    overlay.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    const content = document.getElementById('videoCallContent');
    if (content) {
      content.style.width = '100%';
      content.style.height = '100%';
      content.style.minHeight = '100vh';
    }
    return overlay;
  }

  function hideVideoCallOverlay() {
    const overlay = document.getElementById('videoCallOverlay');
    const content = document.getElementById('videoCallContent');
    if (window.__smartTrackCallCleanup) {
      try { window.__smartTrackCallCleanup(); } catch (_) { /* ignore */ }
      window.__smartTrackCallCleanup = null;
    }
    window.__smartTrackActiveCall = false;
    if (overlay) {
      overlay.classList.add('hidden');
      overlay.style.display = 'none';
      overlay.setAttribute('aria-hidden', 'true');
    }
    if (content) content.innerHTML = '';
    document.body.style.overflow = '';
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const base = src.split('?')[0];
      const existing = Array.from(document.querySelectorAll('script[src]')).find(
        (s) => s.src && (s.src === src || s.src.includes(base))
      );
      if (existing) {
        if (existing.dataset.loaded === '1' || existing.readyState === 'complete') return resolve();
        existing.addEventListener('load', () => resolve());
        existing.addEventListener('error', () => reject(new Error('Script failed: ' + src)));
        return;
      }
      const script = document.createElement('script');
      script.src = src;
      script.async = false;
      script.onload = () => {
        script.dataset.loaded = '1';
        resolve();
      };
      script.onerror = () => reject(new Error('Failed to load: ' + src));
      document.head.appendChild(script);
    });
  }

  async function injectHtmlScripts(container) {
    const scripts = Array.from(container.querySelectorAll('script'));
    for (const oldScript of scripts) {
      const src = oldScript.getAttribute('src');
      if (src) {
        await loadScript(src);
        oldScript.remove();
      } else if (oldScript.textContent.trim()) {
        const inline = document.createElement('script');
        inline.textContent = oldScript.textContent;
        document.head.appendChild(inline);
        oldScript.remove();
      } else {
        oldScript.remove();
      }
    }
  }

  async function ensureWebRtcScript() {
    const src =
      (window.SMARTTRACK_STATIC && window.SMARTTRACK_STATIC.webrtc) ||
      '/static/js/webrtc_consultation.js?v=1';
    if (typeof window.initSmartTrackConsultation === 'function') return;
    await loadScript(src);
  }

  async function bootConsultationFromDom() {
    const root = document.getElementById('video-call-container');
    if (!root) throw new Error('Call UI missing');

    await ensureWebRtcScript();

    const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
    const config = {
      aptId: root.dataset.aptId,
      roomId: root.dataset.roomId,
      role: root.dataset.role,
      isInitiator: root.dataset.isInitiator === 'true',
      csrfToken: root.dataset.csrfToken || csrfInput?.value || '',
      signalUrl: root.dataset.signalUrl || `/appointments/webrtc-signal/${root.dataset.aptId}/`,
      endCallUrl: root.dataset.endCallUrl || `/appointments/video-call/end/${root.dataset.aptId}/`,
    };

    if (!config.aptId) throw new Error('Invalid appointment session');

    if (typeof window.initSmartTrackConsultation !== 'function') {
      throw new Error('WebRTC module failed to load');
    }

    window.initSmartTrackConsultation(config);
  }

  async function joinVideoCall(url) {
    const trimmed = normalizeVideoCallUrl(url);
    console.log('[SmartTrack Video] joinVideoCall', trimmed);

    if (!trimmed) {
      notify('Video link is not available. Confirm the appointment first.', 'error');
      return;
    }

    if (window.__smartTrackActiveCall) {
      showVideoCallOverlay();
      return;
    }

    const overlay = showVideoCallOverlay();
    const content = document.getElementById('videoCallContent');

    if (!overlay || !content) {
      console.warn('[SmartTrack Video] No overlay — full page navigation');
      window.location.href = trimmed;
      return;
    }

    content.innerHTML = `
      <div class="h-full w-full flex flex-col items-center justify-center text-white gap-4">
        <div class="w-12 h-12 bg-white/20 rounded-full flex items-center justify-center animate-spin">
          <i class="fas fa-spinner text-2xl"></i>
        </div>
        <p class="text-lg font-medium">Launching secure consultation...</p>
        <p class="text-sm text-slate-400">Allow camera &amp; microphone when prompted</p>
      </div>
    `;

    try {
      const response = await fetch(trimmed, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        credentials: 'same-origin',
        cache: 'no-store',
      });

      console.log('[SmartTrack Video] fetch', response.status, response.url);

      if (!response.ok) {
        let errMsg = `Could not join call (HTTP ${response.status}).`;
        try {
          const data = await response.json();
          if (data.error) errMsg = data.error;
        } catch (_) { /* not JSON */ }
        throw new Error(errMsg);
      }

      const html = await response.text();
      if (!html.includes('video-call-container') && !html.includes('id="remote-video"')) {
        throw new Error('Call session unavailable. Confirm the appointment is active.');
      }

      content.innerHTML = html;
      await injectHtmlScripts(content);
      window.__smartTrackActiveCall = true;
      await bootConsultationFromDom();
      console.log('[SmartTrack Video] consultation started — allow camera/mic when prompted');
    } catch (e) {
      console.error('[SmartTrack Video] error', e);
      content.innerHTML = `
        <div class="text-white p-8 text-center max-w-md mx-auto">
          <p class="font-semibold text-lg mb-2">Could not start video call</p>
          <p class="text-sm text-slate-300 mb-6">${e.message || 'Unknown error'}</p>
          <button type="button" id="videoJoinCloseBtn"
            class="px-5 py-2.5 bg-white/20 rounded-xl text-sm hover:bg-white/30 transition">Close</button>
        </div>`;
      document.getElementById('videoJoinCloseBtn')?.addEventListener('click', hideVideoCallOverlay);
      notify(e.message || 'Failed to start video call', 'error');
    }
  }

  /** Single entry point used by all Join Video Call buttons. */
  function smartTrackJoinVideoCall(btn, event) {
    console.log('Join button clicked');
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    if (!btn) return false;

    const url = normalizeVideoCallUrl(btn.getAttribute('data-join-video'));
    joinVideoCall(url);
    return false;
  }

  function bindJoinVideoButtons(root) {
    (root || document).querySelectorAll('[data-join-video]').forEach((btn) => {
      if (btn.dataset.joinBound === '1' || btn.getAttribute('onclick')) return;
      btn.dataset.joinBound = '1';
      btn.addEventListener('click', (e) => smartTrackJoinVideoCall(btn, e));
    });
  }

  document.addEventListener('DOMContentLoaded', () => bindJoinVideoButtons());

  window.joinVideoCall = joinVideoCall;
  window.hideVideoCallOverlay = hideVideoCallOverlay;
  window.smartTrackJoinVideoCall = smartTrackJoinVideoCall;
  window.bindJoinVideoButtons = bindJoinVideoButtons;
  window.SmartTrackBootConsultation = bootConsultationFromDom;

  console.log('[SmartTrack Video] join module ready');
})();
