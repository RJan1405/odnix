import struct
import json
import time
import os
import hashlib
from abc import ABC, abstractmethod

# ==============================================================================
# ODNIX PROTOCOL MODEL (MTProto 2.0 Partial Implementation)
# ==============================================================================
# This module defines the "Type Language" (TL) schema and packet structure
# mirroring Telegram's MTProto 2.0 design.
# ==============================================================================

class TLObject(ABC):
    """Base class for all Type Language objects"""
    
    @abstractmethod
    def to_bytes(self) -> bytes:
        """Serialize object to bytes"""
        pass
    
    @classmethod
    @abstractmethod
    def from_bytes(cls, data: bytes):
        """Deserialize bytes to object"""
        pass

# --- Primitives ---

def write_int(data: int) -> bytes:
    return struct.pack('<I', data)

def write_long(data: int) -> bytes:
    return struct.pack('<Q', data)

def write_bytes(data: bytes) -> bytes:
    """TL-style bytes serialization (1-byte length if <254, else 4-byte)"""
    length = len(data)
    if length < 254:
        padding = (4 - (length + 1) % 4) % 4
        return struct.pack('B', length) + data + b'\x00' * padding
    else:
        padding = (4 - (length + 4) % 4) % 4
        return b'\xfe' + struct.pack('<I', length)[:3] + data + b'\x00' * padding

def read_int(stream) -> int:
    return struct.unpack('<I', stream.read(4))[0]

def read_long(stream) -> int:
    return struct.unpack('<Q', stream.read(8))[0]

# ==============================================================================
# PACKET STRUCTURE (The Envelope)
# ==============================================================================

class OdnixPacket(TLObject):
    """
    Represents the full Secure Packet (Layer 3 in Architecture).
    Structure: [AuthKeyId+MsgKey+EncryptedData]
    """
    def __init__(self, auth_key_id: bytes, msg_key: bytes, encrypted_data: bytes):
        self.auth_key_id = auth_key_id  # 8 bytes
        self.msg_key = msg_key          # 16 bytes (128-bit)
        self.encrypted_data = encrypted_data

    def to_bytes(self) -> bytes:
        return self.auth_key_id + self.msg_key + self.encrypted_data

    @classmethod
    def from_bytes(cls, data: bytes):
        if len(data) < 24:
            raise ValueError("Packet too short")
        return cls(
            auth_key_id=data[0:8],
            msg_key=data[8:24],
            encrypted_data=data[24:]
        )

# ==============================================================================
# PAYLOAD STRUCTURE (The Content)
# ==============================================================================

class OdnixPayload(TLObject):
    """
    Represents the Decrypted Payload which sits inside AES-IGE.
    Structure: [Salt+SessionId+MsgId+SeqNo+Length+Data+Padding]
    """
    def __init__(self, salt: bytes, session_id: bytes, msg_id: int, seq_no: int, message_data: TLObject):
        self.salt = salt              # 8 bytes
        self.session_id = session_id  # 8 bytes
        self.msg_id = msg_id          # 8 bytes (64-bit time)
        self.seq_no = seq_no          # 4 bytes
        self.message = message_data   # The actual RPC/Update object

    def to_bytes(self) -> bytes:
        msg_bytes = self.message.to_bytes()
        msg_len = len(msg_bytes)
        
        header = (
            self.salt +
            self.session_id + 
            write_long(self.msg_id) +
            write_int(self.seq_no) +
            write_int(msg_len)
        )
        
        payload = header + msg_bytes
        
        # MTProto Padding: Total length must be divisible by 16
        pad_len = 16 - (len(payload) % 16)
        if pad_len < 12: pad_len += 16
        padding = os.urandom(pad_len)
        
        return payload + padding

# ==============================================================================
# SERVICE MESSAGES (TL Schema Definitions)
# ==============================================================================

class RpcRequest(TLObject):
    CONSTRUCTOR_ID = 0x6a157529  # CRC32("rpc_request")

    def __init__(self, method: str, params: dict):
        self.method = method
        self.params = params

    def to_bytes(self) -> bytes:
        # Simplified JSON serialization for the "Body" (Hybrid Approach)
        body = json.dumps({"method": self.method, "params": self.params}).encode('utf-8')
        return write_int(self.CONSTRUCTOR_ID) + body

class RpcResult(TLObject):
    CONSTRUCTOR_ID = 0xf35c6d01 # CRC32("rpc_result")

    def __init__(self, req_msg_id: int, result: dict):
        self.req_msg_id = req_msg_id
        self.result = result

    def to_bytes(self) -> bytes:
        body = json.dumps(self.result).encode('utf-8')
        return write_int(self.CONSTRUCTOR_ID) + write_long(self.req_msg_id) + body

class UpdateNewMessage(TLObject):
    CONSTRUCTOR_ID = 0x1f2b3c4d

    def __init__(self, message_id: int, pts: int, content: str):
        self.message_id = message_id
        self.pts = pts
        self.content = content

    def to_bytes(self) -> bytes:
        return (
            write_int(self.CONSTRUCTOR_ID) +
            write_long(self.message_id) +
            write_int(self.pts) +
            write_bytes(self.content.encode('utf-8'))
        )

# ==============================================================================
# HELPERS
# ==============================================================================

def generate_msg_id() -> int:
    """
    Generates a Client Message ID based on time.
    Must be approx unix_time * 2^32.
    """
    return int(time.time() * 4294967296)

def generate_session_id() -> bytes:
    return os.urandom(8)
