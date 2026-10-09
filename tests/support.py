#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Shared helpers for the test suite (not collected as tests)."""
from __future__ import annotations

from typing import Any, Sequence

from tools.learning_data import (
    exit_unit_by_level,
    knowledge_required_dimensions,
    level_placement_requirements,
)


def exit_check_records(
    curricula: Sequence[dict[str, Any]],
    level: str,
    *,
    date_value: str = "2026-10-09",
    evidence_prefix: str = "evidence_placement",
    session_id: str = "placement_0001",
) -> list[dict[str, Any]]:
    """Two compliant placement records for one level: one listening, one speaking.

    They cover every knowledge item the level exit requires, each item by a record
    of the dimension that item actually needs. This is what the strict rules
    demand, so tests that expect a successful skip must use it.
    """
    exit_unit = exit_unit_by_level(curricula)[level]
    requirements = level_placement_requirements(curricula)[level]
    listening: list[str] = []
    speaking: list[str] = []
    for knowledge_id in requirements:
        required = knowledge_required_dimensions(knowledge_id, curricula)
        if "listening" in required:
            listening.append(knowledge_id)
        if "speaking" in required:
            speaking.append(knowledge_id)

    records: list[dict[str, Any]] = []
    if listening:
        records.append(
            {
                "evidence_id": f"{evidence_prefix}_listening",
                "unit_id": exit_unit,
                "knowledge_ids": listening,
                "skill": "listening",
                "modality": "voice",
                "support_level": "none",
                "result": "PASS",
                "learner_response_summary": f"{level} exit check: unseen listening tasks.",
                "prompt_novelty": "unseen",
                "text_shown_before_response": False,
                "listening_check_grade": "strict_unseen",
            }
        )
    if speaking:
        records.append(
            {
                "evidence_id": f"{evidence_prefix}_speaking",
                "unit_id": exit_unit,
                "knowledge_ids": speaking,
                "skill": "speaking",
                "modality": "voice",
                "support_level": "none",
                "result": "PASS",
                "learner_response_summary": f"{level} exit check: independent spoken production.",
                "prompt_novelty": "unseen",
                "text_shown_before_response": False,
                "listening_check_grade": "not_applicable",
            }
        )
    for record in records:
        record["session_id"] = session_id
        record["date"] = date_value
    return records


def placement_input(
    curricula: Sequence[dict[str, Any]],
    levels: Sequence[str],
    *,
    date_value: str = "2026-10-09",
) -> dict[str, Any]:
    """A placement input file that credits each requested level properly."""
    evidence: list[dict[str, Any]] = []
    for index, level in enumerate(levels, start=1):
        evidence.extend(
            exit_check_records(
                curricula,
                level,
                date_value=date_value,
                evidence_prefix=f"evidence_placement_{index:02d}",
                session_id="placement_0001",
            )
        )
    return {
        "timezone": "Asia/Shanghai",
        "target_english_variety": "General_American",
        "assessment_confidence": "medium",
        "screening_session": {"session_id": "placement_0001", "date": date_value},
        "screening_evidence": evidence,
    }
