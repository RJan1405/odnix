// Odnix P2P Audio/Video Calls via WebRTC + WebSocket signaling
(function () {
    if (!window.OdnixCallConfig) return;
    const { chatId, userId, wsScheme, host, iceServers } = window.OdnixCallConfig;

    let pc = null;
    let localStream = null;
    let remoteStream = null;
    let ws = null;
    let isCaller = false;
    let audioOnlyMode = false;
    let offerResendInterval = null;
    let callActive = false; // tracks if a call UI/session is active
    let inboundPromptVisible = false; // prevents duplicate incoming prompts
    let lastOfferFingerprint = null; // dedupe repeated offers
    let suppressOffersUntil = 0; // ms timestamp to ignore offers temporarily
    let remoteIceQueue = []; // Queue for early arrival ICE candidates

    const rtcConfig = {
        iceServers: Array.isArray(iceServers) && iceServers.length
            ? iceServers
            : [
                { urls: 'stun:stun.l.google.com:19302' },
                { urls: 'stun:stun1.l.google.com:19302' },
                { urls: 'stun:stun2.l.google.com:19302' }
            ]
    };

    // Ringtone / ringback via WebAudio (avoids asset management)
    let audioCtx = null;
    let ringOsc = null;
    let ringGain = null;
    let ringTimer = null;
    function startTone(pattern = 'ring') {
        try {
            if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            ringOsc = audioCtx.createOscillator();
            ringGain = audioCtx.createGain();
            ringGain.gain.value = 0.0;
            ringOsc.connect(ringGain).connect(audioCtx.destination);
            ringOsc.type = 'sine';
            ringOsc.frequency.value = pattern === 'ringback' ? 440 : 880;
            ringOsc.start();
            // Pulse pattern
            ringTimer = setInterval(() => {
                if (!ringGain) return;
                ringGain.gain.value = ringGain.gain.value ? 0.0 : 0.08; // gentle volume
            }, 500);
        } catch (e) {
            // ignore autoplay restrictions
        }
    }
    function stopTone() {
        try {
            if (ringTimer) { clearInterval(ringTimer); ringTimer = null; }
            if (ringOsc) { ringOsc.stop(); ringOsc.disconnect(); ringOsc = null; }
            if (ringGain) { ringGain.disconnect(); ringGain = null; }
        } catch (e) { }
    }

    function ensureUI() {
        let modal = document.getElementById('callModal');
        if (modal) return;
        modal = document.createElement('div');
        modal.id = 'callModal';
        modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);display:none;z-index:10000;align-items:center;justify-content:center;';
        modal.innerHTML = `
      <div style="background:#111;color:#fff;border-radius:12px;max-width:900px;width:95%;padding:16px;">
        <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center;justify-content:space-between;">
          <div style="display:flex;gap:8px;align-items:center;font-weight:600;">Odnix Call <span id="callModeLabel" style="opacity:.7;font-weight:400;margin-left:6px;"></span></div>
          <div>
            <button id="endCallBtn" style="background:#ef4444;color:#fff;border:none;border-radius:8px;padding:8px 12px;cursor:pointer;">End</button>
          </div>
        </div>
        <div style="display:flex;gap:12px;margin-top:12px;flex-wrap:wrap;">
          <video id="remoteVideo" playsinline autoplay style="width:100%;max-height:60vh;background:#000;border-radius:8px;"></video>
          <video id="localVideo" playsinline autoplay muted style="position:absolute;right:32px;bottom:32px;width:220px;height:140px;background:#000;border-radius:8px;object-fit:cover;border:2px solid rgba(255,255,255,.2);"></video>
        </div>
      </div>`;
        document.body.appendChild(modal);
        document.getElementById('endCallBtn').onclick = endCall;

        // Incoming call prompt
        let incoming = document.getElementById('incomingCallModal');
        if (!incoming) {
            incoming = document.createElement('div');
            incoming.id = 'incomingCallModal';
            incoming.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);display:none;z-index:10001;align-items:center;justify-content:center;';
            incoming.innerHTML = `
                            <div style="background:#111;color:#fff;border-radius:12px;max-width:380px;width:92%;padding:16px;text-align:center;">
                                <div style="font-weight:600;margin-bottom:8px;">Incoming Call</div>
                                <div id="incomingModeLabel" style="opacity:.8;margin-bottom:16px;">Audio</div>
                                <div style="display:flex;gap:12px;justify-content:center;">
                                    <button id="acceptCallBtn" style="background:#10b981;color:#fff;border:none;border-radius:8px;padding:10px 16px;cursor:pointer;">Accept</button>
                                    <button id="declineCallBtn" style="background:#ef4444;color:#fff;border:none;border-radius:8px;padding:10px 16px;cursor:pointer;">Decline</button>
                                </div>
                            </div>`;
            document.body.appendChild(incoming);
        }
    }

    function openWS() {
        if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return ws;
        const url = `${wsScheme}://${host}/ws/call/${chatId}/`;
        ws = new WebSocket(url);
        ws.onmessage = async (evt) => {
            const msg = JSON.parse(evt.data);
            const type = msg.type;
            const payload = msg.payload || {};
            if (type === 'webrtc.offer') {
                await onOffer(payload);
            } else if (type === 'webrtc.answer') {
                await onAnswer(payload);
            } else if (type === 'webrtc.ice') {
                await onRemoteIce(payload);
            } else if (type === 'webrtc.end') {
                stopTone();
                teardown('Peer ended call');
            }
        };
        ws.onclose = () => {
            // try to reconnect after short delay
            setTimeout(() => {
                try { openWS(); } catch (e) { }
            }, 2000);
        };
        return ws;
    }

    function send(type, payload) {
        const sock = openWS();
        if (sock.readyState === WebSocket.OPEN) {
            sock.send(JSON.stringify({ type, payload }));
        } else {
            sock.addEventListener('open', () => sock.send(JSON.stringify({ type, payload })), { once: true });
        }
    }

    async function setupPeer() {
        pc = new RTCPeerConnection(rtcConfig);
        remoteStream = new MediaStream();
        pc.onicecandidate = (e) => {
            if (e.candidate) send('webrtc.ice', { candidate: e.candidate });
        };
        pc.ontrack = (e) => {
            e.streams[0].getTracks().forEach(t => remoteStream.addTrack(t));
            const remoteVideo = document.getElementById('remoteVideo');
            if (remoteVideo) remoteVideo.srcObject = remoteStream;
        };
        pc.onconnectionstatechange = () => {
            if (pc.connectionState === 'disconnected' || pc.connectionState === 'failed' || pc.connectionState === 'closed') {
                teardown('Connection closed');
            }
        };
        if (localStream) {
            localStream.getTracks().forEach(t => pc.addTrack(t, localStream));
        }
    }

    async function getMedia({ audioOnly }) {
        const constraints = audioOnly ? { audio: true, video: false } : { audio: true, video: { width: { ideal: 1280 }, height: { ideal: 720 } } };
        localStream = await navigator.mediaDevices.getUserMedia(constraints);
        const localVideo = document.getElementById('localVideo');
        if (localVideo) {
            localVideo.style.display = audioOnly ? 'none' : 'block';
            localVideo.srcObject = localStream;
        }
    }

    async function startCall({ audioOnly = false } = {}) {
        audioOnlyMode = audioOnly;
        ensureUI();
        document.getElementById('callModeLabel').textContent = audioOnly ? '(Audio)' : '(Video)';
        document.getElementById('callModal').style.display = 'flex';
        isCaller = true;
        callActive = true;

        await getMedia({ audioOnly });
        openWS();
        await setupPeer();

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        send('webrtc.offer', { sdp: offer.sdp, type: offer.type, audioOnly });
        // ringback until answered/ended
        startTone('ringback');
        // Periodically re-send offer so late-joiners receive it
        clearInterval(offerResendInterval);
        let resendCount = 0;
        offerResendInterval = setInterval(() => {
            if (!pc || !pc.localDescription) return;
            resendCount += 1;
            if (resendCount > 8) { // ~16s at 2s interval
                clearInterval(offerResendInterval);
                offerResendInterval = null;
                return;
            }
            send('webrtc.offer', { sdp: pc.localDescription.sdp, type: pc.localDescription.type, audioOnly });
        }, 2000);
    }

    let pendingOffer = null;
    async function onOffer({ sdp, type, audioOnly }) {
        // FIXED: Ignore offers if we initiated the call
        if (isCaller) return;

        audioOnlyMode = !!audioOnly;
        ensureUI();
        // isCaller = false; 
        openWS();

        // If a call is already active, ignore further offers
        const callModal = document.getElementById('callModal');
        if (callModal && callModal.style.display === 'flex') {
            return;
        }

        // Also check boolean flag just in case DOM is slow
        if (callActive) return;

        // Cooldown: ignore offers for a while after decline/end
        if (Date.now() < suppressOffersUntil) {
            return;
        }

        // Deduplicate identical offers that may be resent for late-join handling
        try {
            const fp = String(sdp || '') + '|' + String(type || '');
            if (inboundPromptVisible) {
                return; // already showing a prompt; ignore subsequent offers
            }
            if (fp === lastOfferFingerprint) {
                return; // identical resent offer
            }
            lastOfferFingerprint = fp;
        } catch (_) { }

        // show incoming modal and ringtone; wait for user action
        pendingOffer = { sdp, type };
        inboundPromptVisible = true; // FIXED: Mark prompt as visible immediately

        const incoming = document.getElementById('incomingCallModal');
        const incomingModeLabel = document.getElementById('incomingModeLabel');
        if (incoming && incomingModeLabel) {
            incomingModeLabel.textContent = audioOnlyMode ? 'Audio Call' : 'Video Call';
            incoming.style.display = 'flex';

            // FIXED: Hide global banner if it exists to avoid double notification
            const globalBanner = document.getElementById('globalCallBanner');
            if (globalBanner) globalBanner.style.display = 'none';

            startTone('ring');
            const acceptBtn = document.getElementById('acceptCallBtn');
            const declineBtn = document.getElementById('declineCallBtn');
            acceptBtn.onclick = async () => {
                incoming.style.display = 'none';
                stopTone();
                // Ensure global banner is hidden
                const globalBanner = document.getElementById('globalCallBanner');
                if (globalBanner) globalBanner.style.display = 'none';

                // inboundPromptVisible will remain true until call is fully set up
                // to prevent race conditions during getMedia()

                await getMedia({ audioOnly: audioOnlyMode });
                await setupPeer();
                document.getElementById('callModeLabel').textContent = audioOnlyMode ? '(Audio)' : '(Video)';
                document.getElementById('callModal').style.display = 'flex';
                callActive = true;
                inboundPromptVisible = false; // FIXED: Only clear this AFTER call is active

                await pc.setRemoteDescription(new RTCSessionDescription(pendingOffer));
                // Process any queued ICE candidates now that remote description is set
                await flushIceQueue();
                const answer = await pc.createAnswer();
                await pc.setLocalDescription(answer);
                send('webrtc.answer', { sdp: answer.sdp, type: answer.type });
                pendingOffer = null;
            };
            declineBtn.onclick = () => {
                incoming.style.display = 'none';
                stopTone();
                // Ensure global banner is hidden
                const globalBanner = document.getElementById('globalCallBanner');
                if (globalBanner) globalBanner.style.display = 'none';

                inboundPromptVisible = false;
                pendingOffer = null;
                send('webrtc.end', {});
                suppressOffersUntil = Date.now() + 20000; // 20s cooldown to avoid repeated prompts
            };
        }
    }

    async function onAnswer({ sdp, type }) {
        if (!pc) return;
        await pc.setRemoteDescription(new RTCSessionDescription({ sdp, type }));
        // Process any queued ICE candidates now that handshake is complete
        await flushIceQueue();
        // stop ringback once answered
        stopTone();
        if (offerResendInterval) { clearInterval(offerResendInterval); offerResendInterval = null; }
    }

    async function flushIceQueue() {
        if (!pc) return;
        while (remoteIceQueue.length > 0) {
            const cand = remoteIceQueue.shift();
            try {
                await pc.addIceCandidate(new RTCIceCandidate(cand));
            } catch (e) {
                console.warn('Queued ICE add failed', e);
            }
        }
    }

    async function onRemoteIce({ candidate }) {
        if (!candidate) return;
        // If PC not ready or remote description not set, queue the candidate
        if (!pc || !pc.remoteDescription) {
            remoteIceQueue.push(candidate);
            return;
        }
        try { await pc.addIceCandidate(new RTCIceCandidate(candidate)); } catch (e) { console.warn('ICE add failed', e); }
    }

    function endCall() {
        send('webrtc.end', {});
        teardown('Call ended');
    }

    function teardown(_reason) {
        const modal = document.getElementById('callModal');
        if (modal) modal.style.display = 'none';
        stopTone();
        if (offerResendInterval) { clearInterval(offerResendInterval); offerResendInterval = null; }
        if (pc) { pc.ontrack = null; pc.onicecandidate = null; try { pc.close(); } catch (_) { } pc = null; }
        if (localStream) { localStream.getTracks().forEach(t => t.stop()); localStream = null; }
        const rv = document.getElementById('remoteVideo');
        if (rv) rv.srcObject = null;
        const lv = document.getElementById('localVideo');
        if (lv) lv.srcObject = null;
        callActive = false;
        inboundPromptVisible = false;
        pendingOffer = null;
        lastOfferFingerprint = null;
        remoteIceQueue = [];
        suppressOffersUntil = Date.now() + 5000; // brief suppression after teardown
    }

    // Expose controls
    window.OdnixCall = {
        startAudioCall: () => startCall({ audioOnly: true }),
        startVideoCall: () => startCall({ audioOnly: false }),
        endCall,
    };

    // Open signaling socket immediately so we can receive incoming calls
    try { openWS(); } catch (e) { /* will retry on use */ }
})();
