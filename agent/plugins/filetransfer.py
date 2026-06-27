"""
plugins/filetransfer.py — Transferencia de archivos entre servidor y agente.

Uso exclusivo en entornos de laboratorio autorizados.

Acciones:
  upload    {path}              Lee un archivo local y lo envia al servidor (base64 en result)
  download  {path, content_b64} Recibe contenido base64 y lo escribe en path local
  list      {path?}             Lista directorio (default: directorio actual)
  checksum  {path}              SHA-256 del archivo
  mkdir     {path}              Crea directorio (con parents)
  delete    {path, confirm}     Elimina archivo (requiere confirm=true)

Limite de tamaño: 10 MB por operacion.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
from pathlib import Path
from typing import Any

from .base import BasePlugin

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


class FileTransferPlugin(BasePlugin):
    name = "filetransfer"
    version = "1.0.0"
    author = "Aligo"
    description = "Transferencia de archivos agente<->servidor (limite 10MB)"

    def actions(self) -> list[str]:
        return ["upload", "download", "list", "checksum", "mkdir", "delete"]

    async def execute(self, action: str, args: dict[str, Any]) -> Any:
        if action == "upload":
            return await self._upload(args.get("path", ""))
        if action == "download":
            return await self._download(args.get("path", ""), args.get("content_b64", ""))
        if action == "list":
            return await self._list(args.get("path", "."))
        if action == "checksum":
            return await self._checksum(args.get("path", ""))
        if action == "mkdir":
            return await self._mkdir(args.get("path", ""))
        if action == "delete":
            return await self._delete(args.get("path", ""), args.get("confirm", False))
        return {"error": f"Accion no reconocida: {action}"}

    # ------------------------------------------------------------------

    async def _upload(self, path: str) -> dict:
        if not path:
            return {"ok": False, "error": "path requerido"}
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"ok": False, "error": f"Archivo no encontrado: {p}"}
        if not p.is_file():
            return {"ok": False, "error": f"No es un archivo: {p}"}
        size = p.stat().st_size
        if size > MAX_FILE_SIZE:
            return {"ok": False, "error": f"Archivo demasiado grande: {size} bytes (max {MAX_FILE_SIZE})"}

        data = await asyncio.to_thread(p.read_bytes)
        sha256 = hashlib.sha256(data).hexdigest()
        content_b64 = base64.b64encode(data).decode("ascii")

        return {
            "ok": True,
            "action": "upload",
            "path": str(p),
            "filename": p.name,
            "size_bytes": size,
            "sha256": sha256,
            "content_b64": content_b64,
        }

    async def _download(self, path: str, content_b64: str) -> dict:
        if not path:
            return {"ok": False, "error": "path requerido"}
        if not content_b64:
            return {"ok": False, "error": "content_b64 requerido"}

        p = Path(path).expanduser().resolve()
        try:
            data = base64.b64decode(content_b64)
        except Exception as exc:
            return {"ok": False, "error": f"Error decodificando base64: {exc}"}

        if len(data) > MAX_FILE_SIZE:
            return {"ok": False, "error": f"Contenido demasiado grande: {len(data)} bytes (max {MAX_FILE_SIZE})"}

        p.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(p.write_bytes, data)
        sha256 = hashlib.sha256(data).hexdigest()

        return {
            "ok": True,
            "action": "download",
            "path": str(p),
            "filename": p.name,
            "size_bytes": len(data),
            "sha256": sha256,
        }

    async def _list(self, path: str) -> dict:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"ok": False, "error": f"Ruta no encontrada: {p}"}
        if not p.is_dir():
            return {"ok": False, "error": f"No es un directorio: {p}"}

        entries = []
        for item in sorted(p.iterdir()):
            try:
                stat = item.stat()
                entries.append({
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "size": stat.st_size if item.is_file() else None,
                    "modified": stat.st_mtime,
                })
            except PermissionError:
                entries.append({"name": item.name, "type": "?", "error": "permission denied"})

        return {
            "ok": True,
            "path": str(p),
            "count": len(entries),
            "entries": entries,
        }

    async def _checksum(self, path: str) -> dict:
        if not path:
            return {"ok": False, "error": "path requerido"}
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"ok": False, "error": f"Archivo no encontrado: {p}"}
        if not p.is_file():
            return {"ok": False, "error": f"No es un archivo: {p}"}

        data = await asyncio.to_thread(p.read_bytes)
        return {
            "ok": True,
            "path": str(p),
            "size_bytes": len(data),
            "md5": hashlib.md5(data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    async def _mkdir(self, path: str) -> dict:
        if not path:
            return {"ok": False, "error": "path requerido"}
        p = Path(path).expanduser().resolve()
        try:
            p.mkdir(parents=True, exist_ok=True)
            return {"ok": True, "path": str(p), "created": p.exists()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def _delete(self, path: str, confirm: bool) -> dict:
        if not path:
            return {"ok": False, "error": "path requerido"}
        if not confirm:
            return {"ok": False, "error": "Debes pasar confirm=true para eliminar archivos"}
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"ok": False, "error": f"No encontrado: {p}"}
        if not p.is_file():
            return {"ok": False, "error": f"Solo se eliminan archivos (no directorios): {p}"}
        p.unlink()
        return {"ok": True, "deleted": str(p)}
