"""Bounded, read-only file preview and workspace-wide search."""
from __future__ import annotations

from pathlib import Path
from app.core import database
from app.core.explorer import EXCLUDE

MAX_FILE_BYTES = 256 * 1024
MAX_SEARCH_FILES = 1200
MAX_RESULTS = 80
MAX_DEPTH = 8
TEXT_EXTENSIONS = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".html", ".htm",
                   ".css", ".scss", ".json", ".jsonc", ".md", ".txt", ".yml",
                   ".yaml", ".toml", ".ini", ".cfg", ".xml", ".svg", ".sql",
                   ".sh", ".bat", ".cmd", ".ps1", ".gitignore", ".env.example"}
TEXT_NAMES = {"Dockerfile", "Makefile", "LICENSE", ".gitignore", ".editorconfig",
              ".gitattributes", "requirements.txt", "README"}
SKIP_DIRS = EXCLUDE | {"runtime", "dist", "build", "backups", ".mypy_cache", ".ruff_cache"}
SKIP_FILES = {".env", ".env.local", ".env.production", ".env.development"}

class InvalidFile(ValueError):
    pass

def _path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or len(relative) > 1000 or "\x00" in relative:
        raise InvalidFile("invalid_path")
    candidate = Path(relative.replace("\\", "/"))
    if candidate.is_absolute() or any(part in ("..", ".") for part in candidate.parts):
        raise InvalidFile("invalid_path")
    if any(part in SKIP_DIRS or part in SKIP_FILES for part in candidate.parts):
        raise InvalidFile("restricted_path")
    root = root.resolve()
    path = root / candidate
    # Reject symlinks even when they point back into the project.
    cursor = root
    for part in candidate.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise InvalidFile("symlink_not_allowed")
    if not path.resolve().is_relative_to(root):
        raise InvalidFile("invalid_path")
    return path

def _text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS or path.name in TEXT_NAMES

def preview(root: Path, relative: str) -> dict:
    path = _path(root, relative)
    if not path.is_file() or not _text_file(path):
        raise InvalidFile("unsupported_file")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise InvalidFile("file_too_large")
    try:
        content = path.read_text(encoding="utf-8-sig")
    except (UnicodeError, OSError):
        raise InvalidFile("unreadable_file") from None
    if "\x00" in content:
        raise InvalidFile("binary_file")
    return {"path": path.relative_to(root.resolve()).as_posix(), "name": path.name,
            "extension": path.suffix.lower(), "content": content,
            "lines": content.count("\n") + 1, "bytes": path.stat().st_size}

def search(root: Path, query: str, limit: int = 50) -> dict:
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 120:
        raise ValueError("query_must_be_2_to_120_characters")
    query = query.strip()
    limit = max(1, min(int(limit), MAX_RESULTS))
    needle = query.casefold()
    results = []
    scanned = 0
    truncated = False

    def add(result: dict) -> bool:
        nonlocal truncated
        if len(results) >= limit:
            truncated = True
            return False
        results.append(result)
        return True

    # Existing notes API is the source of truth for active notes.
    for note in database.list_notes(search=query):
        if note.get("deleted_at"):
            continue
        title = note.get("title", "")
        content = note.get("content", "")
        pos = content.casefold().find(needle)
        excerpt = content[max(0, pos - 55):pos + len(query) + 85] if pos >= 0 else content[:125]
        if not add({"type": "note", "id": note["id"], "title": title, "excerpt": excerpt}):
            return {"query": query, "results": results, "scanned_files": scanned, "truncated": truncated}

    root = root.resolve()
    def walk(folder: Path, depth: int) -> None:
        nonlocal scanned, truncated
        if depth > MAX_DEPTH or scanned >= MAX_SEARCH_FILES or truncated:
            truncated = True
            return
        try:
            children = sorted(folder.iterdir(), key=lambda p: p.name.casefold())
        except OSError:
            return
        for path in children:
            if truncated:
                return
            if path.is_symlink() or path.name in SKIP_DIRS or path.name in SKIP_FILES:
                continue
            if path.is_dir():
                walk(path, depth + 1)
                continue
            if not path.is_file() or not _text_file(path):
                continue
            scanned += 1
            if scanned > MAX_SEARCH_FILES:
                truncated = True
                return
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
                content = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                continue
            if "\x00" in content:
                continue
            relative = path.relative_to(root).as_posix()
            if needle in path.name.casefold():
                if not add({"type": "file", "path": relative, "title": path.name,
                            "line": 0, "excerpt": relative}):
                    return
            for line_number, line in enumerate(content.splitlines(), 1):
                if needle in line.casefold():
                    if not add({"type": "file", "path": relative, "title": path.name,
                                "line": line_number, "excerpt": line.strip()[:220]}):
                        return
    walk(root, 0)
    return {"query": query, "results": results, "scanned_files": scanned, "truncated": truncated}
