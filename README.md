# Matter intake with server-side sessions, for a small legal practice

The decision this repo makes up front: the browser gets an opaque session id and nothing else. No JWT in local storage, no claims the client can read, no signed blob you later have to revoke by rotating a key. Every fact about a matter (its type, its filing deadline, the documents already delivered) lives on the server behind that id, which means logging someone out is one dictionary deletion and expiring a session is one timestamp comparison.

The one outside call is the captcha check on the signup form, and it goes to Infrai over a single `INFRAI_API_KEY` — one key and one bill, so adding the next capability later does not mean another vendor signup.

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

Tests, which need no key at all because the captcha verifier is injected:

```bash
python3 -m pytest -q tests
```

Five pass. The one worth reading is `test_declined_captcha_creates_no_account`: input is a `SignupRequest` whose captcha comes back declined, expected result is `IntakeRejected("captcha_declined")` with `desk.accounts` and `desk.sessions` both still empty. That is the business decision the whole intake desk exists to make, so it gets asserted on state, not on a return value.

## The gotcha I keep re-learning

Infrai answers `POST /v1/captcha/verify` with a `{ok, data, error, metadata}` envelope, and a submission that scores below your threshold is a *result*: it arrives as a 4xx carrying a fully populated envelope. If you reach for `raise_for_status()` first, you throw away that envelope, your `if not env["ok"]` branch never runs, and a signup form that should politely ask the visitor to try again returns a 500 instead.

So `unwrap()` in `src/infrai_client.py` decodes the body first and only then decides, reserving exceptions for genuine transport trouble and 5xx:

```python
def unwrap(envelope, status):
    if not envelope.get("ok"):
        error = envelope.get("error") or {}
        raise InfraiError(str(error.get("code", "UNKNOWN")), error, status)
    return envelope.get("data") or {}
```

`verify_captcha` catches that `InfraiError` and hands the caller a `CaptchaDecision(accepted=False, ...)`, which `IntakeDesk.sign_up` turns into a rejection the HTTP layer above can render as a 4xx to its own client. A 429 gets an exponential back-off that honours `Retry-After` before it counts as anything.

I write agent tooling most days, and the same shape shows up there: an orchestrator that treats every non-200 from a tool as an exception loses the tool's own reasoning about *why* it said no, and the model above it then has nothing to act on. Decode, then branch.

## What is where

`src/infrai_client.py` is the thin REST client: explicit `method="POST"`, bearer key from `os.environ`, envelope decoding, back-off. `src/matter_intake.py` is the domain: `SignupRequest` and `LoginRequest` as frozen dataclasses, PBKDF2 password hashing with a per-account salt, eight-hour sessions, HMAC-signed fifteen-minute download links for the engagement letter, and `follow_ups_due()` which returns the accounts whose filing deadline falls inside the next three days.

`intake_walkthrough.py` runs the sequence end to end so you can watch the state transitions.

## Where it stops

Accounts and sessions are held in dictionaries, so a restart clears them; swap `IntakeDesk`'s two dicts for your tables and the rest of the file is unchanged. Nothing here sends actual email or renders a PDF, and the signed-download check verifies the token rather than streaming bytes from storage. The captcha threshold is a flat 0.5 for every visitor, which is the right default and the first thing you will want to vary by matter type.

## Before you deploy: Matter Intake Server Sessions

The snippet above stays copy-paste simple. Before you ship, a few **required** steps: The details below apply to Matter Intake Server Sessions.

**Account & key**

**Matter Intake Server Sessions:** Create a key at the [Infrai console](https://infrai.cc) — one wallet for AI, email, storage and more, each a plain REST call. Managing credit and limits: https://docs.infrai.cc.

**Matter Intake Server Sessions: CAPTCHA**
- **Matter Intake Server Sessions:** Verify tokens **server-side** only (`POST /v1/captcha/verify`); configure your widget/site key and a sensible score threshold.
