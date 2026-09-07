"""Matter intake for a small legal-tech practice.

Signup and login live entirely on the server: the browser only ever holds an
opaque session id, and every piece of matter state hangs off the account row.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

SESSION_TTL = timedelta(hours=8)
DOWNLOAD_TTL = timedelta(minutes=15)
FOLLOW_UP_LEAD = timedelta(days=3)


class IntakeRejected(Exception):
    """Raised when a signup or login must not proceed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SignupRequest:
    email: str
    password: str
    captcha_token: str
    matter_type: str
    filing_deadline: date
    ip: Optional[str] = None


@dataclass(frozen=True)
class LoginRequest:
    email: str
    password: str


@dataclass
class Matter:
    matter_type: str
    filing_deadline: date
    documents: List[str] = field(default_factory=list)


@dataclass
class Account:
    email: str
    password_hash: str
    salt: str
    matter: Matter


@dataclass
class Session:
    session_id: str
    email: str
    expires_at: datetime


@dataclass
class SignedDelivery:
    """A one-shot link the client emails to the signing party."""

    document: str
    token: str
    expires_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()


class IntakeDesk:
    """In-memory store so the example runs with no database attached."""

    def __init__(self, captcha_verifier, signing_key: Optional[str] = None) -> None:
        self._verify_captcha = captcha_verifier
        self._signing_key = (signing_key or os.environ.get("INTAKE_SIGNING_KEY", "local-dev-key")).encode()
        self.accounts: Dict[str, Account] = {}
        self.sessions: Dict[str, Session] = {}

    # --- signup / login -------------------------------------------------
    def sign_up(self, request: SignupRequest) -> Session:
        email = request.email.strip().lower()
        if email in self.accounts:
            raise IntakeRejected("account_exists")
        decision = self._verify_captcha(request.captcha_token, request.ip)
        if not decision.accepted:
            raise IntakeRejected("captcha_declined")
        salt = secrets.token_hex(16)
        self.accounts[email] = Account(
            email=email,
            password_hash=hash_password(request.password, salt),
            salt=salt,
            matter=Matter(matter_type=request.matter_type, filing_deadline=request.filing_deadline),
        )
        return self._open_session(email)

    def log_in(self, request: LoginRequest) -> Session:
        account = self.accounts.get(request.email.strip().lower())
        if account is None:
            raise IntakeRejected("no_such_account")
        if not hmac.compare_digest(
            account.password_hash, hash_password(request.password, account.salt)
        ):
            raise IntakeRejected("bad_password")
        return self._open_session(account.email)

    def resolve(self, session_id: str) -> Account:
        session = self.sessions.get(session_id)
        if session is None or session.expires_at <= _now():
            self.sessions.pop(session_id, None)
            raise IntakeRejected("session_expired")
        return self.accounts[session.email]

    def log_out(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    def _open_session(self, email: str) -> Session:
        session = Session(secrets.token_urlsafe(32), email, _now() + SESSION_TTL)
        self.sessions[session.session_id] = session
        return session

    # --- documents and deadlines ---------------------------------------
    def deliver_signed_document(self, session_id: str, document: str) -> SignedDelivery:
        account = self.resolve(session_id)
        account.matter.documents.append(document)
        expires_at = _now() + DOWNLOAD_TTL
        return SignedDelivery(document, self.sign_download(account.email, document, expires_at), expires_at)

    def sign_download(self, email: str, document: str, expires_at: datetime) -> str:
        payload = f"{email}|{document}|{int(expires_at.timestamp())}".encode()
        return hmac.new(self._signing_key, payload, hashlib.sha256).hexdigest()

    def check_download(self, delivery: SignedDelivery, email: str) -> bool:
        if delivery.expires_at <= _now():
            return False
        expected = self.sign_download(email, delivery.document, delivery.expires_at)
        return hmac.compare_digest(expected, delivery.token)

    def follow_ups_due(self, today: Optional[date] = None) -> List[Account]:
        today = today or _now().date()
        return [
            account
            for account in self.accounts.values()
            if account.matter.filing_deadline - today <= FOLLOW_UP_LEAD
            and account.matter.filing_deadline >= today
        ]
