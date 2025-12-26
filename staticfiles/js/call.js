// Odnix P2P Audio/Video Calls via WebRTC + WebSocket signaling with Server Fallback
(function () {
    console.log('[CallJS] Initializing...');
    
    // Configuration validation
    if (!window.OdnixCallConfig) {
        console.error('[CallJS] Error: window.OdnixCallConfig is missing! Call functionality will not work.');
        return;
    }
    
    const { chatId, userId, wsScheme, host, iceServers } = window.OdnixCallConfig;
    
    if (!chatId) {
        console.error('[CallJS] Error: chatId is missing from config!');
        return;
    }
    
    console.log(`[CallJS] Initialized for chat ${chatId}, user ${userId}`);

    // ========== State Management ==========
    let pc = null;                           // RTCPeerConnection
    let localStream = null;                  // Local media stream
    let remoteStream = null;                 // Remote media stream
    let ws = null;                          // WebSocket connection
    let isCaller = false;                   // Are we initiating the call?
    let audioOnlyMode = false;              // Audio-only mode
    let callActive = false;                 // Is call UI active?
    let inboundPromptVisible = false;       // Incoming call prompt shown?
    let pendingOffer = null;                // Pending offer to accept
    let remoteIceQueue = [];                // Queue for early ICE candidates
    let useServerRelay = false;             // Use HTTP polling fallback?
    let signalPollInterval = null;          // Polling interval ID
    let offerResendInterval = null;         // Offer resend interval
    let lastOfferFingerprint = null;        // Dedupe offers
    let suppressOffersUntil = 0;            // Timestamp to suppress offers
    let iceGatheringComplete = false;       // ICE gathering state
    let connectionAttempts = 0;             // Track connection attempts
    const MAX_RECONNECT_ATTEMPTS = 3;

    // ========== Encryption & Security ==========
    const proto = new OdnixProtoClient();
    let handshakeStep = 0;                  // 0: None, 1: Req Sent, 2: Key Established
    let handshakeResolvers = [];            // Promise resolvers waiting for handshake

    // ========== ICE/STUN/TURN Configuration ==========
    const rtcConfig = {
        iceServers: Array.isArray(iceServers) && iceServers.length
            ? iceServers
            : [
                { urls: 'stun:stun.l.google.com:19302' },
                { urls: 'stun:stun1.l.google.com:19302' },
                { urls: 'stun:stun2.l.google.com:19302' },
                { urls: 'stun:stun3.l.google.com:19302' },
                { urls: 'stun:stun4.l.google.com:19302' }
            ],
        iceCandidatePoolSize: 10,
        iceTransportPolicy: 'all',  // Try all available paths (STUN/TURN/host)
        bundlePolicy: 'max-bundle',
        rtcpMuxPolicy: 'require'
    };

    // ========== Utility Functions ==========
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

    // ========== Audio Tones (Ring/Ringback) ==========
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
            ringTimer = setInterval(() => {
                if (!ringGain) return;
                ringGain.gain.value = ringGain.gain.value ? 0.0 : 0.08;
            }, 500);
        } catch (e) {
            // Ignore autoplay restrictions
        }
    }

    function stopTone() {
        try {
            if (ringTimer) { clearInterval(ringTimer); ringTimer = null; }
            if (ringOsc) { ringOsc.stop(); ringOsc.disconnect(); ringOsc = null; }
            if (ringGain) { ringGain.disconnect(); ringGain = null; }
        } catch (e) { }
    }

    // ========== UI Management ==========
    function ensureUI() {
        let modal = document.getElementById('callModal');
        if (modal) return;
        
        // Call modal
        modal = document.createElement('div');
        modal.id = 'callModal';
        modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);display:none;z-index:10000;align-items:center;justify-content:center;';
        modal.innerHTML = `
            <div style="background:#111;color:#fff;border-radius:12px;max-width:900px;width:95%;padding:16px;">
                <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center;justify-content:space-between;">
                    <div style="display:flex;gap:8px;align-items:center;font-weight:600;">
                        Odnix Call <span id="callModeLabel" style="opacity:.7;font-weight:400;margin-left:6px;"></span>
                    </div>
                    <div id="callStatusIndicator" style="opacity:0.7;font-size:12px;"></div>
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

    function updateCallStatus(status) {
        const indicator = document.getElementById('callStatusIndicator');
        if (indicator) indicator.textContent = status;
        updateDebugStatus(status);
    }

    // ========== WebSocket Management ==========
    function resolveHandshakeWaiters(err) {
        const resolvers = handshakeResolvers;
        handshakeResolvers = [];
        resolvers.forEach(fn => {
            try { fn(err); } catch (_) { }
        });
    }

    function waitForHandshakeReady(timeoutMs = 8000) {
        if (handshakeStep === 2) {
            return Promise.resolve();
        }
        return new Promise((resolve, reject) => {
            const resolver = (err) => {
                cleanup();
                if (err) return reject(err);
                resolve();
            };
            const timer = setTimeout(() => {
                cleanup();
                reject(new Error(`Handshake timeout after ${timeoutMs}ms`));
            }, timeoutMs);
            const cleanup = () => {
                clearTimeout(timer);
                handshakeResolvers = handshakeResolvers.filter(fn => fn !== resolver);
            };
            handshakeResolvers.push(resolver);
        });
    }

    function openWS() {
        if (ws) {
            if (ws.readyState === WebSocket.OPEN) {
                return ws;
            }
            if (ws.readyState === WebSocket.CONNECTING) {
                return ws;
            }
            try { ws.close(); } catch (e) { }
            ws = null;
            handshakeStep = 0;
            resolveHandshakeWaiters(new Error('WebSocket reconnecting'));
        }

        const url = `${wsScheme}://${host}/ws/call/${chatId}/`;
        updateDebugStatus(`Connecting to ${url}...`);

        try {
            ws = new WebSocket(url);
            handshakeStep = 0;

            ws.onopen = () => {
                updateDebugStatus('WebSocket connected, starting handshake');
                const handshakeMsg = {
                    type: 'req_dh_params',
                    nonce: Array.from(proto.clientNonce),
                    p: 0, q: 0, fingerprint: 0
                };
                try {
                    ws.send(JSON.stringify(handshakeMsg));
                    handshakeStep = 1;
                } catch (e) {
                    updateDebugStatus('Failed to send handshake: ' + e.message);
                    enableServerRelay();
                }
            };

            ws.onclose = (event) => {
                updateDebugStatus(`WebSocket closed (code: ${event.code})`);
                handshakeStep = 0;
                resolveHandshakeWaiters(new Error('WS closed'));
                
                // Enable server relay fallback
                if (callActive && !useServerRelay) {
                    updateDebugStatus('Call active, switching to server relay');
                    enableServerRelay();
                }
            };

            ws.onerror = (e) => {
                updateDebugStatus('WebSocket error');
                enableServerRelay();
            };

            ws.onmessage = async (evt) => {
                try {
                    let msg;
                    
                    // Handshake messages are plain JSON
                    if (handshakeStep < 2) {
                        msg = JSON.parse(evt.data);
                        await handleHandshakeMessage(msg);
                    } else {
                        // Encrypted signaling messages
                        const decrypted = proto.decrypt(evt.data);
                        if (!decrypted) {
                            console.warn('Failed to decrypt message');
                            return;
                        }
                        msg = decrypted;
                        await handleSignalMessage(msg);
                    }
                } catch (e) {
                    console.error('Message handling error:', e);
                }
            };

            return ws;
        } catch (e) {
            updateDebugStatus('WebSocket creation failed: ' + e.message);
            enableServerRelay();
            return null;
        }
    }

    async function handleHandshakeMessage(msg) {
        const type = msg.type;

        if (type === 'error') {
            updateDebugStatus('Server error: ' + (msg.message || 'Unknown'));
            resolveHandshakeWaiters(new Error(msg.message || 'Server error'));
            enableServerRelay();
            return;
        }

        if (type === 'res_dh_params') {
            updateDebugStatus('Received DH params');
            const clientPublicHex = proto.generateClientDhParams();
            const clientParams = {
                type: 'set_client_dh_params',
                nonce: msg.nonce,
                server_nonce: msg.server_nonce,
                gb: clientPublicHex
            };
            try {
                ws.send(JSON.stringify(clientParams));
            } catch (e) {
                updateDebugStatus('Failed to send client params: ' + e.message);
                enableServerRelay();
            }
        } else if (type === 'dh_gen_ok') {
            updateDebugStatus('Handshake complete, encryption enabled');
            try {
                proto.computeSharedKey(msg.ga);
                proto.serverNonce = msg.server_nonce;
                handshakeStep = 2;
                resolveHandshakeWaiters();
            } catch (e) {
                updateDebugStatus('Handshake error: ' + e.message);
                resolveHandshakeWaiters(e);
                enableServerRelay();
            }
        }
    }

    async function handleSignalMessage(msg) {
        const type = msg.type;
        const payload = msg.payload || msg;

        updateDebugStatus(`Received ${type} via WebSocket`);

        if (type === 'webrtc.offer') {
            await onOffer(payload.sdp ? payload : msg);
        } else if (type === 'webrtc.answer') {
            await onAnswer(payload.sdp ? payload : msg);
        } else if (type === 'webrtc.ice') {
            await onRemoteIce(payload.candidate ? payload : msg);
        } else if (type === 'webrtc.end') {
            updateDebugStatus('Peer ended call');
            stopTone();
            teardown('Peer ended call');
        }
    }

    // ========== Server Relay Fallback ==========
    function enableServerRelay() {
        if (useServerRelay) return; // Already enabled
        
        updateDebugStatus('Enabling server relay fallback');
        useServerRelay = true;
        
        if (!signalPollInterval) {
            startSignalPolling();
        }
    }

    async function sendViaServerRelay(type, payload) {
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
                    target_user_id: null,
                    signal_data: { type: signalType, ...payload }
                })
            });
            
            const data = await response.json();
            if (data.success) {
                updateDebugStatus(`Signal sent via server: ${signalType}`);
            } else {
                updateDebugStatus(`Server relay error: ${data.error || 'Unknown'}`);
            }
        } catch (e) {
            console.error('Server relay failed:', e);
            updateDebugStatus('Server relay failed: ' + e.message);
        }
    }

    function startSignalPolling() {
        if (signalPollInterval) return;
        
        updateDebugStatus('Starting signal polling');
        signalPollInterval = setInterval(async () => {
            try {
                const response = await fetch(`/api/p2p/${chatId}/signals/`);
                const data = await response.json();
                
                if (data.success && data.signals && data.signals.length > 0) {
                    for (const signalInfo of data.signals) {
                        const signal = signalInfo.signal;
                        const signalType = signal.type || '';
                        
                        // Only process call signals (not file transfer)
                        const isCallSignal = !signal.fileInfo;
                        
                        if (!isCallSignal) continue;
                        
                        if ((signalType === 'webrtc.offer' || signalType === 'offer') && signal.sdp) {
                            await onOffer({
                                sdp: signal.sdp,
                                type: signal.type || 'offer',
                                audioOnly: signal.audioOnly || false
                            });
                        } else if ((signalType === 'webrtc.answer' || signalType === 'answer') && signal.sdp) {
                            await onAnswer({
                                sdp: signal.sdp,
                                type: signal.type || 'answer'
                            });
                        } else if ((signalType === 'webrtc.ice' || signalType === 'ice') && signal.candidate) {
                            await onRemoteIce({
                                candidate: signal.candidate
                            });
                        }
                    }
                }
            } catch (e) {
                console.error('Polling error:', e);
            }
        }, 1500);
    }

    function stopSignalPolling() {
        if (signalPollInterval) {
            clearInterval(signalPollInterval);
            signalPollInterval = null;
        }
    }

    // ========== Signaling Send Function ==========
    function send(type, payload) {
        // Try WebSocket first if available
        if (!useServerRelay && ws && ws.readyState === WebSocket.OPEN && handshakeStep === 2) {
            try {
                const msg = { type, ...payload };
                const encrypted = proto.encrypt(msg);
                ws.send(encrypted);
                updateDebugStatus(`Sent ${type} via WebSocket`);
                return;
            } catch (e) {
                updateDebugStatus(`WebSocket send failed for ${type}, using server relay`);
                enableServerRelay();
            }
        }
        
        // Fallback to server relay
        sendViaServerRelay(type, payload);
    }

    // ========== WebRTC Peer Connection ==========
    async function setupPeer() {
        pc = new RTCPeerConnection(rtcConfig);
        remoteStream = new MediaStream();
        iceGatheringComplete = false;

        // ICE candidate handling
        pc.onicecandidate = (e) => {
            if (e.candidate) {
                updateDebugStatus('Sending ICE candidate');
                send('webrtc.ice', { candidate: e.candidate });
            } else {
                iceGatheringComplete = true;
                updateDebugStatus('ICE gathering complete');
            }
        };

        // ICE connection state monitoring
        pc.oniceconnectionstatechange = () => {
            updateCallStatus(`ICE: ${pc.iceConnectionState}`);
            
            if (pc.iceConnectionState === 'connected' || pc.iceConnectionState === 'completed') {
                updateDebugStatus('✓ P2P connection established!');
                connectionAttempts = 0;
            } else if (pc.iceConnectionState === 'failed') {
                updateDebugStatus('ICE connection failed, attempting restart');
                handleConnectionFailure();
            } else if (pc.iceConnectionState === 'disconnected') {
                updateDebugStatus('ICE disconnected, monitoring...');
                // Give it a moment to reconnect
                setTimeout(() => {
                    if (pc && pc.iceConnectionState === 'disconnected') {
                        handleConnectionFailure();
                    }
                }, 3000);
            }
        };

        // Connection state monitoring
        pc.onconnectionstatechange = () => {
            updateCallStatus(`Connection: ${pc.connectionState}`);
            
            if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
                handleConnectionFailure();
            }
        };

        // Remote track handling
        pc.ontrack = (e) => {
            updateDebugStatus('Received remote track');
            e.streams[0].getTracks().forEach(t => {
                if (!remoteStream.getTrackById(t.id)) {
                    remoteStream.addTrack(t);
                }
            });
            const remoteVideo = document.getElementById('remoteVideo');
            if (remoteVideo && remoteVideo.srcObject !== remoteStream) {
                remoteVideo.srcObject = remoteStream;
            }
        };

        // Add local tracks
        if (localStream) {
            localStream.getTracks().forEach(t => {
                pc.addTrack(t, localStream);
            });
        }

        updateDebugStatus('Peer connection setup complete');
    }

    async function handleConnectionFailure() {
        if (!pc || !callActive) return;
        
        connectionAttempts++;
        updateDebugStatus(`Connection failure (attempt ${connectionAttempts}/${MAX_RECONNECT_ATTEMPTS})`);
        
        if (connectionAttempts >= MAX_RECONNECT_ATTEMPTS) {
            updateDebugStatus('Max reconnection attempts reached');
            alert('Connection failed. Please try calling again.');
            teardown('Connection failed');
            return;
        }
        
        // Try ICE restart
        try {
            if (isCaller) {
                const offer = await pc.createOffer({ iceRestart: true });
                await pc.setLocalDescription(offer);
                send('webrtc.offer', { sdp: offer.sdp, type: offer.type, audioOnly: audioOnlyMode });
                updateDebugStatus('Sent ICE restart offer');
            }
        } catch (e) {
            updateDebugStatus('ICE restart failed: ' + e.message);
        }
    }

    // ========== Media Handling ==========
    async function getMedia({ audioOnly }) {
        const constraints = audioOnly 
            ? { audio: { echoCancellation: true, noiseSuppression: true }, video: false }
            : { 
                audio: { echoCancellation: true, noiseSuppression: true }, 
                video: { width: { ideal: 1280 }, height: { ideal: 720 } } 
            };
        
        try {
            localStream = await navigator.mediaDevices.getUserMedia(constraints);
            const localVideo = document.getElementById('localVideo');
            if (localVideo) {
                localVideo.style.display = audioOnly ? 'none' : 'block';
                localVideo.srcObject = localStream;
            }
            updateDebugStatus('Media acquired');
        } catch (e) {
            console.error('Media error:', e);
            alert('Could not access camera/microphone: ' + e.message);
            throw e;
        }
    }

    // ========== Call Notification ==========
    async function sendCallNotification(audioOnly) {
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
                updateDebugStatus(`Call notification sent to ${data.notified} user(s)`);
            }
        } catch (e) {
            console.error('Notification failed:', e);
        }
    }

    // ========== Call Control Functions ==========
    async function startCall({ audioOnly = false } = {}) {
        try {
            audioOnlyMode = audioOnly;
            ensureUI();
            
            document.getElementById('callModeLabel').textContent = audioOnly ? '(Audio)' : '(Video)';
            document.getElementById('callModal').style.display = 'flex';
            
            isCaller = true;
            callActive = true;
            connectionAttempts = 0;

            // Send notification
            await sendCallNotification(audioOnly);

            // Get media
            await getMedia({ audioOnly });
            
            // Open WebSocket (with automatic server relay fallback)
            openWS();
            
            // If WebSocket fails quickly, enable server relay
            setTimeout(() => {
                if (handshakeStep !== 2) {
                    enableServerRelay();
                }
            }, 3000);
            
            // Setup peer connection
            await setupPeer();

            // Create and send offer
            const offer = await pc.createOffer();
            await pc.setLocalDescription(offer);
            
            send('webrtc.offer', { sdp: offer.sdp, type: offer.type, audioOnly });
            
            startTone('ringback');

            // Resend offer periodically
            clearInterval(offerResendInterval);
            let resendCount = 0;
            offerResendInterval = setInterval(() => {
                if (!pc || !pc.localDescription || !callActive) {
                    clearInterval(offerResendInterval);
                    return;
                }
                resendCount++;
                if (resendCount > 6) {
                    clearInterval(offerResendInterval);
                    return;
                }
                send('webrtc.offer', { 
                    sdp: pc.localDescription.sdp, 
                    type: pc.localDescription.type, 
                    audioOnly 
                });
            }, 2000);

        } catch (e) {
            console.error('Error starting call:', e);
            alert('Could not start call: ' + e.message);
            teardown('Setup failed');
        }
    }

    async function onOffer({ sdp, type, audioOnly }) {
        // Ignore if we're the caller
        if (isCaller) return;
        
        // Ignore if call already active
        if (callActive) return;
        
        // Cooldown check
        if (Date.now() < suppressOffersUntil) return;
        
        // Dedupe check
        const fp = String(sdp || '') + '|' + String(type || '');
        if (inboundPromptVisible || fp === lastOfferFingerprint) return;
        lastOfferFingerprint = fp;
        
        audioOnlyMode = !!audioOnly;
        pendingOffer = { sdp, type };
        inboundPromptVisible = true;

        ensureUI();
        openWS();
        
        // If WebSocket fails, ensure polling is active
        setTimeout(() => {
            if (handshakeStep !== 2) {
                enableServerRelay();
            }
        }, 2000);

        const incoming = document.getElementById('incomingCallModal');
        const incomingModeLabel = document.getElementById('incomingModeLabel');
        
        if (incoming && incomingModeLabel) {
            incomingModeLabel.textContent = audioOnlyMode ? 'Audio Call' : 'Video Call';
            incoming.style.display = 'flex';

            // Hide global banner if exists
            const globalBanner = document.getElementById('globalCallBanner');
            if (globalBanner) globalBanner.style.display = 'none';

            startTone('ring');

            document.getElementById('acceptCallBtn').onclick = async () => {
                incoming.style.display = 'none';
                stopTone();
                if (globalBanner) globalBanner.style.display = 'none';

                try {
                    await getMedia({ audioOnly: audioOnlyMode });
                    await setupPeer();
                    
                    document.getElementById('callModeLabel').textContent = audioOnlyMode ? '(Audio)' : '(Video)';
                    document.getElementById('callModal').style.display = 'flex';
                    
                    callActive = true;
                    inboundPromptVisible = false;

                    await pc.setRemoteDescription(new RTCSessionDescription(pendingOffer));
                    await flushIceQueue();
                    
                    const answer = await pc.createAnswer();
                    await pc.setLocalDescription(answer);
                    
                    send('webrtc.answer', { sdp: answer.sdp, type: answer.type });
                    
                    pendingOffer = null;
                } catch (e) {
                    console.error('Error accepting call:', e);
                    alert('Could not accept call: ' + e.message);
                    teardown('Accept failed');
                }
            };

            document.getElementById('declineCallBtn').onclick = () => {
                incoming.style.display = 'none';
                stopTone();
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
        
        try {
            await pc.setRemoteDescription(new RTCSessionDescription({ sdp, type }));
            await flushIceQueue();
            stopTone();
            
            if (offerResendInterval) {
                clearInterval(offerResendInterval);
                offerResendInterval = null;
            }
            
            updateDebugStatus('Answer processed, awaiting connection');
        } catch (e) {
            console.error('Error processing answer:', e);
            updateDebugStatus('Error processing answer: ' + e.message);
        }
    }

    async function onRemoteIce({ candidate }) {
        if (!candidate) return;
        
        if (!pc || !pc.remoteDescription) {
            remoteIceQueue.push(candidate);
            updateDebugStatus('Queued ICE candidate (no remote description yet)');
            return;
        }
        
        try {
            await pc.addIceCandidate(new RTCIceCandidate(candidate));
            updateDebugStatus('Added ICE candidate');
        } catch (e) {
            console.error('Error adding ICE candidate:', e);
        }
    }

    async function flushIceQueue() {
        if (!pc) return;
        
        updateDebugStatus(`Flushing ${remoteIceQueue.length} queued ICE candidates`);
        
        while (remoteIceQueue.length > 0) {
            const cand = remoteIceQueue.shift();
            try {
                await pc.addIceCandidate(new RTCIceCandidate(cand));
            } catch (e) {
                console.error('Error adding queued ICE:', e);
            }
        }
    }

    function endCall() {
        send('webrtc.end', {});
        teardown('Call ended');
    }

    function teardown(reason) {
        updateDebugStatus('Teardown: ' + reason);
        
        const modal = document.getElementById('callModal');
        if (modal) modal.style.display = 'none';
        
        stopTone();
        stopSignalPolling();
        
        if (offerResendInterval) {
            clearInterval(offerResendInterval);
            offerResendInterval = null;
        }
        
        if (pc) {
            pc.ontrack = null;
            pc.onicecandidate = null;
            pc.oniceconnectionstatechange = null;
            pc.onconnectionstatechange = null;
            try { pc.close(); } catch (_) { }
            pc = null;
        }
        
        if (localStream) {
            localStream.getTracks().forEach(t => t.stop());
            localStream = null;
        }
        
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
        connectionAttempts = 0;
    }

    // ========== Public API ==========
    window.OdnixCall = {
        startAudioCall: () => startCall({ audioOnly: true }),
        startVideoCall: () => startCall({ audioOnly: false }),
        endCall,
    };

    // ========== Auto-Initialize ==========
    try {
        console.log(`[CallJS] Connecting to WebSocket for chat ${chatId}`);
        openWS();
        
        // Always start polling as fallback
        console.log(`[CallJS] Starting signal polling for chat ${chatId}`);
        startSignalPolling();
        
        updateDebugStatus(`Initialized for chat ${chatId}`, 'green');
    } catch (e) {
        console.error('[CallJS] Initialization failed:', e);
        updateDebugStatus('Initialization failed: ' + e.message);
        enableServerRelay();
    }

})();
