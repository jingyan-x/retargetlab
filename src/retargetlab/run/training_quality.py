"""Training quality relative to a recorded source-Joint baseline."""

from __future__ import annotations

from collections.abc import Sequence


def assess_contacts(
    target_pairs: Sequence[Sequence[str]],
    source_pairs: Sequence[Sequence[str]],
    *,
    terminal_links: dict[str, list[str]],
    kinematics_valid: bool,
) -> dict:
    """Existing scoped pairs are advisory; new or unlisted pairs are excluded.

    Pair identity does not establish that penetration severity is unchanged.
    """

    def canonical(pair):
        return tuple(sorted(pair))

    target = {canonical(p) for p in target_pairs}
    source = {canonical(p) for p in source_pairs}
    left, right = set(terminal_links["left"]), set(terminal_links["right"])
    new = target - source
    unscoped = {
        p
        for p in target
        if not ((p[0] in left and p[1] in right) or (p[1] in left and p[0] in right))
    }
    valid = kinematics_valid and not new and not unscoped
    return {
        "source_collision_free": not source,
        "target_collision_free": not target,
        "source_pairs": sorted(source),
        "target_pairs": sorted(target),
        "new_collision_pairs": sorted(new),
        "shared_collision_pairs": sorted(target & source),
        "out_of_scope_pairs": sorted(unscoped),
        "kinematics_valid": kinematics_valid,
        "training_eligible": bool(valid),
        "quality": "EXCLUDED" if not valid else "BASELINE_CONTACT" if target else "CLEAN",
        "severity_comparison": "NOT_MEASURED" if target else "NO_TARGET_CONTACT",
    }
