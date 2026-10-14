"""Website submissions (BSIL-58) against a real database: the public form endpoint, spam limits,
private file storage, the email to the admin and the admin review endpoints.

Files go to an in-memory store and emails to a fake transport; rows are rolled back after each
test.
"""

import json
import time
from collections.abc import AsyncIterator, Sequence
from io import BytesIO
from typing import Any

import httpx2
import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import Settings
from app.core.exceptions import PictureStorageUnavailableError
from app.core.security import hash_api_key
from app.db.dependencies import get_session
from app.db.models import Submission, SubmissionStatus
from app.main import create_app
from app.routes.submissions import get_submission_storage
from app.services import submissions
from app.services.notifications import SubmissionNotifier, get_notifier
from app.services.site_rebuild import changes_site_data

pytestmark = pytest.mark.anyio

KEY = "integration-test-admin-key-0123456789"
AUTH = {"X-API-Key": KEY}
URL = "/api/v1/submissions"
ADMIN = "/api/v1/admin/submissions"


class MemoryStorage:
    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, str]] = {}
        self.fail = False

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        if self.fail:
            raise PictureStorageUnavailableError()
        self.files[key] = (data, content_type)

    async def delete(self, keys: Sequence[str]) -> None:
        for key in keys:
            self.files.pop(key, None)

    async def get(self, key: str) -> bytes:
        return self.files[key][0]


class Mailbox:
    """Fake Resend: records each email; `status` decides the answer."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.status = 200

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.sent.append(json.loads(request.content))
        return httpx2.Response(self.status, json={"id": "email-1"})


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture
def mailbox() -> Mailbox:
    return Mailbox()


def make_client(
    session: AsyncSession, storage: MemoryStorage | None, mailbox: Mailbox | None
) -> httpx2.AsyncClient:
    settings = Settings(
        _env_file=None,
        environment="ci",
        database_url=None,
        admin_api_key_hash=hash_api_key(KEY),
    )
    app = create_app(settings)

    async def test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[get_submission_storage] = lambda: storage
    notifier = (
        SubmissionNotifier(
            "re_test_key",
            "owner@example.test",
            "BackstageIL <onboarding@resend.dev>",
            "https://www.backstageil.com",
            transport=httpx2.MockTransport(mailbox.handler),
        )
        if mailbox is not None
        else None
    )
    app.dependency_overrides[get_notifier] = lambda: notifier
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def client(
    session: AsyncSession, storage: MemoryStorage, mailbox: Mailbox
) -> AsyncIterator[httpx2.AsyncClient]:
    async with make_client(session, storage, mailbox) as http:
        yield http


def form(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "kind": "correction",
        "message": "The stage depth is 11 m, not 12 m.",
        "venue": "zqs-venue",
        "hall": "main",
        "rights": "true",
        "started_at": str(int(time.time() * 1000) - 60_000),
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def jpeg_with_gps() -> bytes:
    image = Image.new("RGB", (40, 30), "red")
    exif = image.getexif()
    exif[0x8825] = {2: (32.0, 4.0, 0.0)}  # GPS info
    exif[0x010F] = "PhoneMaker"
    buffer = BytesIO()
    image.save(buffer, "JPEG", exif=exif)
    return buffer.getvalue()


async def count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(Submission))).scalar_one()


async def latest(session: AsyncSession) -> Submission:
    query = select(Submission).order_by(Submission.id.desc()).limit(1)
    return (await session.execute(query)).scalar_one()


# --- public form -------------------------------------------------------------------------------


async def test_text_submission_is_saved_and_emailed(
    client: httpx2.AsyncClient, session: AsyncSession, mailbox: Mailbox
) -> None:
    before = await count(session)
    response = await client.post(
        URL, data=form(contact_name="Dana", contact_email="dana@example.test")
    )

    assert response.status_code == 201
    assert response.json() == {"status": "received"}
    assert response.headers["cache-control"] == "no-store"
    assert await count(session) == before + 1
    row = await latest(session)
    assert (row.kind, row.venue_slug, row.hall_slug, row.status) == (
        "correction",
        "zqs-venue",
        "main",
        SubmissionStatus.NEW,
    )
    assert row.contact_email == "dana@example.test"
    assert len(row.client_hash) == 64 and row.notified
    [email] = mailbox.sent
    assert email["to"] == ["owner@example.test"]
    assert "/venues/zqs-venue/halls/main/" in email["text"]
    assert "The stage depth is 11 m" in email["text"]
    assert "Dana, dana@example.test" in email["text"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"website": "http://spam.example"},  # the hidden trap field
        {"started_at": "now"},  # sent faster than a person can (filled in at run time)
    ],
)
async def test_bots_are_dropped_quietly(
    client: httpx2.AsyncClient, session: AsyncSession, mailbox: Mailbox, overrides: dict[str, str]
) -> None:
    if overrides.get("started_at") == "now":
        overrides = {"started_at": str(int(time.time() * 1000))}
    before = await count(session)
    response = await client.post(URL, data=form(**overrides))

    assert response.status_code == 201  # same answer, so bots learn nothing
    assert await count(session) == before
    assert mailbox.sent == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"rights": None},
        {"rights": "false"},
        {"kind": "spam"},
        {"message": "x"},
        {"message": "Call me on 052-1234567"},  # no personal details
        {"venue": "Not A Slug"},
        {"contact_email": "not-an-email"},
    ],
)
async def test_invalid_forms_are_422(
    client: httpx2.AsyncClient, session: AsyncSession, overrides: dict[str, Any]
) -> None:
    before = await count(session)
    response = await client.post(URL, data=form(**overrides))

    assert response.status_code == 422
    assert await count(session) == before


async def test_files_are_checked_cleaned_and_stored_privately(
    client: httpx2.AsyncClient, session: AsyncSession, storage: MemoryStorage, mailbox: Mailbox
) -> None:
    files = [
        ("files", ("../../stage photo.jpg", jpeg_with_gps(), "image/jpeg")),
        ("files", ("rider.pdf", b"%PDF-1.7 tiny", "application/pdf")),
        ("files", ("lights.xlsx", b"PK\x03\x04 sheet", "application/octet-stream")),
    ]
    response = await client.post(URL, data=form(kind="document"), files=files)

    assert response.status_code == 201
    row = await latest(session)
    assert [f["name"] for f in row.files] == ["stage photo.jpg", "rider.pdf", "lights.xlsx"]
    assert all(f["key"].startswith("submissions/") for f in row.files)
    photo, content_type = storage.files[row.files[0]["key"]]
    assert content_type == "image/jpeg"
    with Image.open(BytesIO(photo)) as image:
        assert not image.getexif()  # GPS and camera details removed
    assert row.files[2]["content_type"].endswith("spreadsheetml.sheet")
    assert "rider.pdf" in mailbox.sent[0]["text"]


async def test_disguised_files_are_rejected(
    client: httpx2.AsyncClient, session: AsyncSession, storage: MemoryStorage
) -> None:
    before = await count(session)
    files = [("files", ("photo.jpg", b"MZ\x90\x00 an exe", "image/jpeg"))]
    response = await client.post(URL, data=form(), files=files)

    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_SUBMISSION_FILE"
    assert await count(session) == before and storage.files == {}


@pytest.mark.parametrize(
    "files",
    [
        [("files", (f"{i}.pdf", b"%PDF-1", "application/pdf")) for i in range(6)],
        [("files", ("big.pdf", b"%PDF" + b"0" * submissions.MAX_TOTAL_BYTES, "application/pdf"))],
    ],
)
async def test_too_many_or_too_large_files_are_413(
    client: httpx2.AsyncClient, files: list[Any]
) -> None:
    response = await client.post(URL, data=form(), files=files)

    assert response.status_code == 413
    assert response.json()["error_code"] == "SUBMISSION_TOO_LARGE"


async def test_files_without_a_store_are_503_but_text_works(
    session: AsyncSession, mailbox: Mailbox
) -> None:
    async with make_client(session, None, mailbox) as http:
        files = [("files", ("rider.pdf", b"%PDF-1", "application/pdf"))]
        with_files = await http.post(URL, data=form(), files=files)
        text_only = await http.post(URL, data=form())

    assert with_files.status_code == 503
    assert with_files.json()["error_code"] == "SUBMISSIONS_NOT_CONFIGURED"
    assert text_only.status_code == 201


async def test_storage_failure_keeps_nothing(
    client: httpx2.AsyncClient, session: AsyncSession, storage: MemoryStorage
) -> None:
    storage.fail = True
    before = await count(session)
    files = [("files", ("rider.pdf", b"%PDF-1", "application/pdf"))]
    response = await client.post(URL, data=form(), files=files)

    assert response.status_code == 503
    assert await count(session) == before


async def test_one_connection_is_limited_per_hour(client: httpx2.AsyncClient) -> None:
    answers = [(await client.post(URL, data=form())).status_code for _ in range(6)]

    assert answers == [201] * submissions.MAX_PER_HOUR + [429]


async def test_a_failed_email_still_saves_the_submission(
    client: httpx2.AsyncClient, session: AsyncSession, mailbox: Mailbox
) -> None:
    mailbox.status = 500
    response = await client.post(URL, data=form())

    assert response.status_code == 201
    row = await latest(session)
    assert not row.notified


async def test_emails_stop_at_the_daily_limit(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    mailbox: Mailbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(submissions, "MAX_EMAILS_PER_DAY", 0)
    response = await client.post(URL, data=form())

    assert response.status_code == 201
    assert mailbox.sent == []


# --- admin review ------------------------------------------------------------------------------


async def make_submission(client: httpx2.AsyncClient, session: AsyncSession) -> Submission:
    files = [("files", ("rider.pdf", b"%PDF-1.7 rider", "application/pdf"))]
    response = await client.post(
        URL, data=form(contact_name="Dana", contact_email="dana@example.test"), files=files
    )
    assert response.status_code == 201
    return await latest(session)


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", ""), ("GET", "/1"), ("GET", "/1/files/0"), ("PATCH", "/1"), ("DELETE", "/1")],
)
async def test_admin_needs_the_key(client: httpx2.AsyncClient, method: str, path: str) -> None:
    response = await client.request(method, ADMIN + path, json={"status": "handled"})

    assert response.status_code == 401


async def test_admin_lists_views_and_downloads(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    row = await make_submission(client, session)

    listed = (await client.get(ADMIN, headers=AUTH)).json()
    one = (await client.get(f"{ADMIN}/{row.id}", headers=AUTH)).json()
    download = await client.get(f"{ADMIN}/{row.id}/files/0", headers=AUTH)
    missing = await client.get(f"{ADMIN}/{row.id}/files/5", headers=AUTH)

    assert row.id in [s["id"] for s in listed]
    assert one["files"] == [
        {"index": 0, "name": "rider.pdf", "content_type": "application/pdf", "size": 14}
    ]
    assert download.status_code == 200
    assert download.content == b"%PDF-1.7 rider"
    assert "attachment" in download.headers["content-disposition"]
    assert missing.status_code == 404


async def test_handled_clears_contact_details_and_new_reopens(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    row = await make_submission(client, session)

    handled = (
        await client.patch(f"{ADMIN}/{row.id}", json={"status": "handled"}, headers=AUTH)
    ).json()
    reopened = (
        await client.patch(f"{ADMIN}/{row.id}", json={"status": "new"}, headers=AUTH)
    ).json()

    assert handled["status"] == "handled" and handled["handled_at"] is not None
    assert (handled["contact_name"], handled["contact_email"]) == (None, None)
    assert reopened["status"] == "new" and reopened["handled_at"] is None


async def test_delete_removes_the_row_and_its_files(
    client: httpx2.AsyncClient, session: AsyncSession, storage: MemoryStorage
) -> None:
    row = await make_submission(client, session)
    assert storage.files

    response = await client.delete(f"{ADMIN}/{row.id}", headers=AUTH)

    assert response.status_code == 204
    assert storage.files == {}
    assert (await client.get(f"{ADMIN}/{row.id}", headers=AUTH)).status_code == 404


def test_submission_admin_calls_dont_rebuild_the_site() -> None:
    def request(method: str, path: str) -> Request:
        return Request(
            {"type": "http", "method": method, "path": path, "headers": [], "query_string": b""}
        )

    ok = Response(status_code=200)

    assert not changes_site_data(request("PATCH", "/api/v1/admin/submissions/3"), ok)
    assert not changes_site_data(request("DELETE", "/api/v1/admin/submissions/3"), ok)
    assert changes_site_data(request("PATCH", "/api/v1/admin/venues/x"), ok)
