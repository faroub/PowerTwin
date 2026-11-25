"""Dedicated, append-only, tamper-evident journal of operator actions.

Audit finding **F-09** recorded that the platform had no single, dedicated
operator-action journal. The audit trail was spread over four mechanisms that
did not agree with each other:

* ``backend/app/core/audit.py`` kept authentication events in memory and
  flushed them to a JSON file inside the source tree,
* ``backend/app/core/config_audit.py`` kept configuration changes in memory
  only,
* ``backend/app/controllers/command_log.py`` kept commands and setpoint
  changes in memory only, in a separate instance per control layer,
* ``backend/app/historian/service.py`` owned the durable ``command_records``
  table, but nothing in the running application ever wrote to it.

None of those was both durable and tamper-evident, and the operator actions
that matter most — the simulation control endpoint, which starts, pauses,
steps and resets the plant — were not recorded at all.

This module is the dedicated journal that the audit trail now flows through.

**Append-only.** The journal is a JSON Lines file that is only ever opened in
append mode. There is no method that rewrites, truncates or deletes an entry,
and the file is never rewritten in place.

**Tamper-evident.** Every entry carries the SHA-256 hash of its predecessor
and the SHA-256 hash of its own canonical content. Changing, removing or
reordering an entry breaks the chain from that point on, and
:meth:`OperatorActionJournal.verify` reports the first break. A journal whose
chain is intact is evidence that the trail was not edited after the fact; it
is not a signature, and it says nothing about an entry that was never written.

**Process-scoped.** An audit trail belongs to the process that produced it.
Two applications running in one process must not be able to write two trails
that both claim to be complete, so the journal is a single guarded service
reached through :func:`get_operator_journal` — one entry point, one trail.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend.app.core.secrets import redact_details

logger = logging.getLogger(__name__)

# Key used by the application to hold the journal on ``app.state``.
OPERATOR_JOURNAL_KEY = "operator_journal"

# The predecessor hash of the very first entry: a chain has to start
# somewhere, and a fixed value is easier to verify than an empty field.
GENESIS_HASH = "0" * 64


class OperatorJournalError(RuntimeError):
    """Raised when an entry cannot be written to, or read back from, the journal."""


def _now_ns() -> int:
    """Return the current wall-clock time as nanoseconds since the epoch."""
    return int(datetime.datetime.now(datetime.UTC).timestamp() * 1_000_000_000)


def _canonical(payload: dict[str, Any]) -> str:
    """Return the canonical serialisation of a journal payload.

    The keys are sorted and the separators are fixed, so the same content
    always produces the same string — on any machine, in any process, at any
    time. The hash of an entry is taken over this string, which is what makes
    the chain reproducible during verification.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def _hash_payload(payload: dict[str, Any]) -> str:
    """Return the SHA-256 hash of a canonicalised journal payload."""
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    """Return a value that can be stored as JSON and re-read unchanged.

    Audit details come from arbitrary callers, so a value that is not JSON
    native — a NumPy float, a ``Decimal``, an object — is rendered as its
    string form rather than making the write fail.
    """
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return str(value)


class JournalEntry(BaseModel):
    """One immutable, hash-chained record of an operator action."""

    sequence: int = Field(description="Position of the entry in the chain, starting at 1")
    timestamp_ns: int = Field(description="Wall-clock time of the record, in nanoseconds")
    recorded_at: str = Field(description="Wall-clock time of the record as an ISO-8601 string")
    source: str = Field(description="Origin of the record, e.g. OPERATOR, EXTERNAL_CIL, AUTH")
    action: str = Field(description="What was done, e.g. SIMULATION_START")
    actor: str = Field(description="Who or what caused it, e.g. an operator name")
    target: str = Field(description="What it was done to, e.g. the plant identifier")
    outcome: str = Field(description="How it ended, e.g. SUCCESS, FAILURE, REJECTED")
    details: dict[str, Any] = Field(default_factory=dict, description="Action-specific context")
    previous_hash: str = Field(description="The entry_hash of the preceding entry")
    entry_hash: str = Field(description="The SHA-256 hash of this entry's own content")


class JournalVerification(BaseModel):
    """The outcome of checking the chain of a journal."""

    ok: bool = Field(description="True when every entry follows its predecessor unchanged")
    entries: int = Field(description="Number of entries that were checked")
    first_broken_sequence: int | None = Field(
        default=None, description="Sequence number of the first entry that broke the chain"
    )
    reason: str | None = Field(default=None, description="Why the chain is broken")


class OperatorActionJournal:
    """An append-only, hash-chained journal of operator actions.

    The journal is safe to share between threads: every write is serialised by
    a re-entrant lock, so the chain cannot be interleaved.
    """

    def __init__(self, path: Path | str, *, fsync: bool = True) -> None:
        """Bind the journal to a file path.

        The file is created on the first write, not here, so that constructing
        a journal never touches the filesystem.
        """
        self.path = Path(path)
        self.fsync = fsync
        self._lock = threading.RLock()
        self._handle: Any = None
        self._sequence = 0
        self._last_hash = GENESIS_HASH
        self._degraded = False
        self._last_error: str | None = None

    # ------------------------------------------------------------------ #
    # State
    # ------------------------------------------------------------------ #

    @property
    def degraded(self) -> bool:
        """True when a write has failed since the journal was opened.

        A degraded journal has a gap in its trail. The condition is reported
        rather than hidden, so that an operator can tell the difference
        between "nothing happened" and "the record could not be written".
        """
        return self._degraded

    @property
    def last_error(self) -> str | None:
        """The message of the last write failure, or ``None``."""
        return self._last_error

    @property
    def sequence(self) -> int:
        """The sequence number of the last entry written to this journal."""
        with self._lock:
            return self._sequence

    # ------------------------------------------------------------------ #
    # Writing
    # ------------------------------------------------------------------ #

    def record(
        self,
        *,
        action: str,
        actor: str,
        target: str,
        source: str = "OPERATOR",
        outcome: str = "SUCCESS",
        details: dict[str, Any] | None = None,
        timestamp_ns: int | None = None,
    ) -> JournalEntry:
        """Append one entry to the journal and return it.

        The entry is written in append mode, flushed to the operating system
        and — unless ``fsync`` was turned off — forced all the way to the
        storage device before this call returns.

        Sensitive values inside ``details`` are redacted before the entry is
        stored, so an audit trail never becomes a secondary store of
        credentials.

        Raises:
            OperatorJournalError: when the entry could not be written. The
                failure is never swallowed: the journal is marked degraded and
                the error is logged as an error.
        """
        with self._lock:
            self._ensure_open()

            payload: dict[str, Any] = {
                "sequence": self._sequence + 1,
                "timestamp_ns": timestamp_ns if timestamp_ns is not None else _now_ns(),
                "recorded_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "source": source,
                "action": action,
                "actor": actor,
                "target": target,
                "outcome": outcome,
                "details": _json_safe(redact_details(details) if details else {}),
                "previous_hash": self._last_hash,
            }
            entry_hash = _hash_payload(payload)
            entry = JournalEntry(**payload, entry_hash=entry_hash)

            try:
                self._handle.write(entry.model_dump_json() + "\n")
                self._handle.flush()
                if self.fsync:
                    os.fsync(self._handle.fileno())
            except (OSError, ValueError) as err:
                self._degraded = True
                self._last_error = str(err)
                logger.error(
                    "Could not write the operator-action journal to %s: %s", self.path, err
                )
                msg = f"the operator-action journal at {self.path} could not be written: {err}"
                raise OperatorJournalError(msg) from err

            self._sequence = payload["sequence"]
            self._last_hash = entry_hash
            return entry

    # ------------------------------------------------------------------ #
    # Reading and verification
    # ------------------------------------------------------------------ #

    def read(self) -> list[JournalEntry]:
        """Return every entry that can be parsed from the journal.

        A line that cannot be parsed is skipped with a warning, because this
        is a convenience view. :meth:`verify` is the authoritative integrity
        check and it treats the same line as a break in the chain.
        """
        entries: list[JournalEntry] = []
        for number, line in self._lines():
            try:
                entries.append(JournalEntry.model_validate_json(line))
            except Exception as err:  # noqa: BLE001 - a malformed line must not stop the read
                logger.warning(
                    "Malformed operator-action journal entry on line %d ignored: %s", number, err
                )
        return entries

    def verify(self) -> JournalVerification:
        """Check the chain of the journal and report the first break.

        The check confirms that every entry follows its predecessor, carries
        the expected sequence number, and still hashes to the value it was
        written with. An entry that was altered, removed or reordered breaks
        the chain at that point.
        """
        previous = GENESIS_HASH
        expected_sequence = 1
        checked = 0

        for number, line in self._lines():
            checked += 1
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as err:
                return JournalVerification(
                    ok=False,
                    entries=checked,
                    first_broken_sequence=expected_sequence,
                    reason=f"line {number} is not valid JSON: {err}",
                )
            if not isinstance(payload, dict):
                return JournalVerification(
                    ok=False,
                    entries=checked,
                    first_broken_sequence=expected_sequence,
                    reason=f"line {number} is not a JSON object",
                )

            stored_hash = payload.pop("entry_hash", None)
            if not isinstance(stored_hash, str):
                return JournalVerification(
                    ok=False,
                    entries=checked,
                    first_broken_sequence=expected_sequence,
                    reason=f"line {number} carries no entry hash",
                )
            if payload.get("previous_hash") != previous:
                return JournalVerification(
                    ok=False,
                    entries=checked,
                    first_broken_sequence=expected_sequence,
                    reason=f"line {number} does not follow the preceding entry",
                )
            if payload.get("sequence") != expected_sequence:
                return JournalVerification(
                    ok=False,
                    entries=checked,
                    first_broken_sequence=expected_sequence,
                    reason=(
                        f"line {number} carries sequence {payload.get('sequence')} "
                        f"where {expected_sequence} was expected"
                    ),
                )
            if _hash_payload(payload) != stored_hash:
                return JournalVerification(
                    ok=False,
                    entries=checked,
                    first_broken_sequence=expected_sequence,
                    reason=f"line {number} has been altered since it was written",
                )

            previous = stored_hash
            expected_sequence += 1

        return JournalVerification(
            ok=True, entries=checked, first_broken_sequence=None, reason=None
        )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _lines(self) -> list[tuple[int, str]]:
        """Return the non-empty lines of the journal with their line numbers."""
        if not self.path.exists():
            return []
        try:
            raw = self.path.read_text(encoding="utf-8")
        except (OSError, ValueError) as err:
            msg = f"the operator-action journal at {self.path} could not be read: {err}"
            raise OperatorJournalError(msg) from err
        return [
            (number, line.strip())
            for number, line in enumerate(raw.splitlines(), start=1)
            if line.strip()
        ]

    def _ensure_open(self) -> None:
        """Open the journal for appending and recover the end of the chain.

        The chain continues an existing file: the last entry is read back so
        that the next entry follows it, rather than starting a second,
        parallel chain in the same file.
        """
        if self._handle is not None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("a", encoding="utf-8")
        except (OSError, ValueError) as err:
            self._degraded = True
            self._last_error = str(err)
            logger.error("Could not open the operator-action journal %s: %s", self.path, err)
            msg = f"the operator-action journal at {self.path} could not be opened: {err}"
            raise OperatorJournalError(msg) from err

        last = self._last_persisted_entry()
        if last is not None:
            self._sequence = last.sequence
            self._last_hash = last.entry_hash

    def _last_persisted_entry(self) -> JournalEntry | None:
        """Return the last entry already on disk, or ``None`` for an empty journal."""
        entries = self.read()
        return entries[-1] if entries else None

    def close(self) -> None:
        """Close the underlying file. The journal can be reopened afterwards."""
        with self._lock:
            if self._handle is not None:
                try:
                    self._handle.flush()
                    self._handle.close()
                finally:
                    self._handle = None


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #

_resolution_lock = threading.Lock()
_default_journal: OperatorActionJournal | None = None


def _build_default_journal() -> OperatorActionJournal:
    """Build the process-level journal from the application settings."""
    from backend.app.core.config import settings

    return OperatorActionJournal(
        settings.OPERATOR_JOURNAL_PATH, fsync=settings.OPERATOR_JOURNAL_FSYNC
    )


def get_operator_journal(app: Any = None, request: Any = None) -> OperatorActionJournal:
    """Return the operator-action journal of this process.

    The journal is created on first use and is the same object for every
    caller, whether it holds an application handle or not. Two applications in
    one process therefore write to one trail rather than to two trails that
    both claim to be complete.

    The application handle is accepted so that a request handler can reach
    the journal through the same mechanism the rest of the platform uses, and
    so that a test can point the journal at a temporary file by binding it to
    the application's state.
    """
    base_app = request.app if request is not None else app
    if base_app is not None:
        state = getattr(base_app, "state", None)
        journal = getattr(state, OPERATOR_JOURNAL_KEY, None)
        if journal is None:
            journal = _process_journal()
            setattr(state, OPERATOR_JOURNAL_KEY, journal)
        return journal

    return _process_journal()


def _process_journal() -> OperatorActionJournal:
    """Return the process-level journal, creating it on first use."""
    global _default_journal  # noqa: PLW0603 - one journal per process, by design

    with _resolution_lock:
        if _default_journal is None:
            _default_journal = _build_default_journal()
        return _default_journal


def set_operator_journal(app: Any, journal: OperatorActionJournal) -> OperatorActionJournal:
    """Bind a specific journal to an application and return it.

    The journal becomes the process journal as well, so every caller — with
    or without an application handle — writes to the same trail. This is what
    a test does to point the platform at a temporary file, and what a
    deployment does when it keeps its trail somewhere particular.
    """
    global _default_journal  # noqa: PLW0603 - one journal per process, by design

    state = getattr(app, "state", None)
    setattr(state, OPERATOR_JOURNAL_KEY, journal)
    with _resolution_lock:
        _default_journal = journal
    return journal


def close_operator_journal() -> None:
    """Close the process journal, if one has been created.

    Every entry is flushed and — unless ``fsync`` was turned off — forced to
    the storage device before ``record`` returns, so closing is a tidy-up
    rather than a durability step. A journal that is written to again after
    this call is reopened transparently.
    """
    global _default_journal  # noqa: PLW0603 - one journal per process, by design

    with _resolution_lock:
        journal = _default_journal
    if journal is not None:
        journal.close()
