"""Bind owned JSON outputs to their run and to the exact bytes written/read."""

from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path
from typing import IO

from .contracts import PathInput, Provenance


def validate_checksum(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(
            "No valid SHA-256 checksum is recorded for this result file. It cannot be opened."
        )
    return value


def validate_run_id(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise ValueError("Results must identify their owning run with a valid run ID.")
    return value


def verify_run_id(provenance: Provenance, run_id: str) -> None:
    expected = validate_run_id(run_id)
    actual = validate_run_id(provenance.get("run_id"))
    if actual != expected:
        raise ValueError("This result file belongs to a different run. It cannot be opened here.")


def provenance_for_run(provenance: Provenance, run_id: str) -> Provenance:
    """Identify new owned writes without concealing a contradictory identity."""
    validate_run_id(run_id)
    if "run_id" in provenance:
        verify_run_id(provenance, run_id)
    return {**provenance, "run_id": run_id}


def read_verified_text(path: PathInput, checksum: object) -> str:
    expected = validate_checksum(checksum)
    # Hash this buffer and decode it once; never hash a pathname and then reopen
    # a potentially replaced file to obtain the scientific values.
    raw = Path(path).read_bytes()
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected):
        raise ValueError(
            "The result file has changed since it was saved or exported. "
            "Its SHA-256 checksum does not match run history."
        )
    return raw.decode("utf-8")


class DigestTextWriter:
    """Hash UTF-8 text sent to the atomic JSON writer, without another file read."""

    def __init__(self, stream: IO[str]) -> None:
        self.stream = stream
        self.digest = hashlib.sha256()

    def write(self, text: str) -> int:
        written = self.stream.write(text)
        if written != len(text):
            raise OSError("The result file could not be written completely.")
        self.digest.update(text.encode("utf-8"))
        return written

    def hexdigest(self) -> str:
        return self.digest.hexdigest()

    @property
    def mode(self) -> str:
        return self.stream.mode

    def flush(self) -> None:
        self.stream.flush()

    def seekable(self) -> bool:
        return False

    def seek(self, offset: int, whence: int = 0, /) -> int:
        raise OSError("A checksum writer cannot seek after hashing text.")

    def tell(self) -> int:
        return self.stream.tell()
