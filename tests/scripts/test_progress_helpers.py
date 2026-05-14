"""Tests for ``scripts/_progress.py`` — the P6 script UX toolkit."""

import io
import sys
import time

import pytest

from scripts import _progress as progress


def test_step_emits_indexed_label(capsys):
    progress.step(3, 13, "running adversarial report")
    captured = capsys.readouterr()
    # Width-aligned to total, so [ 3/13] (with space pad) is the expected form.
    assert "3/13" in captured.err
    assert "adversarial" in captured.err


def test_progress_bar_advances_and_finishes(capsys):
    bar = progress.ProgressBar(total=4, label="downloading")
    for _ in range(4):
        bar.advance()
    bar.finish("done")
    captured = capsys.readouterr()
    assert "100%" in captured.err
    assert "done" in captured.err


def test_progress_bar_zero_total_does_not_crash(capsys):
    bar = progress.ProgressBar(total=0)
    bar.advance()  # should clamp to total, no division-by-zero
    bar.finish()
    captured = capsys.readouterr()
    assert "100%" in captured.err


def test_confirm_returns_default_in_noninteractive(monkeypatch, capsys):
    monkeypatch.setenv("HACKME_NONINTERACTIVE", "1")
    assert progress.confirm("delete?", default=False) is False
    assert progress.confirm("keep?", default=True) is True


def test_confirm_returns_true_when_assume_yes(monkeypatch):
    monkeypatch.setenv("HACKME_ASSUME_YES", "1")
    monkeypatch.delenv("HACKME_NONINTERACTIVE", raising=False)
    assert progress.confirm("anything?", default=False) is True


def test_bounded_loop_expires_after_deadline():
    """The waiter predicate must return False once the deadline passes —
    this is what stops scripts from spinning forever silently."""
    iterations = 0
    with progress.bounded_loop(0.05, label="quick") as should_continue:
        while should_continue():
            iterations += 1
            if iterations > 10000:
                break
            time.sleep(0.005)
    # Iterations should be > 0 (the loop ran) but finite.
    assert 0 < iterations < 10000


def test_assert_not_silent_raises_with_stderr_excerpt():
    with pytest.raises(RuntimeError) as exc:
        progress.assert_not_silent(2, label="fake op", stderr_text="line1\nline2 boom")
    assert "fake op" in str(exc.value)
    assert "boom" in str(exc.value)


def test_assert_not_silent_passes_on_zero():
    progress.assert_not_silent(0, label="ok op")


def test_heading_prints_bordered_text(capsys):
    progress.heading("Stage 2")
    captured = capsys.readouterr()
    lines = captured.err.strip().splitlines()
    assert len(lines) == 3
    assert "Stage 2" in lines[1]
