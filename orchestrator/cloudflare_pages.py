"""Direct Upload client for publishing static projects to Cloudflare Pages."""

import base64
import json
import mimetypes
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests
from blake3 import blake3

from elite_cloud.config import (
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_API_TOKEN,
    CLOUDFLARE_PAGES_ENABLED,
)


class CloudflarePagesError(RuntimeError):
    """A safe, user-displayable Cloudflare Pages deployment error."""


class CloudflarePagesDeployer:
    API_BASE = "https://api.cloudflare.com/client/v4"
    _IGNORED_PARTS = {".git", ".wrangler", "node_modules", "__pycache__"}

    def __init__(self) -> None:
        self.account_id = CLOUDFLARE_ACCOUNT_ID.strip()
        self.api_token = CLOUDFLARE_API_TOKEN.strip()

    @property
    def configured(self) -> bool:
        return bool(CLOUDFLARE_PAGES_ENABLED and self.account_id and self.api_token)

    @staticmethod
    def project_name(value: str) -> str:
        name = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
        name = re.sub(r"-+", "-", name)[:58].rstrip("-")
        if not name:
            raise CloudflarePagesError("The project name cannot be converted to a valid Pages name.")
        return name

    def _headers(self, token: str = "") -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token or self.api_token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _error_message(response: requests.Response) -> str:
        try:
            payload = response.json()
            errors = payload.get("errors") or []
            if errors:
                return "; ".join(str(error.get("message", error)) for error in errors)
            return str(payload.get("message") or response.reason)
        except ValueError:
            return response.reason or "Unknown Cloudflare API error"

    def _request(self, method: str, path: str, *, token: str = "", **kwargs: Any) -> Dict[str, Any]:
        headers = kwargs.pop("headers", self._headers(token))
        try:
            response = requests.request(
                method,
                f"{self.API_BASE}{path}",
                headers=headers,
                timeout=(15, 120),
                **kwargs,
            )
        except requests.RequestException as exc:
            raise CloudflarePagesError(f"Could not reach Cloudflare Pages: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise CloudflarePagesError(
                f"Cloudflare returned an invalid response (HTTP {response.status_code})."
            ) from exc

        if not response.ok or payload.get("success") is False:
            raise CloudflarePagesError(
                f"Cloudflare API error (HTTP {response.status_code}): {self._error_message(response)}"
            )
        return payload

    def _ensure_project(self, name: str) -> None:
        path = f"/accounts/{self.account_id}/pages/projects/{name}"
        try:
            response = requests.get(
                f"{self.API_BASE}{path}", headers=self._headers(), timeout=(15, 60)
            )
        except requests.RequestException as exc:
            raise CloudflarePagesError(f"Could not reach Cloudflare Pages: {exc}") from exc
        if response.status_code == 404:
            self._request(
                "POST",
                f"/accounts/{self.account_id}/pages/projects",
                json={"name": name, "production_branch": "main"},
            )
            return
        if not response.ok:
            raise CloudflarePagesError(
                f"Could not check Cloudflare Pages project (HTTP {response.status_code}): "
                f"{self._error_message(response)}"
            )
        try:
            if response.json().get("success") is False:
                raise CloudflarePagesError(self._error_message(response))
        except ValueError as exc:
            raise CloudflarePagesError("Cloudflare returned an invalid project response.") from exc

    def _collect_assets(self, root: Path) -> List[Tuple[str, bytes, str, str]]:
        assets: List[Tuple[str, bytes, str, str]] = []
        for file_path in sorted(root.rglob("*")):
            relative = file_path.relative_to(root)
            if not file_path.is_file() or any(part in self._IGNORED_PARTS for part in relative.parts):
                continue
            content = file_path.read_bytes()
            extension = file_path.suffix.lstrip(".")
            encoded = base64.b64encode(content)
            digest = blake3(encoded + extension.encode("utf-8")).hexdigest()[:32]
            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            assets.append((relative.as_posix(), content, digest, content_type))
        if not assets:
            raise CloudflarePagesError("The static project contains no deployable files.")
        return assets

    def deploy(self, directory: Path, requested_name: str) -> Dict[str, str]:
        if not self.configured:
            raise CloudflarePagesError(
                "Cloudflare Pages is not configured. Add CLOUDFLARE_ACCOUNT_ID and "
                "CLOUDFLARE_API_TOKEN to Streamlit Secrets."
            )

        root = Path(directory).resolve()
        if not (root / "index.html").is_file():
            raise CloudflarePagesError("Static deployment requires an index.html file at ZIP root.")

        name = self.project_name(requested_name)
        assets = self._collect_assets(root)
        self._ensure_project(name)

        upload_token_payload = self._request(
            "GET", f"/accounts/{self.account_id}/pages/projects/{name}/upload-token"
        )
        upload_token = upload_token_payload.get("result", {}).get("jwt")
        if not upload_token:
            raise CloudflarePagesError("Cloudflare did not return an asset upload token.")

        hashes = list(dict.fromkeys(asset[2] for asset in assets))
        missing = set()
        for start in range(0, len(hashes), 1000):
            missing_payload = self._request(
                "POST",
                "/pages/assets/check-missing",
                token=upload_token,
                json={"hashes": hashes[start:start + 1000]},
            )
            missing.update(missing_payload.get("result") or [])

        # Avoid duplicate uploads when multiple paths contain identical bytes.
        pending_by_hash = {asset[2]: asset for asset in assets if asset[2] in missing}
        pending = list(pending_by_hash.values())
        batches: List[List[Tuple[str, bytes, str, str]]] = []
        batch: List[Tuple[str, bytes, str, str]] = []
        batch_bytes = 0
        for asset in pending:
            asset_bytes = len(asset[1])
            if asset_bytes > 25 * 1024 * 1024:
                raise CloudflarePagesError(
                    f"{asset[0]} exceeds the Cloudflare Pages 25 MiB per-file limit."
                )
            if batch and (len(batch) >= 50 or batch_bytes + asset_bytes > 20 * 1024 * 1024):
                batches.append(batch)
                batch = []
                batch_bytes = 0
            batch.append(asset)
            batch_bytes += asset_bytes
        if batch:
            batches.append(batch)

        for batch in batches:
            upload_body = [
                {
                    "key": digest,
                    "value": base64.b64encode(content).decode("ascii"),
                    "metadata": {"contentType": content_type},
                    "base64": True,
                }
                for _, content, digest, content_type in batch
            ]
            self._request("POST", "/pages/assets/upload", token=upload_token, json=upload_body)

        for start in range(0, len(hashes), 1000):
            self._request(
                "POST",
                "/pages/assets/upsert-hashes",
                token=upload_token,
                json={"hashes": hashes[start:start + 1000]},
            )

        manifest = {f"/{relative}": digest for relative, _, digest, _ in assets}
        multipart_headers = {"Authorization": f"Bearer {self.api_token}"}
        fields = {
            "manifest": (None, json.dumps(manifest), "application/json"),
            "branch": (None, "main"),
            "commit_dirty": (None, "false"),
            "commit_message": (None, "Deployed via Elite Hosting Telegram Bot"),
        }
        deployment = self._request(
            "POST",
            f"/accounts/{self.account_id}/pages/projects/{name}/deployments",
            headers=multipart_headers,
            files=fields,
        ).get("result", {})

        return {
            "project_name": name,
            "deployment_id": str(deployment.get("id", "")),
            "url": f"https://{name}.pages.dev",
        }


cloudflare_pages = CloudflarePagesDeployer()

