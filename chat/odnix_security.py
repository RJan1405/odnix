
import os
import struct
import hashlib
import time
import json
import base64
from Crypto.Cipher import AES
from Crypto.Util import number
from Crypto.Util.Padding import pad, unpad
from Crypto.Random import get_random_bytes

# OdnixProto 1.0 Constants
DH_PRIME = int('C71CAEB9C6B1C9048E6C522F70F13F73980D40238E3E21C14934D037563D930F48198A0AA7C14058229493D22530F4DBFA336F6E0AC925139543A94464314C7F2012519CE6DE5BF3ADBD63796D41780160830B75F3A90248238F76953D64AF663004013B9F8D1768822610B71311531E83FA79715DAF63', 16)
DH_G = 3

class OdnixSecurity:
    def __init__(self):
        self.auth_key = None
        self.session_id = get_random_bytes(8)
        self.salt = get_random_bytes(8)
        self.server_nonce = None
    
    # ---------------------------------------------------------
    # Diffie-Hellman Key Exchange (Simplified for demo)
    # ---------------------------------------------------------
    
    def create_dh_config(self):
        """Step 1: Server sends P and G, and a server nonce."""
        self.server_nonce = get_random_bytes(16)
        # In a real impl, we'd cycle nonces.
        return {
            'prime': str(DH_PRIME),
            'g': DH_G,
            'server_nonce': base64.b64encode(self.server_nonce).decode('utf-8')
        }

    def compute_shared_key(self, client_public_key_int, server_private_key_int):
        """Compute the shared secret (AuthKey)."""
        shared_secret = pow(client_public_key_int, server_private_key_int, DH_PRIME)
        # AuthKey is usually the straight bytes of the shared secret, simplified here
        # to a 256-bit hash of it for convenient AES usage.
        b_secret = number.long_to_bytes(shared_secret)
        self.auth_key = hashlib.sha256(b_secret).digest() # 32 bytes (256 bits)
        return self.auth_key

    # ---------------------------------------------------------
    # AES-256 IGE Encryption / Decryption
    # ---------------------------------------------------------

    @staticmethod
    def aes_ige_encrypt(data, key, iv):
        """
        AES-IGE encryption. 
        Infinite Garble Extension (IGE) mode implementation using AES-ECB.
        block[i] = AES_ENC(block[i] ^ prev_ciphertext) ^ prev_plaintext
        """
        cipher = AES.new(key, AES.MODE_ECB)
        block_size = AES.block_size
        
        # Pad data with PKCS7
        pad_len = block_size - (len(data) % block_size)
        data += bytes([pad_len] * pad_len)

        iv_1 = iv[:block_size] # c_prev
        iv_2 = iv[block_size:] # m_prev (random noise usually)
        
        ciphertext = b''
        
        for i in range(0, len(data), block_size):
            plaintext_block = data[i:i+block_size]
            
            # Input to AES: P_i XOR C_{i-1}
            input_block = bytes(a ^ b for a, b in zip(plaintext_block, iv_1))
            
            # AES Encrypt
            encrypted_block = cipher.encrypt(input_block)
            
            # C_i = Encrypted XOR M_{i-1}
            cipher_block = bytes(a ^ b for a, b in zip(encrypted_block, iv_2))
            
            ciphertext += cipher_block
            
            # Update state for next block
            iv_1 = cipher_block # C_{i-1} becomes this block
            iv_2 = plaintext_block # M_{i-1} becomes this plaintext
            
        return ciphertext

    @staticmethod
    def aes_ige_decrypt(data, key, iv):
        """
        AES-IGE decryption.
        P_i = AES_DEC(C_i ^ M_{i-1}) ^ C_{i-1}
        """
        cipher = AES.new(key, AES.MODE_ECB)
        block_size = AES.block_size
        
        iv_1 = iv[:block_size] # c_prev
        iv_2 = iv[block_size:] # m_prev
        
        plaintext = b''
        
        for i in range(0, len(data), block_size):
            ciphertext_block = data[i:i+block_size]
            
            # Input to AES DEC: C_i ^ M_{i-1}
            input_block = bytes(a ^ b for a, b in zip(ciphertext_block, iv_2))
            
            # AES Decrypt
            decrypted_block = cipher.decrypt(input_block)
            
            # P_i = Decrypted ^ C_{i-1}
            plain_block = bytes(a ^ b for a, b in zip(decrypted_block, iv_1))
            
            plaintext += plain_block
            
            # Update state
            iv_1 = ciphertext_block
            iv_2 = plain_block
            
        # Unpad
        pad_len = plaintext[-1]
        if isinstance(pad_len, int):
             # Python 3 byte access returns int
             if pad_len < 1 or pad_len > block_size:
                 # This might happen if 'raw' access or corruption. 
                 # For now, return as is or handle error.
                 return plaintext 
             return plaintext[:-pad_len]
        return plaintext

    # ---------------------------------------------------------
    # OdnixProto Wrapper
    # ---------------------------------------------------------

    def wrap_message(self, json_payload):
        """
        Wraps a JSON payload into an OdnixProto-like packet.
        Format:
        auth_key_id (8 bytes) + msg_key (16 bytes) + AES_IGE( salt (8) + session (8) + seq (8) + len (4) + payload + padding )
        """
        if not self.auth_key:
            raise ValueError("No AuthKey established")

        payload_bytes = json.dumps(json_payload).encode('utf-8')
        message_len = len(payload_bytes)
        
        # Inner Data
        # salt (8) + session_id (8) + seq_no (8) + message_len (4) + payload + padding
        # Simplified: salt + session + timestamp + payload
        
        inner_data = (
            self.salt + 
            self.session_id + 
            struct.pack('<Q', int(time.time()*1000)) + 
            payload_bytes
        )
        
        msg_key_hash = hashlib.sha256(self.auth_key + inner_data).digest()
        msg_key = msg_key_hash[:16]
        
        sha256_full = hashlib.sha256(msg_key + self.auth_key).digest()
        aes_key = sha256_full # 32 bytes
        aes_iv = hashlib.sha256(self.auth_key + msg_key).digest() # 32 bytes
        
        encrypted_data = self.aes_ige_encrypt(inner_data, aes_key, aes_iv)
        
        # Auth Key ID (hashed simplified)
        auth_key_id = hashlib.sha1(self.auth_key).digest()[-8:]
        
        final_packet = auth_key_id + msg_key + encrypted_data
        return base64.b64encode(final_packet).decode('utf-8')

    def unwrap_message(self, b64_packet):
        """
        Unwraps an OdnixProto-like packet.
        """
        if not self.auth_key:
            raise ValueError("No AuthKey established")
            
        try:
            packet = base64.b64decode(b64_packet)
        except:
            return None
            
        if len(packet) < 24: # auth_key_id(8) + msg_key(16)
            return None
            
        auth_key_id = packet[:8]
        msg_key = packet[8:24]
        encrypted_data = packet[24:]
        
        # Verify Auth Key ID (skip for now, assume single user matches)
        
        # Derive Key/IV
        aes_key = hashlib.sha256(msg_key + self.auth_key).digest()
        aes_iv = hashlib.sha256(self.auth_key + msg_key).digest()
        
        decrypted_data = self.aes_ige_decrypt(encrypted_data, aes_key, aes_iv)
        
        # Structure: salt(8) + session(8) + time(8) + payload
        if len(decrypted_data) < 24:
            return None
            
        # salt = decrypted_data[:8]
        # session = decrypted_data[8:16]
        # timestamp = decrypted_data[16:24]
        payload_bytes = decrypted_data[24:]
        
        try:
            return json.loads(payload_bytes.decode('utf-8'))
        except:
            return None
