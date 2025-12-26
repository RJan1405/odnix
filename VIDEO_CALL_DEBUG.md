# Video Call Signal Debugging Guide

## Overview

This guide helps diagnose "no signal received" issues in the video call system.

## Quick Diagnosis

### 1. Check if signals are being sent

Open browser console when starting a call. You should see:

```
[CallJS] Sending webrtc.offer...
✓ Sent webrtc.offer via WebSocket
Signal sent via server: webrtc.offer
```

If you don't see these messages, the `send()` function isn't being called.

### 2. Check server logs

When a signal is sent, you should see in Django logs:

```
[P2P_SEND] Signal stored: webrtc.offer from user 1 (John Doe) to 1 users in chat 5
```

If missing, the endpoint `/api/p2p/send-signal/` isn't receiving requests.

### 3. Check signal polling

Browser console should show every 1.5 seconds:

```
[Polling] Response: true Signals: 0
```

When signals exist:

```
[Polling] Response: true Signals: 2
[Polling] Processing signal: webrtc.offer
[Polling] Processing signal: webrtc.ice
```

Server logs should show:

```
[P2P_GET] Retrieved 2 call signals for user 2 (Jane Doe) in chat 5
```

### 4. Verify database storage

Run the test script:

```bash
python test_signal_flow.py
```

This will show:

- Total signals in database
- Recent signals with details (type, sender, receiver, status)
- Unconsumed signals count
- Signals per user

## Common Issues & Solutions

### Issue 1: No signals in database

**Symptoms:** `test_signal_flow.py` shows 0 signals

**Possible causes:**

1. `sendViaServerRelay()` not being called
2. CSRF token missing
3. Endpoint returning error

**Solution:**

- Check browser console for fetch errors
- Verify CSRF token in request headers
- Check Django logs for errors in `p2p_send_signal`

### Issue 2: Signals stored but not retrieved

**Symptoms:** Signals in DB but polling returns empty

**Possible causes:**

1. Wrong chat_id in polling URL
2. User not a participant of the chat
3. Signals marked as consumed too quickly
4. Signals older than 30 seconds (call signals only)

**Solution:**

- Verify `chatId` variable in call.js
- Check chat participants
- Look for premature `is_consumed=True` updates

### Issue 3: WebSocket handshake fails

**Symptoms:** "WS not ready" messages, only server relay used

**Possible causes:**

1. WebSocket route not configured
2. Channels not running
3. Encryption handshake failed

**Solution:**

- This is OK! System now uses server relay (DB) as primary path
- WebSocket is optimization, not required
- If you want WS to work, check Channels configuration

### Issue 4: Signals received but WebRTC connection fails

**Symptoms:** Polling works, signals processed, but no video/audio

**Possible causes:**

1. ICE candidates not exchanged
2. STUN/TURN servers unreachable
3. Firewall blocking UDP
4. SDP offer/answer mismatch

**Solution:**

- Check browser console for ICE connection state
- Verify STUN server in rtcConfig
- Check if both users behind strict NAT (need TURN)

## System Architecture

### Dual-Path Signal Delivery

```
Client A                    Server                    Client B
   |                          |                          |
   |  1. send(offer)          |                          |
   |------------------------->|                          |
   |  2. Store in DB          |                          |
   |  3. Try WebSocket ------>|                          |
   |                          |                          |
   |                          |  4. Poll /api/p2p/      |
   |                          |<-------------------------|
   |                          |  5. Return signals      |
   |                          |------------------------>|
   |                          |  6. Process offer       |
   |                          |                          |
```

### Signal Flow Steps

1. **Send:** Client calls `send(type, payload)`
2. **Store:** `sendViaServerRelay()` POSTs to `/api/p2p/send-signal/`
3. **Database:** Signal stored in `P2PSignal` table with `is_consumed=False`
4. **WebSocket (optional):** If connected, signal also sent via WS for real-time delivery
5. **Poll:** Other client polls `/api/p2p/${chatId}/signals/` every 1.5s
6. **Retrieve:** Server returns unconsumed signals, marks as consumed
7. **Process:** Client processes signal (offer/answer/ICE candidate)

## Key Code Locations

### Client-Side (call.js)

- **send()** (line ~458): Dual-path signal sending
- **sendViaServerRelay()** (line ~365): HTTP POST to store signal
- **startSignalPolling()** (line ~394): Poll for signals every 1.5s
- **setupPeer()** (line ~477): WebRTC connection setup

### Server-Side (chat/views/chat.py)

- **p2p_send_signal()** (line ~2001): Store signals in database
- **p2p_get_signals()** (line ~2059): Retrieve unconsumed signals

### Database Model (chat/models.py)

- **P2PSignal** (line ~241): Signal storage model
- **cleanup_old_signals()** (line ~257): Remove stale signals

## Testing Steps

### Manual Test

1. **Open two browsers** (or incognito window)
2. **Login as two different users**
3. **Navigate to chat** between the two users
4. **User A:** Open browser console, click "Start Video Call"
5. **Check console** for signal sending messages
6. **User B:** Check console for polling and signal receipt
7. **Verify connection** established

### Automated Test

```bash
# Terminal 1: Run Django server
python manage.py runserver

# Terminal 2: Check signals
python test_signal_flow.py

# Before starting call: Should show 0 signals
# After starting call: Should show offer, answer, ICE signals
```

## Debugging Checklist

- [ ] Browser console shows "Sending webrtc.offer..."
- [ ] Browser console shows "Signal sent via server"
- [ ] Django logs show "[P2P_SEND] Signal stored"
- [ ] `test_signal_flow.py` shows signals in database
- [ ] Polling console logs show "[Polling] Response: true Signals: X"
- [ ] Django logs show "[P2P_GET] Retrieved X call signals"
- [ ] Browser console shows "[Polling] Processing signal: webrtc.offer"
- [ ] Call modal shows connection status updates
- [ ] Video/audio streams visible

## Log Filtering

To see only P2P-related logs:

```bash
# In Django terminal, look for:
[P2P_SEND]  # Signal storage
[P2P_GET]   # Signal retrieval

# In browser console:
[CallJS]    # General call system
[Polling]   # Signal polling
```

## Performance Notes

- Polling interval: 1.5 seconds (configurable)
- Signal TTL: 30 seconds for call signals, immediate for others
- Cleanup: Consumed signals deleted after 1 minute, stale after 5 minutes
- Maximum signals per poll: No limit (all unconsumed returned)

## Known Limitations

1. **No real-time notification:** Relies on polling, max 1.5s delay
2. **Database load:** Each client polls every 1.5s (consider WebSocket if scaling)
3. **Signal ordering:** Not guaranteed if network delays vary
4. **Duplicate processing:** Client-side deduplication needed if signal re-sent

## Future Improvements

1. **Server-Sent Events (SSE):** Replace polling with SSE for real-time updates
2. **Redis Pub/Sub:** Use Redis for signal delivery instead of database
3. **Signal acknowledgment:** Require explicit ACK before marking consumed
4. **Retry logic:** Auto-retry failed signal sends
5. **Compression:** Compress large SDP payloads
