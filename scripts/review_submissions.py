"""
Review submissions sent from the website (BSIL-58), from your own computer.

Usage (asks for the admin key, hidden; it is never stored):
  uv run python -m scripts.review_submissions list            # new submissions
  uv run python -m scripts.review_submissions list --all      # every status
  uv run python -m scripts.review_submissions show ID         # text + downloads the files
  uv run python -m scripts.review_submissions done ID         # handled (clears contact details)
  uv run python -m scripts.review_submissions reject ID       # rejected (clears contact details)
  uv run python -m scripts.review_submissions delete ID       # the submission and its files

Files are saved to ../private/submissions/<ID>/ (the local-only folder, never in a repo).
"""

import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API = "https://backstageil-api.vercel.app/api/v1/admin/submissions"
DOWNLOADS = Path(__file__).resolve().parents[2] / "private" / "submissions"


def call(method: str, path: str, key: str, body: dict[str, Any] | None = None) -> bytes:
    request = urllib.request.Request(
        f"{API}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return bytes(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:300]
        sys.exit(f"{method} {path or '/'} failed ({error.code}): {detail}")


def show_list(key: str, everything: bool) -> None:
    rows: list[dict[str, Any]] = []
    statuses = ["new", "handled", "rejected"] if everything else ["new"]
    for status in statuses:
        rows += json.loads(call("GET", f"?status={status}&limit=200", key))
    rows.sort(key=lambda row: row["created_at"], reverse=True)
    if not rows:
        print("No submissions." if everything else "No new submissions.")
        return
    for row in rows:
        where = row["venue_slug"] or row["venue_name"] or "general"
        if row["hall_slug"]:
            where += f" / {row['hall_slug']}"
        first_line = row["message"].splitlines()[0][:70]
        print(
            f"#{row['id']:<5} {row['created_at'][:16]}  {row['status']:<8} {row['kind']:<10} "
            f"{where}  ({len(row['files'])} files)  {first_line}"
        )


def show_one(key: str, submission_id: int) -> None:
    row = json.loads(call("GET", f"/{submission_id}", key))
    print(f"#{row['id']}  {row['kind']}  {row['status']}  {row['created_at'][:16]}")
    print(
        f"Venue: {row['venue_slug'] or row['venue_name'] or '-'}  Hall: {row['hall_slug'] or '-'}"
    )
    contact = ", ".join(c for c in (row["contact_name"], row["contact_email"]) if c)
    print(f"Contact: {contact or 'not given'}\n")
    print(row["message"])
    if row["files"]:
        folder = DOWNLOADS / str(submission_id)
        folder.mkdir(parents=True, exist_ok=True)
        print(f"\nFiles → {folder}")
        for file in row["files"]:
            data = call("GET", f"/{submission_id}/files/{file['index']}", key)
            target = folder / Path(file["name"]).name
            target.write_bytes(data)
            print(f"  {target.name} ({len(data) // 1000} KB)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Review website submissions")
    parser.add_argument("action", choices=["list", "show", "done", "reject", "delete"])
    parser.add_argument("id", nargs="?", type=int)
    parser.add_argument("--all", action="store_true", help="list every status, not only new")
    args = parser.parse_args(argv)
    if args.action != "list" and args.id is None:
        parser.error(f"{args.action} needs a submission ID")

    key = getpass.getpass("Admin key (hidden): ").strip()
    if args.action == "list":
        show_list(key, args.all)
    elif args.action == "show":
        show_one(key, args.id)
    elif args.action in ("done", "reject"):
        status = "handled" if args.action == "done" else "rejected"
        call("PATCH", f"/{args.id}", key, {"status": status})
        print(f"#{args.id} marked {status}; contact details cleared.")
    else:
        if input(f"Delete #{args.id} and its files? Type yes: ").strip().lower() != "yes":
            sys.exit("Nothing deleted.")
        call("DELETE", f"/{args.id}", key)
        print(f"#{args.id} deleted.")


if __name__ == "__main__":
    main(sys.argv[1:])
