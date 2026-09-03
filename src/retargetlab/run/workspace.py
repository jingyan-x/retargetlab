"""Create non-overwriting run directories and persist recipe evidence."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from retargetlab.contracts import Recipe
from retargetlab.run.fingerprint import recipe_sha256

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class RunWorkspace:
    """Paths and hash for one newly created run."""

    path: Path
    run_id: str
    recipe_sha256: str

    @property
    def result_dir(self) -> Path:
        return self.path / "result"

    @property
    def export_dir(self) -> Path:
        return self.path / "export"


def _write_json_exclusive(path: Path, payload: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def create_run_workspace(
    project_dir: Path,
    run_id: str,
    recipe: Recipe,
) -> RunWorkspace:
    """Create a run once; an existing run id is never overwritten."""

    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("run_id must be a simple portable identifier")
    run_path = project_dir / "runs" / run_id
    run_path.mkdir(parents=True, exist_ok=False)
    result_dir = run_path / "result"
    export_dir = run_path / "export"
    result_dir.mkdir()
    export_dir.mkdir()

    digest = recipe_sha256(recipe)
    _write_json_exclusive(run_path / "recipe.json", recipe.model_dump(mode="json"))
    with (run_path / "recipe.sha256").open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{digest}\n")
    return RunWorkspace(path=run_path, run_id=run_id, recipe_sha256=digest)
