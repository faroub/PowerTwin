"""Report the failed tests of a pytest run as GitHub Actions annotations.

Why this exists
---------------
A pipeline that fails without saying *which* test failed is a pipeline that
nobody without administrative rights can diagnose. The job log can only be
downloaded with repository administration permission, and the artifacts need
authentication too, so the check-run annotations are the only part of a
failing run that the public API exposes.

GitHub Actions turns a ``::error`` workflow command into an annotation on the
job's check run, with the file and the line of the problem attached. Pytest
writes the same information into its JUnit XML report. This script reads that
report and prints one annotation per failed test, so a failing pipeline names
the failing test, its file and its line without anyone needing a token.

The script reports; it does not gate. The gate is the pytest exit status.
A reporting step that failed would mask the failure it exists to explain, so
this script exits successfully whatever it finds.

Safety note
-----------
The script only reads a report file that pytest has already written. It never
starts the simulation, never opens a socket, never touches a database and
never touches any equipment.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "FailedTest",
    "escape_message",
    "escape_property",
    "parse_failures",
    "render_annotation",
    "main",
]


@dataclass(frozen=True)
class FailedTest:
    """One test that did not pass.

    Attributes:
        name: The test's identifier, as pytest recorded it.
        file: The repository-relative path of the test file.
        line: The line the failure was reported at, when the report carries one.
        kind: ``"failure"`` for an assertion that did not hold, ``"error"``
            for a test or a collection that raised.
        message: The one-line reason the test did not pass.
    """

    name: str
    file: str
    line: int | None
    kind: str
    message: str

    @property
    def title(self) -> str:
        """Return the short title of the annotation."""
        return f"{self.kind}: {self.name}"


def escape_message(text: str) -> str:
    """Escape a workflow-command message.

    A newline ends the command, a carriage return moves the cursor, and a
    percent sign starts an escape sequence. Each is replaced by the encoding
    GitHub defines for it.

    Args:
        text: The raw message.

    Returns:
        The message with every reserved character encoded.
    """
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(text: str) -> str:
    """Escape a workflow-command property value.

    A property additionally cannot contain a colon or a comma, because both
    separate the properties from each other.

    Args:
        text: The raw property value.

    Returns:
        The value with every reserved character encoded.
    """
    return (
        text.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
        .replace(":", "%3A")
        .replace(",", "%2C")
    )


def _relative_path(raw: str, root: Path) -> str:
    """Return the report's path relative to the repository root.

    Pytest records absolute paths. An absolute path in an annotation points at
    the runner's own directory, which tells the reader nothing; the relative
    path is the one they can open.

    Args:
        raw: The path as the report recorded it.
        root: The repository root.

    Returns:
        The relative path, or the raw path when it cannot be made relative.
    """
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return raw


#: The location pytest appends to a failure, as in ``tests/test_x.py:42:``.
_LOCATION_PATTERN = re.compile(r"^(?P<file>.+?):(?P<line>\d+):", re.MULTILINE)


def _location_from_text(text: str) -> tuple[str, int] | None:
    """Return the file and the line a failure was reported at.

    Pytest does not record the location as an attribute of the test case; it
    appends it to the failure text as the last line of the traceback, in the
    form ``path:line: Error``. That line is the one that is read here.

    Args:
        text: The text of the failure element.

    Returns:
        The file and the line, or ``None`` when the text carries neither.
    """
    matches = _LOCATION_PATTERN.findall(text or "")
    if not matches:
        return None
    file, line = matches[-1]
    try:
        return file.strip(), int(line)
    except ValueError:
        return None


def _module_path(classname: str) -> str:
    """Return the file a dotted test class name most likely lives in.

    This is the last resort, used only when the report carries no location at
    all. The name of the module the test was collected from is the path of
    its file with the separators exchanged.

    Args:
        classname: The dotted class name pytest recorded.

    Returns:
        The path of the file the test most likely lives in.
    """
    if not classname:
        return ""
    return classname.replace(".", "/") + ".py"


def _first_line(text: str) -> str:
    """Return the first non-empty line of a block of text."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def parse_failures(report: Path, *, root: Path | None = None) -> list[FailedTest]:
    """Return the tests that did not pass, as the JUnit report records them.

    A test that raised counts as a failure too: it did not pass, and the
    reader needs to know which one it was.

    Args:
        report: The JUnit XML report pytest wrote.
        root: The repository root the paths are made relative to. Defaults to
            the current working directory.

    Returns:
        One entry per test that failed or errored.

    Raises:
        ET.ParseError: If the report is not valid XML.
    """
    base = root if root is not None else Path.cwd()
    tree = ET.parse(report)
    failures: list[FailedTest] = []

    for case in tree.getroot().iter("testcase"):
        problem = case.find("failure")
        kind = "failure"
        if problem is None:
            problem = case.find("error")
            kind = "error"
        if problem is None:
            continue

        message = problem.get("message") or ""
        if not message:
            message = _first_line(problem.text or "")
        if not message:
            message = "The test did not pass and the report carried no reason."

        text = problem.text or ""
        raw_file = case.get("file")
        raw_line = case.get("line")
        try:
            line = int(raw_line) if raw_line is not None else None
        except ValueError:
            line = None

        if raw_file:
            file = _relative_path(raw_file, base)
        else:
            location = _location_from_text(text)
            if location is not None:
                file, line = _relative_path(location[0], base), location[1]
            else:
                file = _module_path(case.get("classname") or "")

        name = case.get("name") or "(unnamed test)"
        classname = case.get("classname")
        identifier = f"{classname}::{name}" if classname else name

        failures.append(
            FailedTest(
                name=identifier,
                file=file,
                line=line,
                kind=kind,
                message=message,
            )
        )

    return failures


def render_annotation(failure: FailedTest) -> str:
    """Return the GitHub Actions workflow command that annotates a failure.

    Args:
        failure: The failure to annotate.

    Returns:
        The ``::error`` command, ready to be printed.
    """
    properties = [f"file={escape_property(failure.file)}"]
    if failure.line is not None:
        properties.append(f"line={failure.line}")
    properties.append(f"title={escape_property(failure.title)}")
    return "::error " + ",".join(properties) + "::" + escape_message(failure.message)


def main(argv: list[str] | None = None) -> int:
    """Print one annotation per failed test.

    Args:
        argv: Command line arguments. Defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` in every case. The script reports the failures; the pytest exit
        status is what fails the build.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Print one GitHub Actions annotation per test that did not pass, so "
            "that a failing pipeline names the failing test without needing "
            "access to the job log."
        )
    )
    parser.add_argument(
        "report",
        help="The JUnit XML report that pytest wrote.",
    )
    parser.add_argument(
        "--repository-root",
        default=None,
        help=(
            "The repository root the recorded paths are made relative to. "
            "Defaults to the current working directory."
        ),
    )
    args = parser.parse_args(argv)

    report = Path(args.report)
    if not report.is_file():
        print(f"No test report was found at '{report}'; the test run produced none.")
        return 0

    root = Path(args.repository_root) if args.repository_root else Path.cwd()
    try:
        failures = parse_failures(report, root=root)
    except (ET.ParseError, OSError) as err:
        print(f"The test report '{report}' could not be read: {err}")
        return 0

    if not failures:
        print(f"The test report '{report}' records no failed test.")
        return 0

    for failure in failures:
        print(render_annotation(failure))

    print(f"{len(failures)} test(s) did not pass and are listed above as annotations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
