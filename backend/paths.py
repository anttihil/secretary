"""Shared filesystem locations and note naming conventions."""

import os
import re
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
NOTES_DIR = Path(os.environ.get("NOTES_DIR", PROJECT_DIR / "notes"))
GLOSSARY_PATH = NOTES_DIR / "glossary.txt"
FRONTMATTER_TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%S"
FILE_TIMESTAMP_FMT = "%Y%m%d-%H%M%S"
FILENAME_RE = re.compile(r"^.+-\d{8}-\d{6}\.md$")
