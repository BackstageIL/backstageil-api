"""
Promote a Vercel deployment to production: the blue-green traffic switch (also used for rollback).

Usage:
  uv run python -m scripts.promote https://<deployment-url>

Calls the Vercel REST API directly, the same endpoints `vercel promote` uses, but without the
CLI's user lookup (it answers 404 for our deploy token). Needs VERCEL_TOKEN, VERCEL_ORG_ID and
VERCEL_PROJECT_ID. Waits until production serves the deployment; exits 1 on failure or timeout.
"""

import argparse
import os
import sys
import time
from typing import Any
from urllib.parse import urlsplit

import httpx2

API_URL = "https://api.vercel.com"


class PromoteError(Exception):
    pass


def deployment_host(url: str) -> str:
    """Accept a full URL or a bare host."""
    return urlsplit(url).hostname or url


def json_or_raise(response: httpx2.Response) -> Any:
    if response.is_error:
        try:
            message = response.json()["error"]["message"]
        except ValueError, KeyError, TypeError:
            message = response.text[:200]
        raise PromoteError(
            f"{response.request.method} {response.url.path}: HTTP {response.status_code} {message}"
        )
    return response.json() if response.content else None


def is_serving(project: dict[str, Any], deployment_id: str) -> bool | None:
    """True: production serves the deployment; False: the switch failed; None: still pending."""
    if ((project.get("targets") or {}).get("production") or {}).get("id") == deployment_id:
        return True
    request = project.get("lastAliasRequest") or {}
    if request.get("toDeploymentId") != deployment_id:
        return None
    status = request.get("jobStatus")
    if status == "succeeded":
        return True
    if status in ("failed", "skipped"):
        return False
    return None


def promote(
    client: httpx2.Client,
    project_id: str,
    deployment_url: str,
    *,
    timeout_seconds: float = 180,
    poll_seconds: float = 2,
) -> str:
    """Switch production traffic to the deployment and wait until it is done; return its id."""
    deployment = json_or_raise(client.get(f"/v13/deployments/{deployment_host(deployment_url)}"))
    deployment_id: str = deployment["id"]
    if deployment.get("target") != "production":
        raise PromoteError(f"{deployment_url} is not a production deployment (deploy with --prod)")

    json_or_raise(client.post(f"/v10/projects/{project_id}/promote/{deployment_id}", json={}))

    deadline = time.monotonic() + timeout_seconds
    while True:
        serving = is_serving(json_or_raise(client.get(f"/v9/projects/{project_id}")), deployment_id)
        if serving:
            return deployment_id
        if serving is False:
            raise PromoteError(f"Vercel reported the promotion of {deployment_id} as failed")
        if time.monotonic() >= deadline:
            raise PromoteError(
                f"Promotion of {deployment_id} not finished after {timeout_seconds}s"
            )
        time.sleep(poll_seconds)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Promote a Vercel deployment to production")
    parser.add_argument("deployment_url")
    args = parser.parse_args(argv)

    missing = [
        name
        for name in ("VERCEL_TOKEN", "VERCEL_ORG_ID", "VERCEL_PROJECT_ID")
        if not os.environ.get(name)
    ]
    if missing:
        sys.exit(f"Missing environment variables: {', '.join(missing)}")

    with httpx2.Client(
        base_url=API_URL,
        headers={"Authorization": f"Bearer {os.environ['VERCEL_TOKEN']}"},
        params={"teamId": os.environ["VERCEL_ORG_ID"]},
        timeout=30,
    ) as client:
        try:
            deployment_id = promote(client, os.environ["VERCEL_PROJECT_ID"], args.deployment_url)
        except PromoteError as exc:
            sys.exit(f"Promote failed: {exc}")
    print(f"Production now serves {deployment_id} ({args.deployment_url})")


if __name__ == "__main__":
    main(sys.argv[1:])
