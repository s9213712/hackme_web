"""Shared progress / interactive guidance helpers for scripts (P6).

Conventions enforced here so every long-running script has the same look:

- ``step(n, total, label)`` prints a ``[3/13] adversarial - running...`` line
  to stderr; downstream output stays clean for piping to JSON tools.
- ``ProgressBar`` is a minimal text bar (no external deps) suitable for
  scripts that loop over a known number of items.
- ``confirm(prompt, default)`` asks for ``y/N`` confirmation from the
  operator, with a non-interactive escape hatch via
  ``HACKME_NONINTERACTIVE=1``.
- ``bounded_loop(seconds, label)`` is a context manager that wraps any
  while-style waiter with a hard timeout so a polling loop can never run
  forever silently.
- ``check_no_silent_failure(result, label)`` wraps a subprocess.run-style
  ``CompletedProcess`` and raises if ``returncode != 0``, surfacing
  stdout/stderr instead of swallowing it.

Every helper is import-safe (no side effects) so any script can use it
without pulling in optional dependencies.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from typing import Iterator, Optional


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stderr.isatty():
        return False
    return True


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def announce(message: str) -> None:
    """Single-line status message to stderr (visible to operator, does
    not pollute stdout)."""
    line = f"[{_ts()}] {message}"
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


def step(current: int, total: int, label: str) -> None:
    """Print a ``[3/13] label - running...`` style header."""
    width = max(1, len(str(total)))
    prefix = f"[{current:>{width}}/{total}]"
    announce(f"{prefix} {label}")


def heading(text: str) -> None:
    bar = "─" * min(60, max(20, len(text) + 4))
    announce(bar)
    announce(text)
    announce(bar)


@dataclass
class ProgressBar:
    """Minimal ASCII progress bar. Call ``advance()`` after each item.

    Example::

        bar = ProgressBar(total=len(items), label="downloading")
        for item in items:
            do_work(item)
            bar.advance()
        bar.finish()
    """

    total: int
    label: str = ""
    width: int = 28
    start_time: float = field(default_factory=time.monotonic)
    current: int = 0

    def _render(self) -> str:
        if self.total <= 0:
            ratio = 1.0
        else:
            ratio = max(0.0, min(1.0, self.current / self.total))
        filled = int(round(self.width * ratio))
        bar = "█" * filled + "░" * (self.width - filled)
        pct = int(round(ratio * 100))
        elapsed = time.monotonic() - self.start_time
        label_part = f" {self.label}" if self.label else ""
        return f"\r[{bar}] {pct:3d}% ({self.current}/{self.total}){label_part} {elapsed:.1f}s"

    def advance(self, amount: int = 1) -> None:
        self.current = min(self.total, self.current + max(0, amount))
        sys.stderr.write(self._render())
        sys.stderr.flush()

    def set_label(self, label: str) -> None:
        self.label = label
        sys.stderr.write(self._render())
        sys.stderr.flush()

    def finish(self, message: Optional[str] = None) -> None:
        self.current = self.total
        sys.stderr.write(self._render())
        if message:
            sys.stderr.write(f"\n[{_ts()}] {message}\n")
        else:
            sys.stderr.write("\n")
        sys.stderr.flush()


def confirm(prompt: str, *, default: bool = False) -> bool:
    """Prompt the operator for y/N. Returns ``default`` non-interactively.

    Honours ``HACKME_NONINTERACTIVE=1`` and ``HACKME_ASSUME_YES=1`` so CI
    runs can drive scripts without hanging on input.
    """
    if os.environ.get("HACKME_ASSUME_YES") == "1":
        announce(f"[auto-yes] {prompt}")
        return True
    if os.environ.get("HACKME_NONINTERACTIVE") == "1" or not sys.stdin.isatty():
        announce(f"[auto-{'yes' if default else 'no'}] {prompt}")
        return default
    suffix = " [Y/n] " if default else " [y/N] "
    sys.stderr.write(prompt + suffix)
    sys.stderr.flush()
    try:
        reply = sys.stdin.readline().strip().lower()
    except (EOFError, KeyboardInterrupt):
        sys.stderr.write("\n")
        return default
    if not reply:
        return default
    return reply in {"y", "yes", "t", "true", "1"}


class BoundedLoopTimeout(RuntimeError):
    """Raised when a ``bounded_loop`` context exceeds its allotted time."""


@contextlib.contextmanager
def bounded_loop(seconds: float, *, label: str = "wait") -> Iterator[callable]:
    """Context manager that yields a ``should_continue()`` predicate.

    Use it instead of ``while True:`` whenever a script is waiting for a
    side effect (server boot, file appearance, queue drain). The
    predicate becomes ``False`` after ``seconds`` so the loop is
    guaranteed to terminate.
    """
    deadline = time.monotonic() + max(0.0, float(seconds))
    last_announce = [0.0]

    def should_continue() -> bool:
        now = time.monotonic()
        if now - last_announce[0] > 5.0:
            remaining = max(0.0, deadline - now)
            announce(f"⏳ {label} (remaining ~{remaining:.0f}s)")
            last_announce[0] = now
        return now < deadline

    try:
        yield should_continue
    finally:
        if time.monotonic() >= deadline:
            # Still inside the with-block when time expired; let caller
            # detect via should_continue() returning False.
            pass


def assert_not_silent(returncode: int, *, label: str, stderr_text: str = "") -> None:
    """Raise if a subprocess returned non-zero — never swallow failures.

    Pair with ``subprocess.run(..., capture_output=True)``::

        proc = subprocess.run([...], capture_output=True, text=True)
        assert_not_silent(proc.returncode, label="git fetch",
                          stderr_text=proc.stderr)
    """
    if returncode == 0:
        return
    tail = (stderr_text or "").strip().splitlines()[-12:]
    detail = "\n  ".join(tail) if tail else "(no stderr captured)"
    raise RuntimeError(
        f"{label} failed (exit={returncode}):\n  {detail}"
    )


def terminal_width(default: int = 80) -> int:
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return default
