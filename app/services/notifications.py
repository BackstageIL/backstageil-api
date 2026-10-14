"""
Email to the admin about each new submission (BSIL-58), through Resend's HTTP API.

Best effort, like the site rebuild: a failure is logged and never fails the submission. The
API key is never logged; the email holds the submission's text and file names, not the files.
"""

import httpx2
from fastapi import Request

from app.core.config import Settings
from app.core.logger import get_logger
from app.db.models import Submission

logger = get_logger(__name__)

RESEND_URL = "https://api.resend.com/emails"

KIND_LABELS = {
    "correction": "Correction",
    "document": "Technical document",
    "photos": "Photos",
    "nearby": "Place near a venue",
    "new_venue": "New venue",
    "other": "Other",
}


def email_text(submission: Submission, site_url: str) -> tuple[str, str]:
    """Subject and plain-text body."""
    where = submission.venue_slug or submission.venue_name or "general"
    if submission.venue_slug and submission.hall_slug:
        where = f"{submission.venue_slug} / {submission.hall_slug}"
    subject = f"BackstageIL: {KIND_LABELS[submission.kind]} ({where}) #{submission.id}"

    lines = [f"New submission #{submission.id}: {KIND_LABELS[submission.kind]}", ""]
    if submission.venue_slug:
        page = f"{site_url}/venues/{submission.venue_slug}/"
        if submission.hall_slug:
            page += f"halls/{submission.hall_slug}/"
        lines.append(f"Page: {page}")
    if submission.venue_name:
        lines.append(f"Venue named: {submission.venue_name}")
    lines += ["", "Message:", submission.message, ""]
    if submission.files:
        lines.append(f"Files ({len(submission.files)}):")
        lines += [f"  - {f['name']} ({f['size'] // 1000} KB)" for f in submission.files]
        lines.append("")
    contact = ", ".join(c for c in (submission.contact_name, submission.contact_email) if c)
    lines.append(f"Contact: {contact or 'not given'}")
    lines += [
        "",
        "Review it (files stay private):",
        "  uv run python -m scripts.review_submissions show " + str(submission.id),
    ]
    return subject, "\n".join(lines)


class SubmissionNotifier:
    """`transport` is for tests."""

    def __init__(
        self,
        api_key: str,
        to: str,
        sender: str,
        site_url: str,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self.to = to
        self.sender = sender
        self.site_url = site_url.rstrip("/")
        self._transport = transport

    async def notify(self, submission: Submission) -> bool:
        subject, text = email_text(submission, self.site_url)
        body = {"from": self.sender, "to": [self.to], "subject": subject, "text": text}
        transport = self._transport or httpx2.AsyncHTTPTransport(retries=1)
        try:
            async with httpx2.AsyncClient(transport=transport, timeout=10) as client:
                response = await client.post(
                    RESEND_URL, json=body, headers={"Authorization": f"Bearer {self._api_key}"}
                )
                response.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            logger.error(
                "Submission email failed: Resend answered %s: %s",
                exc.response.status_code,
                exc.response.text[:300],
            )
            return False
        except httpx2.HTTPError as exc:
            logger.error("Submission email failed: %s", exc.__class__.__name__)
            return False
        return True


def notifier_from_settings(settings: Settings) -> SubmissionNotifier | None:
    if settings.resend_api_key is None or not settings.submissions_notify_email:
        return None
    return SubmissionNotifier(
        settings.resend_api_key.get_secret_value(),
        settings.submissions_notify_email,
        settings.submissions_from_email,
        settings.site_url,
    )


def get_notifier(request: Request) -> SubmissionNotifier | None:
    """Route dependency: the configured notifier, or None (no emails)."""
    notifier: SubmissionNotifier | None = request.app.state.submission_notifier
    return notifier
