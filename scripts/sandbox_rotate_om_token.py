"""Rotate the OpenMetadata JWT in `/opt/metasift/.env` on the sandbox VPS.

Use this after a full `make reset-all` (which wipes OM's MySQL volume and
regenerates the `ingestion-bot` user with a new token). The nightly soft
reset NEVER needs this — it only wipes MetaSift's own SQLite, leaving the
OM volumes and JWT intact.

Usage (on the VPS, as the `metasift` user):

    /opt/metasift/.venv/bin/python /opt/metasift/scripts/sandbox_rotate_om_token.py "<new-jwt>"

Or one-line from your laptop:

    ssh vps /opt/metasift/.venv/bin/python /opt/metasift/scripts/sandbox_rotate_om_token.py "<new-jwt>"

What it does:

1. Validates the new JWT against OpenMetadata
   (`GET /v1/services/databaseServices?limit=1`). Refuses to write a token
   OM would reject — the local UI's OMConnectionPanel does the same. A
   bad write here would otherwise lock the API out of OM until manual
   recovery.
2. Atomically rewrites `.env` — writes a temp file in the same directory,
   fsyncs, renames into place. `OPENMETADATA_JWT_TOKEN` and `AI_SDK_TOKEN`
   are updated in place; every other line is preserved verbatim. Missing
   keys are appended.
3. Restores `chmod 600` on the new file (matches the `.env` permission
   pattern from the runbook).
4. Restarts `metasift-api.service` via `sudo systemctl restart`. The
   `metasift` user has a NOPASSWD sudoers entry for exactly that command
   (deploy/sandbox/sudoers.d-metasift), so this works without a password
   prompt under the unit user.

Never logs the JWT. Never echoes the JWT in error output. The token is
only ever sent to OM (for validation) and written to `.env`.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

# Keys we rotate together. ingestion-bot uses one JWT; both vars in .env
# point at it (AI_SDK_TOKEN is consumed by the MCP-client side of the app).
# Keeping them in sync avoids a half-rotated state where some routes work
# and others 401.
_JWT_KEYS = ("OPENMETADATA_JWT_TOKEN", "AI_SDK_TOKEN")
_DEFAULT_ENV = Path("/opt/metasift/.env")
_DEFAULT_HOST_KEY = "OPENMETADATA_HOST"
_DEFAULT_HOST = "http://127.0.0.1:8585"
_DEFAULT_API_SERVICE = "metasift-api.service"


def _read_env(env_path: Path) -> dict[str, str]:
    """Parse a .env file into a dict. Lines beginning with `#`, blanks,
    and lines without `=` are kept as-is in the rewrite path; this dict
    is only used to look up the OM host for validation."""
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def _validate_token(host: str, jwt: str) -> None:
    """Probe `/v1/services/databaseServices?limit=1` — the same endpoint
    the OM panel UI uses. 200 = good, 401 = OM rejected the token, other
    statuses surface verbatim. Mirrors `app/api/routers/om.py::_validate`
    so the operator-side check behaves identically to the in-app check."""
    api_base = f"{host.rstrip('/')}/api"
    try:
        with httpx.Client(base_url=api_base, timeout=10.0) as c:
            r = c.get(
                "/v1/services/databaseServices",
                params={"limit": 1, "fields": "name"},
                headers={"Authorization": f"Bearer {jwt}"},
            )
    except httpx.RequestError as e:
        raise SystemExit(
            f"✗ Could not reach OpenMetadata at {host} ({type(e).__name__}). "
            "Is the OM stack up? Try `systemctl status metasift-om.service`."
        ) from e
    if r.status_code == 401:
        raise SystemExit(
            "✗ OpenMetadata rejected the token (401). "
            "Generate a fresh one via Settings → Bots → ingestion-bot."
        )
    if r.status_code != 200:
        raise SystemExit(
            f"✗ OpenMetadata returned HTTP {r.status_code}. "
            "Check the host + token and retry."
        )


def _rewrite_env(env_path: Path, new_token: str) -> None:
    """Atomic .env rewrite. Read existing lines, replace the two JWT keys
    in place (preserving line order, comments, blank lines), append any
    that weren't present, write to a temp file in the same directory,
    fsync, then rename into place. Same-directory tempfile guarantees the
    rename is atomic on POSIX (no cross-device move)."""
    existing_lines: list[str] = (
        env_path.read_text().splitlines() if env_path.exists() else []
    )
    seen: set[str] = set()
    out_lines: list[str] = []
    for raw in existing_lines:
        stripped = raw.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in _JWT_KEYS:
                out_lines.append(f"{key}={new_token}")
                seen.add(key)
                continue
        out_lines.append(raw)
    # Append any missing keys (first-time rotation, or .env was hand-trimmed).
    for k in _JWT_KEYS:
        if k not in seen:
            out_lines.append(f"{k}={new_token}")

    fd, tmp_path = tempfile.mkstemp(prefix=".env.", dir=str(env_path.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(out_lines))
            if not (out_lines and out_lines[-1] == ""):
                fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, env_path)
    except Exception:
        # Best-effort cleanup if we crashed before the rename.
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def _restart_api(service: str) -> None:
    """`sudo systemctl restart` — the metasift user's sudoers entry permits
    exactly this command without a password prompt. If the script is run
    as root (e.g. for first-time setup before the metasift user exists),
    sudo is a no-op."""
    try:
        subprocess.run(
            ["sudo", "/bin/systemctl", "restart", service],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        raise SystemExit(
            f"✗ `sudo` or systemctl not found ({e}). Run on the VPS, not in dev."
        ) from e
    except subprocess.CalledProcessError as e:
        raise SystemExit(
            f"✗ `systemctl restart {service}` failed: {e.stderr.strip() or e}"
        ) from e


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rotate the OM ingestion-bot JWT in /opt/metasift/.env",
    )
    parser.add_argument(
        "token",
        help="The new ingestion-bot JWT. Generate via Settings → Bots → ingestion-bot.",
    )
    parser.add_argument(
        "--env",
        type=Path,
        default=_DEFAULT_ENV,
        help=f"Path to the .env to rotate. Default: {_DEFAULT_ENV}",
    )
    parser.add_argument(
        "--om-host",
        default=None,
        help=f"OM host for validation. Default: read from .env or {_DEFAULT_HOST}.",
    )
    parser.add_argument(
        "--service",
        default=_DEFAULT_API_SERVICE,
        help=f"systemd unit to restart after writing. Default: {_DEFAULT_API_SERVICE}",
    )
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="Skip the systemctl restart (dry-run friendly).",
    )
    args = parser.parse_args()

    token = args.token.strip()
    if not token:
        raise SystemExit("✗ Empty token. Pass the JWT as the first argument.")

    env_vars = _read_env(args.env)
    host = args.om_host or env_vars.get(_DEFAULT_HOST_KEY, _DEFAULT_HOST)

    print(f"→ Validating new token against OM at {host} …")
    _validate_token(host, token)
    print("✓ OM accepted the token.")

    print(f"→ Atomically rewriting {args.env} …")
    _rewrite_env(args.env, token)
    print("✓ .env updated (mode 0600, both JWT keys in sync).")

    if args.no_restart:
        print("⚠  --no-restart set; the API is still using the OLD token until")
        print(f"   you run: sudo systemctl restart {args.service}")
        return 0

    print(f"→ Restarting {args.service} …")
    _restart_api(args.service)
    print(f"✓ {args.service} restarted. Token rotation complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
