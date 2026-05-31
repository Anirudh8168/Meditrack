/**
 * WebRTC consultation — offer/answer/ICE via Django signaling API.
 *
 * PRODUCTION FIXES:
 *  1. Added TURN relay servers (required when both peers are behind NAT).
 *     STUN alone fails on most mobile/corporate networks in production.
 *  2. ICE restart on connection failure (reconnect without page reload).
 *  3. Better error messages for production permission failures.
 *  4. Reads TURN config from data-turn-* attributes (set via Django settings).
 *  5. playsInline always set for iOS Safari compatibility.
 */
(function () {
  function getCsrfToken(fallback) {
    const fromInput = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
    if (fromInput) return fromInput;
    if (fallback) return fallback;
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  /**
   * Build ICE server list.
   * Priority: data attributes (from Django settings) > hard-coded public fallbacks.
   *
   * For production, set these environment variables in Render:
   *   TURN_URL=turn:your-turn-server.com:3478
   *   TURN_USERNAME=your-username
   *   TURN_CREDENTIAL=your-credential
   *
   * Free option: https://www.metered.ca/tools/openrelay/ provides TURN free tier.
   */
  function buildIceServers(root) {
    const turnUrl      = root?.dataset?.turnUrl      || '';
    const turnUsername = root?.dataset?.turnUsername || '';
    const turnCred     = root?.dataset?.turnCredential || '';

    const servers = [
      // Multiple Google STUN servers for resilience
      { urls: 'stun:stun.l.google.com:19302' },
      { urls: 'stun:stun1.l.google.com:19302' },
      { urls: 'stun:stun2.l.google.com:19302' },
      { urls: 'stun:stun3.l.google.com:19302' },
    ];

    if (turnUrl && turnUsername && turnCred) {
      // Use configured TURN server (highest priority)
      servers.push(
        { urls: turnUrl,              username: turnUsername, credential: turnCred },
        { urls: turnUrl.replace('turn:', 'turns:').replace(':3478', ':5349'),
          username: turnUsername, credential: turnCred },
      );
    } else {
      // ── Free public TURN relay via Open Relay Project ──────────────────────
      // These are real, publicly accessible TURN servers. Rate-limited but work
      // for low-traffic apps. Replace with a paid TURN service for production scale.
      // https://openrelay.metered.ca/
      servers.push(
        {
          urls: 'turn:openrelay.metered.ca:80',
          username: 'openrelayproject',
          credential: 'openrelayproject',
        },
        {
          urls: 'turn:openrelay.metered.ca:443',
          username: 'openrelayproject',
          credential: 'openrelayproject',
        },
        {
          urls: 'turn:openrelay.metered.ca:443?transport=tcp',
          username: 'openrelayproject',
          credential: 'openrelayproject',
        },
        {
          urls: 'turns:openrelay.metered.ca:443',
          username: 'openrelayproject',
          credential: 'openrelayproject',
        },
      );
    }

    return servers;
  }

  function initConsultation(config) {
    const aptId = config.aptId;
    const userRole = config.role;
    const isInitiator = config.isInitiator === true || config.isInitiator === 'true';
    const signalUrl = config.signalUrl || `/appointments/webrtc-signal/${aptId}/`;
    const endCallUrl = config.endCallUrl || `/appointments/video-call/end/${aptId}/`;
    const csrfToken = getCsrfToken(config.csrfToken);
    const roomId = config.roomId || `appointment_${aptId}`;

    if (window.__smartTrackCallSession === aptId) {
      log('session already active for appointment', aptId);
      return;
    }
    window.__smartTrackCallSession = aptId;

    let localStream = null;
    let remoteStream = null;
    let peerConnection = null;
    let pollTimer = null;
    let timerInterval = null;
    let callStartedAt = null;
    let timerStarted = false;
    let offerCreated = false;
    let answerHandled = false;
    let offerHandled = false;
    let appliedRemoteIceCount = 0;
    let pollInFlight = false;
    let pendingRemoteIce = [];
    let isConnected = false;
    let endingCall = false;
    let callEnded = false;
    let iceRestartAttempts = 0;
    const MAX_ICE_RESTARTS = 3;

    const remoteVideo = document.getElementById('remote-video');
    const localVideo = document.getElementById('local-video');
    const remotePlaceholder = document.getElementById('remote-placeholder');
    const localPlaceholder = document.getElementById('local-placeholder');
    const timerEl = document.getElementById('callTimer');
    const statusTitle = document.getElementById('remote-status-title') || remotePlaceholder?.querySelector('p.text-lg');
    const statusSubtitle = document.getElementById('remote-status-subtitle') || remotePlaceholder?.querySelector('p.text-sm');
    const root = document.getElementById('video-call-container');

    const peerConfig = {
      iceServers: buildIceServers(root),
      iceTransportPolicy: 'all',          // try STUN first; fall back to TURN relay
      bundlePolicy: 'max-bundle',
      rtcpMuxPolicy: 'require',
    };

    log('ICE servers configured', peerConfig.iceServers.map(s => s.urls));

    function log(msg, extra) {
      if (extra !== undefined) {
        console.log(`[WebRTC][${userRole}] ${msg}`, extra);
      } else {
        console.log(`[WebRTC][${userRole}] ${msg}`);
      }
    }

    function setWaitingForPeer() {
      if (!remotePlaceholder) return;
      remotePlaceholder.classList.remove('hidden', 'opacity-0');
      if (statusTitle) statusTitle.textContent = 'Waiting for participant to join';
      if (statusSubtitle) statusSubtitle.textContent = '';
    }

    function setNegotiating() {
      if (!remotePlaceholder || isConnected) return;
      remotePlaceholder.classList.remove('hidden', 'opacity-0');
      if (statusTitle) statusTitle.textContent = 'Connecting...';
      if (statusSubtitle) statusSubtitle.textContent = 'Establishing secure channel';
    }

    function setConnectedUI() {
      if (isConnected) return;
      isConnected = true;
      if (statusTitle) statusTitle.textContent = 'Connected';
      if (statusSubtitle) statusSubtitle.textContent = '';
      if (remotePlaceholder) {
        remotePlaceholder.classList.add('opacity-0');
        setTimeout(() => remotePlaceholder.classList.add('hidden'), 300);
      }
    }

    function hasRemoteDescription() {
      return !!(peerConnection && peerConnection.remoteDescription);
    }

    async function postSignal(data, retries = 4) {
      let lastErr;
      for (let attempt = 0; attempt < retries; attempt++) {
        try {
          const res = await fetch(signalUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': csrfToken,
            },
            body: JSON.stringify(data),
          });
          const json = await res.json().catch(() => ({}));
          if (res.status === 503 && attempt < retries - 1) {
            await new Promise((r) => setTimeout(r, 80 * (attempt + 1)));
            continue;
          }
          if (!res.ok || !json.success) {
            throw new Error(json.error || `Signaling failed (${res.status})`);
          }
          return json;
        } catch (e) {
          lastErr = e;
          if (attempt < retries - 1) {
            await new Promise((r) => setTimeout(r, 80 * (attempt + 1)));
          }
        }
      }
      throw lastErr;
    }

    function startSyncedTimer(serverIso) {
      if (timerStarted) return;
      timerStarted = true;
      callStartedAt = serverIso ? new Date(serverIso) : new Date();
      log('timer started', callStartedAt.toISOString());
      updateTimer();
    }

    function updateTimer() {
      if (!timerEl) return;
      if (!timerStarted || !callStartedAt) {
        timerEl.textContent = '00:00';
        return;
      }
      const elapsed = Math.max(0, Math.floor((Date.now() - callStartedAt.getTime()) / 1000));
      const m = Math.floor(elapsed / 60);
      const s = elapsed % 60;
      timerEl.textContent = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }

    async function onPeerConnected() {
      if (peerConnection.connectionState !== 'connected') return;
      setConnectedUI();
      try {
        const res = await postSignal({ type: 'connected' });
        startSyncedTimer(res.call_started_at || null);
      } catch (e) {
        log('connected signal failed', e);
        if (!timerStarted) startSyncedTimer(null);
      }
    }

    async function verifyAndInitMedia() {
      // HTTPS / secure context check (required in production)
      const isSecure = location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1';
      if (!isSecure) {
        throw new Error('Video calls require a secure connection (HTTPS). Contact your administrator.');
      }

      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('Your browser does not support video calls. Please use Chrome, Edge, or Safari on iOS.');
      }

      localStream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' },
        audio: { echoCancellation: true, noiseSuppression: true, sampleRate: 44100 },
      });
      log('local stream created', { tracks: localStream.getTracks().length });

      const audioTrack = localStream.getAudioTracks()[0];
      const videoTrack = localStream.getVideoTracks()[0];

      if (!audioTrack && !videoTrack) {
        throw new Error('No camera or microphone was found. Please check your device.');
      }

      if (audioTrack) audioTrack.enabled = true;
      if (videoTrack) videoTrack.enabled = true;

      localVideo.srcObject = localStream;
      localVideo.muted = true;
      localVideo.autoplay = true;
      localVideo.playsInline = true;
      localVideo.setAttribute('playsinline', 'true');

      remoteVideo.muted = false;
      remoteVideo.autoplay = true;
      remoteVideo.playsInline = true;
      remoteVideo.setAttribute('playsinline', 'true');

      await localVideo.play().catch((e) => log('local play warning', e));
      localPlaceholder?.classList.add('hidden');
    }

    function createPeerConnection() {
      if (peerConnection) {
        try { peerConnection.close(); } catch (_) {}
      }
      peerConnection = new RTCPeerConnection(peerConfig);
      log('RTCPeerConnection created');

      localStream.getTracks().forEach((track) => {
        peerConnection.addTrack(track, localStream);
        log('track added', { kind: track.kind, enabled: track.enabled });
      });

      peerConnection.onicecandidate = (event) => {
        if (!event.candidate) {
          log('ICE gathering complete');
          return;
        }
        log('sending ICE candidate', { type: event.candidate.type });
        postSignal({ type: 'ice', candidate: event.candidate.toJSON() })
          .then(() => log('ICE candidate sent'))
          .catch((err) => log('ICE send failed', err));
      };

      peerConnection.ontrack = (event) => {
        log('ontrack fired', { kind: event.track.kind, streams: event.streams?.length });

        if (event.streams && event.streams[0]) {
          remoteStream = event.streams[0];
        } else {
          if (!remoteStream) remoteStream = new MediaStream();
          if (!remoteStream.getTracks().some((t) => t.id === event.track.id)) {
            remoteStream.addTrack(event.track);
          }
        }

        remoteVideo.srcObject = remoteStream;
        remoteVideo.muted = false;
        remoteVideo.autoplay = true;
        remoteVideo.playsInline = true;
        remoteVideo.setAttribute('playsinline', 'true');

        // Resume on user gesture if autoplay was blocked
        const playPromise = remoteVideo.play();
        if (playPromise !== undefined) {
          playPromise
            .then(() => log('remote video/audio playing'))
            .catch((e) => {
              log('remote autoplay blocked — will retry on interaction', e);
              // Show a "tap to continue" banner so users can unblock audio
              showTapToPlayBanner();
            });
        }
      };

      peerConnection.onconnectionstatechange = async () => {
        const state = peerConnection.connectionState;
        log('connectionState', state);

        if (state === 'connected') {
          iceRestartAttempts = 0;
          await onPeerConnected();
        } else if (state === 'failed') {
          log('connection failed — attempting ICE restart');
          isConnected = false;
          if (statusTitle) {
            remotePlaceholder?.classList.remove('hidden', 'opacity-0');
            statusTitle.textContent = 'Connection lost — reconnecting...';
            if (statusSubtitle) statusSubtitle.textContent = '';
          }
          await attemptIceRestart();
        } else if (state === 'disconnected') {
          isConnected = false;
          if (statusTitle && !remotePlaceholder?.classList.contains('hidden')) {
            statusTitle.textContent = 'Connection interrupted';
            if (statusSubtitle) statusSubtitle.textContent = 'Trying to reconnect...';
          }
          // Allow brief grace period before treating as failed
          setTimeout(async () => {
            if (peerConnection?.connectionState === 'disconnected') {
              await attemptIceRestart();
            }
          }, 5000);
        }
      };

      peerConnection.oniceconnectionstatechange = () => {
        log('iceConnectionState', peerConnection.iceConnectionState);
      };

      peerConnection.onicegatheringstatechange = () => {
        log('iceGatheringState', peerConnection.iceGatheringState);
      };
    }

    async function attemptIceRestart() {
      if (iceRestartAttempts >= MAX_ICE_RESTARTS || callEnded || endingCall) {
        if (statusTitle) {
          statusTitle.textContent = 'Connection failed';
          if (statusSubtitle) statusSubtitle.textContent = 'Please end and rejoin the call.';
        }
        showReconnectButton();
        return;
      }
      iceRestartAttempts++;
      log(`ICE restart attempt ${iceRestartAttempts}/${MAX_ICE_RESTARTS}`);

      try {
        if (isInitiator && peerConnection) {
          // Restart ICE as initiator: create new offer with iceRestart flag
          const offer = await peerConnection.createOffer({ iceRestart: true });
          await peerConnection.setLocalDescription(offer);
          offerCreated = false; // allow re-sending
          answerHandled = false;
          offerHandled = false;
          await postSignal({
            type: 'offer',
            sdp: { type: peerConnection.localDescription.type, sdp: peerConnection.localDescription.sdp },
            ice_restart: true,
          });
          offerCreated = true;
          log('ICE restart offer sent');
        }
      } catch (e) {
        log('ICE restart failed', e);
      }
    }

    function showReconnectButton() {
      const existing = document.getElementById('reconnectBtn');
      if (existing) return;
      const placeholder = document.getElementById('remote-placeholder');
      if (!placeholder) return;
      const btn = document.createElement('button');
      btn.id = 'reconnectBtn';
      btn.type = 'button';
      btn.textContent = 'Rejoin Call';
      btn.className = 'mt-4 px-5 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700 transition';
      btn.onclick = () => { window.location.reload(); };
      placeholder.appendChild(btn);
    }

    function showTapToPlayBanner() {
      const existing = document.getElementById('tapToPlayBanner');
      if (existing) return;
      const container = document.getElementById('video-call-container');
      if (!container) return;
      const banner = document.createElement('div');
      banner.id = 'tapToPlayBanner';
      banner.className = 'absolute inset-x-0 bottom-28 flex justify-center z-40';
      banner.innerHTML = `
        <button type="button"
          class="px-5 py-2.5 bg-white/90 text-slate-800 rounded-2xl text-sm font-semibold shadow-xl flex items-center gap-2"
          onclick="document.getElementById('remote-video').play();this.closest('#tapToPlayBanner').remove()">
          <i class='fas fa-volume-up'></i> Tap to enable audio
        </button>`;
      container.appendChild(banner);
    }

    async function flushPendingIce() {
      if (!hasRemoteDescription() || pendingRemoteIce.length === 0) return;
      const batch = pendingRemoteIce.splice(0);
      for (const cand of batch) {
        try {
          await peerConnection.addIceCandidate(new RTCIceCandidate(cand));
          log('ICE candidate received (flushed from queue)');
        } catch (e) {
          log('ICE candidate add failed', e);
        }
      }
    }

    async function applyRemoteIceCandidates(candidates) {
      if (!Array.isArray(candidates) || candidates.length <= appliedRemoteIceCount) return;

      for (let i = appliedRemoteIceCount; i < candidates.length; i++) {
        const cand = candidates[i];
        if (!hasRemoteDescription()) {
          pendingRemoteIce.push(cand);
          continue;
        }
        try {
          await peerConnection.addIceCandidate(new RTCIceCandidate(cand));
          log('ICE candidate applied');
        } catch (e) {
          log('addIceCandidate error', e);
        }
      }
      appliedRemoteIceCount = candidates.length;
      await flushPendingIce();
    }

    async function createAndSendOffer() {
      if (!isInitiator || offerCreated || !peerConnection) return;
      if (peerConnection.signalingState !== 'stable') return;

      const offer = await peerConnection.createOffer();
      log('offer created');

      await peerConnection.setLocalDescription(offer);
      log('setLocalDescription(offer)');

      await postSignal({
        type: 'offer',
        sdp: { type: peerConnection.localDescription.type, sdp: peerConnection.localDescription.sdp },
      });
      offerCreated = true;
      log('offer sent');
    }

    async function handleRemoteOffer(offerSdp) {
      if (!offerSdp?.type || !offerSdp?.sdp || offerHandled) return;
      offerHandled = true;

      log('offer received');
      await peerConnection.setRemoteDescription(new RTCSessionDescription(offerSdp));
      log('remote description set (offer)');

      const answer = await peerConnection.createAnswer();
      await peerConnection.setLocalDescription(answer);
      log('setLocalDescription(answer)');

      await postSignal({
        type: 'answer',
        sdp: { type: peerConnection.localDescription.type, sdp: peerConnection.localDescription.sdp },
      });
      log('answer sent');

      await flushPendingIce();
    }

    async function handleRemoteAnswer(answerSdp) {
      if (!answerSdp?.type || !answerSdp?.sdp || answerHandled) return;
      answerHandled = true;

      log('answer received');
      await peerConnection.setRemoteDescription(new RTCSessionDescription(answerSdp));
      log('remote description set (answer)');

      await flushPendingIce();
    }

    async function pollSignaling() {
      if (pollInFlight || !peerConnection) return;
      pollInFlight = true;
      try {
        const res = await fetch(signalUrl, { credentials: 'same-origin', cache: 'no-store' });
        const data = await res.json();
        if (!data.success) return;

        if (data.call_ended) {
          if (!callEnded) {
            callEnded = true;
            await finishCallLocally('The other participant ended the consultation.', false);
          }
          return;
        }

        if (!data.both_joined) {
          setWaitingForPeer();
        } else if (!isConnected) {
          setNegotiating();
        }

        if (data.call_started_at && isConnected && !timerStarted) {
          startSyncedTimer(data.call_started_at);
        }
        updateTimer();

        if (isInitiator && data.both_joined && !offerCreated) {
          await createAndSendOffer();
        }

        if (!isInitiator && data.offer?.sdp && !offerHandled) {
          await handleRemoteOffer(data.offer);
        }

        if (isInitiator && data.answer?.sdp && !answerHandled) {
          await handleRemoteAnswer(data.answer);
        }

        if (data.ice?.length) {
          await applyRemoteIceCandidates(data.ice);
        }
      } catch (err) {
        log('poll error', err);
      } finally {
        pollInFlight = false;
      }
    }

    async function start() {
      log('joining room', roomId);
      const connOverlay = document.getElementById('connection-overlay');
      if (connOverlay) connOverlay.classList.remove('hidden');

      try {
        await verifyAndInitMedia();
        if (connOverlay) connOverlay.classList.add('hidden');
      } catch (e) {
        if (connOverlay) connOverlay.classList.add('hidden');
        log('media init failed', e);

        let msg = e.message || 'Camera and microphone are required for the consultation.';
        if (e.name === 'NotAllowedError' || e.name === 'PermissionDeniedError') {
          msg = 'Camera and microphone access was denied. Please allow permissions in your browser settings, then click Join again.';
        } else if (e.name === 'NotFoundError' || e.name === 'DevicesNotFoundError') {
          msg = 'No camera or microphone detected. Please connect a device and try again.';
        } else if (e.name === 'NotReadableError' || e.name === 'TrackStartError') {
          msg = 'Camera or microphone is in use by another app. Please close other apps and try again.';
        } else if (e.name === 'OverconstrainedError') {
          msg = 'Camera settings are not supported on this device. Please try a different browser.';
        }

        if (typeof showToast === 'function') {
          showToast('error', 'Media Access Required', msg);
        }
        if (typeof window.hideVideoCallOverlay === 'function') {
          window.hideVideoCallOverlay();
        }
        return;
      }

      createPeerConnection();
      setWaitingForPeer();

      timerInterval = setInterval(updateTimer, 1000);
      pollTimer = setInterval(() => pollSignaling(), 1000);
      await pollSignaling();
    }

    function cleanup() {
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
      if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
      try {
        peerConnection?.getSenders()?.forEach((sender) => {
          try { sender.track?.stop(); } catch (_) {}
        });
        peerConnection?.close();
      } catch (_) {}
      peerConnection = null;
      if (localStream) {
        localStream.getTracks().forEach((t) => { try { t.stop(); } catch (_) {} });
        localStream = null;
      }
      if (remoteStream) {
        remoteStream.getTracks().forEach((t) => { try { t.stop(); } catch (_) {} });
        remoteStream = null;
      }
      if (remoteVideo) remoteVideo.srcObject = null;
      if (localVideo) localVideo.srcObject = null;
      window.__smartTrackCallSession = null;
      window.__smartTrackActiveCall = false;
    }

    function showEndConfirmModal() {
      return new Promise((resolve) => {
        const modal = document.getElementById('endCallConfirmModal');
        const confirmBtn = document.getElementById('endCallConfirmBtn');
        const cancelBtn = document.getElementById('endCallCancelBtn');
        if (!modal || !confirmBtn || !cancelBtn) {
          if (typeof showConfirmModal === 'function') {
            showConfirmModal({
              title: 'End Consultation?',
              message: 'Are you sure you want to leave the consultation?',
              confirmText: 'End Call',
              variant: 'danger',
            }).then(resolve);
            return;
          }
          resolve(window.confirm('End this consultation?'));
          return;
        }

        modal.classList.remove('hidden');
        const close = (result) => {
          modal.classList.add('hidden');
          confirmBtn.onclick = null;
          cancelBtn.onclick = null;
          resolve(result);
        };
        confirmBtn.onclick = () => close(true);
        cancelBtn.onclick = () => close(false);
      });
    }

    async function finishCallLocally(successMessage, showSuccessToast) {
      cleanup();
      if (typeof window.hideVideoCallOverlay === 'function') {
        window.hideVideoCallOverlay();
      }
      if (showSuccessToast !== false && typeof showToast === 'function') {
        showToast('success', 'Consultation Ended', successMessage || 'Consultation ended successfully.');
      }
      setTimeout(() => {
        window.location.href = '/appointments/';
      }, showSuccessToast === false ? 300 : 1200);
    }

    async function endCallFlow() {
      if (endingCall || callEnded) return;
      const endBtn = document.getElementById('endCall');
      const endIcon = endBtn?.querySelector('i');

      const confirmed = await showEndConfirmModal();
      if (!confirmed) return;

      endingCall = true;
      callEnded = true;
      if (endBtn) {
        endBtn.disabled = true;
        endBtn.classList.add('opacity-60', 'cursor-not-allowed');
        if (endIcon) endIcon.className = 'fas fa-spinner fa-spin text-xl';
        endBtn.title = 'Ending consultation...';
      }

      cleanup();

      try {
        const res = await fetch(endCallUrl, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: JSON.stringify({}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) {
          throw new Error(data.error || 'Could not end call');
        }
        await finishCallLocally(
          data.message || `Consultation ended. Duration: ${data.duration || '—'}.`,
          true,
        );
      } catch (e) {
        log('end_call error', e);
        if (typeof showToast === 'function') {
          showToast('error', 'End Call Failed', e.message || 'Could not end the consultation.');
        }
        if (endBtn) {
          endBtn.disabled = false;
          endBtn.classList.remove('opacity-60', 'cursor-not-allowed');
          if (endIcon) endIcon.className = 'fas fa-phone-slash text-xl';
          endBtn.title = 'End call';
        }
        endingCall = false;
        callEnded = false;
      }
    }

    window.__smartTrackCallCleanup = cleanup;

    const endCallBtn = document.getElementById('endCall');
    if (endCallBtn) {
      endCallBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        endCallFlow();
      });
    } else {
      log('endCall button not found');
    }

    document.getElementById('toggleMic')?.addEventListener('click', function () {
      const track = localStream?.getAudioTracks()[0];
      if (!track) return;
      track.enabled = !track.enabled;
      const icon = this.querySelector('i');
      if (icon) {
        icon.className = track.enabled ? 'fas fa-microphone' : 'fas fa-microphone-slash';
      }
      this.classList.toggle('bg-red-500/30', !track.enabled);
      log('mic toggled', { enabled: track.enabled });
    });

    document.getElementById('toggleCam')?.addEventListener('click', function () {
      const track = localStream?.getVideoTracks()[0];
      if (!track) return;
      track.enabled = !track.enabled;
      const icon = this.querySelector('i');
      if (icon) {
        icon.className = track.enabled ? 'fas fa-video' : 'fas fa-video-slash';
      }
      this.classList.toggle('bg-red-500/30', !track.enabled);
      log('camera toggled', { enabled: track.enabled });
    });

    document.getElementById('toggleFullscreen')?.addEventListener('click', () => {
      const elem = document.getElementById('video-call-container');
      if (!document.fullscreenElement) elem?.requestFullscreen?.();
      else document.exitFullscreen?.();
    });

    start().catch((e) => log('start failed', e));
  }

  window.initSmartTrackConsultation = initConsultation;
})();
