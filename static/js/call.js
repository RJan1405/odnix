// Odnix P2P Audio/Video Calls via WebRTC + WebSocket signaling
(function () {
    console.log('[CallJS] Initializing...');
    if (!window.OdnixCallConfig) {
        console.error('[CallJS] Error: window.OdnixCallConfig is missing! Call functionality will not work.');
        return;
    }
    console.log('[CallJS] Config found:', window.OdnixCallConfig);
    const { chatId, userId, wsScheme, host, iceServers } = window.OdnixCallConfig;

    if (!chatId) {
        console.error('[CallJS] Error: chatId is missing from config!');
        return;
    }
    console.log(`[CallJS] Initialized for chat ${chatId}, user ${userId}`);

    // OdnixProto Client
    const proto = new OdnixProtoClient();
    let handshakeStep = 0; // 0: None, 1: Req Sent, 2: Key Established
    let handshakeResolvers = [];

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

    // Debug helper
    function getWebSocketState(state) {
        switch (state) {
            case WebSocket.CONNECTING: return 'CONNECTING';
            case WebSocket.OPEN: return 'OPEN';
            case WebSocket.CLOSING: return 'CLOSING';
            case WebSocket.CLOSED: return 'CLOSED';
            default: return `UNKNOWN (${state})`;
        }
    }

    function updateDebugStatus(status, color = '#666') {
        let el = document.getElementById('callDebugStatus');
        if (!el) {
            el = document.createElement('div');
            el.id = 'callDebugStatus';
            el.style.cssText = 'position:fixed;bottom:10px;right:10px;background:#fff;padding:4px 8px;border:1px solid #ccc;font-size:10px;z-index:9999;opacity:0.7;pointer-events:none;max-width:500px;max-height:200px;overflow:auto;';
            document.body.appendChild(el);
        }
        const timestamp = new Date().toISOString().substr(11, 12);
        const logLine = `[${timestamp}] ${status}`;
        el.innerHTML = logLine + '<br>' + el.innerHTML;
        console.log('[CallWS] ' + status);
    }

    function resolveHandshakeWaiters(err) {
        const resolvers = handshakeResolvers;
        handshakeResolvers = [];
        resolvers.forEach(fn => {
            try { fn(err); } catch (_) { }
        });
    }

    function waitForHandshakeReady(timeoutMs = 8000) {
        if (handshakeStep === 2) {
            updateDebugStatus('Handshake already complete, proceeding', 'green');
            return Promise.resolve();
        }
        return new Promise((resolve, reject) => {
            const resolver = (err) => {
                cleanup();
                if (err) {
                    updateDebugStatus('Handshake waiter error: ' + err.message, 'red');
                    return reject(err);
                }
                updateDebugStatus('Handshake ready for pending message', 'green');
                resolve();
            };
            const timer = setTimeout(() => {
                cleanup();
                const errMsg = `Handshake timeout after ${timeoutMs}ms. Current step: ${handshakeStep}`;
                updateDebugStatus(errMsg, 'red');
                reject(new Error(errMsg));
            }, timeoutMs);
            const cleanup = () => {
                clearTimeout(timer);
                handshakeResolvers = handshakeResolvers.filter(fn => fn !== resolver);
            };
            handshakeResolvers.push(resolver);
        });
    }

    const rtcConfig = {
        iceServers: Array.isArray(iceServers) && iceServers.length
            ? iceServers
            : [
                { urls: 'stun:stun.l.google.com:19302' },
                { urls: 'stun:stun1.l.google.com:19302' },
                { urls: 'stun:stun2.l.google.com:19302' }
            ]
    };

    // Ringtone / ringback via WebAudio
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
        if (ws) {
            const state = getWebSocketState(ws.readyState);
            updateDebugStatus(`WebSocket state: ${state}`, 'blue');

            if (ws.readyState === WebSocket.OPEN) {
                updateDebugStatus('Reusing existing WebSocket connection', 'green');
                return ws;
            }

            if (ws.readyState === WebSocket.CONNECTING) {
                updateDebugStatus('WebSocket connection in progress, waiting...', 'orange');
                return ws;
            }

            // If CLOSING or CLOSED, clean up and create new connection
            if (ws.readyState === WebSocket.CLOSING || ws.readyState === WebSocket.CLOSED) {
                updateDebugStatus(`WebSocket is ${state}, creating new connection`, 'orange');
                try { ws.close(); } catch (e) { }
                ws = null;
                handshakeStep = 0; // Reset handshake on new connection
                resolveHandshakeWaiters(new Error('WebSocket reconnecting'));
            }
        }

        const url = `${wsScheme}://${host}/ws/odnix/`;
        updateDebugStatus(`Connecting to ${url}...`, 'orange');

        try {
            ws = new WebSocket(url);
            handshakeStep = 0; // Reset handshake on new connection
            updateDebugStatus('WebSocket created, setting up event handlers', 'blue');

            ws.onopen = (event) => {
                updateDebugStatus('WebSocket connection established', 'green');
                updateDebugStatus('WS Open. Starting handshake...', 'orange');
                // Step 1: Request DH Params
                const handshakeMsg = {
                    type: 'req_dh_params',
                    nonce: Array.from(proto.clientNonce),
                    p: 0, q: 0, fingerprint: 0
                };
                updateDebugStatus('Sending req_dh_params', 'blue');
                try {
                    ws.send(JSON.stringify(handshakeMsg));
                    handshakeStep = 1;
                } catch (e) {
                    updateDebugStatus('Failed to send req_dh_params: ' + e.message, 'red');
                }
            };

            ws.onclose = (event) => {
                updateDebugStatus(`WebSocket closed - Code: ${event.code}, Reason: ${event.reason || 'unknown'}`, 'red');
                handshakeStep = 0;
                resolveHandshakeWaiters(new Error('WS closed: ' + event.reason));
                if (callActive) {
                    updateDebugStatus('Call was active, connection lost', 'red');
                    // Don't auto-teardown immediately, let user decide
                }
            };

            ws.onerror = (e) => {
                updateDebugStatus('WebSocket error: ' + (e.message || 'Unknown error'), 'red');
            };

            ws.onmessage = async (evt) => {
                let msg;
                try {
                    // Handshake Handling (plaintext JSON)
                    if (handshakeStep < 2) {
                        msg = JSON.parse(evt.data);
                        updateDebugStatus(`Received ${msg.type} (step ${handshakeStep})`, 'purple');
                    } else {
                        // Encrypted messages
                        const decrypted = proto.decrypt(evt.data);
                        if (!decrypted) {
                            console.warn('Failed to decrypt signaling message');
                            updateDebugStatus('Decryption failed', 'red');
                            return;
                        }
                        msg = decrypted;
                        updateDebugStatus(`Received encrypted ${msg.type}`, 'purple');
                    }
                } catch (e) {
                    console.error('Parse Error:', e);
                    updateDebugStatus('Parse error: ' + e.message, 'red');
                    return;
                }

                const type = msg.type;
                const payload = msg.payload || msg;

                if (type === 'error') {
                    const errMsg = msg.message || 'Unknown server error';
                    updateDebugStatus('❌ Server error: ' + errMsg, 'red');
                    resolveHandshakeWaiters(new Error(errMsg));
                    return;
                }

                if (type === 'res_dh_params') {
                    updateDebugStatus('Received res_dh_params ✓', 'orange');
                    const clientPublicHex = proto.generateClientDhParams();
                    const clientParams = {
                        type: 'set_client_dh_params',
                        nonce: msg.nonce,
                        server_nonce: msg.server_nonce,
                        gb: clientPublicHex
                    };
                    updateDebugStatus('Sending set_client_dh_params...', 'blue');
                    try {
                        ws.send(JSON.stringify(clientParams));
                    } catch (e) {
                        updateDebugStatus('Failed to send set_client_dh_params: ' + e.message, 'red');
                    }
                }
                else if (type === 'dh_gen_ok') {
                    updateDebugStatus('Received dh_gen_ok ✓, computing shared key...', 'green');
                    try {
                        proto.computeSharedKey(msg.ga);
                        proto.serverNonce = msg.server_nonce;
                        handshakeStep = 2;
                        updateDebugStatus('✓ Handshake complete! Encryption ready. 🔒', 'green');
                        resolveHandshakeWaiters();
                    } catch (e) {
                        const errMsg = 'Handshake error: ' + e.message;
                        updateDebugStatus(errMsg, 'red');
                        resolveHandshakeWaiters(e);
                    }
                }
                else if (handshakeStep === 2) {
                    // Encrypted Application Messages
                    if (type === 'webrtc.offer') {
                        updateDebugStatus('✓ Offer Received via WebSocket', 'green');
                        console.log('[CallJS] Received webrtc.offer via WebSocket');
                        await onOffer(payload.sdp ? payload : msg);
                    } else if (type === 'webrtc.answer') {
                        updateDebugStatus('✓ Answer Received via WebSocket', 'green');
                        console.log('[CallJS] Received webrtc.answer via WebSocket');
                        await onAnswer(payload.sdp ? payload : msg);
                    } else if (type === 'webrtc.ice') {
                        console.log('[CallJS] Received webrtc.ice via WebSocket');
                        await onRemoteIce(payload.candidate ? payload : msg);
                    } else if (type === 'webrtc.end') {
                        updateDebugStatus('Peer ended call', 'orange');
                        stopTone();
                        teardown('Peer ended call');
                    } else if (type === 'relay_data') {
                        console.log('Received Relay Data chunk', msg.seq);
                    } else {
                        console.log(`[CallJS] Received unknown encrypted message type: ${type}`);
                    }
                } else {
                    updateDebugStatus(`Unexpected message type '${type}' during handshake step ${handshakeStep}`, 'red');
                    console.warn(`[CallJS] Unexpected message during handshake: type=${type}, step=${handshakeStep}`);
                }
            };
            return ws;
        } catch (e) {
            updateDebugStatus('WebSocket creation failed: ' + e.message, 'red');
            console.error('WS Exception', e);
            return null;
        }
    }

    function send(type, payload) {
        // If using server relay, send via HTTP
        if (useServerRelay) {
            sendViaServerRelay(type, payload);
            return;
        }

        const sock = openWS();
        if (!sock) {
            updateDebugStatus('WebSocket unavailable, using server relay for ' + type, 'orange');
            useServerRelay = true;
            sendViaServerRelay(type, payload);
            if (!signalPollInterval) startSignalPolling();
            return;
        }
        updateDebugStatus('Sending ' + type, 'blue');

        const doSend = async () => {
            try {
                // Wait for handshake completion before sending
                await waitForHandshakeReady(8000);
                const msg = { type, ...payload };
                const encrypted = proto.encrypt(msg);
                sock.send(encrypted);
                updateDebugStatus('Sent ' + type + ' successfully via WebSocket', 'green');
            } catch (err) {
                console.warn('Handshake failed/timeout, using server relay for ' + type, err);
                updateDebugStatus('WebSocket failed, using server relay for ' + type, 'orange');
                useServerRelay = true;
                sendViaServerRelay(type, payload);
                if (!signalPollInterval) startSignalPolling();
            }
        };

        if (sock.readyState === WebSocket.OPEN) {
            doSend();
        } else if (sock.readyState === WebSocket.CONNECTING) {
            // WebSocket is still connecting, wait for open event
            const openHandler = () => {
                sock.removeEventListener('open', openHandler);
                doSend();
            };
            sock.addEventListener('open', openHandler);
        } else {
            updateDebugStatus('WebSocket not ready, using server relay for ' + type, 'orange');
            useServerRelay = true;
            sendViaServerRelay(type, payload);
            if (!signalPollInterval) startSignalPolling();
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

    // Server relay fallback
    let useServerRelay = false;
    let signalPollInterval = null;

    async function sendCallNotification(audioOnly) {
        // Send notification immediately via HTTP (works even if WebSocket fails)
        try {
            const response = await fetch('/api/call/notify/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: JSON.stringify({
                    chat_id: chatId,
                    audio_only: audioOnly
                })
            });
            const data = await response.json();
            if (data.success) {
                updateDebugStatus(`Call notification sent to ${data.notified} user(s)`, 'green');
            }
        } catch (e) {
            console.error('Failed to send call notification:', e);
            updateDebugStatus('Failed to send call notification: ' + e.message, 'orange');
        }
    }

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    async function sendViaServerRelay(type, payload) {
        // Fallback: Send signal via HTTP to database
        // Ensure type is prefixed with 'webrtc.' for call signals
        const signalType = type.startsWith('webrtc.') ? type : `webrtc.${type}`;
        try {
            const response = await fetch('/api/p2p/send-signal/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: JSON.stringify({
                    chat_id: chatId,
                    target_user_id: null, // Will be sent to all participants
                    signal_data: { type: signalType, ...payload }
                })
            });
            const data = await response.json();
            if (data.success) {
                updateDebugStatus(`Signal sent via server relay: ${signalType}`, 'blue');
            }
        } catch (e) {
            console.error('Failed to send signal via server relay:', e);
        }
    }

    function startSignalPolling() {
        // Poll for signals if WebSocket fails
        if (signalPollInterval) return;
        updateDebugStatus('Starting signal polling (server relay fallback)', 'orange');
        signalPollInterval = setInterval(async () => {
            try {
                if (!chatId) {
                    updateDebugStatus('Cannot poll: chatId not set', 'orange');
                    return;
                }
                const response = await fetch(`/api/p2p/${chatId}/signals/`);
                const data = await response.json();
                if (data.success && data.signals && data.signals.length > 0) {
                    updateDebugStatus(`Polling: Received ${data.signals.length} signals`, 'blue');
                    for (const signalInfo of data.signals) {
                        const signal = signalInfo.signal;
                        // Handle both 'webrtc.offer' and 'offer' for backward compatibility
                        const signalType = signal.type || '';

                        // Check if this is a call signal (has sdp/candidate but no fileInfo)
                        const isCallOffer = (signalType === 'webrtc.offer' || signalType === 'offer') &&
                            signal.sdp && !signal.fileInfo;
                        const isCallAnswer = (signalType === 'webrtc.answer' || signalType === 'answer') &&
                            signal.sdp && !signal.fileInfo;
                        const isCallIce = (signalType === 'webrtc.ice' || signalType === 'ice') &&
                            signal.candidate && !signal.fileInfo;

                        if (isCallOffer) {
                            // This is a call offer (has sdp, no fileInfo)
                            updateDebugStatus(`✓ Processing call offer from ${signalInfo.sender_name || 'unknown'}`, 'green');
                            // Ensure we pass the correct structure to onOffer
                            await onOffer({
                                sdp: signal.sdp,
                                type: signal.type || 'offer',
                                audioOnly: signal.audioOnly || false
                            });
                        } else if (isCallAnswer) {
                            // This is a call answer
                            updateDebugStatus(`✓ Processing call answer from ${signalInfo.sender_name || 'unknown'}`, 'green');
                            await onAnswer({
                                sdp: signal.sdp,
                                type: signal.type || 'answer'
                            });
                        } else if (isCallIce) {
                            // This is a call ICE candidate
                            await onRemoteIce({
                                candidate: signal.candidate
                            });
                        }
                        // Ignore file transfer signals (they have fileInfo)
                    }
                } else if (data.success) {
                    // No signals - this is normal, just silent
                } else {
                    updateDebugStatus(`Polling error: ${data.error || 'Unknown'}`, 'orange');
                }
            } catch (e) {
                console.error('Error polling signals:', e);
                updateDebugStatus('Error polling: ' + e.message, 'red');
            }
        }, 1500); // Poll every 1.5 seconds (faster than P2P handler)
    }

    function stopSignalPolling() {
        if (signalPollInterval) {
            clearInterval(signalPollInterval);
            signalPollInterval = null;
        }
    }

    async function startCall({ audioOnly = false } = {}) {
        try {
            audioOnlyMode = audioOnly;
            ensureUI();
            document.getElementById('callModeLabel').textContent = audioOnly ? '(Audio)' : '(Video)';
            document.getElementById('callModal').style.display = 'flex';
            isCaller = true;
            callActive = true;

            // Send notification immediately (before WebSocket handshake)
            await sendCallNotification(audioOnly);

            await getMedia({ audioOnly });
            openWS();
            await setupPeer();

            const offer = await pc.createOffer();
            await pc.setLocalDescription(offer);

            // Try to send via WebSocket, fallback to server relay
            try {
                send('webrtc.offer', { sdp: offer.sdp, type: offer.type, audioOnly });
                // If handshake fails, use server relay
                setTimeout(() => {
                    if (handshakeStep !== 2) {
                        updateDebugStatus('WebSocket handshake failed, using server relay', 'orange');
                        useServerRelay = true;
                        sendViaServerRelay('webrtc.offer', { sdp: offer.sdp, type: offer.type, audioOnly });
                        startSignalPolling();
                    }
                }, 10000); // Wait 10 seconds for handshake
            } catch (e) {
                // Immediately fallback to server relay
                updateDebugStatus('WebSocket send failed, using server relay', 'orange');
                useServerRelay = true;
                sendViaServerRelay('webrtc.offer', { sdp: offer.sdp, type: offer.type, audioOnly });
                startSignalPolling();
            }

            startTone('ringback');

            // Resend logic
            clearInterval(offerResendInterval);
            let resendCount = 0;
            offerResendInterval = setInterval(() => {
                if (!pc || !pc.localDescription) return;
                resendCount += 1;
                if (resendCount > 8) {
                    clearInterval(offerResendInterval);
                    offerResendInterval = null;
                    return;
                }
                send('webrtc.offer', { sdp: pc.localDescription.sdp, type: pc.localDescription.type, audioOnly });
            }, 2000);

        } catch (e) {
            console.error('Error starting call:', e);
            alert('Could not start call: ' + e.message);
            teardown('Setup failed');
        }
    }

    let pendingOffer = null;
    async function onOffer({ sdp, type, audioOnly }) {
        if (isCaller) return; // ignore if we are calling
        audioOnlyMode = !!audioOnly;
        ensureUI();
        openWS();

        // If active, ignore
        if (callActive) return;
        const callModal = document.getElementById('callModal');
        if (callModal && callModal.style.display === 'flex') return;

        // Cooldown
        if (Date.now() < suppressOffersUntil) return;

        // Dedupe
        try {
            const fp = String(sdp || '') + '|' + String(type || '');
            if (inboundPromptVisible) return;
            if (fp === lastOfferFingerprint) return;
            lastOfferFingerprint = fp;
        } catch (_) { }

        pendingOffer = { sdp, type };
        inboundPromptVisible = true;

        const incoming = document.getElementById('incomingCallModal');
        const incomingModeLabel = document.getElementById('incomingModeLabel');
        if (incoming && incomingModeLabel) {
            incomingModeLabel.textContent = audioOnlyMode ? 'Audio Call' : 'Video Call';
            incoming.style.display = 'flex';

            // Hide global banner
            const globalBanner = document.getElementById('globalCallBanner');
            if (globalBanner) globalBanner.style.display = 'none';

            startTone('ring');
            const acceptBtn = document.getElementById('acceptCallBtn');
            const declineBtn = document.getElementById('declineCallBtn');

            acceptBtn.onclick = async () => {
                incoming.style.display = 'none';
                stopTone();
                const globalBanner = document.getElementById('globalCallBanner');
                if (globalBanner) globalBanner.style.display = 'none';

                await getMedia({ audioOnly: audioOnlyMode });
                await setupPeer();
                document.getElementById('callModeLabel').textContent = audioOnlyMode ? '(Audio)' : '(Video)';
                document.getElementById('callModal').style.display = 'flex';
                callActive = true;
                inboundPromptVisible = false;

                // Start polling for signals in case WebSocket fails
                if (!signalPollInterval) startSignalPolling();

                await pc.setRemoteDescription(new RTCSessionDescription(pendingOffer));
                await flushIceQueue();
                const answer = await pc.createAnswer();
                await pc.setLocalDescription(answer);
                send('webrtc.answer', { sdp: answer.sdp, type: answer.type });
                pendingOffer = null;
            };

            declineBtn.onclick = () => {
                incoming.style.display = 'none';
                stopTone();
                const globalBanner = document.getElementById('globalCallBanner');
                if (globalBanner) globalBanner.style.display = 'none';

                inboundPromptVisible = false;
                pendingOffer = null;
                send('webrtc.end', {});
                suppressOffersUntil = Date.now() + 20000;
            };
        }
    }

    async function onAnswer({ sdp, type }) {
        if (!pc) return;
        await pc.setRemoteDescription(new RTCSessionDescription({ sdp, type }));
        await flushIceQueue();
        stopTone();
        if (offerResendInterval) { clearInterval(offerResendInterval); offerResendInterval = null; }
    }

    async function flushIceQueue() {
        if (!pc) return;
        while (remoteIceQueue.length > 0) {
            const cand = remoteIceQueue.shift();
            try { await pc.addIceCandidate(new RTCIceCandidate(cand)); } catch (_) { }
        }
    }

    async function onRemoteIce({ candidate }) {
        if (!candidate) return;
        if (!pc || !pc.remoteDescription) {
            remoteIceQueue.push(candidate);
            return;
        }
        try { await pc.addIceCandidate(new RTCIceCandidate(candidate)); } catch (_) { }
    }

    function endCall() {
        send('webrtc.end', {});
        teardown('Call ended');
    }

    function teardown(_reason) {
        const modal = document.getElementById('callModal');
        if (modal) modal.style.display = 'none';
        stopTone();
        stopSignalPolling();
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
        suppressOffersUntil = Date.now() + 5000;
        useServerRelay = false;
    }

    // Expose controls - IMPORTANT
    window.OdnixCall = {
        startAudioCall: () => startCall({ audioOnly: true }),
        startVideoCall: () => startCall({ audioOnly: false }),
        endCall,
    };

    // Connect immediately to receive calls
    try {
        console.log(`[CallJS] Connecting to WebSocket for chat ${chatId}`);
        openWS();
        // Also start polling for signals in case WebSocket fails
        console.log(`[CallJS] Starting signal polling for chat ${chatId}`);
        startSignalPolling();
        updateDebugStatus(`Initialized for chat ${chatId} - WebSocket + Polling active`, 'green');
    } catch (e) {
        console.error('[CallJS] Failed to initialize:', e);
        updateDebugStatus('Failed to initialize: ' + e.message, 'red');
    }

})();
