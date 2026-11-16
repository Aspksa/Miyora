"""Cloud.ru Foundation Models configuration and authenticated model catalog."""
from __future__ import annotations
import base64
import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from app.core import database

BASE_URL = "https://foundation-models.api.cloud.ru/v1"
SECRET_PATH_NAME = "cloudru.key"
MAX_KEY_LENGTH = 4096

class CloudError(ValueError):
    pass

def _secret_path() -> Path:
    return database.DB_PATH.parent / SECRET_PATH_NAME

def _protect(data: bytes, decrypt: bool = False) -> bytes:
    if sys.platform != "win32":
        return data
    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]
    def blob(value: bytes):
        buffer = ctypes.create_string_buffer(value)
        return BLOB(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer
    source, keep = blob(data)
    target = BLOB()
    crypt = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if decrypt:
        ok = crypt(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target))
    else:
        ok = crypt(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target))
    if not ok:
        raise CloudError("windows_secret_protection_failed")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)

def _read_key() -> str:
    path = _secret_path()
    if not path.exists():
        return ""
    try:
        return _protect(base64.b64decode(path.read_bytes(), validate=True), decrypt=True).decode("utf-8")
    except (OSError, ValueError, UnicodeError) as exc:
        raise CloudError("stored_key_unavailable") from exc

def save_key(key: str) -> None:
    if not isinstance(key, str) or not 8 <= len(key.strip()) <= MAX_KEY_LENGTH or any(c in key for c in "\r\n"):
        raise CloudError("invalid_api_key")
    path = _secret_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = base64.b64encode(_protect(key.strip().encode("utf-8")))
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        os.replace(temp, path)
        if sys.platform != "win32":
            path.chmod(0o600)
    finally:
        temp.unlink(missing_ok=True)

def clear_key() -> None:
    _secret_path().unlink(missing_ok=True)

def _setting() -> str:
    with database.connect() as db:
        row = db.execute("SELECT value FROM settings WHERE key='cloudru_model'").fetchone()
        return row[0] if row else ""

def settings() -> dict:
    return {"provider": "Cloud.ru", "base_url": BASE_URL,
            "has_key": bool(_read_key()), "model": _setting(),
            "key_storage": "Windows DPAPI" if sys.platform == "win32" else "local file (0600)"}

def set_model(model: str) -> dict:
    if not isinstance(model, str) or len(model) > 200 or any(c in model for c in "\r\n\x00"):
        raise CloudError("invalid_model")
    with database.connect() as db:
        db.execute("INSERT INTO settings(key,value) VALUES ('cloudru_model',?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",
                   (model,))
        db.commit()
    return settings()

def models() -> dict:
    key = _read_key()
    if not key:
        raise CloudError("api_key_required")
    request = Request(BASE_URL + "/models", headers={"Authorization": "Bearer " + key,
                                                       "Accept": "application/json"})
    try:
        with urlopen(request, timeout=12) as response:
            payload = response.read(1024 * 1024 + 1)
            if len(payload) > 1024 * 1024:
                raise CloudError("response_too_large")
            data = json.loads(payload)
    except HTTPError as exc:
        raise CloudError("cloudru_auth_failed" if exc.code in (401, 403) else "cloudru_http_" + str(exc.code)) from None
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise CloudError("cloudru_unavailable") from exc
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise CloudError("invalid_model_catalog")
    names = sorted({entry["id"] for entry in data["data"]
                    if isinstance(entry, dict) and isinstance(entry.get("id"), str)
                    and 0 < len(entry["id"]) <= 200})
    return {"models": names[:500]}
