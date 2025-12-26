import os
import time
import json
import secrets
import hashlib
import base64
from websocket import create_connection

# Config
CHAT_ID = os.environ.get("CHAT_ID", "1")
HOST = os.environ.get("HOST", "127.0.0.1:8000")
WS_URL = f"ws://{HOST}/ws/call/{CHAT_ID}/"

# DH params must match server
DH_PRIME = int("C71CAEB9C6B1C9048E6C522F70F13F73980D40238E3E21C14934D037563D930F48198A0AA7C14058229493D22530F4DBFA336F6E0AC925139543A94464314C7F2012519CE6DE5BF3ADBD63796D41780160830B75F3A90248238F76953D64AF663004013B9F8D1768822610B71311531E83FA79715DAF63", 16)
DH_G = 3


def modexp(base, exp, mod):
    return pow(base, exp, mod)


def main():
    print(f"Connecting to {WS_URL}...")
    ws = create_connection(WS_URL, timeout=5)
    print("Connected.")

    # Step 1: req_dh_params
    client_nonce = [secrets.randbelow(256) for _ in range(16)]
    req = {
        "type": "req_dh_params",
        "nonce": client_nonce,
        "p": 0,
        "q": 0,
        "fingerprint": 0
    }
    ws.send(json.dumps(req))
    print("Sent req_dh_params")

    # Receive res_dh_params
    msg = json.loads(ws.recv())
    assert msg.get("type") == "res_dh_params", f"Unexpected response: {msg}"
    print("Got res_dh_params")

    server_nonce_list = msg.get("server_nonce", [])
    # Prepare client DH
    client_priv = secrets.randbits(256)
    client_pub = modexp(DH_G, client_priv, DH_PRIME)
    client_pub_hex = format(client_pub, 'x')

    # Step 2: set_client_dh_params
    set_req = {
        "type": "set_client_dh_params",
        "nonce": msg.get("nonce"),
        "server_nonce": server_nonce_list,
        "gb": client_pub_hex
    }
    ws.send(json.dumps(set_req))
    print("Sent set_client_dh_params")

    # Receive dh_gen_ok
    msg2 = json.loads(ws.recv())
    assert msg2.get("type") == "dh_gen_ok", f"Unexpected response: {msg2}"
    print("Got dh_gen_ok")

    server_pub_hex = msg2.get("ga")
    server_pub = int(server_pub_hex, 16)
    shared_secret = modexp(server_pub, client_priv, DH_PRIME)
    shared_bytes = shared_secret.to_bytes(
        (shared_secret.bit_length()+7)//8, 'big')
    auth_key = hashlib.sha256(shared_bytes).digest()

    print("Handshake SUCCESS. Auth key:", base64.b16encode(auth_key).decode())
    ws.close()


if __name__ == "__main__":
    main()
