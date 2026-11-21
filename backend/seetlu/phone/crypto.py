"""Raw notification sealing (docs/09): RSA-OAEP(SHA-256, MGF1-SHA-256) wraps an AES-256-GCM key.

Blob layout (base64 in JSON):
    0x01 | key_len (2 bytes, big endian) | wrapped key | iv (12) | ciphertext+tag

The phone only has the public key; the private key is given to the worker only (RAW_PRIVATE_KEY_B64).
"""

import base64
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = 1
_OAEP = padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)


def generate_keypair() -> tuple[str, str]:
    """(public SPKI DER base64, private PKCS8 DER base64) — single-line values for env vars."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    priv = key.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return base64.b64encode(pub).decode(), base64.b64encode(priv).decode()


def seal(public_b64: str, plaintext: str) -> bytes:
    pub = serialization.load_der_public_key(base64.b64decode(public_b64))
    assert isinstance(pub, rsa.RSAPublicKey)
    key, iv = AESGCM.generate_key(bit_length=256), os.urandom(12)
    wrapped = pub.encrypt(key, _OAEP)
    return (
        bytes([VERSION])
        + len(wrapped).to_bytes(2, "big")
        + wrapped
        + iv
        + AESGCM(key).encrypt(iv, plaintext.encode(), None)
    )


def open_sealed(private_b64: str, blob: bytes) -> str:
    if not blob or blob[0] != VERSION:
        raise ValueError("unknown blob version")
    n = int.from_bytes(blob[1:3], "big")
    wrapped, iv, ct = blob[3 : 3 + n], blob[3 + n : 15 + n], blob[15 + n :]
    priv = serialization.load_der_private_key(base64.b64decode(private_b64), password=None)
    assert isinstance(priv, rsa.RSAPrivateKey)
    return AESGCM(priv.decrypt(wrapped, _OAEP)).decrypt(iv, ct, None).decode()


def valid_blob(blob: bytes) -> bool:
    """Shape check only (the API never holds the private key)."""
    if len(blob) < 3 or blob[0] != VERSION:
        return False
    n = int.from_bytes(blob[1:3], "big")
    return n >= 128 and len(blob) >= 3 + n + 12 + 16


if __name__ == "__main__":  # python -m seetlu.phone.crypto → env lines for .env
    pub, priv = generate_keypair()
    print(f"RAW_PUBLIC_KEY_B64={pub}")
    print(f"RAW_PRIVATE_KEY_B64={priv}")
