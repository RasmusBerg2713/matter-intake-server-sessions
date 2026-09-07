from datetime import date, timedelta

import pytest

from src.infrai_client import CaptchaDecision, InfraiError, unwrap
from src.matter_intake import IntakeDesk, IntakeRejected, LoginRequest, SignupRequest


def accepting(token, ip):
    return CaptchaDecision(accepted=True, code=None, metadata={"score": 0.9})


def declining(token, ip):
    return CaptchaDecision(accepted=False, code="score_below_threshold", metadata={})


def signup(deadline_in_days=2, token="widget-token"):
    return SignupRequest(
        email="Dana@Northgate-Law.example",
        password="a-long-passphrase-kept-server-side",
        captcha_token=token,
        matter_type="commercial_lease_dispute",
        filing_deadline=date.today() + timedelta(days=deadline_in_days),
    )


def test_declined_captcha_creates_no_account():
    desk = IntakeDesk(declining)
    with pytest.raises(IntakeRejected) as caught:
        desk.sign_up(signup())
    assert caught.value.reason == "captcha_declined"
    assert desk.accounts == {} and desk.sessions == {}


def test_session_survives_logout_and_login_with_normalised_email():
    desk = IntakeDesk(accepting)
    first = desk.sign_up(signup())
    desk.log_out(first.session_id)
    with pytest.raises(IntakeRejected):
        desk.resolve(first.session_id)
    second = desk.log_in(LoginRequest("dana@northgate-law.example", "a-long-passphrase-kept-server-side"))
    assert desk.resolve(second.session_id).matter.matter_type == "commercial_lease_dispute"


def test_signed_link_only_matches_the_client_it_was_issued_to():
    desk = IntakeDesk(accepting, signing_key="test-key")
    session = desk.sign_up(signup())
    delivery = desk.deliver_signed_document(session.session_id, "engagement-letter.pdf")
    assert desk.check_download(delivery, "dana@northgate-law.example")
    assert not desk.check_download(delivery, "someone-else@example.com")


def test_follow_up_covers_the_three_day_window_only():
    desk = IntakeDesk(accepting)
    desk.sign_up(signup(deadline_in_days=2))
    assert [a.email for a in desk.follow_ups_due()] == ["dana@northgate-law.example"]
    desk.accounts.clear()
    desk.sign_up(signup(deadline_in_days=30))
    assert desk.follow_ups_due() == []


def test_envelope_is_decoded_before_the_status_code():
    envelope = {"ok": False, "error": {"code": "score_below_threshold", "message": "below threshold"}}
    with pytest.raises(InfraiError) as caught:
        unwrap(envelope, 422)
    assert caught.value.code == "score_below_threshold"
    assert caught.value.status == 422
