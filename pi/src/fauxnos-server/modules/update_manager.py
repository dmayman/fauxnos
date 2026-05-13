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

    Whole-repo fields:
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
                       (whole-repo; kept for legacy callers).
        ahead        : how many commits on HEAD are not in origin/main.
        fetch_failed : True if the fetch step we attempted didn't succeed.
                       Surfaced so the UI can show "(offline)" instead of
                       silently presenting stale drift counts.

    Per-component drift (Phase F1, 2026-05-13). The UI compares these
    against the deployed SHAs in server_config.json to decide whether
    to light up "Update server" / "Update clients (N)" pills independently:

        server_path_tip   : sha of the most-recent origin/main commit
                            touching pi/src/fauxnos-server/ (the "server tip")
        server_path_behind: commits from server_deployed_sha to
                            server_path_tip, filtered to that subtree.
                            None if server_deployed_sha is unset or
                            unreachable.
        server_deployed_sha: the SHA the running fauxnos-server is using,
                             persisted to server_config.json top-level.
                             None on a server that never self-updated via
                             /api/server/update (e.g. dev-iteration rsync).
        client_path_tip   : sha of the most-recent origin/main commit
                            touching pi/src/fauxnos-client/. Same purpose
                            for the client subtree.
    """
    sha: str
    short_sha: str
    branch: str
    dirty: bool
    origin_sha: Optional[str]
    behind: int
    ahead: int
    fetch_failed: bool
    server_path_tip: Optional[str] = None
    server_path_behind: Optional[int] = None
    server_deployed_sha: Optional[str] = None
    client_path_tip: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClientDeployInfo:
    """A client's last-deployed state, tracked in `server_config.json`.

    All fields are Optional because clients registered before the update
    pipeline existed have no deploy record — the UI surfaces those as
    "unknown, first update will sync."

    Phase F1 (2026-05-13): the single `deployed_sha` was renamed to
    `deployed_client_sha` to make the per-component intent explicit
    (the recorded SHA reflects the state of pi/src/fauxnos-client/ on
    the device, not the whole repo). `commits_behind` is now computed
    against the client-subtree tip on origin/main, not whole-repo HEAD —
    so a server-only commit no longer lights up the client-update button.
    """
    client_id: str
    deployed_client_sha: Optional[str]       # full SHA stored in server_config (renamed from deployed_sha)
    deployed_client_sha_short: Optional[str] # convenience, 7-char
    deployed_at: Optional[str]               # ISO-8601 with timezone
    deploy_needs_reboot: bool                # last deploy touched reboot-sensitive state
    deploy_log_path: Optional[str]           # filesystem path to install log
    commits_behind: Optional[int]            # commits touching pi/src/fauxnos-client/
                                              # between deployed_client_sha and client_path_tip

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


# ── public: path-filtered tip helpers ─────────────────────────────────────────

# The subtree roots whose commits we count separately. If the repo
# layout moves, update these in one place.
SERVER_SUBTREE_PATH = "pi/src/fauxnos-server"
CLIENT_SUBTREE_PATH = "pi/src/fauxnos-client"


def _path_tip(path: str) -> Optional[str]:
    """SHA of the most-recent origin/main commit touching `path`.

    Returns None if origin/main isn't reachable (never fetched) or if
    no commit has ever touched the path. Caller should treat None the
    same as "unknown" — UI renders it as such.
    """
    try:
        result = _git(
            "log", "-1", "--format=%H", "origin/main", "--", path,
            check=False,
        )
        if result.returncode != 0:
            return None
        sha = result.stdout.strip()
        return sha or None
    except subprocess.CalledProcessError:
        return None


def get_server_path_tip() -> Optional[str]:
    """SHA of the most-recent origin/main commit touching the server subtree."""
    return _path_tip(SERVER_SUBTREE_PATH)


def get_client_path_tip() -> Optional[str]:
    """SHA of the most-recent origin/main commit touching the client subtree."""
    return _path_tip(CLIENT_SUBTREE_PATH)


def _commits_in_path_range(from_sha: str, to_sha: str, path: str) -> Optional[int]:
    """Count commits touching `path` in the range from_sha..to_sha.

    Returns None on any error (orphaned SHA after force-push, unreachable
    ref). 0 is a valid value meaning "no path-relevant commits between
    the two SHAs."
    """
    try:
        result = _git(
            "rev-list", "--count", f"{from_sha}..{to_sha}", "--", path,
            check=False,
        )
        if result.returncode != 0:
            return None
        return int(result.stdout.strip() or "0")
    except (subprocess.CalledProcessError, ValueError):
        return None


# ── public: server self-status ────────────────────────────────────────────────

def get_server_git_status(
    fetch: bool = True,
    fetch_timeout: float = 15.0,
    server_config: Optional[Dict[str, Any]] = None,
) -> ServerGitStatus:
    """Inspect this server's git checkout and return a structured status.

    `fetch=True` (default) runs `git fetch origin` first so `origin/main`
    is current. Set False on cheap-polling paths (e.g. a 30s WebSocket
    update tick) to skip the network round-trip — the cached refs are
    fine for "is the server caught up?" UI purposes if a fetch fires
    elsewhere periodically. The endpoint that drives the "Update server"
    button should always pass fetch=True so the badge is accurate at
    click time.

    `server_config` (optional): the live dict from
    `ConfigManager.server_config`. When supplied, populates the
    server-side per-component fields (`server_deployed_sha`,
    `server_path_behind`). Pass None on early-init paths where the
    config isn't loaded yet — the path-tip fields are still populated.
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

    # Per-component drift (Phase F1).
    server_path_tip = get_server_path_tip() if origin_sha else None
    client_path_tip = get_client_path_tip() if origin_sha else None

    server_deployed_sha: Optional[str] = None
    server_path_behind: Optional[int] = None
    if server_config is not None:
        server_deployed_sha = server_config.get("server_deployed_sha") or None

    if server_deployed_sha and server_path_tip:
        server_path_behind = _commits_in_path_range(
            server_deployed_sha, server_path_tip, SERVER_SUBTREE_PATH,
        )
    elif server_path_tip and not server_deployed_sha:
        # No record of what the server was last started from — fall back
        # to "current HEAD vs path tip" so the UI still has a usable
        # signal until the first server self-update writes the field.
        # Using HEAD here is correct: the running fauxnos-server process
        # IS at HEAD if it was started from this working tree.
        server_path_behind = _commits_in_path_range(sha, server_path_tip, SERVER_SUBTREE_PATH)

    return ServerGitStatus(
        sha=sha,
        short_sha=short_sha,
        branch=branch,
        dirty=dirty,
        origin_sha=origin_sha,
        behind=behind,
        ahead=ahead,
        fetch_failed=fetch_failed,
        server_path_tip=server_path_tip,
        server_path_behind=server_path_behind,
        server_deployed_sha=server_deployed_sha,
        client_path_tip=client_path_tip,
    )


# ── public: per-client deploy info ────────────────────────────────────────────

def get_client_deploy_info(
    client_id: str,
    server_config: Dict[str, Any],
    client_path_tip: Optional[str] = None,
) -> ClientDeployInfo:
    """Read deploy state for a given client out of `server_config.json`.

    `server_config` is the live dict from `ConfigManager.server_config` —
    we accept it as a parameter (rather than importing ConfigManager) to
    avoid the circular dependency that would otherwise form (config_manager
    is a relatively low-level module and we want update_manager callable
    from it indirectly if needed).

    `client_path_tip`: pass a pre-computed value when calling this in a
    loop over many clients (one `git log` instead of N). When None, the
    function looks it up once locally; cheap for one-off calls.

    Missing deploy fields are treated as "never deployed via the pipeline"
    — the function returns deployed_client_sha=None, which the UI renders
    as an "unknown / never updated" state. The first update via the
    pipeline sets the fields for the first time.

    `commits_behind` is computed against the client subtree on origin/main,
    not whole-repo HEAD. So a server-only commit no longer makes clients
    "look behind" — only commits actually touching pi/src/fauxnos-client/
    count toward this device's update need.
    """
    client_dict: Dict[str, Any] = {}
    for c in server_config.get("clients", []):
        if c.get("id") == client_id:
            client_dict = c
            break
    # No fall-through error if the client is missing: callers (e.g. the
    # UI loading the device list) get back a deploy-info object with the
    # client_id echoed and all-None fields, which renders cleanly.

    deployed_client_sha: Optional[str] = client_dict.get("deployed_client_sha")
    deployed_at: Optional[str] = client_dict.get("deployed_at")
    deploy_needs_reboot: bool = bool(client_dict.get("deploy_needs_reboot", False))
    deploy_log_path: Optional[str] = client_dict.get("deploy_log_path")

    deployed_client_sha_short: Optional[str] = None
    if deployed_client_sha:
        deployed_client_sha_short = deployed_client_sha[:7]

    if client_path_tip is None:
        client_path_tip = get_client_path_tip()

    commits_behind: Optional[int] = None
    if deployed_client_sha and client_path_tip:
        commits_behind = _commits_in_path_range(
            deployed_client_sha, client_path_tip, CLIENT_SUBTREE_PATH,
        )

    return ClientDeployInfo(
        client_id=client_id,
        deployed_client_sha=deployed_client_sha,
        deployed_client_sha_short=deployed_client_sha_short,
        deployed_at=deployed_at,
        deploy_needs_reboot=deploy_needs_reboot,
        deploy_log_path=deploy_log_path,
        commits_behind=commits_behind,
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
            c["deployed_client_sha"] = sha
            c["deployed_at"] = now_iso
            c["deploy_needs_reboot"] = bool(needs_reboot)
            if log_path is not None:
                c["deploy_log_path"] = log_path
            try:
                config_manager.save_server_config()
                logger.info(
                    "Recorded client deploy: client=%s sha=%s needs_reboot=%s",
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


def record_server_deploy(config_manager, sha: str) -> bool:
    """Persist the SHA the running fauxnos-server is now using.

    Called from the success path of `/api/server/update` after the git
    pull but before the systemd restart fires — so the new SHA is on
    disk in `server_config.json` before the process gets SIGTERM'd.
    The post-restart server reads it back via `get_server_git_status`
    to compute server_path_behind.

    Stored at the top level (one server, one SHA — not per-client).
    Returns True on success, False on persistence failure.
    """
    config_manager.server_config["server_deployed_sha"] = sha
    try:
        config_manager.save_server_config()
        logger.info("Recorded server deploy: sha=%s", sha[:7])
        return True
    except Exception as e:
        logger.error("Failed to persist server deploy record: %s", e)
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
