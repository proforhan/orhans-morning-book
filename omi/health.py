"""Health check: collect problems per section and raise a visible alert.

A *problem* is something that makes today's email worse than it should be
(empty section, FRED down, Claude curation unavailable). A *note* is routine
noise (one slow feed) that is logged but never alerts. Problems are written to
output/health.json, emailed to the owner, and make the workflow finish red so
GitHub also flags the run. Nothing here can stop the newsletter from sending.
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
from email.message import EmailMessage

from .common import OUTPUT, log


class Health:
    def __init__(self) -> None:
        self._problems: dict[str, list[str]] = {}
        self.notes: list[str] = []

    def errors(self, section: str) -> list[str]:
        """A list the section's code appends to; anything in it is a problem."""
        return self._problems.setdefault(section, [])

    def problem(self, section: str, message: str) -> None:
        self.errors(section).append(message)

    def problems(self) -> dict[str, list[str]]:
        return {k: v for k, v in self._problems.items() if v}

    @property
    def ok(self) -> bool:
        return not self.problems()

    def summary(self) -> str:
        return "; ".join(f"{section}: {' / '.join(msgs[:2])}"
                         for section, msgs in self.problems().items())

    def write(self) -> None:
        OUTPUT.mkdir(exist_ok=True)
        (OUTPUT / "health.json").write_text(json.dumps(
            {"ok": self.ok, "problems": self.problems(), "notes": self.notes},
            indent=2), encoding="utf-8")


def send_alert(subject: str, body: str) -> bool:
    """Email the owner through Gmail SMTP. Best effort: returns False on failure."""
    user = os.getenv("GMAIL_USER")
    password = os.getenv("GMAIL_APP_PASSWORD")
    to = os.getenv("OMB_ALERT_TO") or user
    if not (user and password and to):
        log("alert not emailed: GMAIL_USER / GMAIL_APP_PASSWORD not set")
        return False
    msg = EmailMessage()
    msg["From"] = f"Morning Brief monitor <{user}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(),
                              timeout=30) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
        return True
    except Exception as exc:  # never let alerting break the run
        log(f"alert email failed: {type(exc).__name__}")
        return False
