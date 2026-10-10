"""Import existing Markdown files into Secretary's note format."""

import re
from datetime import datetime, timezone

from fastapi import APIRouter

from backend import paths
from backend.git_sync import schedule_git_sync
from backend.note_storage import (
    ensure_notes_dir,
    format_frontmatter,
    is_excluded_note,
    parse_frontmatter,
    slugify,
)
from backend.paths import (
    FILE_TIMESTAMP_FMT,
    FILENAME_RE,
    FRONTMATTER_TIMESTAMP_FMT,
)

router = APIRouter()


@router.post("/api/migrate")
async def migrate_notes():
    ensure_notes_dir()
    resolved = paths.NOTES_DIR.resolve()
    migrated = 0
    skipped = 0
    files = []
    for path in sorted(
        p for p in paths.NOTES_DIR.rglob("*.md") if not is_excluded_note(p)
    ):
        metadata, body = parse_frontmatter(path.read_text())
        actions = []
        m = re.match(r"^(.+)-(\d{8}-\d{6})$", path.stem)
        if m:
            slug = m.group(1)
            file_dt = datetime.strptime(m.group(2), FILE_TIMESTAMP_FMT).replace(
                tzinfo=timezone.utc
            )
        else:
            slug = path.stem
            file_dt = None
        filename_compliant = FILENAME_RE.match(path.name) is not None
        all_keys_present = all(k in metadata for k in ("title", "created", "updated"))
        if all_keys_present and filename_compliant:
            skipped += 1
            continue
        if "title" not in metadata:
            s = slug.replace("-", " ")
            metadata["title"] = s[0].upper() + s[1:]
            actions.append("added title")
        if "created" not in metadata:
            if file_dt:
                metadata["created"] = file_dt.strftime(FRONTMATTER_TIMESTAMP_FMT)
            else:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                metadata["created"] = mtime.strftime(FRONTMATTER_TIMESTAMP_FMT)
            actions.append("added created")
        if "updated" not in metadata:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            metadata["updated"] = mtime.strftime(FRONTMATTER_TIMESTAMP_FMT)
            actions.append("added updated")
        path.write_text(format_frontmatter(metadata, body))
        original_filename = str(path.resolve().relative_to(resolved))
        new_filename = original_filename
        if not filename_compliant:
            created_dt = datetime.strptime(
                metadata["created"], FRONTMATTER_TIMESTAMP_FMT
            )
            created_ts = created_dt.strftime(FILE_TIMESTAMP_FMT)
            new_basename = f"{slugify(metadata['title'])}-{created_ts}.md"
            new_path = path.parent / new_basename
            path.rename(new_path)
            new_filename = str(new_path.resolve().relative_to(resolved))
            actions.append(f"renamed to {new_basename}")
        migrated += 1
        files.append(
            {
                "original_filename": original_filename,
                "filename": new_filename,
                "actions": actions,
            }
        )
    if migrated > 0:
        schedule_git_sync()
    return {"migrated": migrated, "skipped": skipped, "files": files}
