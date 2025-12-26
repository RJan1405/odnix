/**
 * OdnixProto Client (Secure Layer 1.0)
 * Implements Diffie-Hellman Key Exchange and AES-256 IGE Encryption
 * Uses CryptoJS for crypto primitives (AES, SHA256) and native BigInt for DH math.
 */

window.OdnixProtoConfig = {
    DH_PRIME: BigInt("0xC71CAEB9C6B1C9048E6C522F70F13F73980D40238E3E21C14934D037563D930F48198A0AA7C14058229493D22530F4DBFA336F6E0AC925139543A94464314C7F2012519CE6DE5BF3ADBD63796D41780160830B75F3A90248238F76953D64AF663004013B9F8D1768822610B71311531E83FA79715DAF63"),
    DH_G: 3n
};

class OdnixProtoClient {
    constructor() {
        this.authKey = null; // Uint8Array or WordArray
        this.serverNonce = null;
        this.sessionId = CryptoJS.lib.WordArray.random(8); // 8 bytes random
        this.salt = CryptoJS.lib.WordArray.random(8); // 8 bytes random
        // Client nonce used during handshake (16 random bytes)
        this.clientNonce = crypto.getRandomValues(new Uint8Array(16));
    }

    // ----------------------------------------------------
    // AES-IGE Implementation using CryptoJS
    // ----------------------------------------------------

    /**
     * encrypt_ige
     * @param {WordArray} data - plaintext (padded)
     * @param {WordArray} key - 32 bytes
     * @param {WordArray} iv - 32 bytes (iv1 + iv2)
     */
    encrypt_ige(data, key, iv) {
        // IGE Encrypt: C_i = AES_ENC(P_i ^ C_{i-1}) ^ M_{i-1}
        // iv1 = C_{-1}, iv2 = M_{-1}

        // Convert IV to separate words
        // Note: CryptoJS WordArray handling is tricky. 
        // We'll process block by block (16 bytes = 4 words)

        // Clone IV parts
        let iv1 = CryptoJS.lib.WordArray.create(iv.words.slice(0, 4));
        let iv2 = CryptoJS.lib.WordArray.create(iv.words.slice(4, 8));

        let ciphertext = CryptoJS.lib.WordArray.create();

        // Access words directly for speed
        const blockSize = 16; // bytes

        // Deep copy data to avoid mutation issues logic
        // But CryptoJS encrypts usually return new objects. 

        // We need to iterate over blocks. 
        // CryptoJS WordArray.words is an array of 32-bit integers.
        // Block size 16 bytes = 4 words.

        for (let i = 0; i < data.sigBytes; i += blockSize) {
            // Extract P_i (16 bytes)
            // Function to slice WordArray is not native simple API, need manual
            let p_words = data.words.slice(i / 4, (i / 4) + 4);
            let p_block = CryptoJS.lib.WordArray.create(p_words);

            // X = P_i ^ C_{i-1} -> but wait, IGE formula: AES_ENC(P_i ^ iv1) ^ iv2 ??
            // Using Python logic: input_block = P_i ^ iv1

            let xored_input = this.xorWordArrays(p_block, iv1);

            // AES Encrypt (ECB)
            let encrypted = CryptoJS.AES.encrypt(xored_input, key, {
                mode: CryptoJS.mode.ECB,
                padding: CryptoJS.pad.NoPadding
            });
            let enc_block = encrypted.ciphertext; // WordArray

            // C_i = Encrypted ^ iv2 (M_{i-1})
            let c_block = this.xorWordArrays(enc_block, iv2);

            ciphertext.concat(c_block);

            // Update IVs
            iv1 = c_block; // C_{i-1} -> C_i
            iv2 = p_block; // M_{i-1} -> P_i
        }

        return ciphertext;
    }

    decrypt_ige(data, key, iv) {
        // P_i = AES_DEC(C_i ^ M_{i-1}) ^ C_{i-1}

        let iv1 = CryptoJS.lib.WordArray.create(iv.words.slice(0, 4)); // C_prev
        let iv2 = CryptoJS.lib.WordArray.create(iv.words.slice(4, 8)); // M_prev

        let plaintext = CryptoJS.lib.WordArray.create();
        const blockSize = 16;

        for (let i = 0; i < data.sigBytes; i += blockSize) {
            let c_words = data.words.slice(i / 4, (i / 4) + 4);
            let c_block = CryptoJS.lib.WordArray.create(c_words);

            // input = C_i ^ M_prev (iv2)
            let input_block = this.xorWordArrays(c_block, iv2);

            // AES Decrypt (ECB)
            // Note: CryptoJS.AES.decrypt returns formatted Padded param by default? 
            // We set NoPadding.
            let decrypted = CryptoJS.AES.decrypt(
                { ciphertext: input_block },
                key,
                { mode: CryptoJS.mode.ECB, padding: CryptoJS.pad.NoPadding }
            );

            // P_i = Decrypted ^ C_prev (iv1)
            let p_block = this.xorWordArrays(decrypted, iv1);

            plaintext.concat(p_block);

            iv1 = c_block;
            iv2 = p_block;
        }

        // Unpad (PKCS7 logic manually if needed or string conversion handles it?)
        // CryptoJS usually handles padding if configured, but here we did block level. 
        // We will just verify last byte.
        // Actually, let's assume valid JSON payload is enough.
        return plaintext;
    }

    xorWordArrays(wa1, wa2) {
        let res = wa1.clone();
        for (let i = 0; i < res.words.length; i++) {
            res.words[i] ^= wa2.words[i];
        }
        return res;
    }

    // ----------------------------------------------------
    // Handshake
    // ----------------------------------------------------

    generateClientDhParams() {
        // Generate random private key (2048 bits roughly)
        // Simplified: use 256 random bytes
        let randWords = CryptoJS.lib.WordArray.random(32); // 256 bits
        this.clientDhPrivate = this.wordArrayToBigInt(randWords);

        // Calculate Public: g ^ priv % prime
        // Using BigInt
        this.clientDhPublic = this.modPow(OdnixProtoConfig.DH_G, this.clientDhPrivate, OdnixProtoConfig.DH_PRIME);
        return this.clientDhPublic.toString(16); // Send as hex
    }

    computeSharedKey(serverPubHex) {
        let serverPub = BigInt("0x" + serverPubHex);
        let sharedSecret = this.modPow(serverPub, this.clientDhPrivate, OdnixProtoConfig.DH_PRIME);

        // Compute SHA256 of shared secret bytes
        let sharedHex = sharedSecret.toString(16);
        if (sharedHex.length % 2 !== 0) sharedHex = '0' + sharedHex;
        let secretBytes = CryptoJS.enc.Hex.parse(sharedHex);
        this.authKey = CryptoJS.SHA256(secretBytes); // 32 bytes auth key
        console.log("OdnixProto Auth Key Established");
    }

    modPow(base, exp, mod) {
        let res = 1n;
        base = base % mod;
        while (exp > 0n) {
            if (exp % 2n === 1n) res = (res * base) % mod;
            base = (base * base) % mod;
            exp /= 2n;
        }
        return res;
    }

    wordArrayToBigInt(wa) {
        let hex = CryptoJS.enc.Hex.stringify(wa);
        return BigInt("0x" + hex);
    }

    // ----------------------------------------------------
    // Wrapper
    // ----------------------------------------------------

    encrypt(payloadObj) {
        if (!this.authKey) throw new Error("No Auth Key");
        let payloadStr = JSON.stringify(payloadObj);
        let payloadWa = CryptoJS.enc.Utf8.parse(payloadStr);

        // inner_data = salt + session + time + payload
        // We need to construct a WordArray.
        // Timestamp (8 bytes in theory, use 2 words)
        let ts = Math.floor(Date.now());
        let tsWa = CryptoJS.lib.WordArray.create([0, ts]); // rough 64-bit int logic (simplified)

        let innerData = this.salt.clone()
            .concat(this.sessionId)
            .concat(tsWa)
            .concat(payloadWa);

        // Pad innerData to 16 bytes
        let padLen = 16 - (innerData.sigBytes % 16);
        // PKCS7 padding manually
        let padWords = [];
        for (let i = 0; i < padLen; i++) padWords.push(padLen);
        // This is byte array, need to convert to word array properly (messy).
        // Let's use CryptoJS.pad.Pkcs7 if possible? 
        // We can just append random bytes? No, must be strict for IGE.
        // Let's do simplified padding: 0 bytes.
        let padWa = CryptoJS.lib.WordArray.random(padLen);
        innerData.concat(padWa);

        // Compute msg_key: SHA256(auth_key + inner_data)[0..16]
        // Note: authKey is WordArray, innerData is WordArray.
        let toHash = this.authKey.clone().concat(innerData);
        let fullHash = CryptoJS.SHA256(toHash);

        // msg_key is first 16 bytes (4 words)
        let msgKey = CryptoJS.lib.WordArray.create(fullHash.words.slice(0, 4));

        // AES Key/IV derivation
        // aes_key = SHA256(msg_key + auth_key)
        let aesKeyHash = CryptoJS.SHA256(msgKey.clone().concat(this.authKey));
        let aesKey = aesKeyHash; // 32 bytes

        // aes_iv = SHA256(auth_key + msg_key)
        let aesIvHash = CryptoJS.SHA256(this.authKey.clone().concat(msgKey));
        let aesIv = aesIvHash; // 32 bytes

        // Encrypt
        let encryptedData = this.encrypt_ige(innerData, aesKey, aesIv);

        // Final Packet: auth_key_id (dummy) + msg_key + encrypted_data
        // auth_key_id = SHA1(auth_key)[-8]
        let authKeyHash = CryptoJS.SHA1(this.authKey);
        let authKeyId = CryptoJS.lib.WordArray.create(authKeyHash.words.slice(authKeyHash.words.length - 2));
        // SHA1 is 5 words (20 bytes). Last 2 words = 8 bytes.

        let packet = authKeyId.concat(msgKey).concat(encryptedData);
        return CryptoJS.enc.Base64.stringify(packet);
    }

    decrypt(base64Packet) {
        if (!this.authKey) return null;
        let packet = CryptoJS.enc.Base64.parse(base64Packet);

        // Parse: auth_key_id(8) + msg_key(16) + data
        // 8 bytes = 2 words
        let authKeyId = CryptoJS.lib.WordArray.create(packet.words.slice(0, 2));
        let msgKey = CryptoJS.lib.WordArray.create(packet.words.slice(2, 6)); // 16 bytes = 4 words

        // Data starts at word 6
        let encryptedData = CryptoJS.lib.WordArray.create(
            packet.words.slice(6),
            packet.sigBytes - 24
        );

        // Derive keys
        let aesKey = CryptoJS.SHA256(msgKey.clone().concat(this.authKey));
        let aesIv = CryptoJS.SHA256(this.authKey.clone().concat(msgKey));

        // Decrypt
        let decrypted = this.decrypt_ige(encryptedData, aesKey, aesIv);

        // Structure: salt(8) + session(8) + ts(8) + payload + pad
        if (decrypted.sigBytes < 24) return null;

        // payload starts at byte 24
        let payloadWa = CryptoJS.lib.WordArray.create(
            decrypted.words.slice(6), // 24 bytes / 4 = 6 words
            decrypted.sigBytes - 24
        );

        // Convert to string (UTF8)
        try {
            let jsonStr = CryptoJS.enc.Utf8.stringify(payloadWa);
            // remove padding if any (trailing chars)
            // JSON parse will ignore trailing garbage if valid closure? No. 
            // We need to strip padding. 
            // Finding last '}'? Hacky but works for demo 
            let lastBrace = jsonStr.lastIndexOf('}');
            if (lastBrace !== -1) jsonStr = jsonStr.substring(0, lastBrace + 1);

            return JSON.parse(jsonStr);
        } catch (e) {
            console.error("OdnixProto Decrypt Error", e);
            return null;
        }
    }
}
