"""
Generate a new admin API key and its hash.

Usage (run it yourself; the key is shown once and never stored by the app):
  uv run python -m scripts.new_admin_key

1. Save the KEY in your password manager. You send it as the X-API-Key header.
2. Put the HASH in ADMIN_API_KEY_HASH: your local .env, or the hosting secret store.
Rotating the key = run this again, replace the hash, redeploy; the old key stops working.
"""

import secrets

from app.core.security import hash_api_key


def new_admin_key() -> tuple[str, str]:
    key = secrets.token_urlsafe(32)  # 256 bits of randomness
    return key, hash_api_key(key)


def main() -> None:
    key, key_hash = new_admin_key()
    print("ADMIN KEY (save it in your password manager, it is not stored anywhere):")
    print(f"  {key}")
    print("ADMIN_API_KEY_HASH (put this in .env / the hosting secret store):")
    print(f"  {key_hash}")


if __name__ == "__main__":
    main()
