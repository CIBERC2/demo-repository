"""
solana_anchor.py — Ancla el block_hash del audit trail en Solana.

Redes soportadas (SOLANA_NETWORK env var):
  devnet       (default) — red de pruebas, airdrop automatico disponible
  mainnet-beta           — red principal, requiere SOL real (~$0.00025/tx)
  testnet                — red de pruebas alternativa

Activar en .env:
  SOLANA_ANCHOR=true
  SOLANA_NETWORK=devnet        # o mainnet-beta
  SOLANA_WALLET_PATH=solana_wallet.json
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("solana_anchor")

# Endpoints por red
_RPC_ENDPOINTS = {
    "devnet": [
        "https://api.devnet.solana.com",
        "https://rpc.ankr.com/solana_devnet",
    ],
    "testnet": [
        "https://api.testnet.solana.com",
    ],
    "mainnet-beta": [
        "https://api.mainnet-beta.solana.com",
        "https://rpc.ankr.com/solana",
        "https://solana-mainnet.g.alchemy.com/v2/demo",
    ],
}

MEMO_PROGRAM_STR = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
MIN_LAMPORTS     = 5_000_000   # 0.005 SOL (solo relevante en devnet/testnet)


def _is_enabled() -> bool:
    return os.getenv("SOLANA_ANCHOR", "false").lower() == "true"


def _get_network() -> str:
    net = os.getenv("SOLANA_NETWORK", "devnet").lower().strip()
    if net not in _RPC_ENDPOINTS:
        logger.warning("SOLANA_NETWORK='%s' no reconocida, usando 'devnet'", net)
        return "devnet"
    return net


def _get_rpc_urls() -> list[str]:
    return _RPC_ENDPOINTS[_get_network()]


def _wallet_path() -> Path:
    return Path(os.getenv("SOLANA_WALLET_PATH", "solana_wallet.json"))

_solana_imports: Optional[dict] = None

# Signatures guardadas en memoria: block_id → tx_signature
_sig_cache: dict[int, str] = {}


def get_signatures() -> dict[int, str]:
    """Retorna todas las firmas Solana ancladas en esta sesión."""
    return dict(_sig_cache)


def _imports() -> dict:
    global _solana_imports
    if _solana_imports is not None:
        return _solana_imports
    try:
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey
        from solders.instruction import Instruction, AccountMeta
        from solders.message import MessageV0
        from solders.transaction import VersionedTransaction
        from solana.rpc.async_api import AsyncClient
        from solana.rpc.commitment import Confirmed
        from solana.rpc.types import TxOpts
        _solana_imports = dict(
            Keypair=Keypair, Pubkey=Pubkey,
            Instruction=Instruction, AccountMeta=AccountMeta,
            MessageV0=MessageV0, VersionedTransaction=VersionedTransaction,
            AsyncClient=AsyncClient, Confirmed=Confirmed, TxOpts=TxOpts,
        )
        return _solana_imports
    except ImportError as exc:
        raise RuntimeError(f"solana/solders no disponibles: {exc}") from exc


# ── Wallet ────────────────────────────────────────────────────────────────────

_cached_kp = None


def load_or_create_wallet():
    global _cached_kp
    if _cached_kp is not None:
        return _cached_kp, str(_cached_kp.pubkey())

    Keypair = _imports()["Keypair"]
    wp = _wallet_path()
    if wp.exists():
        secret = json.loads(wp.read_text())
        kp = Keypair.from_bytes(bytes(secret))
        logger.info("Wallet Devnet cargada: %s", kp.pubkey())
    else:
        kp = Keypair()
        wp.write_text(json.dumps(list(bytes(kp))))
        logger.info("Nueva wallet Devnet creada: %s  →  %s", kp.pubkey(), wp)

    _cached_kp = kp
    return kp, str(kp.pubkey())


# ── Airdrop ───────────────────────────────────────────────────────────────────

async def _airdrop_via_rpc(pubkey_str: str, url: str) -> bool:
    """
    Solicita airdrop vía JSON-RPC usando httpx estándar (no httpx2 de solana-py).
    """
    try:
        import httpx
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "requestAirdrop",
            "params": [pubkey_str, 1_000_000_000],
        }
        async with httpx.AsyncClient(timeout=20) as hc:
            r = await hc.post(url, json=payload)
            data = r.json()
            if "error" in data:
                logger.warning("Airdrop RPC error en %s: %s", url, data["error"])
                return False
            logger.info("Airdrop RPC OK (%s): %s", url, str(data.get("result", ""))[:60])
            return True
    except Exception as exc:
        logger.warning("Airdrop vía %s falló: %s", url, exc)
        return False


async def _ensure_funded(kp, client, rpc_url: str) -> int:
    S = _imports()
    resp = await client.get_balance(kp.pubkey(), commitment=S["Confirmed"])
    balance = resp.value
    pubkey_str = str(kp.pubkey())
    network = _get_network()

    if balance < MIN_LAMPORTS:
        if network == "mainnet-beta":
            logger.warning(
                "Balance bajo en MAINNET (%.6f SOL). "
                "Deposita SOL en %s para continuar anclando bloques.",
                balance / 1e9, pubkey_str,
            )
            return balance

        logger.info("Balance bajo (%.6f SOL) — solicitando airdrop en %s…", balance / 1e9, network)
        for url in _get_rpc_urls():
            if await _airdrop_via_rpc(pubkey_str, url):
                break

        await asyncio.sleep(8)
        resp2 = await client.get_balance(kp.pubkey(), commitment=S["Confirmed"])
        balance = resp2.value
        logger.info("Balance despues de airdrop: %.6f SOL", balance / 1e9)

    return balance


# ── Ancla un bloque ───────────────────────────────────────────────────────────

async def anchor_hash(block_hash: str, block_id: int) -> Optional[str]:
    """
    Publica block_hash como memo en Solana Devnet.
    Retorna la firma de la tx (str) o None si está desactivado/falla.
    """
    if not _is_enabled():
        return None

    S = _imports()
    AsyncClient       = S["AsyncClient"]
    Confirmed         = S["Confirmed"]
    Pubkey            = S["Pubkey"]
    Instruction       = S["Instruction"]
    AccountMeta       = S["AccountMeta"]
    MessageV0         = S["MessageV0"]
    VersionedTransaction = S["VersionedTransaction"]
    TxOpts            = S["TxOpts"]

    network = _get_network()
    for rpc_url in _get_rpc_urls():
        try:
            kp, _ = load_or_create_wallet()
            async with AsyncClient(rpc_url) as client:
                await _ensure_funded(kp, client, rpc_url)

                bh_resp = await client.get_latest_blockhash(commitment=Confirmed)
                recent_blockhash = bh_resp.value.blockhash

                memo_text = f"openc2:block#{block_id}:{block_hash}"
                MEMO_PROG = Pubkey.from_string(MEMO_PROGRAM_STR)
                memo_ix = Instruction(
                    program_id=MEMO_PROG,
                    accounts=[AccountMeta(pubkey=kp.pubkey(), is_signer=True, is_writable=False)],
                    data=memo_text.encode("utf-8"),
                )

                msg = MessageV0.try_compile(
                    payer=kp.pubkey(),
                    instructions=[memo_ix],
                    address_lookup_table_accounts=[],
                    recent_blockhash=recent_blockhash,
                )
                tx = VersionedTransaction(msg, [kp])
                opts = TxOpts(skip_preflight=True, preflight_commitment=Confirmed)
                tx_resp = await client.send_transaction(tx, opts=opts)
                sig = str(tx_resp.value)
                _sig_cache[block_id] = sig
                explorer_cluster = "" if network == "mainnet-beta" else f"?cluster={network}"
                explorer = f"https://explorer.solana.com/tx/{sig}{explorer_cluster}"
                logger.info("Block #%d anclado en %s (%s) → %s", block_id, network, rpc_url, explorer)
                return sig

        except Exception as exc:
            logger.warning("RPC %s fallo para block #%d: %s", rpc_url, block_id, exc)

    logger.error("Block #%d no pudo anclarse en ninguna RPC de %s", block_id, network)
    return None


# ── Info pública ──────────────────────────────────────────────────────────────

def wallet_info() -> dict:
    """Estado de la wallet sin conectar a la red. Seguro llamar en cualquier momento."""
    if not _is_enabled():
        return {"enabled": False, "message": "Activar SOLANA_ANCHOR=true en .env"}
    try:
        network = _get_network()
        _, pubkey = load_or_create_wallet()
        wp = str(_wallet_path())
        cluster_param = "" if network == "mainnet-beta" else f"?cluster={network}"
        return {
            "enabled": True,
            "network": network,
            "pubkey": pubkey,
            "wallet_file": wp,
            "rpc_urls": _get_rpc_urls(),
            "is_mainnet": network == "mainnet-beta",
            "explorer": f"https://explorer.solana.com/address/{pubkey}{cluster_param}",
            "warning": "Mainnet activo — cada tx tiene costo real en SOL" if network == "mainnet-beta" else None,
        }
    except Exception as exc:
        return {"enabled": True, "error": str(exc)}
