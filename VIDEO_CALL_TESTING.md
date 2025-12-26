# Video Call Testing Guide

## Quick Test Checklist

### Prerequisites

- [ ] Two different browsers (or incognito + normal)
- [ ] Two user accounts logged in
- [ ] Chat conversation between the two users

### Test 1: Basic Video Call (Both WebSockets Working)

1. **User A**: Click video call button
2. **Expected**:
   - Ringback tone starts
   - Camera permission requested
   - Debug panel shows "WebSocket connected"
3. **User B**: Should see incoming call notification
4. **Expected**:
   - Ring tone plays
   - "Accept" and "Decline" buttons appear
5. **User B**: Click "Accept"
6. **Expected**:
   - Camera permission requested
   - Call modal opens
   - Video starts flowing both ways
   - Debug panel shows "P2P connection established"

**Success Criteria**: ✅ Video and audio working in both directions

---

### Test 2: Audio-Only Call

1. **User A**: Click audio call button
2. **Expected**:
   - Microphone permission only
   - Local video hidden
3. **User B**: Accept call
4. **Expected**:
   - Audio flows both ways
   - No video elements visible

**Success Criteria**: ✅ Audio working, no video

---

### Test 3: Server Relay Fallback (Simulate WebSocket Failure)

#### Method 1: Block WebSocket in DevTools

1. Open DevTools → Network tab
2. Block WebSocket connection pattern: `ws://*/ws/call/*`
3. **User A**: Start video call
4. **Expected in debug panel**:
   - "WebSocket error"
   - "Enabling server relay fallback"
   - "Starting signal polling"
5. **Expected**: Call still works via HTTP polling

#### Method 2: Disconnect After Call Starts

1. Start a normal call (WebSocket working)
2. In DevTools, close WebSocket connection manually
3. **Expected**:
   - Debug shows "WebSocket closed"
   - Auto-switch to server relay
   - Call continues without interruption

**Success Criteria**: ✅ Call works even when WebSocket fails

---

### Test 4: Decline Call

1. **User A**: Start call
2. **User B**: Click "Decline"
3. **Expected**:
   - Ring stops
   - Call modal closes
   - User A sees call ended
4. **User A**: Try calling again within 20 seconds
5. **Expected**: User B doesn't see notification (cooldown period)

**Success Criteria**: ✅ Decline works, cooldown prevents spam

---

### Test 5: End Call

1. Start a call and connect
2. **User A**: Click "End" button
3. **Expected**:
   - Both sides: call modal closes
   - Camera/mic stops
   - Connection cleaned up

**Success Criteria**: ✅ Clean teardown on both sides

---

### Test 6: Simultaneous Calls (Race Condition)

1. **User A**: Start call to User B
2. **User B**: Immediately start call to User A (before accepting)
3. **Expected**: One call wins, other is ignored
4. **Verify**: Only one incoming call prompt shows

**Success Criteria**: ✅ No duplicate calls or crashes

---

### Test 7: Network Reconnection

1. Start a call
2. Disconnect internet for 5 seconds
3. Reconnect
4. **Expected**:
   - Debug shows "ICE disconnected"
   - Auto-reconnection attempt
   - Either reconnects or fails gracefully

**Success Criteria**: ✅ Handles network issues gracefully

---

## Debug Panel Indicators

### Normal Flow (WebSocket)

```
[HH:MM:SS] Connecting to ws://...
[HH:MM:SS] WebSocket connected, starting handshake
[HH:MM:SS] Received DH params
[HH:MM:SS] Handshake complete, encryption enabled
[HH:MM:SS] Sent webrtc.offer via WebSocket
[HH:MM:SS] Received webrtc.answer via WebSocket
[HH:MM:SS] ICE: checking
[HH:MM:SS] ✓ P2P connection established!
[HH:MM:SS] ICE: connected
```

### Fallback Flow (Server Relay)

```
[HH:MM:SS] WebSocket error
[HH:MM:SS] Enabling server relay fallback
[HH:MM:SS] Starting signal polling
[HH:MM:SS] Signal sent via server: webrtc.offer
[HH:MM:SS] Polling: Received 1 signals
[HH:MM:SS] ✓ Processing call answer from John
[HH:MM:SS] ICE: checking
[HH:MM:SS] ✓ P2P connection established!
```

## Browser Console Commands

### Check Connection Status

```javascript
// WebSocket state
console.log('WebSocket:', ws?.readyState); // 1 = OPEN

// Handshake status
console.log('Handshake step:', handshakeStep); // 2 = complete

// Relay mode
console.log('Using server relay:', useServerRelay); // false = WebSocket

// Peer connection
console.log('ICE state:', pc?.iceConnectionState); // 'connected' = working
console.log('Connection state:', pc?.connectionState); // 'connected' = working

// Streams
console.log('Local stream:', localStream?.getTracks());
console.log('Remote stream:', remoteStream?.getTracks());
```

### Force Server Relay (For Testing)

```javascript
// In browser console before starting call:
useServerRelay = true;
```

## Common Issues & Solutions

### Issue: No video/audio flowing

**Check:**

1. Permissions granted? (should see camera/mic icon in address bar)
2. ICE state = 'connected'? (check debug panel)
3. Remote video srcObject set? (`document.getElementById('remoteVideo').srcObject`)

**Fix:**

- Grant permissions
- Check firewall/NAT settings
- May need TURN server for strict NATs

---

### Issue: Incoming call not showing

**Check:**

1. NotifyConsumer connected? (Network tab → WS)
2. Signal in database? (Django admin → P2P Signals)
3. Polling active? (debug panel should show "Starting signal polling")

**Fix:**

- Check WebSocket connection
- Verify signal stored in DB
- Check server logs for errors

---

### Issue: Call connects but video freezes

**Check:**

1. Network bandwidth sufficient?
2. CPU usage high?
3. Browser tab backgrounded? (some browsers throttle)

**Fix:**

- Keep tab in foreground
- Close other tabs
- Check network speed

---

### Issue: Echo/feedback on audio

**Cause:** Same device for both users (testing)

**Fix:**

- Use headphones
- Test on different devices
- Audio echo cancellation should handle this automatically

## Database Verification

### Check Signals in DB

```bash
# Django shell
python manage.py shell

from chat.models import P2PSignal
from django.utils import timezone
from datetime import timedelta

# Recent signals
recent = P2PSignal.objects.filter(
    created_at__gte=timezone.now() - timedelta(minutes=5)
)
for sig in recent:
    print(f"{sig.sender} -> {sig.target_user}: {sig.signal_data.get('type')}")

# Unconsumed signals
unconsumed = P2PSignal.objects.filter(is_consumed=False)
print(f"Unconsumed signals: {unconsumed.count()}")
```

### Manual Signal Cleanup

```bash
# Django shell
from chat.models import P2PSignal
P2PSignal.cleanup_old_signals()
# Returns: number of deleted signals
```

## Server Logs

### Tail logs while testing

```bash
# Linux/Mac
tail -f /path/to/logs/django.log | grep -E "CallConsumer|P2PSignal"

# Windows (PowerShell)
Get-Content -Path "logs\django.log" -Wait | Select-String -Pattern "CallConsumer|P2PSignal"
```

### Expected log entries

```
[CallConsumer] ✓ Stored webrtc.offer in DB for polling fallback
[CallConsumer] ✓ Forwarded webrtc.offer to group call_123
[CallConsumer] ✓ Sent call notifications to 1 user(s)
[CallConsumer] ✓ Sent encrypted webrtc.answer to user 456
[P2PSignal] Cleaned up 5 consumed and 2 stale signals
```

## Performance Metrics

### Acceptable Values

- **Signaling delay (WebSocket)**: < 100ms
- **Signaling delay (Polling)**: < 2 seconds
- **ICE connection time**: < 5 seconds
- **Video start time**: < 3 seconds after answer

### Monitor in DevTools

1. Network tab → WS (WebSocket messages)
2. Check timing for signal exchange
3. Console → Check ICE gathering time

## Security Testing

### Test 1: Unauthorized Access

1. Try accessing WebSocket without authentication
2. **Expected**: Connection rejected

### Test 2: Cross-Chat Signaling

1. User A in Chat 1
2. Try sending signal to Chat 2
3. **Expected**: Blocked by server

### Test 3: Signal Encryption

1. Monitor WebSocket traffic
2. **Expected**: Encrypted payload after handshake
3. **Verify**: Cannot read SDP or ICE candidates

## Load Testing (Optional)

### Concurrent Calls

1. Open multiple browser windows
2. Start calls simultaneously
3. **Monitor**: Database query count
4. **Expected**: Signals stored efficiently

### Signal Cleanup

1. Generate 100+ signals
2. Run cleanup
3. **Verify**: Old signals deleted
4. **Expected**: Database size reasonable

## Production Readiness Checklist

- [ ] Video calls work (WebSocket)
- [ ] Audio calls work (WebSocket)
- [ ] Server relay works (HTTP polling)
- [ ] Call decline works
- [ ] Call end works
- [ ] Notifications work
- [ ] Signal cleanup works
- [ ] No console errors
- [ ] Performance acceptable
- [ ] Security tested
- [ ] Documentation reviewed

## Post-Test Cleanup

```bash
# Clear old signals
python manage.py shell
>>> from chat.models import P2PSignal
>>> P2PSignal.objects.all().delete()

# Or use cleanup method
>>> P2PSignal.cleanup_old_signals()
```

## Next Steps

After successful testing:

1. Add TURN server for production (optional)
2. Monitor error rates in production
3. Collect user feedback
4. Optimize polling interval based on usage
5. Consider adding call recording feature
