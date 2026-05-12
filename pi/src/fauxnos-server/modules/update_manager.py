#!/usr/bin/env python3
"""
Fauxnos Update Manager — version detection + deploy bookkeeping
================================================================

Two drift signals power the update pipeline:

    1. Server vs GitHub.   `git status` on this machine's sparse checkout
       compared to `origin/main`. Drives the "GitHub has N new commits —
       Update server" pill in the UI. See `get_server_git_status()`.

    2. Each client vs server.  Each registered client carries a
       `deployed_sha` in `server_config.json`. We compare it to our own
       HEAD to count commits behind. Drives the per-device "Update"
       button. See `get_client_deploy_info()`.

This module is the pure-Python core: no HTTP, no SSH, no SSE. Those
glue layers live in `api_server.py` (endpoints, SSE) and will live
alongside `install_runner.py` (SSH push). Keeping the core pure makes
it easy to unit-test and reason about in isolation.

The canonical deploy chain (codified in
`memory/feedback_deploy_workflow.md`):

    macbook ── rsync (dev) ──► fauxnos000 working tree
    macbook ── git push ─────► github origin/main
    fauxnos000 ── git pull ──► fauxnos000 working tree    (the "server self-update")
    fauxnos000 ── SSH + curl install.sh ──► each client   (the "client deploy")

`record_client_deploy()` is called by the SSH-side glue after a
successful per-client deploy; it persists the SHA + timestamp +
needs-reboot flag back to `server_config.json` so subsequent UI loads
show "up to date" instead of "N behind".
"""

import json
import logging
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


logger = logging.getLogger("update_manager")


# ── git checkout location ─────────────────────────────────────────────────────

def _find_repo_root() -> Path:
    """Walk up from this file's location looking for the .git directory.

    On fauxnos000 after the 2026-05-12 conversion this resolves to
    `~/src/fauxnos/` (the sparse-checkout clone of github.com/dmayman/fauxnos),
    reached through the `~/src/fauxnos-server` → `~/src/fauxnos/pi/src/
    fauxnos-server` symlink. On a dev macbook it resolves to the repo root.

    Raises RuntimeError if no `.git` exists anywhere up the chain — that
    means the server was deployed via the legacy rsync-only path and the
    update pipeline can't run until it's converted (see
    `feedback_deploy_workflow.md` for the conversion procedure).
    """
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    raise RuntimeError(
        f"update_manager: could not find a .git ancestor of {__file__}. "
        "The server must run from inside a git checkout. See "
        "memory/feedback_deploy_workflow.md for the conversion procedure."
    )


REPO_ROOT = _find_repo_root()


# ── dataclasses for typed return values ───────────────────────────────────────

@dataclass
class ServerGitStatus:
    """Snapshot of this server's checkout state vs origin/main.

    Field meanings:
        sha          : full HEAD sha (40 hex)
        short_sha    : 7-char short for display
        branch       : current branch name (`main` in the canonical state;
                       `(detached)` if HEAD is not on a branch)
        dirty        : `git status --porcelain` is non-empty — there are
                       uncommitted changes in the working tree. Usually
                       means dev iteration is in progress; we should NOT
                       offer a "git pull" button in this state (would
                       conflict).
        origin_sha   : `origin/main` HEAD (full sha), or None if origin
                       hasn't been fetched / is unreachable.
        behind       : how many commits on origin/main are not in HEAD
                       (= "Update server" badge count when > 0).
        ahead        : how many commits on HEAD are not in origin/main
                       (rare on a server, but possible during a hot dev
                       iteration where rsync brought changes that were
                       then committed locally on the server).
        fetch_failed : True if the fetch step we attempted didn't succeed.
                       Surfaced so the UI can show "(offline)" instead of
                       silently presenting stale drift counts.
    """
    sha: str
    short_sha: str
    branch: str
    dirty: bool
    origin_sha: Optional[str]
    behind: int
    ahead: int
    fetch_failed: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClientDeployInfo:
    """A client's last-deployed state, tracked in `server_config.json`.

    All fields are Optional because clients registered before the update
    pipeline existed have no deploy record — the UI surfaces those as
    "unknown, first update will sync."

    `behind_server` is computed (not stored): it's the commit count from
    the stored `deployed_sha` to the server's current HEAD. It can also
    be None if the stored SHA isn't reachable in our object DB (e.g.
    after a force-push that orphaned it).
    """
    client_id: str
    deployed_sha: Optional[str]            # full SHA stored in server_config
    deployed_sha_short: Optional[str]      # convenience, 7-char
    deployed_at: Optional[str]             # ISO-8601 with timezone
    deploy_needs_reboot: bool              # last deploy touched reboot-sensitive state
    deploy_log_path: Optional[str]         # filesystem path to install log
    behind_server: Optional[int]           # commits between deployed_sha and HEAD

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── git wrapper ───────────────────────────────────────────────────────────────

def _git(*args: str, check: bool = True, timeout: float = 30.0) -> subprocess.CompletedProcess:
    """Run `git ...` in REPO_ROOT, capturing stdout/stderr as text.

    Default check=True raises on non-zero exit. Callers that expect
    failures (probing for refs that may not exist) should pass check=False
    and inspect `returncode`.
    """
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
    )


# ── public: server self-status ────────────────────────────────────────────────

def get_server_git_status(fetch: bool = True, fetch_timeout: float = 15.0) -> ServerGitStatus:
    """Inspect this server's git checkout and return a structured status.

    `fetch=True` (default) runs `git fetch origin` first so `origin/main`
    is current. Set False on cheap-polling paths (e.g. a 30s WebSocket
    update tick) to skip the network round-trip — the cached refs are
    fine for "is the server caught up?" UI purposes if a fetch fires
    elsewhere periodically. The endpoint that drives the "Update server"
    button should always pass fetch=True so the badge is accurate at
    click time.
    """
    fetch_failed = False
    if fetch:
        try:
            _git("fetch", "origin", "--quiet", timeout=fetch_timeout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            fetch_failed = True
            logger.warning("git fetch failed (offline?): %s — using cached refs", e)

    sha = _git("rev-parse", "HEAD").stdout.strip()
    short_sha = _git("rev-parse", "--short", "HEAD").stdout.strip()

    try:
        branch = _git("symbolic-ref", "--short", "HEAD").stdout.strip()
    except subprocess.CalledProcessError:
        # Detached HEAD — happens if someone manually checked out a SHA.
        branch = "(detached)"

    dirty = bool(_git("status", "--porcelain").stdout.strip())

    origin_sha: Optional[str] = None
    behind = 0
    ahead = 0
    try:
        origin_sha = _git("rev-parse", "origin/main").stdout.strip()
        behind = int(
            _git("rev-list", "--count", "HEAD..origin/main").stdout.strip() or "0"
        )
        ahead = int(
            _git("rev-list", "--count", "origin/main..HEAD").stdout.strip() or "0"
        )
    except subprocess.CalledProcessError:
        # origin/main not present (no remote, or never fetched).
        pass

    return ServerGitStatus(
        sha=sha,
        short_sha=short_sha,
        branch=branch,
        dirty=dirty,
        origin_sha=origin_sha,
        behind=behind,
        ahead=ahead,
        fetch_failed=fetch_failed,
    )


# ── public: per-client deploy info ────────────────────────────────────────────

def get_client_deploy_info(client_id: str, server_config: Dict[str, Any]) -> ClientDeployInfo:
    """Read deploy state for a given client out of `server_config.json`.

    `server_config` is the live dict from `ConfigManager.server_config` —
    we accept it as a parameter (rather than importing ConfigManager) to
    avoid the circular dependency that would otherwise form (config_manager
    is a relatively low-level module and we want update_manager callable
    from it indirectly if needed).

    Missing fields are treated as "never deployed via the pipeline" — the
    function returns a ClientDeployInfo with deployed_sha=None, which the
    UI renders as an "unknown / never updated" state. The first update
    via the new pipeline sets the fields for the first time.
    """
    client_dict: Dict[str, Any] = {}
    for c in server_config.get("clients", []):
        if c.get("id") == client_id:
            client_dict = c
            break
    # No fall-through error if the client is missing: callers (e.g. the
    # UI loading the device list) get back a deploy-info object with the
    # client_id echoed and all-None fields, which renders cleanly.

    deployed_sha: Optional[str] = client_dict.get("deployed_sha")
    deployed_at: Optional[str] = client_dict.get("deployed_at")
    deploy_needs_reboot: bool = bool(client_dict.get("deploy_needs_reboot", False))
    deploy_log_path: Optional[str] = client_dict.get("deploy_log_path")

    deployed_sha_short: Optional[str] = None
    if deployed_sha:
        deployed_sha_short = deployed_sha[:7]

    behind_server: Optional[int] = None
    if deployed_sha:
        try:
            result = _git(
                "rev-list", "--count", f"{deployed_sha}..HEAD",
                check=False,
            )
            if result.returncode == 0:
                behind_server = int(result.stdout.strip() or "0")
            # else: the stored SHA isn't in our object DB (force-push
            # orphaned it, or it's from a deleted branch). behind_server
            # stays None — UI shows "?".
        except (subprocess.CalledProcessError, ValueError):
            behind_server = None

    return ClientDeployInfo(
        client_id=client_id,
        deployed_sha=deployed_sha,
        deployed_sha_short=deployed_sha_short,
        deployed_at=deployed_at,
        deploy_needs_reboot=deploy_needs_reboot,
        deploy_log_path=deploy_log_path,
        behind_server=behind_server,
    )


# ── public: persist a deploy ──────────────────────────────────────────────────

def record_client_deploy(
    config_manager,                  # duck-typed ConfigManager (no import to avoid cycle)
    client_id: str,
    sha: str,
    needs_reboot: bool,
    log_path: Optional[str] = None,
) -> bool:
    """Persist a successful deploy to `server_config.json`.

    Called by the SSH-side glue (Phase B3 endpoint) once install.sh has
    completed on the target client. Stores the FULL sha (so future
    rev-list math is unambiguous), an ISO-8601 timestamp, the
    needs-reboot flag (from the install.sh marker file), and optionally
    a path to the install log.

    Returns True on success, False if the client wasn't in
    server_config.json. **Does not raise** — a failed bookkeeping write
    shouldn't undo an otherwise-successful install; we log loudly and
    let the caller decide how to surface that to the user.
    """
    server_config = config_manager.server_config
    now_iso = datetime.now(timezone.utc).isoformat()

    for c in server_config.get("clients", []):
        if c.get("id") == client_id:
            c["deployed_sha"] = sha
            c["deployed_at"] = now_iso
            c["deploy_needs_reboot"] = bool(needs_reboot)
            if log_path is not None:
                c["deploy_log_path"] = log_path
            try:
                config_manager.save_server_config()
                logger.info(
                    "Recorded deploy: client=%s sha=%s needs_reboot=%s",
                    client_id, sha[:7], needs_reboot,
                )
                return True
            except Exception as e:
                logger.error(
                    "Failed to persist deploy record for %s: %s",
                    client_id, e,
                )
                return False

    logger.error(
        "record_client_deploy: client %s not present in server_config",
        client_id,
    )
    return False


# ── smoke test when run directly ──────────────────────────────────────────────

if __name__ == "__main__":
    # `python3 -m modules.update_manager` from ~/src/fauxnos-server prints
    # the current server git status and (if server_config.json is present)
    # a deploy-info summary per registered client. Useful for verifying
    # the module on a freshly-converted server without spinning up Flask.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("=== REPO_ROOT ===")
    print(REPO_ROOT)
    print()
    print("=== Server git status ===")
    s = get_server_git_status(fetch=True)
    print(json.dumps(s.to_dict(), indent=2))
    print()

    # Best-effort: load server_config.json if it's where we expect it and
    # print client deploy info. Pure read; doesn't modify anything.
    config_path = REPO_ROOT / "pi/src/fauxnos-server/server_config.json"
    if config_path.exists():
        with open(config_path) as f:
            cfg = json.load(f)
        print(f"=== Client deploy info ({len(cfg.get('clients', []))} clients) ===")
        for c in cfg.get("clients", []):
            info = get_client_deploy_info(c["id"], cfg)
            print(json.dumps(info.to_dict(), indent=2))
    else:
        print(f"(no server_config.json at {config_path} — skipping client summary)")
