"""
CR-001 magic-link email sender — Gmail SMTP via app password.

Single function: send_magic_link(to, link). Plain-text + minimal HTML body.
Sender is `greeningofstreaming@gmail.com` (configurable via OWL_SMTP_USER).
Auth uses an app password from OWL_SMTP_PASSWORD (16-char Gmail app password,
not the account password).

Dry-run mode: if OWL_SMTP_DRY_RUN=1 (or no OWL_SMTP_PASSWORD set), the email
is logged instead of sent. Used by tests and lets staging boot without real
credentials.

Connection is per-send (no pool). Magic-link traffic is a few sends per day
even on conference week — pooling buys nothing and complicates failure
recovery.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from dotenv import dotenv_values

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV = dotenv_values(_REPO_ROOT / ".env")


def _cfg(name: str, default: str = "") -> str:
    return _ENV.get(name) or os.environ.get(name) or default


SMTP_HOST = _cfg("OWL_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(_cfg("OWL_SMTP_PORT", "465"))  # 465 = implicit TLS
SMTP_USER = _cfg("OWL_SMTP_USER", "greeningofstreaming@gmail.com")
SMTP_FROM_NAME = _cfg("OWL_SMTP_FROM_NAME", "Greening of Streaming · OWL")


def _is_dry_run() -> bool:
    if _cfg("OWL_SMTP_DRY_RUN") in ("1", "true", "yes"):
        return True
    if not _cfg("OWL_SMTP_PASSWORD"):
        return True
    return False


# CR-067 no-PII-in-logs convention (must hold before the wider logging pass):
# never write a full member email address or a magic link (a live bearer
# credential) to logs. Addresses are redacted to first-char + domain; the link
# is suppressed unless OWL_SMTP_LOG_LINK=1 is set for a deliberate local debug.
def _redact_email(addr: str) -> str:
    """'alice@example.org' → 'a***@example.org'. Keeps the domain (useful for
    delivery debugging) but drops the identifying local-part."""
    try:
        local, sep, domain = addr.partition("@")
        if not sep:
            return "***"
        return f"{(local[:1] or '')}***@{domain}"
    except Exception:
        return "***"


def _build_message(to: str, link: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "Sign in to OWL"
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg["To"] = to
    msg.set_content(
        f"""Hello,

Click the link below to sign in to OWL (the Greening of Streaming
energy-and-CO2e measurement lab). The link is valid for 15 minutes.

{link}

If you didn't request this, ignore this email — no account exists
unless someone signs in with the link.

— Greening of Streaming
"""
    )
    msg.add_alternative(
        f"""<html><body style="font-family:system-ui,sans-serif;line-height:1.5;color:#222">
<p>Hello,</p>
<p>Click the button below to sign in to <strong>OWL</strong> (the Greening of
Streaming energy-and-CO<sub>2</sub>e measurement lab). The link is valid for
15&nbsp;minutes.</p>
<p style="margin:1.5rem 0">
  <a href="{link}" style="background:#00875a;color:#fff;padding:0.6rem 1.4rem;
     text-decoration:none;border-radius:4px;display:inline-block">Sign in to OWL</a>
</p>
<p style="font-size:0.85rem;color:#666">Or paste this URL into your browser:<br>
  <a href="{link}">{link}</a></p>
<p style="font-size:0.85rem;color:#666">If you didn't request this, you can
  ignore this email — no account exists unless someone signs in with the link.</p>
<p style="font-size:0.85rem;color:#666">— Greening of Streaming</p>
</body></html>""",
        subtype="html",
    )
    return msg


def send_magic_link(to: str, link: str) -> bool:
    """Send the magic-link email. Returns True on success (or dry-run skip),
    False on SMTP failure. Caller decides whether to surface the failure to
    the user; today, we treat send-failure as "the user just won't get an
    email" and the route returns the same generic page either way (defence
    against email-enumeration)."""
    msg = _build_message(to, link)
    if _is_dry_run():
        # The link is a live credential — suppressed by default even in dry-run
        # (staging can run dry-run). Opt in with OWL_SMTP_LOG_LINK=1 for a local
        # test where you need to click it out of the log.
        if _cfg("OWL_SMTP_LOG_LINK") in ("1", "true", "yes"):
            log.info("DRY RUN magic-link email to %s — link: %s",
                     _redact_email(to), link)
        else:
            log.info("DRY RUN magic-link email to %s (link suppressed; "
                     "set OWL_SMTP_LOG_LINK=1 to include)", _redact_email(to))
        return True
    password = _cfg("OWL_SMTP_PASSWORD")
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.login(SMTP_USER, password)
            s.send_message(msg)
        log.info("Sent magic-link email to %s", _redact_email(to))
        return True
    except Exception:
        # log.exception appends the traceback (valuable for SMTP debugging);
        # the address is redacted and the link is never in scope here.
        log.exception("Failed to send magic-link email to %s", _redact_email(to))
        return False
