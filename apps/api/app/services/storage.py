"""Document storage: Supabase Storage (private bucket, short-lived signed URLs) or local disk for development."""

import hashlib
import hmac
import time
from pathlib import Path
from urllib.parse import quote

import httpx

from app.core.config import get_settings
from app.core.logging import log

settings = get_settings()


def _local_sig(path: str, exp: int) -> str:
    return hmac.new(settings.app_secret.encode(), f"{path}:{exp}".encode(), hashlib.sha256).hexdigest()


def verify_local_signature(path: str, exp: int, sig: str) -> bool:
    return exp >= int(time.time()) and hmac.compare_digest(_local_sig(path, exp), sig)


class LocalStorage:
    def __init__(self) -> None:
        self.root = Path(settings.local_storage_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, path: str) -> Path:
        p = (self.root / path).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("invalid path")
        return p

    async def ensure_bucket(self) -> None:
        return None

    async def put(self, path: str, data: bytes, mime: str) -> None:
        p = self._p(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    async def get(self, path: str) -> bytes:
        return self._p(path).read_bytes()

    async def signed_url(self, path: str, expires_in: int = 60) -> str:
        exp = int(time.time()) + expires_in
        return f"{settings.public_api_url}/files/{quote(path)}?exp={exp}&sig={_local_sig(path, exp)}"


class SupabaseStorage:
    def __init__(self) -> None:
        self.base = settings.supabase_url.rstrip("/") + "/storage/v1"
        self.bucket = settings.storage_bucket
        key = settings.supabase_service_role_key
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}"}

    async def ensure_bucket(self) -> None:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{self.base}/bucket/{self.bucket}", headers=self.headers)
            if r.status_code == 200:
                return
            r = await c.post(f"{self.base}/bucket", headers=self.headers,
                             json={"id": self.bucket, "name": self.bucket, "public": False})
            if r.status_code not in (200, 201, 409):
                log.warning("bucket_create_failed", status=r.status_code, body=r.text[:200])

    async def put(self, path: str, data: bytes, mime: str) -> None:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{self.base}/object/{self.bucket}/{path}", content=data,
                             headers={**self.headers, "Content-Type": mime, "x-upsert": "true"})
            r.raise_for_status()

    async def get(self, path: str) -> bytes:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(f"{self.base}/object/authenticated/{self.bucket}/{path}", headers=self.headers)
            r.raise_for_status()
            return r.content

    async def signed_url(self, path: str, expires_in: int = 60) -> str:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{self.base}/object/sign/{self.bucket}/{path}", headers=self.headers,
                             json={"expiresIn": expires_in})
            r.raise_for_status()
            signed = r.json().get("signedURL") or r.json().get("signedUrl")
            return f"{self.base}{signed}" if signed.startswith("/") else signed


storage = SupabaseStorage() if settings.storage_mode == "supabase" else LocalStorage()
