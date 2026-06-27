"""
crypto.py — Módulo de cifrado end-to-end del C2.

Esquema:
  1. Handshake: el agente cifra una clave de sesión AES-256 con la clave
     pública RSA del servidor (RSA-OAEP / SHA-256).
  2. Sesión: todo mensaje viaja como AES-256-GCM (clave de sesión, nonce
     único por mensaje, AAD = agent_id + message_id).
  3. Firma: cada mensaje se firma con HMAC-SHA256 derivado de la clave
     de sesión (suficiente en simétrico) para detectar tampering.

El servidor también puede generar/firmar con su clave privada RSA-PSS
para autenticidad de comandos enviados al agente.
"""

from __future__ import annotations

import base64
import hmac
import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RSA_KEY_SIZE = 3072
AES_KEY_SIZE = 32  # 256 bits
AES_NONCE_SIZE = 12


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))


# ---------------------------------------------------------------------------
# RSA key management
# ---------------------------------------------------------------------------

def generate_rsa_keypair() -> tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    priv = rsa.generate_private_key(public_exponent=65537, key_size=RSA_KEY_SIZE)
    return priv, priv.public_key()


def save_keypair(priv: rsa.RSAPrivateKey, priv_path: Path, pub_path: Path) -> None:
    priv_path.parent.mkdir(parents=True, exist_ok=True)
    priv_path.write_bytes(
        priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    pub_path.write_bytes(
        priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def load_or_create_keypair(priv_path: Path, pub_path: Path) -> rsa.RSAPrivateKey:
    if priv_path.exists() and pub_path.exists():
        return serialization.load_pem_private_key(priv_path.read_bytes(), password=None)
    priv, _ = generate_rsa_keypair()
    save_keypair(priv, priv_path, pub_path)
    return priv


def load_public_key_pem(pem_bytes: bytes) -> rsa.RSAPublicKey:
    return serialization.load_pem_public_key(pem_bytes)


def export_public_key_pem(pub: rsa.RSAPublicKey) -> bytes:
    return pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


# ---------------------------------------------------------------------------
# Hybrid handshake (agent -> server)
# ---------------------------------------------------------------------------

def wrap_session_key(server_pub: rsa.RSAPublicKey, session_key: bytes) -> bytes:
    return server_pub.encrypt(
        session_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )


def unwrap_session_key(server_priv: rsa.RSAPrivateKey, wrapped: bytes) -> bytes:
    return server_priv.decrypt(
        wrapped,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )


def new_session_key() -> bytes:
    return os.urandom(AES_KEY_SIZE)


# ---------------------------------------------------------------------------
# Symmetric envelope (AES-256-GCM + HMAC tag)
# ---------------------------------------------------------------------------

@dataclass
class Envelope:
    """Sobre cifrado para transporte sobre cualquier canal."""

    nonce: bytes
    ciphertext: bytes
    aad: bytes

    def to_dict(self) -> dict[str, str]:
        return {
            "nonce": b64e(self.nonce),
            "ct": b64e(self.ciphertext),
            "aad": b64e(self.aad),
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "Envelope":
        return cls(
            nonce=b64d(data["nonce"]),
            ciphertext=b64d(data["ct"]),
            aad=b64d(data["aad"]),
        )


def encrypt(session_key: bytes, plaintext: bytes, aad: bytes) -> Envelope:
    nonce = os.urandom(AES_NONCE_SIZE)
    ct = AESGCM(session_key).encrypt(nonce, plaintext, aad)
    return Envelope(nonce=nonce, ciphertext=ct, aad=aad)


def decrypt(session_key: bytes, env: Envelope) -> bytes:
    return AESGCM(session_key).decrypt(env.nonce, env.ciphertext, env.aad)


# ---------------------------------------------------------------------------
# Message signature (HMAC over session_key)
# ---------------------------------------------------------------------------

def sign(session_key: bytes, message_bytes: bytes) -> str:
    mac = hmac.new(session_key, message_bytes, sha256).digest()
    return b64e(mac)


def verify_signature(session_key: bytes, message_bytes: bytes, signature_b64: str) -> bool:
    expected = hmac.new(session_key, message_bytes, sha256).digest()
    try:
        return hmac.compare_digest(expected, b64d(signature_b64))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# RSA-PSS plugin signing (Mejora 3)
# Firma el payload de un plugin con la clave privada RSA del servidor.
# El agente verifica con la clave pública recibida en el handshake.
# ---------------------------------------------------------------------------

def sign_plugin(server_priv: rsa.RSAPrivateKey, plugin_code: bytes) -> str:
    """Firma el código de un plugin con RSA-PSS + SHA-256. Retorna base64."""
    sig = server_priv.sign(
        plugin_code,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    return b64e(sig)


def verify_plugin_signature(server_pub, plugin_code: bytes, signature_b64: str) -> bool:
    """Verifica la firma RSA-PSS de un plugin. Retorna True si válida."""
    try:
        server_pub.verify(
            b64d(signature_b64),
            plugin_code,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        return True
    except Exception:
        return False
