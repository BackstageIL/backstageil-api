"""
Smoke-test a deployed API before and after it receives traffic.

Usage:
  uv run python -m scripts.smoke_test https://<deployment-url>

VERCEL_AUTOMATION_BYPASS_SECRET (if set) is sent as `x-vercel-protection-bypass`, so the test can
reach a protected deployment that isn't promoted yet. Exits 1 if any check fails.
"""

import argparse
import os
import sys
import time
from collections.abc import Callable
from typing import Any

import httpx2

Check = tuple[str, Callable[[Any], bool] | None]

CHECKS: list[Check] = [
    ("/health", None),
    ("/health/ready", None),
    ("/api/v1/venues?limit=1", lambda body: body["total"] > 0),
    ("/api/v1/cities", lambda body: len(body) > 0),
]
# Used only to prove the release stops before promote when a check fails
FAILING_CHECK: Check = ("/api/v1/smoke-test-deliberate-failure", None)


def run_checks(
    client: httpx2.Client, checks: list[Check], *, attempts: int = 3, delay_seconds: float = 3
) -> list[str]:
    """Run every check (retrying cold starts); return a description of each failure."""
    failures = []
    for path, condition in checks:
        problem = ""
        for attempt in range(attempts):
            try:
                response = client.get(path)
                if response.status_code != 200:
                    problem = f"HTTP {response.status_code}"
                elif condition is not None and not condition(response.json()):
                    problem = "unexpected content"
                else:
                    problem = ""
                    break
            except (httpx2.HTTPError, ValueError, KeyError, TypeError) as exc:
                problem = f"{type(exc).__name__}: {exc}"
            if attempt < attempts - 1:
                time.sleep(delay_seconds)
        print(f"{'FAIL' if problem else 'ok  '} {path} {problem}".rstrip())
        if problem:
            failures.append(f"{path}: {problem}")
    return failures


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Smoke-test a deployed API")
    parser.add_argument("base_url")
    parser.add_argument(
        "--fail-on-purpose", action="store_true", help="add a check that always fails (drills)"
    )
    args = parser.parse_args(argv)

    headers = {}
    bypass = os.environ.get("VERCEL_AUTOMATION_BYPASS_SECRET")
    if bypass:
        headers["x-vercel-protection-bypass"] = bypass

    checks = CHECKS + ([FAILING_CHECK] if args.fail_on_purpose else [])
    with httpx2.Client(base_url=args.base_url, headers=headers, timeout=30) as client:
        failures = run_checks(client, checks)
    if failures:
        sys.exit(f"Smoke test failed ({len(failures)}): " + "; ".join(failures))
    print("Smoke test passed")


if __name__ == "__main__":
    main(sys.argv[1:])
