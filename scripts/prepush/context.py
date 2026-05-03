from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from scripts.prepush import utils


@dataclass
class PrepushContext:
    repo_root: Path
    mode: str = "quick"
    is_ci: bool = False
    json_output: bool = False
    yes: bool = False
    keep_temp: bool = False
    clean: bool = False
    clean_temp: bool = False
    temp_root: Path | None = None
    staged_files: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    tracked_files: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)
    env_snapshot: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        *,
        repo_root: Path,
        mode: str,
        is_ci: bool,
        json_output: bool = False,
        yes: bool = False,
        keep_temp: bool = False,
        clean: bool = False,
        clean_temp: bool = False,
    ) -> "PrepushContext":
        repo_root = repo_root.resolve()
        return cls(
            repo_root=repo_root,
            mode=mode,
            is_ci=is_ci,
            json_output=json_output,
            yes=yes,
            keep_temp=keep_temp,
            clean=clean,
            clean_temp=clean_temp,
            staged_files=utils.git_lines(repo_root, "diff", "--cached", "--name-only"),
            changed_files=utils.git_lines(repo_root, "diff", "--name-only"),
            tracked_files=utils.git_lines(repo_root, "ls-files"),
            untracked_files=utils.git_lines(repo_root, "ls-files", "--others", "--exclude-standard"),
            env_snapshot={key: "<set>" for key in os.environ if key.startswith(("HTML_LEARNING_", "FLASK_", "PYTEST_"))},
        )

    def ensure_temp_root(self) -> Path:
        if self.temp_root is None:
            self.temp_root = Path(tempfile.mkdtemp(prefix="html_learning_prepush_"))
        return self.temp_root

    def sanitize_path(self, value: str | Path) -> str:
        return utils.sanitize_path(str(value))

    def relpath(self, path: Path) -> str:
        return utils.relpath(path, self.repo_root)

    @property
    def strict(self) -> bool:
        return self.is_ci or self.mode == "full"
