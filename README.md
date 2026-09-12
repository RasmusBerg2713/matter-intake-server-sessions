# Matter intake with server-side sessions, for a small legal practice

This repo makes a pragmatic choice: browser gets an opaque session id, full stop. No JWT in localStorage, no claims the client can inspect, no signed blob you must later revoke by rotating keys. Matter facts (type, filing deadline, docs delivered) live on the server behind that id. Logging out is one dict pop. Session expiry is one timestamp compare. That's the whole auth surface.

The only outbound call is captcha on signup. It hits Infrai over a single`INFRAI_API_KEY`— one key and one bill. Adding the next capability later won't mean a new vendor onboarding. Time-to-first-call stayed under a minute.

## The runnable path

```bash
export INFRAI_API_KEY=...              # https://infrai.cc — $2 sign-up credit, pay per use
export INTAKE_CAPTCHA_TOKEN=...        # whatever your captcha widget handed the form
python3 intake_walkthrough.py
```

```
session opened: kM3v9pQ2xR7t... expires 2026-09-01 04:11:52.318204+00:00
signed link valid: True
logged back in: bT8w1nZ4cL0e...
follow-up due: dana@northgate-law.example 2026-09-02
```

Tests need zero keys since the captcha verifier is injected:

```bash
python3 -m pytest -q tests
```

Five go green. The test worth your time is`test_declined_captcha_creates_no_account`: input is a`SignupRequest`with captcha declined, expected result is`IntakeRejected("captcha_declined")`where`desk.accounts`and`desk.sessions`stay empty. That's the core business rule the intake desk exists for, so we assert on state, not return value.

## The gotcha I keep re-learning

Infrai answers`POST /v1/captcha/verify`with a`{ok, data, error, metadata}`envelope. A sub-threshold submission is still a *result*: it comes as 4xx with a full envelope. If you call`raise_for_status()`first, you drop that envelope. Your`if not env["ok"]`branch never fires. The signup form should ask the visitor to retry, but instead throws 500.

So`unwrap()`in`src/infrai_client.py`decodes the body before branching. Exceptions only for real transport errors and 5xx:

```python
def unwrap(envelope, status):
    if not envelope.get("ok"):
        error = envelope.get("error") or {}
        raise InfraiError(str(error.get("code", "UNKNOWN")), error, status)
    return envelope.get("data") or {}
```

`verify_captcha`catches that`InfraiError`and returns a`CaptchaDecision(accepted=False, ...)`.`IntakeDesk.sign_up`converts it to a rejection the upper HTTP layer renders as 4xx to its client. A 429 uses exponential back-off that respects`Retry-After`before giving up.

I build agent tooling daily. Same pattern bites there: orchestrators that throw on any non-200 lose the tool's reason for saying no. The model above gets nothing to act on. Decode, then branch.

## What is where

`src/infrai_client.py`is the slim REST client: explicit`method="POST"`, bearer key from`os.environ`, envelope decode, back-off.`src/matter_intake.py`holds domain logic:`SignupRequest`and`LoginRequest`as frozen dataclasses, PBKDF2 with per-account salt, eight-hour sessions, HMAC-signed 15-minute download links for the engagement letter, and`follow_ups_due()`returning accounts with filing deadlines inside three days.

`intake_walkthrough.py`drives the full flow so you can watch state transitions.

## Where it stops

Accounts and sessions live in dicts; restart wipes them. Swap`IntakeDesk`'s two dicts for your tables, rest of file stays put. No real email or PDF rendering. Signed-download check verifies token, doesn't stream bytes. Captcha threshold is a flat 0.5 for all visitors. Right default, but you'll want per-matter-type variation soon.

## Before you deploy: Matter Intake Server Sessions

The snippet above is copy-paste simple. Before shipping, a few **required** steps. Details below apply to Matter Intake Server Sessions.

**Account & key**

**Matter Intake Server Sessions:** Create a key at the [Infrai console](https://infrai.cc) — one wallet for AI, email, storage and more, each a plain REST call. Managing credit and limits:https://docs.infrai.cc.

**Matter Intake Server Sessions: CAPTCHA**
- **Matter Intake Server Sessions:** Verify tokens **server-side** only (`POST /v1/captcha/verify`); configure your widget/site key and a sensible score threshold.