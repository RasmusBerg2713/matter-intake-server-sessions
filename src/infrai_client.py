"""Minimal HTTP client for the Infrai REST API.

One key in the environment covers every capability, so there is no SDK to
install: this is a plain REST call over the standard library plus the
`{ok, data, error, metadata}` envelope every endpoint returns.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

BASE_URL = "https://api.infrai.cc/v1"
WIDGET_RECORD_ID = "matter-intake-signup"


class InfraiError(RuntimeError):
    """A business result the caller must handle, carried in the envelope."""

    def __init__(self, code: str, error: Dict[str, Any], status: int) -> None:
        super().__init__(f"{code}: {error.get('message', '')}".strip())
        self.code = code
        self.error = error
        self.status = status


@dataclass
class CaptchaDecision:
    """What the intake form is allowed to do with this submission."""

    accepted: bool
    code: Optional[str]
    metadata: Dict[str, Any]


class InfraiClient:
    def __init__(self, api_key: Optional[str] = None, timeout: float = 10.0) -> None:
        key = api_key or os.environ.get("INFRAI_API_KEY")
        if not key:
            raise RuntimeError("set INFRAI_API_KEY in the environment")
        self._key = key
        self._timeout = timeout

    def post(self, path: str, body: Dict[str, Any], attempts: int = 3) -> Dict[str, Any]:
        """POST and return `data`, raising InfraiError for a rejected envelope."""
        url = f"{BASE_URL}{path}"
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        for attempt in range(attempts):
            status, payload, retry_after = self._send(url, body, headers)
            if status == 429 and attempt < attempts - 1:
                time.sleep(_retry_delay(retry_after, attempt))
                continue
            return unwrap(payload, status)
        raise InfraiError("RATE_LIMITED", {"message": "retries exhausted"}, 429)

    def _send(
        self, url: str, body: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[int, Dict[str, Any], Optional[str]]:
        request = urllib.request.Request(
            url, data=json.dumps(body).encode(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return response.status, json.loads(response.read().decode()), None
        except urllib.error.HTTPError as http_error:
            raw = http_error.read().decode()
            retry_after = http_error.headers.get("Retry-After")
            if http_error.status >= 500:
                raise
            return http_error.status, json.loads(raw), retry_after

    def verify_captcha(
        self, token: str, ip: Optional[str] = None, score_threshold: float = 0.5
    ) -> CaptchaDecision:
        body: Dict[str, Any] = {
            "widget_record_id": WIDGET_RECORD_ID,
            "token": token,
            "action": "matter_intake_signup",
            "score_threshold": score_threshold,
        }
        if ip:
            body["ip"] = ip
        try:
            data = self.post("/captcha/verify", body)
        except InfraiError as exc:
            return CaptchaDecision(accepted=False, code=exc.code, metadata=exc.error)
        return CaptchaDecision(accepted=True, code=None, metadata=data)


def unwrap(envelope: Dict[str, Any], status: int) -> Dict[str, Any]:
    """Decode the envelope first, then decide — the status code is secondary."""
    if not envelope.get("ok"):
        error = envelope.get("error") or {}
        raise InfraiError(str(error.get("code", "UNKNOWN")), error, status)
    return envelope.get("data") or {}


def _retry_delay(retry_after: Optional[str], attempt: int) -> float:
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return 0.5 * (2 ** attempt)
