"""Runnable walkthrough: signup -> session -> signed delivery -> follow-up.

    export INFRAI_API_KEY=...
    export INTAKE_CAPTCHA_TOKEN=...   # the token your widget produced
    python3 intake_walkthrough.py
"""

from __future__ import annotations

import os
from datetime import date, timedelta

from src.infrai_client import InfraiClient
from src.matter_intake import IntakeDesk, LoginRequest, SignupRequest


def main() -> None:
    client = InfraiClient()
    desk = IntakeDesk(
        captcha_verifier=lambda token, ip: client.verify_captcha(token, ip=ip, score_threshold=0.5)
    )

    session = desk.sign_up(
        SignupRequest(
            email="dana@northgate-law.example",
            password="a-long-passphrase-kept-server-side",
            captcha_token=os.environ["INTAKE_CAPTCHA_TOKEN"],
            matter_type="commercial_lease_dispute",
            filing_deadline=date.today() + timedelta(days=2),
            ip="203.0.113.24",
        )
    )
    print("session opened:", session.session_id[:12] + "...", "expires", session.expires_at)

    delivery = desk.deliver_signed_document(session.session_id, "engagement-letter.pdf")
    print("signed link valid:", desk.check_download(delivery, "dana@northgate-law.example"))

    desk.log_out(session.session_id)
    session = desk.log_in(
        LoginRequest("dana@northgate-law.example", "a-long-passphrase-kept-server-side")
    )
    print("logged back in:", session.session_id[:12] + "...")

    for account in desk.follow_ups_due():
        print("follow-up due:", account.email, account.matter.filing_deadline)


if __name__ == "__main__":
    main()
