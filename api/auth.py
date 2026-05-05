"""Simple HMAC-signed token auth for the claims demo."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

SECRET = os.getenv("AUTH_SECRET", "dev-secret-key-change-in-prod")

_MEMBER_PASSWORD: str = os.getenv("MEMBER_PASSWORD", "member123")
_STAFF_CREDENTIALS: dict[str, str] = {
    os.getenv("STAFF_USERNAME", "staff"): os.getenv("STAFF_PASSWORD", "staff@123")
}
_MEMBER_INFO: dict[str, str] = {
    "EMP001": "Rajesh Kumar",
    "EMP002": "Priya Singh",
    "EMP003": "Amit Verma",
    "EMP004": "Sneha Reddy",
    "EMP005": "Vikram Joshi",
    "EMP006": "Kavita Nair",
    "EMP007": "Suresh Patil",
    "EMP008": "Ravi Menon",
    "EMP009": "Anita Desai",
    "EMP010": "Deepak Shah",
    "DEP001": "Sunita Kumar",
    "DEP002": "Arjun Kumar",
}


def authenticate(username: str, password: str) -> dict | None:
    """Return user dict or None if credentials are invalid."""
    if username in _STAFF_CREDENTIALS and _STAFF_CREDENTIALS[username] == password:
        return {"sub": username, "role": "staff", "name": "Staff"}
    if username in _MEMBER_INFO and password == _MEMBER_PASSWORD:
        return {"sub": username, "role": "member", "name": _MEMBER_INFO[username]}
    return None


def create_token(sub: str, role: str, name: str) -> str:
    payload = json.dumps({"sub": sub, "role": role, "name": name, "iat": int(time.time())})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_token(token: str) -> dict | None:
    try:
        payload_b64, sig = token.rsplit(".", 1)
        expected = hmac.new(SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        return json.loads(base64.urlsafe_b64decode(payload_b64.encode()).decode())
    except Exception:
        return None
