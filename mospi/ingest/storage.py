"""Controlled storage for uploaded files.

* Server-generated names only (``<upload root>/<dataset_id>/files/<file_id>.csv``); the client's file name and folder
  path are display text, sanitised and never used to build a path (no traversal is possible).
* Streamed to disk in chunks with a hard size cap; SHA-256, size, UTF-8 validity, BOM and NUL bytes are recorded on the fly.
* A content fingerprint (order- and line-ending-independent sum of per-line digests) detects a re-saved copy of an
  earlier file.  The original bytes are never changed.
"""
from __future__ import annotations

import codecs
import hashlib
import os
import re
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

MASK = (1 << 128) - 1
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
NUL = b"\x00"
CR, LF = b"\r", b"\n"


class UploadRejected(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def new_id() -> str:
    return uuid.uuid4().hex


def safe_display_name(name: str) -> str:
    base = PurePosixPath(str(name or "").replace("\\", "/")).name
    base = CONTROL.sub("", base).strip()[:200]
    if not base or base in {".", ".."}:
        raise UploadRejected("The file name is empty or not allowed.")
    return base


def safe_relative_path(path: str | None) -> str | None:
    """A folder-relative path for display only; absolute paths, drive letters and '..' are refused."""
    if not path:
        return None
    text = CONTROL.sub("", str(path).replace("\\", "/")).strip()
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text) or any(p == ".." for p in parts) or len(text) > 500:
        raise UploadRejected("The folder path of a file must be relative and may not contain '..'.")
    return "/".join(parts) or None


def dataset_dir(upload_root: Path, dataset_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", dataset_id or ""):
        raise UploadRejected("Unknown dataset.", 404)
    return Path(upload_root) / dataset_id


class ContentDigest:
    """SHA-256, size, UTF-8 validity, BOM, NUL bytes and the content fingerprint of a byte stream."""

    def __init__(self, max_bytes: int | None = None) -> None:
        self.max_bytes = max_bytes
        self.size = 0
        self.sha = hashlib.sha256()
        self.decoder = codecs.getincrementaldecoder("utf-8")("strict")
        self.utf8 = True
        self.nul = False
        self.head = b""
        self.pending = b""
        self.lines = 0
        self.total = 0

    def _line(self, line: bytes) -> None:
        line = line.rstrip(CR)
        if not line:
            return
        self.lines += 1
        if self.lines == 1:                     # header row: not part of the content fingerprint
            return
        self.total = (self.total + int.from_bytes(hashlib.blake2b(line, digest_size=16).digest(), "big")) & MASK

    def update(self, chunk: bytes) -> None:
        if not chunk:
            return
        self.size += len(chunk)
        if self.max_bytes is not None and self.size > self.max_bytes:
            raise UploadRejected(f"The file is larger than the configured limit of {self.max_bytes // (1024 * 1024):,} MB.", 413)
        if len(self.head) < 4:
            self.head = (self.head + chunk)[:4]
        self.sha.update(chunk)
        self.nul = self.nul or NUL in chunk
        if self.utf8:
            try:
                self.decoder.decode(chunk)
            except UnicodeDecodeError:
                self.utf8 = False
        *complete, self.pending = (self.pending + chunk).split(LF)
        for line in complete:
            self._line(line)

    def result(self) -> dict[str, Any]:
        if self.pending:
            self._line(self.pending)
            self.pending = b""
        if self.utf8:
            try:
                self.decoder.decode(b"", final=True)
            except UnicodeDecodeError:
                self.utf8 = False
        return {"size_bytes": self.size, "sha256": self.sha.hexdigest(), "content_fingerprint": f"{self.total:032x}:{max(self.lines - 1, 0)}",
                "encoding": "utf-8-bom" if self.head.startswith(codecs.BOM_UTF8) else "utf-8" if self.utf8 else "not-utf-8", "nul_bytes": self.nul}


def fingerprint_file(path: Path) -> dict[str, Any]:
    digest = ContentDigest()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return {**digest.result(), "mtime_ns": Path(path).stat().st_mtime_ns}


class FileReceiver:
    """Write one streamed upload to a temporary file; :meth:`finish` makes it final (atomic rename)."""

    def __init__(self, destination: Path, max_bytes: int) -> None:
        self.destination = destination
        self.temporary = destination.with_suffix(".part")
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.temporary, "xb")
        self.digest = ContentDigest(max_bytes)

    def write(self, chunk: bytes) -> None:
        self.digest.update(chunk)
        self.handle.write(chunk)

    def finish(self) -> dict[str, Any]:
        result = self.digest.result()
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.handle.close()
        os.replace(self.temporary, self.destination)
        return {**result, "mtime_ns": self.destination.stat().st_mtime_ns}

    def abort(self) -> None:
        try:
            self.handle.close()
        finally:
            self.temporary.unlink(missing_ok=True)       # our own incomplete temporary file, never an accepted upload
