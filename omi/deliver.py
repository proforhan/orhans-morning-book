"""Delivery through Buttondown."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .charts import mark_chart_featured
from .common import esc

BUTTONDOWN_API_ROOT = "https://api.buttondown.com/v1"


def buttondown_request(method: str, url: str, api_key: str, *,
                       json_body: dict[str, Any] | None = None,
                       raw_body: bytes | None = None,
                       content_type: str | None = None) -> dict[str, Any]:
    headers = {
        "Authorization": f"Token {api_key}",
        # Required one-time-per-key confirmation for API version 2026-04-01+
        # before a status change is allowed to actually queue a send.
        "X-Buttondown-Live-Dangerously": "true",
    }
    data: bytes | None = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif raw_body is not None:
        data = raw_body
        if content_type:
            headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Buttondown API {method} {url} failed ({exc.code}): {detail}") from exc


def buttondown_upload_image(api_key: str, image_path: Path) -> str:
    """Upload a local chart PNG so it can be referenced by a public <img src> URL.

    Buttondown's JSON email-creation endpoint has no equivalent of the
    cid: inline-attachment trick used for Gmail delivery, so the chart image
    has to be hosted somewhere the recipient's mail client can fetch it.
    """
    boundary = f"----OMI{uuid.uuid4().hex}"
    suffix = image_path.suffix.lower()
    content_type = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="image"; filename="{image_path.name}"\r\n'
        f'Content-Type: {content_type}\r\n\r\n'
    ).encode("utf-8") + image_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
    result = buttondown_request(
        "POST", f"{BUTTONDOWN_API_ROOT}/images", api_key,
        raw_body=body, content_type=f"multipart/form-data; boundary={boundary}",
    )
    return result["image"]


def send_via_buttondown(subject: str, body: str,
                        chart_of_day: dict[str, Any] | None = None) -> None:
    """Deliver the newsletter through Buttondown.

    Buttondown owns the subscriber list (and unsubscribe handling) for
    everyone who signs up through the website form, so this is now the
    single delivery path. Safety default: the email is always created as a
    draft first; it's only advanced to "about_to_send" (which queues actual
    delivery within a few minutes) when OMI_BUTTONDOWN_LIVE is set truthy.
    This keeps a manual test run from ever emailing real subscribers while
    still letting the scheduled daily run go out automatically.

    chart_of_day, when given, is the chart already resolved by build() (which
    may be a fallback chart pulled from coverage rather than a tracked local
    source) - reusing it here keeps the sent email consistent with what was
    generated instead of re-resolving independently.
    """
    api_key = os.getenv("BUTTONDOWN_API_KEY")
    go_live = os.getenv("OMI_BUTTONDOWN_LIVE", "").lower() in {"1", "true", "yes"}
    if not api_key:
        if go_live:
            raise RuntimeError("Set BUTTONDOWN_API_KEY to enable Buttondown delivery.")
        print("Test run: Buttondown withheld, nothing sent. See output/latest.html.")
        return

    chart = chart_of_day
    if chart and "cid:chart-of-the-day" in body:
        try:
            hosted_url = buttondown_upload_image(api_key, Path(chart["image_path"]))
            body = body.replace("cid:chart-of-the-day", hosted_url)
        except Exception as exc:
            # Don't let a chart upload failure block the rest of the newsletter.
            body = body.replace(
                'src="cid:chart-of-the-day"',
                f'src="" alt="Chart of the Day unavailable ({esc(exc)})"',
            )

    created = buttondown_request(
        "POST", f"{BUTTONDOWN_API_ROOT}/emails", api_key,
        json_body={"subject": subject, "body": body, "status": "draft"},
    )
    email_id = created.get("id")

    if go_live and email_id:
        buttondown_request(
            "PATCH", f"{BUTTONDOWN_API_ROOT}/emails/{email_id}", api_key,
            json_body={"status": "about_to_send"},
        )
        if os.getenv("OMI_PRESERVE_CHART_STATE", "").lower() not in {"1", "true", "yes"}:
            mark_chart_featured(chart)
        print(f"Buttondown email {email_id} queued to send to subscribers.")
    else:
        print(
            f"Buttondown draft {email_id} created but NOT sent "
            f"(set OMI_BUTTONDOWN_LIVE=true to actually send, or review/send it "
            f"manually from https://buttondown.com/emails)."
        )

