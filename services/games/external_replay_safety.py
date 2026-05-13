"""Safety contract shared by all external-replay-aware CLIs.

This module is the single source of truth for:

1. Canonical JSON serialization. Every CLI that exposes a final payload
   (stdout, summary.json, dry-run artifact, future promote ledger, ...)
   must round-trip through :func:`serialize_json_payload` so disk and
   stdout are byte-identical and key order / unicode / trailing-newline
   drift cannot reappear.

2. Mutation policy validation. :class:`MutationPolicy` enumerates the
   inputs that decide whether a non-dry-run run is allowed to touch
   model artifacts; :func:`validate_mutation_policy` returns the list of
   blocking problems (empty = OK) so any CLI can ask the same question
   without re-implementing the bundled / runtime-default / models-dir
   detection logic.

3. Default-path detection. :func:`is_default_model_path` resolves an
   explicit path and reports whether it equals the bundled artifact,
   the runtime-default artifact, or sits under the bundled
   ``services/games/models/`` directory — the three ways an operator
   could accidentally point external-replay training at a
   production-adjacent location.

See
``docs/games/archive/chess_debug/2026-05-12_pvp_replay_pipeline_v1.md``
for the CLI mode matrix this module enforces.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


# Resolve the repo root so the bundled-models-dir check works regardless of
# where a caller imports from. parents[2] = services/games/ -> services/ ->
# repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLED_MODELS_DIR = (_REPO_ROOT / "services" / "games" / "models").resolve()


def serialize_json_payload(payload: dict) -> str:
    """Canonical serializer for every CLI payload.

    Settings are pinned so disk / stdout / future ledger writers stay
    byte-identical regardless of caller:

    - ``ensure_ascii=False`` — keep CJK / accented strings legible
    - ``indent=2`` — human-readable
    - ``sort_keys=True`` — deterministic order across Python versions
    - trailing newline — POSIX-friendly, no diff noise on append
    """
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def is_default_model_path(
    explicit_path: str,
    *,
    bundled_resolver: Callable[[], Path],
    default_resolver: Callable[[], Path],
    bundled_models_dir: Path = BUNDLED_MODELS_DIR,
) -> tuple[bool, str]:
    """Return ``(is_default, reason)`` for an explicit ``--*-model-path`` value.

    Three layers of detection so the guard cannot be bypassed:

    1. Path resolves to the bundled artifact.
    2. Path resolves to the runtime-default artifact (typically under
       ``$HACKME_RUNTIME_DIR/games/models/...``).
    3. Path resolves anywhere under ``services/games/models/`` (catches
       hand-crafted "sibling" filenames placed next to the bundled
       artifact).
    """
    if not explicit_path:
        return False, ""
    try:
        explicit = Path(explicit_path).expanduser().resolve()
    except Exception:
        return False, ""
    try:
        bundled = bundled_resolver().resolve()
    except Exception:
        bundled = None
    try:
        runtime_default = default_resolver().resolve()
    except Exception:
        runtime_default = None
    if bundled is not None and explicit == bundled:
        return True, f"resolves to bundled path {bundled}"
    if runtime_default is not None and explicit == runtime_default:
        return True, f"resolves to runtime default {runtime_default}"
    try:
        explicit.relative_to(bundled_models_dir)
    except ValueError:
        return False, ""
    return True, f"resides under bundled-models dir {bundled_models_dir}"


@dataclass(frozen=True)
class EngineMutationSpec:
    """One engine's contribution to the mutation policy.

    Tells the validator which CLI flags drive the engine's path and skip
    decisions, and how to resolve the engine's bundled / runtime-default
    locations. Frozen so accidental mutation between policy creation and
    validation is impossible.
    """

    engine_id: str
    cli_path_flag: str
    cli_skip_flag: str
    explicit_path: str
    skip: bool
    bundled_resolver: Callable[[], Path]
    default_resolver: Callable[[], Path]


@dataclass(frozen=True)
class MutationPolicy:
    """Snapshot of caller intent for a non-dry-run external-replay invocation.

    A CLI builds this from its argparse.Namespace; the validator
    decides whether the combination is safe without re-implementing
    bundled / runtime / models-dir detection.
    """

    dry_run: bool
    allow_default_model_paths: bool
    include_external_replay: bool
    engines: tuple[EngineMutationSpec, ...] = field(default_factory=tuple)


def validate_mutation_policy(policy: MutationPolicy) -> list[str]:
    """Return blocking problems for the given mutation policy.

    Empty list = policy is acceptable. The mode matrix this enforces:

    - **A** no external replay → OK (pre-existing self-play behaviour).
    - **B** external replay + dry-run → OK (dry-run skips all mutation).
    - **C** external replay + non-dry-run + no path → REJECT.
    - **D** external replay + non-dry-run + bundled path → REJECT.
    - **E** external replay + non-dry-run + runtime-default path → REJECT.
    - **F** external replay + non-dry-run + sibling under
      ``services/games/models/`` → REJECT.
    - **G** external replay + non-dry-run + staging/candidate path → OK.
    - **H** external replay + non-dry-run + ``--allow-default-model-paths``
      → OK (explicit unsafe-override).
    """
    if not policy.include_external_replay:
        return []
    if policy.dry_run:
        return []
    if policy.allow_default_model_paths:
        return []
    problems: list[str] = []
    for spec in policy.engines:
        if spec.skip:
            continue
        if not spec.explicit_path:
            problems.append(
                f"{spec.engine_id}: pass {spec.cli_path_flag} "
                f"<staging/candidate.json> or {spec.cli_skip_flag} to gate "
                f"{spec.engine_id} out of this run."
            )
            continue
        is_default, reason = is_default_model_path(
            spec.explicit_path,
            bundled_resolver=spec.bundled_resolver,
            default_resolver=spec.default_resolver,
        )
        if is_default:
            problems.append(f"{spec.engine_id}: {spec.cli_path_flag} {reason}")
    return problems


def format_policy_violation(problems: list[str]) -> str:
    """Render a SystemExit-friendly message for a list of policy problems."""
    lines = [
        "error: refusing to train --include-replay-jsonl into default model paths.",
        "Real (non-dry-run) external-replay warm-up must target explicit "
        "candidate / staging artifacts, not bundled or runtime defaults:",
    ]
    lines.extend(f"  - {p}" for p in problems)
    lines.append(
        "Pass --allow-default-model-paths if you really intend to write defaults."
    )
    return "\n".join(lines)
