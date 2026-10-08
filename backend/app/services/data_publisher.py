"""Publish the working DB to the data repo and push it to GitHub.

The SQLite DB is exported as a plain-text SQL dump (`db/stock-advisor.sql`)
so git can diff and delta-compress it day over day. Everything else the app
writes into the data repo (e.g. models/weights_history.jsonl) is committed
alongside it.

On a fresh machine / container the DB file doesn't exist yet — at startup
`restore_db_if_missing()` rebuilds it from the dump, so cloning both repos
is enough to get the full history back.

Auth: the GitHub PAT is read from `GITHUB_TOKEN_FILE` and passed to git as a
one-off HTTP header, so it is never written into the repo's config or remote URL.
"""

from __future__ import annotations

import base64
import logging
import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings

log = logging.getLogger(__name__)

DUMP_RELPATH = Path("db") / "stock-advisor.sql"


def _dump_path() -> Path:
    return get_settings().data_repo_dir / DUMP_RELPATH


def export_db() -> Path:
    """Write a full SQL dump of the working DB into the data repo."""
    s = get_settings()
    out = _dump_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".sql.tmp")
    src = sqlite3.connect(s.db_path)
    try:
        with tmp.open("w", encoding="utf-8") as f:
            for line in src.iterdump():
                f.write(line + "\n")
    finally:
        src.close()
    tmp.replace(out)
    return out


def restore_db_if_missing() -> bool:
    """Rebuild the SQLite DB from the data-repo dump if the DB file is absent."""
    s = get_settings()
    db_file = s.db_path
    dump = _dump_path()
    if db_file.exists() or not dump.exists():
        return False
    log.info("No local DB at %s — restoring from %s", db_file, dump)
    conn = sqlite3.connect(db_file)
    try:
        conn.executescript(dump.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return True


def _git(*args: str, config: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run git in the data repo. `config` is passed via GIT_CONFIG_* env vars,
    so values (like the auth header) never appear in argv, `ps`, or tracebacks."""
    s = get_settings()
    env = dict(os.environ)
    for i, (k, v) in enumerate((config or {}).items()):
        env[f"GIT_CONFIG_KEY_{i}"] = k
        env[f"GIT_CONFIG_VALUE_{i}"] = v
    env["GIT_CONFIG_COUNT"] = str(len(config or {}))
    return subprocess.run(
        ["git", "-C", str(s.data_repo_dir), *args],
        capture_output=True, text=True, check=True, timeout=300, env=env,
    )


def _auth_config() -> dict[str, str]:
    token = get_settings().github_token()
    if not token:
        return {}
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "credential.helper": "",
        "http.https://github.com/.extraheader": f"AUTHORIZATION: basic {basic}",
    }


def publish(reason: str = "scheduled") -> dict:
    """Export the DB, commit any changes in the data repo, and push.

    Never raises — failures are logged and returned so callers (pipelines,
    routes) are not broken by a publishing problem.
    """
    s = get_settings()
    result: dict = {"committed": False, "pushed": False}
    try:
        if not (s.data_repo_dir / ".git").exists():
            raise RuntimeError(f"data repo not found at {s.data_repo_dir}")

        export_db()
        _git("add", "-A")
        if not _git("status", "--porcelain").stdout.strip():
            result["detail"] = "no changes"
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _git(
                "commit", "-m", f"data: {reason} sync {stamp}",
                config={"user.name": s.git_author_name, "user.email": s.git_author_email},
            )
            result["committed"] = True

        auth = _auth_config()
        if not auth:
            result["detail"] = "no GitHub token — committed locally only"
            log.warning("Data publish: %s", result["detail"])
            return result

        # Push whenever we're ahead of the remote (also retries earlier failed pushes).
        _git("fetch", s.data_repo_remote, s.data_repo_branch, config=auth)
        ahead = _git(
            "rev-list", "--count", f"{s.data_repo_remote}/{s.data_repo_branch}..HEAD"
        ).stdout.strip()
        if ahead != "0":
            _git("push", s.data_repo_remote, f"HEAD:{s.data_repo_branch}", config=auth)
            result["pushed"] = True
        result["sha"] = _git("rev-parse", "HEAD").stdout.strip()
        log.info("Data publish (%s): %s", reason, result)
    except subprocess.CalledProcessError as exc:
        result["error"] = (exc.stderr or str(exc)).strip()[:500]
        log.error("Data publish failed: %s", result["error"])
    except Exception as exc:  # noqa: BLE001
        result["error"] = repr(exc)[:500]
        log.exception("Data publish failed: %s", exc)
    return result
