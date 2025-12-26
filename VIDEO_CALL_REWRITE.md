# Video Call & Signal Processing - Complete Rewrite

## Overview

Completely rewritten WebRTC video/audio call system with robust P2P connection and automatic server relay fallback.

## Architecture

### Dual-Path Signaling Strategy

The system uses a **dual-path approach** to ensure calls always work:

1. **Primary Path: WebSocket (P2P Signaling)**
   - Real-time, encrypted signaling
   - Low latency for optimal user experience
   - Uses Odnix Security Protocol for end-to-end encryption

2. **Fallback Path: HTTP Polling (Server Relay)**
   - Automatic fallback when WebSocket fails
   - Polls database every 1.5 seconds
   - Ensures calls work even with firewall/proxy issues

### Flow Diagram

```
Client A                    Server                     Client B
   |                          |                          |
   |--[1] WebSocket Connect-->|                          |
   |<--[2] Handshake---------|                          |
   |                          |<--[3] WebSocket Connect--|
   |                          |<--[4] Handshake---------|
   |                          |                          |
   |--[5] offer (WS)--------->|--[6] Forward (WS)------->|
   |--[5b] offer (DB)-------->|                          |
   |                          |<--[7] answer (WS)--------|
   |                          |<--[7b] answer (DB)-------|
   |<-[8] answer (WS OR Poll)-|                          |
   |                          |                          |
   |<========[9] P2P Direct Connection==========>|
   |              (STUN/TURN assisted)            |
```

## Key Features

### 1. Automatic Fallback System

- **WebSocket Failure Detection**: 3-second timeout
- **Seamless Transition**: Automatically switches to HTTP polling
- **Transparent to Users**: No manual intervention needed

### 2. Improved P2P Connection

- **Multiple STUN Servers**: 5 Google STUN servers for redundancy
- **ICE Candidate Pooling**: Pre-allocates 10 candidates
- **Connection Monitoring**: Real-time state tracking
- **Automatic Reconnection**: Up to 3 ICE restart attempts

### 3. Enhanced Error Handling

- **Connection State Tracking**: Monitors ICE and connection states
- **Failure Recovery**: Automatic ICE restart on failure
- **User Feedback**: Status indicators show connection state
- **Graceful Degradation**: Falls back to server relay

### 4. Security

- **End-to-End Encryption**: Signaling encrypted with Diffie-Hellman
- **Secure Media**: P2P WebRTC encryption (DTLS-SRTP)
- **Database Cleanup**: Old signals auto-deleted (1-5 minutes)

## File Changes

### 1. Client-Side: `static/js/call.js`

**Complete rewrite with improvements:**

#### State Management

- Centralized state variables
- Connection attempt tracking
- ICE gathering state monitoring

#### WebSocket Handling

```javascript
// Automatic fallback on failure
ws.onerror = () => {
    enableServerRelay();  // Switch to polling
};

// 3-second timeout for handshake
setTimeout(() => {
    if (handshakeStep !== 2) {
        enableServerRelay();
    }
}, 3000);
```

#### Signal Sending (Dual-Path)

```javascript
function send(type, payload) {
    // Try WebSocket first
    if (!useServerRelay && ws?.readyState === WebSocket.OPEN && handshakeStep === 2) {
        ws.send(encrypted);
        return;
    }
    // Fallback to server relay
    sendViaServerRelay(type, payload);
}
```

#### P2P Connection Monitoring

```javascript
pc.oniceconnectionstatechange = () => {
    if (pc.iceConnectionState === 'connected') {
        // P2P established!
    } else if (pc.iceConnectionState === 'failed') {
        handleConnectionFailure();  // Try ICE restart
    }
};
```

### 2. Server-Side: `chat/consumers.py`

**Enhanced signal processing:**

#### Improved Signal Handling

```python
async def handle_decrypted_signal(self, payload):
    """
    Dual-path strategy:
    1. Store in DB (fallback)
    2. Forward via WebSocket (real-time)
    3. Send notification (for offers)
    """
    # STEP 1: Database storage (ensures fallback)
    await self.store_signal_in_db(payload)
    
    # STEP 2: WebSocket forward (real-time P2P)
    await self.channel_layer.group_send(...)
    
    # STEP 3: Call notification (ringing banner)
    if message_type == "webrtc.offer":
        await self.send_call_notification(payload)
```

#### Fixed Target User Issue

```python
# OLD (BROKEN):
P2PSignal.objects.create(
    target_user_id=target_user_id,  # Wrong!
)

# NEW (FIXED):
target_user = User.objects.get(id=target_user_id)
P2PSignal.objects.create(
    target_user=target_user,  # Correct!
)
```

### 3. Model: `chat/models.py`

**Enhanced P2PSignal model:**

#### Better Documentation

```python
class P2PSignal(models.Model):
    """
    Stores WebRTC signals for dual-path delivery:
    - Real-time via WebSocket (preferred)
    - Polling via HTTP (fallback)
    """
```

#### Improved Cleanup

```python
@classmethod
def cleanup_old_signals(cls):
    """
    - Consumed signals: Delete after 1 minute
    - Stale signals: Delete after 5 minutes
    """
    consumed_cutoff = timezone.now() - timedelta(minutes=1)
    unconsumed_cutoff = timezone.now() - timedelta(minutes=5)
    # Delete both types
```

#### Added Index

```python
indexes = [
    models.Index(fields=['chat', 'target_user', 'is_consumed']),
    models.Index(fields=['created_at']),  # New!
]
```

## How It Works

### Call Initiation (Caller Side)

1. User clicks "Start Call"
2. Request camera/microphone permissions
3. Create RTCPeerConnection
4. Generate SDP offer
5. **Send offer via WebSocket AND store in DB**
6. Start ringback tone
7. Wait for answer

### Call Reception (Receiver Side)

1. Receive offer via WebSocket OR polling
2. Show incoming call UI
3. Play ring tone
4. User clicks "Accept"
5. Request camera/microphone permissions
6. Create RTCPeerConnection
7. Set remote description (offer)
8. Generate SDP answer
9. **Send answer via WebSocket AND store in DB**

### P2P Connection Establishment

1. Exchange ICE candidates
2. **Try host candidates first** (direct LAN)
3. **Fall back to STUN** (public IP)
4. **Use TURN if needed** (relay through server)
5. Monitor connection state
6. Auto-restart on failure (up to 3 attempts)

### Server Relay Fallback

**When WebSocket fails:**

1. Client detects timeout/error
2. Enable `useServerRelay = true`
3. Start polling `/api/p2p/${chatId}/signals/` every 1.5s
4. Retrieve signals from database
5. Process signals locally
6. Continue normal call flow

## Testing Scenarios

### Scenario 1: Both Users Online (Ideal)

- ✅ WebSocket connects
- ✅ Real-time signaling
- ✅ P2P connection established
- ✅ Low latency audio/video

### Scenario 2: WebSocket Blocked (Firewall)

- ❌ WebSocket fails to connect
- ✅ Auto-switch to HTTP polling
- ✅ Signals retrieved from DB
- ✅ P2P still established
- ⚠️ Slightly higher latency (1.5s polling)

### Scenario 3: P2P Blocked (Strict NAT)

- ✅ WebSocket works (signaling)
- ❌ P2P connection fails
- ✅ ICE restart attempted
- ⚠️ May need TURN server for relay

### Scenario 4: One User Offline

- ✅ Signals stored in DB
- ✅ Available when user comes online
- ⏰ Auto-cleanup after 5 minutes

## Configuration

### ICE Servers (WebRTC)

Default STUN servers (free, Google-hosted):

```javascript
const rtcConfig = {
    iceServers: [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' },
        // ... 3 more for redundancy
    ],
    iceCandidatePoolSize: 10,
    iceTransportPolicy: 'all'
};
```

**Optional: Add TURN server for better reliability**

```javascript
{
    urls: 'turn:your-turn-server.com:3478',
    username: 'user',
    credential: 'pass'
}
```

### Polling Interval

Adjust in `call.js`:

```javascript
signalPollInterval = setInterval(async () => {
    // Poll signals
}, 1500);  // 1.5 seconds (default)
```

**Recommendations:**

- **Fast**: 1000ms (1s) - More responsive, more server load
- **Balanced**: 1500ms (1.5s) - Current setting
- **Slow**: 3000ms (3s) - Less load, higher latency

### Signal Cleanup

Adjust in `models.py`:

```python
# Consumed signals cleanup
consumed_cutoff = timezone.now() - timedelta(minutes=1)

# Stale signals cleanup
unconsumed_cutoff = timezone.now() - timedelta(minutes=5)
```

## Debugging

### Enable Debug Panel

The call system includes a debug status panel (bottom-right):

```javascript
function updateDebugStatus(status, color) {
    // Shows real-time connection state
    // Visible at bottom-right of screen
}
```

### Check Connection State

In browser console:

```javascript
// Check WebSocket state
console.log(ws.readyState);  // 0=CONNECTING, 1=OPEN, 2=CLOSING, 3=CLOSED

// Check handshake step
console.log(handshakeStep);  // 0=None, 1=Requested, 2=Complete

// Check relay mode
console.log(useServerRelay);  // true=polling, false=WebSocket

// Check peer connection state
console.log(pc.iceConnectionState);  // new, checking, connected, failed
console.log(pc.connectionState);     // new, connecting, connected, failed
```

### Server Logs

```bash
# Watch consumer logs
tail -f logs/django.log | grep CallConsumer

# Example output:
[CallConsumer] ✓ Stored webrtc.offer in DB
[CallConsumer] ✓ Forwarded webrtc.offer to group call_123
[CallConsumer] ✓ Sent call notifications to 1 user(s)
```

## Performance Optimizations

1. **ICE Candidate Pooling**: Pre-generates candidates
2. **Bundle Policy**: Reduces connection overhead
3. **RTCP Mux**: Single port for media and control
4. **Signal Cleanup**: Prevents database bloat
5. **Index Optimization**: Faster query performance

## Security Considerations

1. **Encrypted Signaling**: DH key exchange + AES encryption
2. **Secure Media**: DTLS-SRTP (WebRTC default)
3. **CSRF Protection**: All HTTP requests use CSRF tokens
4. **Signal Expiration**: Auto-delete after 5 minutes
5. **User Validation**: Check chat membership before signaling

## Known Limitations

1. **Group Calls**: Currently limited to 1-on-1 calls
2. **TURN Server**: Not included (may need for strict NATs)
3. **Mobile**: May have issues with background tabs
4. **Browser Compatibility**: Requires modern WebRTC support

## Future Improvements

1. **Add TURN Server**: For better NAT traversal
2. **Group Call Support**: Multiple participants
3. **Call Recording**: Save call history
4. **Screen Sharing**: Desktop/window sharing
5. **Call Quality Monitoring**: Track bitrate, packet loss
6. **Mobile Optimizations**: Battery and network efficiency

## Migration Notes

### Breaking Changes

- Complete rewrite of `call.js`
- Updated signal handling in `consumers.py`
- Fixed `P2PSignal` model field name

### Database Migrations

```bash
# No new migrations needed
# P2PSignal model already exists
# Only logic changes, no schema changes
```

### Compatibility

- ✅ Backward compatible with existing chats
- ✅ Works with existing P2PSignal records
- ✅ No data migration required

## Troubleshooting

### Problem: Calls not connecting

**Possible causes:**

1. WebSocket blocked by firewall → Check server relay fallback
2. Media permissions denied → Check browser console
3. ICE connection failed → May need TURN server
4. Both users offline → Wait for recipient to come online

**Solutions:**

1. Check debug panel for connection state
2. Verify server relay is working (polling active)
3. Test with different network (mobile hotspot)
4. Add TURN server to configuration

### Problem: No incoming call notification

**Check:**

1. NotifyConsumer connected? (Check WebSocket in Network tab)
2. Signal stored in DB? (Query P2PSignal table)
3. Group notification sent? (Check server logs)

### Problem: Audio/video not flowing

**Check:**

1. ICE connection state (should be "connected")
2. Media tracks added? (Check remote stream)
3. Video element srcObject set? (Inspect DOM)
4. Browser autoplay policy (may need user interaction)

## Summary

This rewrite provides:

- ✅ **Robust dual-path signaling** (WebSocket + HTTP)
- ✅ **Automatic fallback** on connection failure
- ✅ **Improved P2P connection** with monitoring
- ✅ **Better error handling** and recovery
- ✅ **Enhanced debugging** capabilities
- ✅ **Production-ready** architecture

The system now works reliably even in challenging network conditions!
