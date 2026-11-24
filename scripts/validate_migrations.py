"""Validate the Alembic migration graph of the PowerTwin historian schema.

Why this exists
---------------
The release workflow used to run ``alembic check``. That command compares the
ORM metadata against the migration history, so it needs a **live database**
connection *and* a non-empty ``target_metadata`` in ``migrations/env.py``.
Neither was available in CI, so the command failed with an import error before
the release could be built at all.

The validation implemented here is deliberately **offline**: it needs no
database, no service container and no credentials, and it is therefore
deterministic and reproducible. It verifies the two properties that can be
checked without a database:

1. the migration graph has exactly **one head** (no branch, no second
   unreferenced head), and
2. the whole chain **renders to SQL** without an error, which proves that
   every revision is importable, that every ``down_revision`` resolves and
   that every operation is well formed.

Comparing the ORM metadata against the migrations still requires a live
database and is therefore **NOT IMPLEMENTED** here. It is listed as a known
limitation in ``docs/CI_CD_GUIDE.md``.

Safety note
-----------
The script renders SQL in Alembic's *offline* mode. No database connection is
opened and no schema is modified.
"""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "MigrationValidationError",
    "MigrationValidationResult",
    "check_single_head",
    "main",
    "validate_migrations",
]

DEFAULT_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "backend" / "alembic.ini"


class MigrationValidationError(RuntimeError):
    """Raised when the migration graph does not satisfy the release policy."""


@dataclass(frozen=True)
class MigrationValidationResult:
    """The outcome of a successful migration validation.

    Attributes:
        heads: The head revisions of the migration graph.
        sql_length: The number of characters of rendered SQL.
        sql_statements: The number of non-empty SQL statements that were
            rendered.
    """

    heads: tuple[str, ...]
    sql_length: int
    sql_statements: int


def check_single_head(heads: Sequence[str]) -> None:
    """Verify that the migration graph has exactly one head.

    Args:
        heads: The head revisions of the migration graph.

    Raises:
        MigrationValidationError: If there is not exactly one head.
    """
    if len(heads) == 1:
        return
    if not heads:
        msg = (
            "The migration graph has no head revision; there is nothing to upgrade to."
        )
        raise MigrationValidationError(msg)
    listed = ", ".join(sorted(heads))
    msg = (
        f"The migration graph has {len(heads)} head revisions ({listed}). "
        "A release requires exactly one head; merge the branches before releasing."
    )
    raise MigrationValidationError(msg)


def _count_statements(sql: str) -> int:
    """Return the number of non-empty, non-comment SQL statements."""
    count = 0
    for raw_line in sql.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("--"):
            continue
        count += 1
    return count


def validate_migrations(ini_path: Path | None = None) -> MigrationValidationResult:
    """Validate the migration graph offline.

    Args:
        ini_path: Path of the Alembic configuration. Defaults to
            ``backend/alembic.ini``.

    Returns:
        The validation result.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
        MigrationValidationError: If the graph has not exactly one head, or
            if the chain does not render to SQL.
    """
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config_path = (ini_path or DEFAULT_ALEMBIC_INI).resolve()
    if not config_path.is_file():
        msg = f"The Alembic configuration '{config_path}' does not exist."
        raise FileNotFoundError(msg)

    # Alembic writes the rendered SQL to the output buffer of the
    # configuration. Capturing it keeps the release log readable and lets the
    # script verify that the chain really produced statements.
    buffer = io.StringIO()
    config = Config(str(config_path), output_buffer=buffer)

    try:
        script = ScriptDirectory.from_config(config)
        heads = tuple(script.get_heads())
    except Exception as err:
        # The failure must be reported, not swallowed: it is re-raised as a
        # validation error so that the caller sees a clear message.
        msg = f"The migration graph could not be read: {err}"
        raise MigrationValidationError(msg) from err

    check_single_head(heads)

    try:
        command.upgrade(config, "head", sql=True)
    except Exception as err:
        # Same as above: the underlying error is preserved as the cause.
        msg = f"The migration chain does not render to SQL: {err}"
        raise MigrationValidationError(msg) from err

    sql = buffer.getvalue()
    statements = _count_statements(sql)
    if statements == 0:
        msg = "The migration chain rendered no SQL statement; the upgrade is empty."
        raise MigrationValidationError(msg)

    return MigrationValidationResult(
        heads=heads,
        sql_length=len(sql),
        sql_statements=statements,
    )


def main(argv: list[str] | None = None) -> int:
    """Run the migration validation.

    Args:
        argv: Command line arguments. Defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` when the migration graph is valid, ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(
        description="Validate the PowerTwin Alembic migration graph without a database."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_ALEMBIC_INI,
        help="Path of the Alembic configuration file (default: backend/alembic.ini).",
    )
    args = parser.parse_args(argv)

    try:
        result = validate_migrations(args.config)
    except (FileNotFoundError, MigrationValidationError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1

    print(f"The migration graph has a single head: {result.heads[0]}")
    print(f"The migration chain renders {result.sql_statements} SQL statements.")
    print("The migration graph is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
