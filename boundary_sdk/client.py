from __future__ import annotations

import os
import subprocess
import time
import json
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import requests

ALLOWED_STATUS = {"healthy", "degraded", "unavailable"}


@dataclass
class BoundaryConfig:
    base_url: str
    token: str = ""
    timeout_s: float = 3.0
    ready_wait_s: float = 8.0
    retries: int = 1
    retry_delay_s: float = 0.3
    autostart_on_demand: bool = False
    autostart_cmd: str = ""
    autostart_timeout_s: float = 20.0
    feature_enabled: bool = True
    allow_local_fallback: bool = False
    shadow_mode: bool = False
    shadow_log_dir: str = ""

    @classmethod
    def from_env(cls, prefix: str, *, default_base_url: str) -> "BoundaryConfig":
        key = prefix.strip().upper()
        if not key:
            raise ValueError("BoundaryConfig.from_env requires a non-empty prefix")

        def env(name: str, default: str = "") -> str:
            return os.getenv(f"{key}_{name}", default).strip()

        def as_bool(raw: str, default: bool) -> bool:
            text = (raw or "").strip().lower()
            if not text:
                return default
            return text in {"1", "true", "yes", "on"}

        def as_float(raw: str, default: float) -> float:
            try:
                return float(raw)
            except (TypeError, ValueError):
                return default

        retries_raw = env("RETRIES", "1")
        try:
            retries_val = max(0, int(retries_raw))
        except ValueError:
            retries_val = 1

        return cls(
            base_url=env("BASE_URL", default_base_url).rstrip("/"),
            token=env("TOKEN", ""),
            timeout_s=as_float(env("TIMEOUT_S", "3"), 3.0),
            ready_wait_s=as_float(env("READY_WAIT_S", "8"), 8.0),
            retries=retries_val,
            retry_delay_s=as_float(env("RETRY_DELAY_S", "0.3"), 0.3),
            autostart_on_demand=as_bool(env("AUTOSTART_ON_DEMAND", "false"), False),
            autostart_cmd=env("AUTOSTART_CMD", ""),
            autostart_timeout_s=as_float(env("AUTOSTART_TIMEOUT_S", "20"), 20.0),
            feature_enabled=as_bool(env("ENABLED", "true"), True),
            allow_local_fallback=as_bool(env("ALLOW_LOCAL_FALLBACK", "false"), False),
            shadow_mode=as_bool(env("SHADOW_MODE", "false"), False),
            shadow_log_dir=env("SHADOW_LOG_DIR", ""),
        )


class BoundaryClient:
    """Shared HTTP + readiness + retry behavior for feature boundaries."""

    def __init__(self, config: BoundaryConfig, *, source: str = "mfs_boundary") -> None:
        self._cfg = config
        self._source = source

    @property
    def config(self) -> BoundaryConfig:
        return self._cfg

    def headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._cfg.token:
            headers["Authorization"] = f"Bearer {self._cfg.token}"
        return headers

    def envelope(self, *, status: str, error: str | None = None, source: str | None = None) -> Dict[str, Any]:
        normalized = status if status in ALLOWED_STATUS else "degraded"
        return {
            "status": normalized,
            "source": source or self._source,
            "error": error,
        }

    def wait_until_ready(self) -> bool:
        health_url = f"{self._cfg.base_url}/health" if self._cfg.base_url else ""
        if not health_url:
            return False
        deadline = time.time() + max(0.0, self._cfg.ready_wait_s)
        while time.time() < deadline:
            try:
                resp = requests.get(health_url, timeout=1.5)
                if resp.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(0.35)
        return False

    def maybe_autostart(self) -> None:
        if not self._cfg.autostart_on_demand:
            return
        cmd = self._cfg.autostart_cmd.strip()
        if not cmd:
            return
        try:
            subprocess.run(
                cmd,
                shell=True,
                timeout=max(1.0, self._cfg.autostart_timeout_s),
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception:
            pass

    def _write_parity_log(self, event: Dict[str, Any]) -> None:
        if not self._cfg.shadow_log_dir:
            return
        log_path = Path(self._cfg.shadow_log_dir) / "parity.jsonl"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except Exception:
            pass

    def _compare_semantics(self, legacy: Any, remote: Any, path: str = "") -> List[str]:
        mismatches = []
        if type(legacy) != type(remote):
            return [path or "root"]
            
        if isinstance(legacy, dict) and isinstance(remote, dict):
            all_keys = set(legacy.keys()).union(set(remote.keys()))
            ignore_keys = {"status", "source", "error"}
            for k in all_keys:
                if k in ignore_keys:
                    continue
                curr_path = f"{path}.{k}" if path else k
                if k not in legacy or k not in remote:
                    mismatches.append(curr_path)
                else:
                    mismatches.extend(self._compare_semantics(legacy[k], remote[k], curr_path))
        elif isinstance(legacy, list) and isinstance(remote, list):
            if len(legacy) != len(remote):
                mismatches.append(path or "root[]")
            else:
                for i, (lvi, rvi) in enumerate(zip(legacy, remote)):
                    mismatches.extend(self._compare_semantics(lvi, rvi, f"{path}[{i}]"))
        elif legacy != remote:
            mismatches.append(path or "root")
            
        return mismatches

    def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        force_refresh: bool = False,
        fallback: Optional[Callable[[str | None], Dict[str, Any]]] = None,
        shadow_safe_write: bool = False,
    ) -> Dict[str, Any]:
        if not self._cfg.feature_enabled:
            disabled = self.envelope(status="degraded", error="feature_disabled")
            if fallback is not None:
                fb = fallback(disabled["error"])
                if isinstance(fb, dict):
                    fb.setdefault("status", "degraded")
                    fb.setdefault("source", "local_fallback")
                    return fb
            return disabled

        if force_refresh and self._cfg.autostart_on_demand:
            self.maybe_autostart()
            self.wait_until_ready()

        if not self._cfg.base_url:
            missing = self.envelope(status="unavailable", error="missing_base_url")
            if fallback is not None and self._cfg.allow_local_fallback:
                fb = fallback(missing["error"])
                if isinstance(fb, dict):
                    fb.setdefault("status", "degraded")
                    fb.setdefault("source", "local_fallback")
                    return fb
            return missing

        is_mutating = method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
        is_shadowing = self._cfg.shadow_mode and fallback is not None
        legacy = None
        
        if is_shadowing:
            legacy = fallback(None)
            if isinstance(legacy, dict):
                legacy.setdefault("status", "healthy")
                legacy.setdefault("source", "local_fallback")
            
            if is_mutating and not shadow_safe_write:
                return legacy

        url = f"{self._cfg.base_url}{path}"
        attempts = max(0, self._cfg.retries) + 1
        last_error: str | None = None
        remote = None

        for attempt in range(attempts):
            try:
                if method.upper() == "POST":
                    response = requests.post(
                        url,
                        headers={**self.headers(), "Content-Type": "application/json"},
                        json=payload or {},
                        timeout=max(0.1, self._cfg.timeout_s),
                    )
                else:
                    response = requests.get(url, headers=self.headers(), timeout=max(0.1, self._cfg.timeout_s))

                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("boundary response must be a JSON object")
                data.setdefault("status", "healthy")
                data.setdefault("source", self._source)
                data.setdefault("error", None)
                remote = data
                break
            except Exception as exc:
                last_error = str(exc)
                if attempt < attempts - 1:
                    time.sleep(max(0.0, self._cfg.retry_delay_s))

        if remote is None:
            remote = self.envelope(status="unavailable", error=last_error or "remote_error")
        
        if is_shadowing:
            if isinstance(legacy, dict):
                mismatches = self._compare_semantics(legacy, remote)
                event = {
                    "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    "path": path,
                    "method": method,
                    "match": len(mismatches) == 0,
                    "mismatched_keys": mismatches,
                    "legacy_status": legacy.get("status"),
                    "remote_status": remote.get("status")
                }
                self._write_parity_log(event)
            return legacy
                
        if fallback is not None and self._cfg.allow_local_fallback:
            fb = fallback(remote["error"])
            if isinstance(fb, dict):
                fb.setdefault("status", "degraded")
                fb.setdefault("source", "local_fallback")
                return fb
        return remote
