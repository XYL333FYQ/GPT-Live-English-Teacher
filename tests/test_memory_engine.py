#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Liqin Luo
"""Lightweight checks for GPT Live English Coach.

This script validates:
- example profile JSON is well-formed;
- Mastery Ladder stage transitions behave as expected;
- active-item update logic works;
- UNTESTED does not mutate learning state;
- a one-time defer flag can be cleared without changing mastery state.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
import json

INTERVALS = [1, 3, 7, 14, 30, 60]
MASTERED_RECHECK_DAYS = 365

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_JSON = ROOT / "fixtures" / "English_Learning_Profile.example.json"


@dataclass
class Item:
    stage: int = 0
    status: str = "active"
    lapse_count: int = 0
    selection_defer_once: bool = False
    last_outcome: str | None = None
    next_review_date: date = date(2026, 7, 12)
    last_review_date: date | None = None


def update_active(item: Item, outcome: str, today: date) -> Item:
    out = replace(item)
    if outcome == "UNTESTED":
        out.selection_defer_once = True
        return out

    out.last_outcome = outcome
    out.last_review_date = today

    if outcome == "PASS":
        if out.stage == 5:
            out.status = "mastered"
            out.next_review_date = today + timedelta(days=MASTERED_RECHECK_DAYS)
        else:
            out.stage += 1
            out.next_review_date = today + timedelta(days=INTERVALS[out.stage])
    elif outcome == "PARTIAL":
        out.stage = max(0, out.stage - 1)
        out.next_review_date = today + timedelta(days=INTERVALS[out.stage])
    elif outcome == "FAIL":
        out.stage = 0
        out.lapse_count += 1
        out.next_review_date = today + timedelta(days=INTERVALS[0])
    else:
        raise ValueError(outcome)

    out.selection_defer_once = False
    return out


def clear_defer_without_learning_change(item: Item) -> Item:
    out = replace(item)
    out.selection_defer_once = False
    return out


def test_example_json() -> None:
    data = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    assert data["schema_version"] == "2.1"
    assert "scientific_assessment" in data
    assert isinstance(data["active_repertoire"], list)
    assert isinstance(data["session_log"], list)
    first = data["active_repertoire"][0]
    assert first["selection_defer_once"] is False
    assert first["stage"] == 0


def test_stage_progression() -> None:
    today = date(2026, 7, 11)
    item = Item(stage=0, status="active", next_review_date=today)
    steps = []
    current = item
    current_day = today
    for _ in range(6):
        current = update_active(current, "PASS", current_day)
        steps.append((current.status, current.stage, (current.next_review_date - current_day).days))
        current_day = current.next_review_date
    assert steps == [
        ("active", 1, 3),
        ("active", 2, 7),
        ("active", 3, 14),
        ("active", 4, 30),
        ("active", 5, 60),
        ("mastered", 5, 365),
    ]


def test_partial_and_fail() -> None:
    today = date(2026, 7, 11)
    partial = update_active(Item(stage=4, next_review_date=today), "PARTIAL", today)
    assert partial.stage == 3
    assert (partial.next_review_date - today).days == 14

    failed = update_active(Item(stage=5, next_review_date=today), "FAIL", today)
    assert failed.stage == 0
    assert failed.lapse_count == 1
    assert (failed.next_review_date - today).days == 1


def test_untested_behavior() -> None:
    today = date(2026, 7, 11)
    original = Item(stage=3, lapse_count=2, next_review_date=date(2026, 7, 8))
    untouched = update_active(original, "UNTESTED", today)
    assert untouched.stage == original.stage
    assert untouched.lapse_count == original.lapse_count
    assert untouched.next_review_date == original.next_review_date
    assert untouched.last_review_date == original.last_review_date
    assert untouched.last_outcome == original.last_outcome
    assert untouched.selection_defer_once is True

    restored = clear_defer_without_learning_change(untouched)
    assert restored.stage == original.stage
    assert restored.lapse_count == original.lapse_count
    assert restored.next_review_date == original.next_review_date
    assert restored.selection_defer_once is False


def main() -> None:
    test_example_json()
    test_stage_progression()
    test_partial_and_fail()
    test_untested_behavior()
    print("All lightweight repository checks passed.")


if __name__ == "__main__":
    main()
