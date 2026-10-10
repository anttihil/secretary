"""Best-effort background commits and pushes for the notes repository."""

import asyncio
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from backend import paths
from backend.paths import FRONTMATTER_TIMESTAMP_FMT

logger = logging.getLogger(__name__)


def is_git_repo(path: Path) -> bool:
    """Check if path is inside a git repository."""
    current = path.resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return True
        current = current.parent
    return False


def git_sync():
    """Commit and push saved notes; log errors without raising them."""
    if not is_git_repo(paths.NOTES_DIR):
        return
    try:
        subprocess.run(
            ["git", "add", "--", "."],
            cwd=paths.NOTES_DIR,
            check=True,
            capture_output=True,
        )
        try:
            timestamp = datetime.now(timezone.utc).strftime(FRONTMATTER_TIMESTAMP_FMT)
            msg = f"Update notes {timestamp}"
            subprocess.run(
                ["git", "commit", "-m", msg],
                cwd=paths.NOTES_DIR,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as commit_err:
            if b"nothing to commit" not in commit_err.stdout:
                logger.error(
                    "Git commit failed: %s (stderr: %s)",
                    commit_err,
                    commit_err.stderr,
                )
        subprocess.run(
            ["git", "push"], cwd=paths.NOTES_DIR, check=True, capture_output=True
        )
    except subprocess.CalledProcessError as e:
        logger.error("Git sync failed: %s (stderr: %s)", e, e.stderr)
    except Exception as e:
        logger.error("Git sync unexpected error: %s", e)


def schedule_git_sync():
    asyncio.create_task(asyncio.to_thread(git_sync))
