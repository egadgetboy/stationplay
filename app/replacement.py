"""Choosing what fills a slot whose program can't play."""

from __future__ import annotations

import random

from .db import Item


def pick_replacement(
    candidates: list[Item],
    failed: Item,
    required_ms: int,
    excluded: set[str],
    seed: int,
) -> Item | None:
    """Picks a stand-in for `failed` that can play the rest of its slot.

    The replacement joins at the same offset the failed program was at, so
    it must be at least `required_ms` long to still be playing when the slot
    ends. Preference order: another episode of the same show, then anything
    of the same kind (episode/movie), then anything at all. The choice is
    seeded by the slot, so a channel restarted mid-slot picks the same one.
    """
    seen: set[str] = set()
    eligible: list[Item] = []
    for c in candidates:
        if (
            c.rating_key in seen
            or c.rating_key == failed.rating_key
            or c.rating_key in excluded
            or c.program_ms < required_ms
        ):
            continue
        seen.add(c.rating_key)
        eligible.append(c)

    tiers = [
        [c for c in eligible if failed.show_key and c.show_key == failed.show_key],
        [c for c in eligible if c.kind == failed.kind],
        eligible,
    ]
    rng = random.Random(seed)
    for tier in tiers:
        if tier:
            tier.sort(key=lambda c: c.rating_key)
            return rng.choice(tier)
    return None
