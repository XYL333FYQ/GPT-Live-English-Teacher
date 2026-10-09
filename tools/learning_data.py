#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Deterministic learning-data engine for GPT Live English Teacher.

The engine is used from ChatGPT Text Mode (Code Interpreter) and from the
repository test suite. It never fabricates evidence: every state it derives is
computed from `practice_evidence` records plus the curriculum files.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any, Iterable, Sequence

CURRICULUM_LEVELS = ("PRE_A1", "A1", "A2", "B1")
ALL_LEVELS = (*CURRICULUM_LEVELS, "B2", "C1", "C2")
LESSON_FLOW = (
    "course_goal",
    "demonstration",
    "repeat_after_model",
    "guided_practice",
    "independent_expression",
    "check",
    "review",
)
INTERVALS = (1, 3, 7, 14, 30, 60)
MASTERED_RECHECK_DAYS = 365
TESTED_OUTCOMES = {"PASS", "PARTIAL", "FAIL"}
CONTACT_OUTCOMES = {"PASS", "PARTIAL", "FAIL", "PRACTICED"}
INDEPENDENT_PHASES = {"independent_expression", "check", "review"}
INDEPENDENT_SUPPORT = {"none", "non_revealing_context"}

# --- Skill-dimension model -------------------------------------------------
# A knowledge item is only "independent" when every dimension the curriculum
# actually requires for it has independent evidence. Listening comprehension and
# active production are therefore tracked separately and can never be inferred
# from each other.
SKILL_DIMENSIONS = ("listening", "speaking")
MODE_TO_SKILL = {"listening": "listening", "speaking": "speaking", "interaction": "speaking"}
KNOWLEDGE_STATES = (
    "not_started",
    "introduced",
    "supported",
    "placement_credited",
    "independent",
    "mastered",
)
STATE_RANK = {state: rank for rank, state in enumerate(KNOWLEDGE_STATES)}
QUALIFIED_KNOWLEDGE_STATES = {"independent", "mastered", "placement_credited"}
KNOWLEDGE_REVIEW_INTERVAL_DAYS = {
    "not_started": 1,
    "introduced": 1,
    "supported": 3,
    "placement_credited": 7,
    "independent": 7,
    "mastered": 30,
}

# --- Listening-test grading ------------------------------------------------
# `strict_unseen` is the only grade that can satisfy an unseen-listening check.
LISTENING_CHECK_GRADES = ("strict_unseen", "text_supported_practice", "unknown", "not_applicable")

LESSON_PACE_VALUES = ("normal", "faster", "slower", "review_only", "paused")
PLACEMENT_BASES = ("initial_screening", "profile_migration", "learner_choice", "independent_level_check")

SUPPORTED_CURRICULUM_VERSIONS = {"1.0.0", "1.1.0"}
DEFAULT_CURRICULUM_VERSION = "1.1.0"
CURRICULUM_ID = "gpt-live-english-foundations"
ROOT = Path(__file__).resolve().parents[1]


class ValidationError(ValueError):
    def __init__(self, errors: Iterable[str]):
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return True


def _resolve_local_ref(root_schema: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise ValidationError([f"unsupported external schema reference {reference}"])
    current: Any = root_schema
    for part in reference[2:].split("/"):
        current = current[part.replace("~1", "/").replace("~0", "~")]
    return current


def schema_errors(
    value: Any,
    schema: dict[str, Any],
    *,
    root_schema: dict[str, Any] | None = None,
    path: str = "$",
) -> list[str]:
    root_schema = root_schema or schema
    if "$ref" in schema:
        return schema_errors(value, _resolve_local_ref(root_schema, schema["$ref"]), root_schema=root_schema, path=path)

    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']!r}")

    expected_types = schema.get("type")
    if expected_types:
        if isinstance(expected_types, str):
            expected_types = [expected_types]
        if not any(_schema_type_matches(value, expected) for expected in expected_types):
            errors.append(f"{path}: expected type {expected_types!r}")
            return errors

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property {key}")
        properties = schema.get("properties", {})
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in properties:
                errors.extend(schema_errors(child, properties[key], root_schema=root_schema, path=child_path))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{child_path}: additional property is not allowed")

    if isinstance(value, list):
        minimum = schema.get("minItems")
        if minimum is not None and len(value) < minimum:
            errors.append(f"{path}: needs at least {minimum} items")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value]
            if len(encoded) != len(set(encoded)):
                errors.append(f"{path}: items must be unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(schema_errors(item, item_schema, root_schema=root_schema, path=f"{path}[{index}]"))

    if isinstance(value, str):
        minimum = schema.get("minLength")
        if minimum is not None and len(value) < minimum:
            errors.append(f"{path}: needs at least {minimum} characters")
        pattern = schema.get("pattern")
        if pattern and re.search(pattern, value) is None:
            errors.append(f"{path}: does not match {pattern}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            errors.append(f"{path}: must be at least {minimum}")
        if maximum is not None and value > maximum:
            errors.append(f"{path}: must be at most {maximum}")
    return errors


def validate_schema_instance(value: Any, schema: dict[str, Any]) -> None:
    errors = schema_errors(value, schema)
    if errors:
        raise ValidationError(errors)


def load_curricula(root: Path = ROOT) -> list[dict[str, Any]]:
    return [load_json(root / "curriculum" / f"{level}.json") for level in CURRICULUM_LEVELS]


# ---------------------------------------------------------------------------
# Curriculum structure helpers
# ---------------------------------------------------------------------------


def ordered_unit_ids(curricula: Sequence[dict[str, Any]]) -> list[str]:
    return [unit["unit_id"] for document in curricula for unit in document["units"]]


def exit_unit_by_level(curricula: Sequence[dict[str, Any]]) -> dict[str, str]:
    return {document["level_id"]: document["units"][-1]["unit_id"] for document in curricula}


def level_placement_requirements(curricula: Sequence[dict[str, Any]]) -> dict[str, list[str]]:
    """Knowledge an integrated level-exit check must cover to skip a level.

    It is not enough to cover the exit unit's own objectives: the first unit of
    the next level also requires knowledge taught earlier in the level. Skipping a
    level therefore has to demonstrate both sets, or the learner would be left
    with a locked next level.
    """
    requirements: dict[str, list[str]] = {}
    for index, document in enumerate(curricula):
        level = document["level_id"]
        required = list(unit_knowledge_requirements(document["units"][-1]))
        if index + 1 < len(curricula):
            for knowledge_id in curricula[index + 1]["units"][0]["prerequisite_knowledge_ids"]:
                if knowledge_id not in required:
                    required.append(knowledge_id)
        requirements[level] = required
    return requirements


def unit_knowledge_requirements(unit: dict[str, Any]) -> list[str]:
    """Knowledge that a completed unit must have demonstrated independently.

    This is the union of the target knowledge of every required objective. It is
    the link that makes "unit completed" and "next unit unlocked" consistent.
    """
    objectives = {objective["objective_id"]: objective for objective in unit["objectives"]}
    required: list[str] = []
    for objective_id in unit["completion_criteria"]["required_objective_ids"]:
        for knowledge_id in objectives[objective_id]["target_knowledge_ids"]:
            if knowledge_id not in required:
                required.append(knowledge_id)
    return required


def unit_objectives(unit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {objective["objective_id"]: objective for objective in unit["objectives"]}


def _curriculum_indexes(
    curricula: Sequence[dict[str, Any]],
) -> tuple[dict, dict, dict, dict, dict]:
    units: dict[str, dict[str, Any]] = {}
    objectives: dict[str, tuple[str, dict[str, Any]]] = {}
    knowledge: dict[str, tuple[str, dict[str, Any]]] = {}
    levels: dict[str, str] = {}
    knowledge_owner: dict[str, str] = {}
    for document in curricula:
        for unit in document["units"]:
            units[unit["unit_id"]] = unit
            levels[unit["unit_id"]] = document["level_id"]
            for objective in unit["objectives"]:
                objectives[objective["objective_id"]] = (unit["unit_id"], objective)
            for entry in unit["knowledge"]:
                knowledge[entry["knowledge_id"]] = (unit["unit_id"], entry)
                knowledge_owner[entry["knowledge_id"]] = unit["unit_id"]
    return units, objectives, knowledge, levels, knowledge_owner


def knowledge_required_dimensions(
    knowledge_id: str, curricula: Sequence[dict[str, Any]]
) -> frozenset[str]:
    """Skill dimensions the curriculum requires for one knowledge item."""
    dimensions: set[str] = set()
    for document in curricula:
        for unit in document["units"]:
            for objective in unit["objectives"]:
                if knowledge_id in objective["target_knowledge_ids"]:
                    dimensions.add(MODE_TO_SKILL[objective["mode"]])
    return frozenset(dimensions)


def aggregate_knowledge_state(
    skill_states: dict[str, str], required_dimensions: Iterable[str]
) -> str:
    """Weakest-link aggregation across the required skill dimensions."""
    if not skill_states:
        return "not_started"
    dimensions = list(required_dimensions) or sorted(skill_states)
    if not dimensions:
        return "not_started"
    states = [skill_states.get(dimension, "not_started") for dimension in dimensions]
    return min(states, key=lambda state: STATE_RANK.get(state, 0))


def validate_curricula(documents: list[dict[str, Any]], schema: dict[str, Any] | None = None) -> None:
    errors: list[str] = []
    if len(documents) != len(CURRICULUM_LEVELS):
        errors.append(f"expected {len(CURRICULUM_LEVELS)} curriculum files, found {len(documents)}")
    if schema:
        for document in documents:
            level = document.get("level_id", "unknown")
            errors.extend(f"{level}: {error}" for error in schema_errors(document, schema))

    ordered = sorted(documents, key=lambda document: document.get("level_order", 999))
    actual_levels = tuple(document.get("level_id") for document in ordered)
    if actual_levels != CURRICULUM_LEVELS:
        errors.append(f"level order must be {CURRICULUM_LEVELS}, found {actual_levels}")

    known_units: set[str] = set()
    known_knowledge: set[str] = set()
    known_objectives: set[str] = set()
    curriculum_ids = {document.get("curriculum_id") for document in ordered}
    curriculum_versions = {document.get("curriculum_version") for document in ordered}
    if curriculum_ids != {CURRICULUM_ID}:
        errors.append(f"all levels must share curriculum_id {CURRICULUM_ID}")
    if len(curriculum_versions) != 1 or None in curriculum_versions:
        errors.append("all levels must share one non-empty curriculum_version")

    previous_english_end = -1
    unit_index: dict[str, dict[str, Any]] = {}
    owner_of: dict[str, str] = {}
    for expected_order, document in enumerate(ordered):
        level = document.get("level_id", f"level-{expected_order}")
        if document.get("schema_version") != "1.0":
            errors.append(f"{level}: schema_version must be 1.0")
        if document.get("level_order") != expected_order:
            errors.append(f"{level}: level_order must be {expected_order}")
        if tuple(document.get("lesson_flow", ())) != LESSON_FLOW:
            errors.append(f"{level}: lesson_flow must contain the required seven phases in order")

        support = document.get("support_policy", {})
        start = support.get("english_input_percent_start")
        end = support.get("english_input_percent_end")
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start <= end <= 100:
            errors.append(f"{level}: invalid English input range")
        elif start < previous_english_end:
            errors.append(f"{level}: English input must not decrease across levels")
        if isinstance(end, int):
            previous_english_end = end

        units = document.get("units")
        if not isinstance(units, list) or not units:
            errors.append(f"{level}: units must be a non-empty list")
            continue
        if [unit.get("order") for unit in units] != list(range(1, len(units) + 1)):
            errors.append(f"{level}: unit order must be contiguous from 1")

        for unit in units:
            unit_id = unit.get("unit_id")
            if not isinstance(unit_id, str) or not unit_id.startswith(f"{level}-U"):
                errors.append(f"{level}: invalid unit_id {unit_id!r}")
                continue
            if unit_id in known_units:
                errors.append(f"{unit_id}: duplicate unit_id")

            prerequisites = unit.get("prerequisite_units")
            if not isinstance(prerequisites, list):
                errors.append(f"{unit_id}: prerequisite_units must be a list")
                prerequisites = []
            for prerequisite in prerequisites:
                if prerequisite not in known_units:
                    errors.append(f"{unit_id}: prerequisite unit {prerequisite} is missing or not earlier")

            knowledge_prerequisites = unit.get("prerequisite_knowledge_ids")
            if not isinstance(knowledge_prerequisites, list):
                errors.append(f"{unit_id}: prerequisite_knowledge_ids must be a list")
                knowledge_prerequisites = []
            for knowledge_id in knowledge_prerequisites:
                if knowledge_id not in known_knowledge:
                    errors.append(f"{unit_id}: prerequisite knowledge {knowledge_id} is missing or not earlier")

            local_knowledge: set[str] = set()
            knowledge_entries = unit.get("knowledge")
            if not isinstance(knowledge_entries, list) or not knowledge_entries:
                errors.append(f"{unit_id}: knowledge must be non-empty")
                knowledge_entries = []
            for entry in knowledge_entries:
                knowledge_id = entry.get("knowledge_id")
                if not isinstance(knowledge_id, str) or not knowledge_id.startswith(f"{level}-K"):
                    errors.append(f"{unit_id}: invalid knowledge_id {knowledge_id!r}")
                    continue
                if knowledge_id in known_knowledge or knowledge_id in local_knowledge:
                    errors.append(f"{unit_id}: duplicate knowledge_id {knowledge_id}")
                local_knowledge.add(knowledge_id)
                for field in ("type", "form", "meaning_zh"):
                    if not entry.get(field):
                        errors.append(f"{knowledge_id}: missing {field}")

            local_objectives: set[str] = set()
            locally_targeted_knowledge: set[str] = set()
            objectives = unit.get("objectives")
            if not isinstance(objectives, list) or not objectives:
                errors.append(f"{unit_id}: objectives must be non-empty")
                objectives = []
            for objective in objectives:
                objective_id = objective.get("objective_id")
                if not isinstance(objective_id, str) or not objective_id.startswith(f"{level}-O"):
                    errors.append(f"{unit_id}: invalid objective_id {objective_id!r}")
                    continue
                if objective_id in known_objectives or objective_id in local_objectives:
                    errors.append(f"{unit_id}: duplicate objective_id {objective_id}")
                local_objectives.add(objective_id)
                targets = objective.get("target_knowledge_ids")
                if not isinstance(targets, list) or not targets:
                    errors.append(f"{objective_id}: target_knowledge_ids must be non-empty")
                else:
                    locally_targeted_knowledge.update(set(targets) & local_knowledge)
                    for target in targets:
                        if target not in known_knowledge and target not in local_knowledge:
                            errors.append(f"{objective_id}: unknown knowledge target {target}")
                for field in ("mode", "can_do_zh", "evidence_requirement"):
                    if not objective.get(field):
                        errors.append(f"{objective_id}: missing {field}")

            untargeted = sorted(local_knowledge - locally_targeted_knowledge)
            if untargeted:
                errors.append(f"{unit_id}: local knowledge without objective coverage {untargeted}")

            criteria = unit.get("completion_criteria", {})
            required_objectives = criteria.get("required_objective_ids")
            if not isinstance(required_objectives, list) or set(required_objectives) != local_objectives:
                errors.append(f"{unit_id}: completion criteria must require every local objective")
            if criteria.get("minimum_independent_passes_per_objective", 0) < 1:
                errors.append(f"{unit_id}: completion requires at least one independent pass")
            if criteria.get("mastery_requires_distinct_sessions", 0) < 2:
                errors.append(f"{unit_id}: mastery must require at least two sessions")
            if criteria.get("repeat_after_model_counts_as_independent") is not False:
                errors.append(f"{unit_id}: repetition cannot count as independent evidence")
            if criteria.get("transcript_only_pronunciation_scoring_allowed") is not False:
                errors.append(f"{unit_id}: transcript-only pronunciation scoring must be forbidden")
            if criteria.get("requires_unseen_listening_check") and not any(
                objective.get("mode") == "listening" for objective in objectives
            ):
                errors.append(f"{unit_id}: unseen listening check requires a listening objective")

            errors.extend(
                _lesson_segment_errors(
                    unit, local_knowledge, local_objectives, support.get("new_knowledge_per_lesson_max")
                )
            )

            known_units.add(unit_id)
            known_knowledge.update(local_knowledge)
            known_objectives.update(local_objectives)
            unit_index[unit_id] = unit
            for knowledge_id in local_knowledge:
                owner_of[knowledge_id] = unit_id

    errors.extend(_prerequisite_reachability_errors(unit_index, owner_of))
    if errors:
        raise ValidationError(errors)


def _lesson_segment_errors(
    unit: dict[str, Any],
    local_knowledge: set[str],
    local_objectives: set[str],
    level_new_knowledge_limit: Any,
) -> list[str]:
    """Validate the optional multi-lesson segmentation of a unit."""
    errors: list[str] = []
    unit_id = unit.get("unit_id")
    segments = unit.get("lesson_segments")
    if segments is None:
        return errors
    if not isinstance(segments, list) or not segments:
        return [f"{unit_id}: lesson_segments must be a non-empty list when present"]
    seen_segments: set[str] = set()
    covered: set[str] = set()
    max_new = level_new_knowledge_limit
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            errors.append(f"{unit_id}: lesson_segments[{index}] must be an object")
            continue
        segment_id = segment.get("segment_id")
        if not isinstance(segment_id, str) or not segment_id.startswith(f"{unit_id}-S"):
            errors.append(f"{unit_id}: invalid lesson segment_id {segment_id!r}")
            continue
        if segment_id in seen_segments:
            errors.append(f"{unit_id}: duplicate lesson segment_id {segment_id}")
        seen_segments.add(segment_id)
        if not segment.get("focus_zh"):
            errors.append(f"{segment_id}: missing focus_zh")
        knowledge_ids = segment.get("knowledge_ids")
        if not isinstance(knowledge_ids, list) or not knowledge_ids:
            errors.append(f"{segment_id}: knowledge_ids must be non-empty")
            continue
        unknown = [kid for kid in knowledge_ids if kid not in local_knowledge]
        if unknown:
            errors.append(f"{segment_id}: unknown local knowledge {sorted(unknown)}")
        covered.update(knowledge_ids)
        max_new_items = segment.get("max_new_items")
        if not isinstance(max_new_items, int) or max_new_items < 1:
            errors.append(f"{segment_id}: max_new_items must be a positive integer")
        elif isinstance(max_new, int) and max_new_items > max_new:
            errors.append(
                f"{segment_id}: max_new_items {max_new_items} exceeds level limit {max_new}"
            )
        for objective_id in segment.get("target_objective_ids", []):
            if objective_id not in local_objectives:
                errors.append(f"{segment_id}: unknown local objective {objective_id}")
    missing = sorted(local_knowledge - covered)
    if missing:
        errors.append(f"{unit_id}: lesson segments must cover every local knowledge item, missing {missing}")
    return errors


def _prerequisite_reachability_errors(
    unit_index: dict[str, dict[str, Any]], owner_of: dict[str, str]
) -> list[str]:
    """Lint: every knowledge prerequisite must be guaranteed by a completed unit.

    A unit is completed only when its required objectives pass *and* every
    knowledge item those objectives target is independently demonstrated. So a
    prerequisite knowledge item is safe exactly when its owner unit is inside the
    prerequisite closure of the dependent unit and that item is part of the
    owner's completion requirements.
    """
    errors: list[str] = []
    closure_cache: dict[str, set[str]] = {}

    def closure(unit_id: str) -> set[str]:
        if unit_id in closure_cache:
            return closure_cache[unit_id]
        seen: set[str] = set()
        stack = list(unit_index[unit_id]["prerequisite_units"])
        while stack:
            current = stack.pop()
            if current in seen or current not in unit_index:
                continue
            seen.add(current)
            stack.extend(unit_index[current]["prerequisite_units"])
        closure_cache[unit_id] = seen
        return seen

    for unit_id, unit in unit_index.items():
        reachable = closure(unit_id)
        requirements: set[str] = set()
        for owner in reachable:
            requirements.update(unit_knowledge_requirements(unit_index[owner]))
        for knowledge_id in unit.get("prerequisite_knowledge_ids", []):
            owner = owner_of.get(knowledge_id)
            if owner is None:
                continue
            if owner not in reachable:
                errors.append(
                    f"{unit_id}: prerequisite knowledge {knowledge_id} is owned by {owner}, "
                    "which is outside the prerequisite closure and can never be guaranteed"
                )
            elif knowledge_id not in requirements:
                errors.append(
                    f"{unit_id}: prerequisite knowledge {knowledge_id} is not part of the "
                    f"completion requirements of any prerequisite unit"
                )
    return errors


def audit_curriculum_prerequisites(curricula: list[dict[str, Any]]) -> dict[str, Any]:
    """Read-only audit used by the CLI and the test suite."""
    units, _objectives, knowledge, _levels, owner_of = _curriculum_indexes(curricula)
    ordered = ordered_unit_ids(curricula)
    closure_cache: dict[str, set[str]] = {}

    def closure(unit_id: str) -> set[str]:
        if unit_id in closure_cache:
            return closure_cache[unit_id]
        seen: set[str] = set()
        stack = list(units[unit_id]["prerequisite_units"])
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(units[current]["prerequisite_units"])
        closure_cache[unit_id] = seen
        return seen

    issues: list[str] = []
    edges = 0
    for unit_id in ordered:
        unit = units[unit_id]
        reachable = closure(unit_id)
        guaranteed: set[str] = set()
        for owner in reachable:
            guaranteed.update(unit_knowledge_requirements(units[owner]))
        for knowledge_id in unit["prerequisite_knowledge_ids"]:
            edges += 1
            owner = owner_of.get(knowledge_id)
            if owner is None:
                issues.append(f"{unit_id}: prerequisite knowledge {knowledge_id} is not taught by any unit")
            elif owner not in reachable:
                issues.append(
                    f"{unit_id}: prerequisite knowledge {knowledge_id} owned by {owner} is outside the closure"
                )
            elif knowledge_id not in guaranteed:
                issues.append(
                    f"{unit_id}: prerequisite knowledge {knowledge_id} is not guaranteed by unit completion"
                )
    return {
        "units": len(ordered),
        "knowledge_items": len(knowledge),
        "prerequisite_knowledge_edges": edges,
        "issues": issues,
        "ok": not issues,
    }


# ---------------------------------------------------------------------------
# CEFR helpers and v2.1 migration
# ---------------------------------------------------------------------------


def normalize_cefr(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(["scientific_assessment.overall_cefr is required for v2.1 migration"])
    normalized = value.upper().strip().replace("-", "_").replace(" ", "_")
    if normalized in {"PRE_A1", "PREA1", "A0"}:
        return "PRE_A1"
    match = re.fullmatch(r"(A1|A2|B1|B2|C1|C2)(?:[+-])?", normalized)
    if match:
        return match.group(1)
    raise ValidationError([f"unsupported CEFR value {value!r}"])


def migrate_profile(profile: dict[str, Any], migrated_at: str | None = None) -> dict[str, Any]:
    migrated = deepcopy(profile)
    version = str(migrated.get("schema_version", ""))
    if version == "3.0":
        return migrated
    if version != "2.1":
        raise ValidationError([f"unsupported profile schema_version {version!r}"])

    migrated_at = migrated_at or datetime.now(timezone.utc).isoformat()
    assessment = migrated.setdefault("scientific_assessment", {})
    level = normalize_cefr(assessment.get("overall_cefr"))
    structured = level in CURRICULUM_LEVELS
    legacy_pronunciation = assessment.get("ielts_dimensions", {}).get("pronunciation")
    if isinstance(legacy_pronunciation, (int, float)) and not isinstance(legacy_pronunciation, bool):
        assessment["legacy_pronunciation_notice"] = (
            "Historical v2.1 estimate retained for compatibility; not current pronunciation evidence."
        )

    migrated["schema_version"] = "3.0"
    migrated["profile_revision"] = int(migrated.get("profile_revision", 0)) + 1
    migrated["updated_at"] = migrated_at
    migrated["learning_track"] = {
        "curriculum_id": CURRICULUM_ID if structured else "legacy-conversation",
        "curriculum_version": DEFAULT_CURRICULUM_VERSION,
        "current_level": level,
        "mode": "structured_curriculum" if structured else "legacy_conversation",
        "placement_basis": "profile_migration",
        "support_language": "zh-CN",
    }
    migrated["current_course_position"] = {
        "level_id": level,
        "unit_id": None,
        "unit_status": "needs_curriculum_mapping" if structured else "not_applicable",
        "lesson_phase": None,
        "lesson_segment_id": None,
        "unlocked_unit_ids": [],
        "completed_unit_ids": [],
        "placement_credited_unit_ids": [],
    }
    migrated.setdefault("knowledge_state", [])
    migrated.setdefault("skill_weaknesses", {"listening": [], "speaking": [], "pronunciation": []})
    migrated.setdefault("practice_evidence", [])
    migrated.setdefault("active_repertoire", [])
    migrated.setdefault("session_log", [])
    migrated.setdefault("migration_history", []).append(
        {"from_version": "2.1", "to_version": "3.0", "migrated_at": migrated_at}
    )
    return migrated


# ---------------------------------------------------------------------------
# Evidence semantics
# ---------------------------------------------------------------------------


def evidence_is_independent(evidence: dict[str, Any]) -> bool:
    return (
        evidence.get("phase") in INDEPENDENT_PHASES
        and evidence.get("support_level") in INDEPENDENT_SUPPORT
        and evidence.get("result") == "PASS"
        and evidence.get("prompt_novelty") == "unseen"
        and evidence.get("modality") in {"voice", "mixed"}
    )


def evidence_is_placement_credit(evidence: dict[str, Any]) -> bool:
    return (
        evidence.get("phase") == "placement"
        and evidence.get("objective_id") is None
        and evidence.get("support_level") in INDEPENDENT_SUPPORT
        and evidence.get("result") == "PASS"
        and evidence.get("prompt_novelty") == "unseen"
        and evidence.get("modality") in {"voice", "mixed"}
        and evidence.get("text_shown_before_response") is False
        and bool(evidence.get("knowledge_ids"))
    )


def evidence_is_unseen_listening(evidence: dict[str, Any]) -> bool:
    """Strict unseen-listening evidence.

    A recording that cannot prove the text was hidden is never accepted, and a
    graded `text_supported_practice` attempt is downgraded to ordinary listening
    practice instead of being upgraded to a strict check.
    """
    if evidence.get("listening_check_grade") in {"text_supported_practice", "unknown"}:
        return False
    return (
        evidence_is_independent(evidence)
        and evidence.get("modality") in {"voice", "mixed"}
        and evidence.get("prompt_novelty") == "unseen"
        and evidence.get("text_shown_before_response") is False
    )


def pronunciation_claim_allowed(evidence_basis: str, claim_type: str) -> bool:
    if claim_type in {"numeric_score", "exact_phoneme_score", "acoustic_measurement"}:
        return False
    if claim_type in {
        "sound_contrast",
        "word_stress",
        "sentence_stress",
        "rhythm",
        "linking",
        "intonation",
        "intelligibility",
    }:
        return evidence_basis == "direct_live_audio"
    return False


def evidence_date(evidence: dict[str, Any]) -> date | None:
    value = evidence.get("date")
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def evidence_skill_dimensions(
    evidence: dict[str, Any],
    knowledge_id: str | None,
    curricula: Sequence[dict[str, Any]] | None,
) -> tuple[str, ...]:
    """Which skill dimensions one evidence record demonstrates for a knowledge item."""
    explicit = evidence.get("skill")
    if explicit in SKILL_DIMENSIONS:
        return (explicit,)
    objective_id = evidence.get("objective_id")
    if objective_id and curricula:
        for document in curricula:
            for unit in document["units"]:
                for objective in unit["objectives"]:
                    if objective["objective_id"] == objective_id:
                        return (MODE_TO_SKILL[objective["mode"]],)
    if knowledge_id and curricula:
        required = knowledge_required_dimensions(knowledge_id, curricula)
        if required:
            return tuple(sorted(required))
    return ()


def _next_dimension_state(current: str, evidence: dict[str, Any], context: dict[str, Any]) -> str:
    phase = evidence.get("phase")
    result = evidence.get("result")
    if context["placement_credit"]:
        return "placement_credited"
    if phase in {"demonstration", "course_goal"}:
        return "introduced" if current == "not_started" else current
    if phase in {"repeat_after_model", "guided_practice"}:
        if result in {"PASS", "PARTIAL", "PRACTICED"} and current in {"not_started", "introduced"}:
            return "supported"
        return current
    if context["independent"]:
        if current == "mastered":
            return "mastered"
        if context["mastery_ready"]:
            return "mastered"
        return "independent"
    if phase in INDEPENDENT_PHASES and result == "FAIL":
        if current == "mastered":
            return "independent"
        if current in {"independent", "placement_credited"}:
            return "supported"
    return current


def apply_knowledge_evidence(
    state: dict[str, Any],
    evidence: dict[str, Any],
    mastery_requires_distinct_sessions: int = 2,
    dimensions: Sequence[str] | None = None,
    session_dates: dict[str, str] | None = None,
    required_dimensions: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Apply one evidence record to one knowledge state.

    `dimensions` selects the skill dimension(s) the record proves and
    `required_dimensions` declares which dimensions the curriculum demands for
    this knowledge item. When both are omitted the function keeps the legacy
    single-state behaviour so that older profiles stay readable.
    """
    updated = deepcopy(state)
    updated.setdefault("state", "not_started")
    updated.setdefault("evidence_ids", [])
    updated.setdefault("independent_pass_sessions", [])
    updated.setdefault("review_pass_sessions", [])
    evidence_id = evidence["evidence_id"]
    if evidence_id not in updated["evidence_ids"]:
        updated["evidence_ids"].append(evidence_id)

    phase = evidence.get("phase")
    result = evidence.get("result")

    # An untested item must never change state, sessions or review dates.
    if result == "UNTESTED":
        return updated

    independent = evidence_is_independent(evidence)
    placement_credit = evidence_is_placement_credit(evidence)
    session_id = evidence.get("session_id")
    prior_sessions = set(updated["independent_pass_sessions"])

    if independent or placement_credit:
        if session_id and session_id not in updated["independent_pass_sessions"]:
            updated["independent_pass_sessions"].append(session_id)
        if independent and phase in {"check", "review"} and session_id:
            if session_id not in updated["review_pass_sessions"]:
                updated["review_pass_sessions"].append(session_id)

    context = {
        "independent": independent,
        "placement_credit": placement_credit,
        "mastery_ready": _mastery_ready(updated, evidence, prior_sessions, mastery_requires_distinct_sessions, session_dates),
    }

    dims = tuple(dimensions or ())
    if dims or required_dimensions:
        skill_states = updated.setdefault("skill_states", {})
        declared = sorted(required_dimensions or updated.get("required_dimensions") or set(dims))
        if required_dimensions:
            updated["required_dimensions"] = declared
        elif not updated.get("required_dimensions"):
            updated["required_dimensions"] = declared
        for dimension in declared:
            skill_states.setdefault(dimension, "not_started")
        for dimension in dims:
            skill_states[dimension] = _next_dimension_state(
                skill_states.get(dimension, "not_started"), evidence, context
            )
        updated["state"] = aggregate_knowledge_state(skill_states, updated["required_dimensions"])
    else:
        updated["state"] = _next_dimension_state(updated["state"], evidence, context)

    if result in CONTACT_OUTCOMES and not (phase == "placement" and not placement_credit):
        # Placement attempts that earned no credit are screening observations; they
        # schedule nothing until the course actually teaches the item.
        observed = evidence_date(evidence)
        if observed is not None:
            updated["last_review_date"] = observed.isoformat()
            # A lapse comes back the next day; otherwise follow the state interval.
            interval = 1 if result == "FAIL" else KNOWLEDGE_REVIEW_INTERVAL_DAYS.get(updated["state"], 1)
            updated["next_review_date"] = (observed + timedelta(days=interval)).isoformat()
    return updated


def _mastery_ready(
    updated: dict[str, Any],
    evidence: dict[str, Any],
    prior_sessions: set[str],
    required_sessions: int,
    session_dates: dict[str, str] | None,
) -> bool:
    session_id = evidence.get("session_id")
    if not session_id or evidence.get("phase") not in {"check", "review"}:
        return False
    if not prior_sessions - {session_id}:
        return False
    if len(prior_sessions | {session_id}) < required_sessions:
        return False
    today = evidence.get("date")
    if today and session_dates:
        prior_dates = [session_dates.get(sid) for sid in prior_sessions]
        prior_dates = [value for value in prior_dates if isinstance(value, str)]
        if prior_dates:
            # Long-term mastery needs a later *date*, not merely another session.
            return today > min(prior_dates)
    return True


def knowledge_mastery_satisfied(
    state_evidence: Sequence[dict[str, Any]],
    session_dates: dict[str, str],
    required_sessions: int,
) -> bool:
    """Repository-side twin of `_mastery_ready`, evaluated over full history."""
    prior_sessions: set[str] = set()
    earliest: str | None = None
    for evidence in state_evidence:
        if not evidence_is_independent(evidence):
            continue
        session_id = evidence.get("session_id")
        observed = evidence.get("date")
        if evidence.get("phase") in {"check", "review"} and prior_sessions - {session_id}:
            if len(prior_sessions | {session_id}) >= required_sessions:
                if earliest is None or observed is None or observed > earliest:
                    return True
        if isinstance(observed, str) and (earliest is None or observed < earliest):
            earliest = observed
        if session_id:
            prior_sessions.add(session_id)
    return False


# ---------------------------------------------------------------------------
# Unit completion, unlocking and planning
# ---------------------------------------------------------------------------


def _objective_passes(profile: dict[str, Any], unit: dict[str, Any], objective: dict[str, Any]) -> set[str]:
    unseen_listening = "unseen_audio" in objective["evidence_requirement"]
    passes: set[str] = set()
    for entry in profile.get("practice_evidence", []):
        if entry.get("unit_id") != unit["unit_id"] or entry.get("objective_id") != objective["objective_id"]:
            continue
        if not evidence_is_independent(entry):
            continue
        if unseen_listening and not evidence_is_unseen_listening(entry):
            continue
        if entry.get("session_id"):
            passes.add(entry["session_id"])
    return passes


def unit_completion(profile: dict[str, Any], unit: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """Return (complete, missing_objective_ids, missing_knowledge_ids).

    A unit is complete only when every required objective has enough independent
    passes **and** every knowledge item those objectives target is independently
    demonstrated. The second condition is what keeps unit completion and the next
    unit's unlock requirements consistent.
    """
    required = unit["completion_criteria"]["minimum_independent_passes_per_objective"]
    objectives = unit_objectives(unit)
    missing_objectives: list[str] = []
    for objective_id in unit["completion_criteria"]["required_objective_ids"]:
        if len(_objective_passes(profile, unit, objectives[objective_id])) < required:
            missing_objectives.append(objective_id)

    qualified = {
        entry.get("knowledge_id")
        for entry in profile.get("knowledge_state", [])
        if entry.get("state") in QUALIFIED_KNOWLEDGE_STATES
    }
    missing_knowledge = [
        knowledge_id
        for knowledge_id in unit_knowledge_requirements(unit)
        if knowledge_id not in qualified
    ]
    return (not missing_objectives and not missing_knowledge), missing_objectives, missing_knowledge


def qualified_knowledge_ids(profile: dict[str, Any]) -> set[str]:
    return {
        entry.get("knowledge_id")
        for entry in profile.get("knowledge_state", [])
        if entry.get("state") in QUALIFIED_KNOWLEDGE_STATES
    }


def completed_unit_ids(profile: dict[str, Any], curricula: Sequence[dict[str, Any]]) -> list[str]:
    units, _objectives, _knowledge, _levels, _owner = _curriculum_indexes(curricula)
    credited = set(profile.get("current_course_position", {}).get("placement_credited_unit_ids", []))
    result: list[str] = []
    for unit_id in ordered_unit_ids(curricula):
        if unit_id in credited:
            continue
        complete, _missing_objectives, _missing_knowledge = unit_completion(profile, units[unit_id])
        if complete:
            result.append(unit_id)
    return result


def unlocked_unit_ids(profile: dict[str, Any], curricula: Sequence[dict[str, Any]]) -> list[str]:
    units, _objectives, _knowledge, _levels, _owner = _curriculum_indexes(curricula)
    position = profile.get("current_course_position", {})
    satisfied = set(position.get("completed_unit_ids", [])) | set(
        position.get("placement_credited_unit_ids", [])
    )
    qualified = qualified_knowledge_ids(profile)
    unlocked: list[str] = []
    for unit_id in ordered_unit_ids(curricula):
        unit = units[unit_id]
        if all(prerequisite in satisfied for prerequisite in unit["prerequisite_units"]) and all(
            knowledge_id in qualified for knowledge_id in unit["prerequisite_knowledge_ids"]
        ):
            unlocked.append(unit_id)
    return unlocked


def remediation_entries(
    profile: dict[str, Any], curricula: Sequence[dict[str, Any]], knowledge_ids: Sequence[str]
) -> list[dict[str, Any]]:
    """Concrete re-teach + independent-check plan for missing knowledge."""
    _units, _objectives, knowledge, _levels, _owner = _curriculum_indexes(curricula)
    states = {entry.get("knowledge_id"): entry for entry in profile.get("knowledge_state", [])}
    entries: list[dict[str, Any]] = []
    for knowledge_id in knowledge_ids:
        owner, entry = knowledge.get(knowledge_id, (None, None))
        entries.append(
            {
                "knowledge_id": knowledge_id,
                "owner_unit_id": owner,
                "form": entry["form"] if entry else None,
                "meaning_zh": entry["meaning_zh"] if entry else None,
                "required_dimensions": sorted(knowledge_required_dimensions(knowledge_id, curricula)),
                "current_state": states.get(knowledge_id, {}).get("state", "not_started"),
                "action": "reteach_then_independent_check",
                "evidence_required": (
                    "phase independent_expression/check, prompt_novelty unseen, "
                    "support none or non_revealing_context, modality voice or mixed"
                ),
            }
        )
    return entries


def unlock_blockers(
    profile: dict[str, Any], unit: dict[str, Any], curricula: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    """Why a unit is locked, plus the concrete remediation that clears the lock.

    A learner must never be stuck: missing prerequisite knowledge is turned into
    an explicit re-teach + independent-check plan instead of a silent dead end.
    """
    units, _objectives, _knowledge, _levels, _owner = _curriculum_indexes(curricula)
    position = profile.get("current_course_position", {})
    satisfied = set(position.get("completed_unit_ids", [])) | set(
        position.get("placement_credited_unit_ids", [])
    )
    qualified = qualified_knowledge_ids(profile)

    missing_units = [
        prerequisite for prerequisite in unit["prerequisite_units"] if prerequisite not in satisfied
    ]
    missing_knowledge = [
        knowledge_id
        for knowledge_id in unit["prerequisite_knowledge_ids"]
        if knowledge_id not in qualified
    ]

    prerequisite_gaps: list[dict[str, Any]] = []
    for prerequisite in missing_units:
        prerequisite_unit = units[prerequisite]
        complete, missing_objectives, missing_unit_knowledge = unit_completion(profile, prerequisite_unit)
        prerequisite_gaps.append(
            {
                "unit_id": prerequisite,
                "complete": complete,
                "missing_objective_ids": missing_objectives,
                "missing_knowledge_ids": missing_unit_knowledge,
            }
        )

    stale_owners: list[str] = []
    for knowledge_id in missing_knowledge:
        owner = _owner.get(knowledge_id)
        if owner in satisfied and owner not in stale_owners:
            # The owner unit is already treated as done, yet this prerequisite is
            # not independent. That is exactly the P0 deadlock shape.
            stale_owners.append(owner)

    return {
        "unit_id": unit["unit_id"],
        "unlocked": not missing_units and not missing_knowledge,
        "missing_prerequisite_units": missing_units,
        "missing_prerequisite_knowledge": missing_knowledge,
        "prerequisite_gaps": prerequisite_gaps,
        "remediation_plan": remediation_entries(profile, curricula, missing_knowledge),
        "stale_owner_units": stale_owners,
        "deadlock_risk": bool(stale_owners),
    }


def adaptive_new_repertoire_count(items: list[dict[str, Any]], today: date) -> int:
    due_dates = [date.fromisoformat(item["next_review_date"]) for item in items]
    due_count = sum(due_date <= today for due_date in due_dates)
    overdue_count = sum(due_date < today for due_date in due_dates)
    if overdue_count > 0 or due_count >= 8:
        return 0
    if due_count >= 5:
        return 1
    return 2


def _order_due_group(items: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    buckets: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        overdue_days = max(0, (today - date.fromisoformat(item["next_review_date"])).days)
        buckets.setdefault(overdue_days, []).append(item)

    ordered: list[dict[str, Any]] = []
    for overdue_days in sorted(buckets, reverse=True):
        by_type: dict[str, list[dict[str, Any]]] = {}
        for item in buckets[overdue_days]:
            by_type.setdefault(item["item_type"], []).append(item)
        for queue in by_type.values():
            queue.sort(key=lambda item: (-int(item.get("lapse_count", 0)), int(item["stage"]), item["item_id"]))
        types = sorted(by_type)
        while any(by_type.values()):
            for item_type in types:
                if by_type[item_type]:
                    ordered.append(by_type[item_type].pop(0))
    return ordered


def prepare_review_queue(
    items: list[dict[str, Any]], today: date, daily_review_limit: int = 8
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    working = deepcopy(items)
    due = [item for item in working if date.fromisoformat(item["next_review_date"]) <= today]
    normal = [item for item in due if not item.get("selection_defer_once", False)]
    deferred = [item for item in due if item.get("selection_defer_once", False)]
    ordered = _order_due_group(normal, today) + _order_due_group(deferred, today)
    selected_ids = [item["item_id"] for item in ordered[:daily_review_limit]]
    for item in deferred:
        item["selection_defer_once"] = False
    working_by_id = {item["item_id"]: item for item in working}
    return [working_by_id[item_id] for item_id in selected_ids], working


def update_repertoire_item(
    item: dict[str, Any], outcome: str, today: date, intervals: tuple[int, ...] = INTERVALS
) -> dict[str, Any]:
    if outcome not in TESTED_OUTCOMES | {"UNTESTED"}:
        raise ValueError(f"unknown outcome {outcome}")
    updated = deepcopy(item)
    if outcome == "UNTESTED":
        updated["selection_defer_once"] = True
        return updated

    updated["last_outcome"] = outcome
    updated["last_review_date"] = today.isoformat()
    updated["selection_defer_once"] = False
    stage = int(updated["stage"])
    status = updated["status"]

    if status == "mastered":
        if outcome == "PASS":
            updated["next_review_date"] = (today + timedelta(days=MASTERED_RECHECK_DAYS)).isoformat()
        elif outcome == "PARTIAL":
            updated["status"] = "active"
            updated["stage"] = 4
            updated["next_review_date"] = (today + timedelta(days=intervals[4])).isoformat()
        else:
            updated["status"] = "active"
            updated["stage"] = 0
            updated["lapse_count"] = int(updated.get("lapse_count", 0)) + 1
            updated["next_review_date"] = (today + timedelta(days=intervals[0])).isoformat()
        return updated

    if outcome == "PASS":
        if stage == len(intervals) - 1:
            updated["status"] = "mastered"
            updated["next_review_date"] = (today + timedelta(days=MASTERED_RECHECK_DAYS)).isoformat()
        else:
            updated["stage"] = stage + 1
            updated["next_review_date"] = (today + timedelta(days=intervals[stage + 1])).isoformat()
    elif outcome == "PARTIAL":
        updated["stage"] = max(0, stage - 1)
        updated["next_review_date"] = (today + timedelta(days=intervals[updated["stage"]])).isoformat()
    else:
        updated["stage"] = 0
        updated["lapse_count"] = int(updated.get("lapse_count", 0)) + 1
        updated["next_review_date"] = (today + timedelta(days=intervals[0])).isoformat()
    return updated


# ---------------------------------------------------------------------------
# Profile derivation (deterministic, evidence-only)
# ---------------------------------------------------------------------------


def _ordered_evidence(profile: dict[str, Any]) -> list[dict[str, Any]]:
    session_order = {
        session.get("session_id"): index
        for index, session in enumerate(profile.get("session_log", []))
    }
    indexed = list(enumerate(profile.get("practice_evidence", [])))
    indexed.sort(key=lambda pair: (session_order.get(pair[1].get("session_id"), len(session_order)), pair[0]))
    return [entry for _index, entry in indexed]


def recompute_knowledge_states(
    profile: dict[str, Any], curricula: Sequence[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Rebuild every knowledge state from `practice_evidence` alone.

    Existing entries are recomputed, and knowledge that only appears in evidence
    (for example a target the coach checked during a lesson) receives an entry of
    its own, so real lesson performance always maps onto the curriculum.
    """
    if curricula is None:
        return profile
    units, _objectives, knowledge, _levels, _owner = _curriculum_indexes(curricula)
    session_dates = {
        session.get("session_id"): session.get("date") for session in profile.get("session_log", [])
    }
    evidence_entries = _ordered_evidence(profile)
    mastery_by_unit = {
        unit_id: units[unit_id]["completion_criteria"]["mastery_requires_distinct_sessions"]
        for unit_id in units
    }

    known_ids: list[str] = []
    for entry in profile.get("knowledge_state", []):
        knowledge_id = entry.get("knowledge_id")
        if isinstance(knowledge_id, str) and knowledge_id in knowledge and knowledge_id not in known_ids:
            known_ids.append(knowledge_id)
    for evidence in evidence_entries:
        for knowledge_id in evidence.get("knowledge_ids", []):
            if knowledge_id in knowledge and knowledge_id not in known_ids:
                known_ids.append(knowledge_id)

    rebuilt: list[dict[str, Any]] = []
    for knowledge_id in known_ids:
        owner = knowledge[knowledge_id][0]
        required = sorted(knowledge_required_dimensions(knowledge_id, curricula))
        current: dict[str, Any] = {
            "knowledge_id": knowledge_id,
            "unit_id": owner,
            "state": "not_started",
            "evidence_ids": [],
            "independent_pass_sessions": [],
            "review_pass_sessions": [],
            "last_review_date": None,
            "next_review_date": None,
        }
        if required:
            current["required_dimensions"] = required
            current["skill_states"] = {dimension: "not_started" for dimension in required}
        mastery_required = mastery_by_unit.get(owner, 2)
        for evidence in evidence_entries:
            if knowledge_id not in evidence.get("knowledge_ids", []):
                continue
            dimensions = evidence_skill_dimensions(evidence, knowledge_id, curricula)
            current = apply_knowledge_evidence(
                current,
                evidence,
                mastery_requires_distinct_sessions=mastery_required,
                dimensions=dimensions,
                session_dates=session_dates,
                required_dimensions=required,
            )
        rebuilt.append(current)
    profile["knowledge_state"] = rebuilt
    return profile


def _unit_status(profile: dict[str, Any], unit: dict[str, Any]) -> str:
    complete, _missing_objectives, _missing_knowledge = unit_completion(profile, unit)
    if complete:
        states = {entry.get("knowledge_id"): entry.get("state") for entry in profile.get("knowledge_state", [])}
        required = unit_knowledge_requirements(unit)
        if required and all(states.get(knowledge_id) == "mastered" for knowledge_id in required):
            return "mastered"
        return "completed"
    has_evidence = any(entry.get("unit_id") == unit["unit_id"] for entry in profile.get("practice_evidence", []))
    return "in_progress" if has_evidence else "not_started"


def sync_course_position(
    profile: dict[str, Any], curricula: Sequence[dict[str, Any]], advance: bool = True
) -> dict[str, Any]:
    units, _objectives, _knowledge, levels, _owner = _curriculum_indexes(curricula)
    ordered = ordered_unit_ids(curricula)
    position = profile.setdefault("current_course_position", {})
    track = profile.setdefault("learning_track", {})
    credited = [unit_id for unit_id in position.get("placement_credited_unit_ids", []) if unit_id in units]
    position["placement_credited_unit_ids"] = credited

    position["completed_unit_ids"] = completed_unit_ids(profile, curricula)
    position["unlocked_unit_ids"] = unlocked_unit_ids(profile, curricula)

    unlocked = set(position["unlocked_unit_ids"])
    satisfied = set(position["completed_unit_ids"]) | set(credited)

    level_index = {document["level_id"]: index for index, document in enumerate(curricula)}
    floor = level_index.get(position.get("level_id"), 0)
    if credited:
        credited_levels = [levels[unit_id] for unit_id in credited if unit_id in levels]
        if credited_levels:
            floor = max(floor, max(level_index[level] for level in credited_levels) + 1)
    floor = min(floor, len(curricula) - 1)

    current = position.get("unit_id")
    done = lambda unit_id: unit_id in satisfied  # noqa: E731
    if advance and (current not in unlocked or done(current)):
        candidate = next(
            (
                unit_id
                for unit_id in ordered
                if unit_id in unlocked
                and not done(unit_id)
                and level_index[levels[unit_id]] >= floor
            ),
            None,
        )
        if candidate is None:
            candidate = next((unit_id for unit_id in reversed(ordered) if unit_id in unlocked), current)
        current = candidate

    position["unit_id"] = current
    if current is None:
        position["unit_status"] = "needs_curriculum_mapping" if track.get("mode") == "structured_curriculum" else "not_applicable"
        position["lesson_segment_id"] = None
        return profile

    position["level_id"] = levels[current]
    position["unit_status"] = _unit_status(profile, units[current])
    track["current_level"] = levels[current]
    if position["unit_status"] in {"completed", "mastered"}:
        position["lesson_segment_id"] = None
        position["lesson_phase"] = None
    return profile


def sync_profile(
    profile: dict[str, Any], curricula: Sequence[dict[str, Any]], advance: bool = True
) -> dict[str, Any]:
    recompute_knowledge_states(profile, curricula)
    sync_course_position(profile, curricula, advance=advance)
    return profile


# ---------------------------------------------------------------------------
# Lesson planning: multi-lesson units, remediation and pacing
# ---------------------------------------------------------------------------


def learner_pace(profile: dict[str, Any]) -> str:
    pace = profile.get("learner_preferences", {}).get("pace", "normal")
    return pace if pace in LESSON_PACE_VALUES else "normal"


def due_knowledge_ids(profile: dict[str, Any], today: date) -> list[str]:
    due: list[tuple[str, str]] = []
    for entry in profile.get("knowledge_state", []):
        if entry.get("state") in {"not_started", None}:
            continue
        next_review = entry.get("next_review_date")
        if not isinstance(next_review, str):
            continue
        try:
            when = date.fromisoformat(next_review)
        except ValueError:
            continue
        if when <= today:
            due.append((next_review, entry.get("knowledge_id")))
    due.sort()
    return [knowledge_id for _date, knowledge_id in due]


def unit_lesson_segments(unit: dict[str, Any]) -> list[dict[str, Any]]:
    segments = unit.get("lesson_segments")
    if segments:
        return list(segments)
    # Automatic fallback for units without an authored segmentation: take the
    # required knowledge in curriculum order, capped by the level's per-lesson
    # allowance. Knowledge is only introduced after its predecessors are solid.
    requirements = unit_knowledge_requirements(unit)
    objectives = unit_objectives(unit)
    owner_objectives: dict[str, list[str]] = {}
    for objective_id, objective in objectives.items():
        for knowledge_id in objective["target_knowledge_ids"]:
            owner_objectives.setdefault(knowledge_id, []).append(objective_id)
    limit = 2
    return [
        {
            "segment_id": f"{unit['unit_id']}-SAUTO{index + 1}",
            "focus_zh": "自动分课次（按课程顺序）",
            "knowledge_ids": requirements[index : index + limit],
            "target_objective_ids": sorted(
                {
                    objective_id
                    for knowledge_id in requirements[index : index + limit]
                    for objective_id in owner_objectives.get(knowledge_id, [])
                }
            ),
            "max_new_items": limit,
            "auto_generated": True,
        }
        for index in range(0, len(requirements), limit)
    ]


def segment_is_done(profile: dict[str, Any], unit: dict[str, Any], segment: dict[str, Any]) -> bool:
    """Whether one lesson segment has been taught and checked.

    A segment is finished when its knowledge is independently demonstrated and its
    objectives are checked, or when the coach explicitly marked the segment as
    taught. The explicit marker is what lets a long knowledge item such as "26
    letter names" span several lessons without pretending it was mastered at once.
    """
    marked = set(profile.get("current_course_position", {}).get("completed_lesson_segment_ids", []))
    if segment["segment_id"] in marked:
        return True
    qualified = qualified_knowledge_ids(profile)
    if any(knowledge_id not in qualified for knowledge_id in segment["knowledge_ids"]):
        return False
    objectives = unit_objectives(unit)
    required = unit["completion_criteria"]["minimum_independent_passes_per_objective"]
    for objective_id in segment.get("target_objective_ids", []):
        objective = objectives.get(objective_id)
        if objective is None:
            continue
        if len(_objective_passes(profile, unit, objective)) < required:
            return False
    return True


def plan_lesson(
    profile: dict[str, Any],
    curricula: Sequence[dict[str, Any]],
    today: date | None = None,
    unit_id: str | None = None,
) -> dict[str, Any]:
    """Decide what the next lesson should do.

    Returns the lesson segment, the capped amount of new knowledge, the review
    load, and whether the coach should continue, remediate, review or advance.
    """
    today = today or date.today()
    units, _objectives, knowledge, levels, _owner = _curriculum_indexes(curricula)
    ordered = ordered_unit_ids(curricula)
    position = profile.get("current_course_position", {})
    unlocked = list(position.get("unlocked_unit_ids", []))
    satisfied = set(position.get("completed_unit_ids", [])) | set(
        position.get("placement_credited_unit_ids", [])
    )

    requested = unit_id or position.get("unit_id")
    redirect: str | None = None
    if requested not in units or requested not in unlocked:
        redirect = requested
        requested = next(
            (candidate for candidate in ordered if candidate in unlocked and candidate not in satisfied),
            None,
        ) or (unlocked[-1] if unlocked else None)

    if requested is None:
        return {
            "date": today.isoformat(),
            "next_action": "needs_curriculum_mapping",
            "unit_id": None,
            "notes_zh": ["档案尚未映射到具体单元，请先完成桥接检验。"],
        }

    unit = units[requested]
    complete, missing_objectives, missing_knowledge = unit_completion(profile, unit)
    blockers = unlock_blockers(profile, unit, curricula) if requested in unlocked else {
        "unlocked": True,
        "missing_prerequisite_units": [],
        "missing_prerequisite_knowledge": [],
        "prerequisite_gaps": [],
        "remediation_plan": [],
        "deadlock_risk": False,
    }

    pace = learner_pace(profile)
    level_limit = next(
        document["support_policy"]["new_knowledge_per_lesson_max"]
        for document in curricula
        if document["level_id"] == levels[requested]
    )
    segments = unit_lesson_segments(unit)
    qualified = qualified_knowledge_ids(profile)
    current_segment = next(
        (segment for segment in segments if not segment_is_done(profile, unit, segment)),
        segments[-1],
    )

    max_new = min(level_limit, int(current_segment.get("max_new_items", level_limit)))
    if pace == "slower":
        max_new = min(max_new, 1)
    if pace in {"review_only", "paused"}:
        max_new = 0

    new_knowledge_ids = [
        knowledge_id
        for knowledge_id in current_segment["knowledge_ids"]
        if knowledge_id not in qualified
    ][:max_new]

    due_items, _working = prepare_review_queue(profile.get("active_repertoire", []), today)
    knowledge_due = due_knowledge_ids(profile, today)
    review_required = bool(due_items) or bool(knowledge_due) or pace in {"slower", "review_only"}

    next_unit = next((candidate for candidate in ordered if candidate in unlocked and candidate not in satisfied), None)

    # Remediation is required when the unit's objectives are checked but the
    # knowledge underneath them is still not independent, or when a prerequisite
    # gap exists. Either way the coach reteaches and re-checks before moving on.
    remediation = list(blockers["remediation_plan"])
    if missing_knowledge and not missing_objectives:
        already = {entry["knowledge_id"] for entry in remediation}
        remediation.extend(
            remediation_entries(
                profile, curricula, [k for k in missing_knowledge if k not in already]
            )
        )

    if pace == "paused":
        next_action = "paused"
    elif remediation:
        next_action = "remediate"
    elif complete and next_unit:
        next_action = "advance"
    elif complete:
        next_action = "consolidate"
    else:
        next_action = "continue"

    notes: list[str] = []
    if redirect:
        notes.append(f"请求的单元 {redirect} 尚未解锁，已改为当前可解锁单元 {requested}。")
    if remediation:
        notes.append("存在知识缺口，必须先做补充教学与独立检验，再进入新内容。")
    if pace == "slower":
        notes.append("学习者要求放慢：本课最多引入 1 个新知识点。")
    if pace == "faster":
        notes.append("学习者要求加快：仍受课程每课上限约束，不得跳过检验。")
    if pace == "review_only":
        notes.append("本次只复习，不引入新内容。")
    if pace == "paused":
        notes.append("学习者已暂停，不引入新内容。")

    return {
        "date": today.isoformat(),
        "level_id": levels[requested],
        "unit_id": requested,
        "unit_title_zh": unit["title_zh"],
        "unit_status": _unit_status(profile, unit),
        "unit_complete": complete,
        "missing_objective_ids": missing_objectives,
        "missing_knowledge_ids": missing_knowledge,
        "segment": {
            "segment_id": current_segment["segment_id"],
            "focus_zh": current_segment["focus_zh"],
            "knowledge_ids": list(current_segment["knowledge_ids"]),
            "target_objective_ids": list(current_segment.get("target_objective_ids", [])),
            "max_new_items": int(current_segment.get("max_new_items", level_limit)),
            "auto_generated": bool(current_segment.get("auto_generated", False)),
        },
        "segment_index": segments.index(current_segment) + 1,
        "segment_total": len(segments),
        "next_action": next_action,
        "new_knowledge_ids": [] if remediation else new_knowledge_ids,
        "new_knowledge_max": max_new,
        "new_repertoire_item_count": adaptive_new_repertoire_count(
            profile.get("active_repertoire", []), today
        ),
        "due_review_item_ids": [item["item_id"] for item in due_items],
        "due_knowledge_ids": knowledge_due,
        "review_required": review_required,
        "remediation_plan": remediation,
        "unlock": blockers,
        "next_unit_id": next_unit,
        "learner_pace": pace,
        "notes_zh": notes,
    }


# ---------------------------------------------------------------------------
# Profile validation
# ---------------------------------------------------------------------------


def _parse_iso_date(value: Any, label: str, errors: list[str], allow_none: bool = False) -> date | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        errors.append(f"{label}: expected ISO date string")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(f"{label}: invalid ISO date {value!r}")
        return None


def _pronunciation_numeric_paths(value: Any, path: str = "$", in_pronunciation: bool = False) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            child_context = in_pronunciation or "pronunciation" in key.lower()
            paths.extend(_pronunciation_numeric_paths(child, child_path, child_context))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_pronunciation_numeric_paths(child, f"{path}[{index}]", in_pronunciation))
    elif in_pronunciation and isinstance(value, (int, float)) and not isinstance(value, bool):
        paths.append(path)
    return paths


def placement_credit_errors(profile: dict[str, Any], curricula: Sequence[dict[str, Any]]) -> list[str]:
    """A level may only be skipped when the exit check covers the real requirements.

    One formally valid integrated record is not enough: the credited knowledge
    must cover the exit unit's required knowledge and must span both listening and
    speaking. Otherwise the learner stays provisional at the lower unit.
    """
    errors: list[str] = []
    units, _objectives, _knowledge, _levels, _owner = _curriculum_indexes(curricula)
    exit_units = set(exit_unit_by_level(curricula).values())
    level_requirements = level_placement_requirements(curricula)
    unit_level = {unit_id: level for level, unit_id in exit_unit_by_level(curricula).items()}
    position = profile.get("current_course_position", {})
    credited = set(position.get("placement_credited_unit_ids", []))
    track = profile.get("learning_track", {})
    basis = track.get("placement_basis")

    if basis == "learner_choice" and credited:
        errors.append("placement_basis learner_choice cannot skip a unit; an independent level check is required")

    for unit_id in sorted(credited):
        if unit_id not in units:
            continue
        if unit_id not in exit_units:
            errors.append(f"{unit_id}: only a level-exit unit may receive placement credit")
            continue
        unit = units[unit_id]
        evidence = [
            entry
            for entry in profile.get("practice_evidence", [])
            if entry.get("unit_id") == unit_id and evidence_is_placement_credit(entry)
        ]
        if not evidence:
            errors.append(f"{unit_id}: placement credit needs an independent placement check")
            continue
        covered: set[str] = set()
        for entry in evidence:
            covered.update(entry.get("knowledge_ids", []))
        required = set(level_requirements.get(unit_level[unit_id], unit_knowledge_requirements(unit)))
        missing = sorted(required - covered)
        if missing:
            errors.append(
                f"{unit_id}: placement credit does not cover the level's required knowledge {missing}"
            )
        dimensions: set[str] = set()
        for knowledge_id in covered:
            dimensions.update(knowledge_required_dimensions(knowledge_id, curricula))
        if not {"listening", "speaking"} <= dimensions:
            errors.append(
                f"{unit_id}: placement credit must cover both listening and speaking, found {sorted(dimensions)}"
            )
    return errors


def validate_profile(
    profile: dict[str, Any],
    curricula: list[dict[str, Any]] | None = None,
    schema: dict[str, Any] | None = None,
) -> None:
    errors: list[str] = []
    if schema:
        errors.extend(schema_errors(profile, schema))

    required = {
        "schema_version",
        "profile_revision",
        "created_at",
        "updated_at",
        "timezone",
        "target_english_variety",
        "scientific_assessment",
        "learning_track",
        "current_course_position",
        "knowledge_state",
        "skill_weaknesses",
        "practice_evidence",
        "active_repertoire",
        "session_log",
    }
    missing = sorted(required - profile.keys())
    if missing:
        errors.append(f"profile missing required fields: {', '.join(missing)}")
    if profile.get("schema_version") != "3.0":
        errors.append("profile schema_version must be 3.0")
    if not isinstance(profile.get("profile_revision"), int) or profile.get("profile_revision", 0) < 1:
        errors.append("profile_revision must be a positive integer")

    preferences = profile.get("learner_preferences", {})
    if not isinstance(preferences, dict):
        errors.append("learner_preferences must be an object")
    elif preferences.get("pace", "normal") not in LESSON_PACE_VALUES:
        errors.append(f"learner_preferences.pace must be one of {list(LESSON_PACE_VALUES)}")

    session_log = profile.get("session_log", [])
    if not isinstance(session_log, list):
        errors.append("session_log must be a list")
        session_log = []
    session_ids: set[str] = set()
    session_order: dict[str, int] = {}
    session_dates: dict[str, str] = {}
    previous_session_date: date | None = None
    for index, session in enumerate(session_log):
        session_id = session.get("session_id")
        if not session_id or session_id in session_ids:
            errors.append(f"session_log[{index}] has a missing or duplicate session_id")
        else:
            session_ids.add(session_id)
            session_order[session_id] = index
            if isinstance(session.get("date"), str):
                session_dates[session_id] = session["date"]
        session_date = _parse_iso_date(session.get("date"), f"session_log[{index}].date", errors)
        if session_date and previous_session_date and session_date < previous_session_date:
            errors.append("session_log dates must be chronological")
        if session_date:
            previous_session_date = session_date

    evidence_entries = profile.get("practice_evidence", [])
    if not isinstance(evidence_entries, list):
        errors.append("practice_evidence must be a list")
        evidence_entries = []
    evidence_ids: set[str] = set()
    evidence_by_id: dict[str, dict[str, Any]] = {}
    evidence_order: dict[str, int] = {}
    evidence_required = {
        "evidence_id",
        "session_id",
        "date",
        "unit_id",
        "objective_id",
        "knowledge_ids",
        "phase",
        "modality",
        "support_level",
        "result",
        "learner_response_summary",
        "pronunciation_evidence_basis",
        "prompt_novelty",
        "text_shown_before_response",
    }
    for index, evidence in enumerate(evidence_entries):
        evidence_id = evidence.get("evidence_id")
        missing_evidence = sorted(evidence_required - evidence.keys())
        if missing_evidence:
            errors.append(f"practice_evidence[{index}] missing {missing_evidence}")
        if not evidence_id:
            errors.append(f"practice_evidence[{index}] missing evidence_id")
        elif evidence_id in evidence_ids:
            errors.append(f"duplicate evidence_id {evidence_id}")
        else:
            evidence_ids.add(evidence_id)
            evidence_by_id[evidence_id] = evidence
            evidence_order[evidence_id] = index
        _parse_iso_date(evidence.get("date"), f"{evidence_id}.date", errors)
        if evidence.get("session_id") not in session_ids:
            errors.append(f"{evidence_id}: session_id is not present in session_log")
        if evidence.get("phase") == "repeat_after_model" and evidence.get("result") == "PASS":
            errors.append(f"{evidence_id}: repetition must be PRACTICED, not PASS")
        if evidence.get("modality") == "text" and evidence.get("pronunciation_evidence_basis") == "direct_live_audio":
            errors.append(f"{evidence_id}: text evidence cannot claim direct Live audio")
        grade = evidence.get("listening_check_grade")
        if grade is not None and grade not in LISTENING_CHECK_GRADES:
            errors.append(f"{evidence_id}: unknown listening_check_grade {grade!r}")
        if grade == "strict_unseen":
            if evidence.get("text_shown_before_response") is not False:
                errors.append(f"{evidence_id}: strict unseen listening requires text_shown_before_response false")
            if evidence.get("prompt_novelty") != "unseen":
                errors.append(f"{evidence_id}: strict unseen listening requires an unseen prompt")
            if evidence.get("modality") not in {"voice", "mixed"}:
                errors.append(f"{evidence_id}: strict unseen listening requires voice or mixed modality")
        if grade == "text_supported_practice" and evidence.get("result") == "PASS":
            if evidence.get("phase") in {"independent_expression", "check", "review"}:
                errors.append(
                    f"{evidence_id}: a text-supported listening attempt must be downgraded to practice, "
                    "not recorded as an independent check"
                )
        score_keys = {
            key
            for key in evidence
            if any(token in key.lower() for token in ("score", "percent", "accuracy"))
        }
        if score_keys and not pronunciation_claim_allowed(
            evidence.get("pronunciation_evidence_basis", "not_assessed"), "numeric_score"
        ):
            errors.append(f"{evidence_id}: exact pronunciation score fields are not allowed: {sorted(score_keys)}")

    units: dict[str, dict[str, Any]] = {}
    objectives: dict[str, tuple[str, dict[str, Any]]] = {}
    curriculum_knowledge: dict[str, tuple[str, dict[str, Any]]] = {}
    unit_levels: dict[str, str] = {}
    if curricula:
        units, objectives, curriculum_knowledge, unit_levels, _owner = _curriculum_indexes(curricula)
        for evidence in evidence_entries:
            evidence_id = evidence.get("evidence_id")
            unit_id = evidence.get("unit_id")
            objective_id = evidence.get("objective_id")
            if unit_id is not None and unit_id not in units:
                errors.append(f"{evidence_id}: unknown curriculum unit {unit_id}")
            if objective_id is not None:
                if objective_id not in objectives:
                    errors.append(f"{evidence_id}: unknown objective {objective_id}")
                else:
                    objective_unit, objective = objectives[objective_id]
                    if unit_id != objective_unit:
                        errors.append(f"{evidence_id}: objective {objective_id} does not belong to {unit_id}")
                    unknown_targets = set(evidence.get("knowledge_ids", [])) - set(objective["target_knowledge_ids"])
                    if unknown_targets:
                        errors.append(f"{evidence_id}: knowledge is outside objective targets {sorted(unknown_targets)}")
                    if "unseen_audio" in objective["evidence_requirement"] and evidence.get("result") == "PASS":
                        if not evidence_is_unseen_listening(evidence):
                            errors.append(f"{evidence_id}: unseen listening PASS needs hidden novel voice evidence")
            for knowledge_id in evidence.get("knowledge_ids", []):
                if knowledge_id not in curriculum_knowledge:
                    errors.append(f"{evidence_id}: unknown curriculum knowledge {knowledge_id}")

    knowledge_entries = profile.get("knowledge_state", [])
    if not isinstance(knowledge_entries, list):
        errors.append("knowledge_state must be a list")
        knowledge_entries = []
    profile_knowledge_ids: set[str] = set()
    knowledge_state_by_id: dict[str, dict[str, Any]] = {}
    for index, state in enumerate(knowledge_entries):
        knowledge_id = state.get("knowledge_id")
        if not knowledge_id:
            errors.append(f"knowledge_state[{index}] missing knowledge_id")
            continue
        if knowledge_id in profile_knowledge_ids:
            errors.append(f"duplicate knowledge_state {knowledge_id}")
        profile_knowledge_ids.add(knowledge_id)
        knowledge_state_by_id[knowledge_id] = state
        state_evidence_ids = state.get("evidence_ids", [])
        unknown_evidence = set(state_evidence_ids) - evidence_ids
        if unknown_evidence:
            errors.append(f"{knowledge_id}: unknown evidence IDs {sorted(unknown_evidence)}")
        all_state_evidence = [
            evidence_by_id[evidence_id] for evidence_id in state_evidence_ids if evidence_id in evidence_by_id
        ]
        for evidence in all_state_evidence:
            if knowledge_id not in evidence.get("knowledge_ids", []):
                errors.append(f"{knowledge_id}: evidence {evidence.get('evidence_id')} does not prove this knowledge")
        state_evidence = [
            evidence for evidence in all_state_evidence if knowledge_id in evidence.get("knowledge_ids", [])
        ]
        state_evidence.sort(
            key=lambda evidence: (
                session_order.get(evidence.get("session_id"), len(session_order)),
                evidence_order.get(evidence.get("evidence_id"), len(evidence_order)),
            )
        )
        _parse_iso_date(state.get("last_review_date"), f"{knowledge_id}.last_review_date", errors, allow_none=True)
        _parse_iso_date(state.get("next_review_date"), f"{knowledge_id}.next_review_date", errors, allow_none=True)
        actual_independent_sessions = {
            evidence["session_id"]
            for evidence in state_evidence
            if evidence_is_independent(evidence) or evidence_is_placement_credit(evidence)
        }
        actual_review_sessions = {
            evidence["session_id"]
            for evidence in state_evidence
            if evidence_is_independent(evidence) and evidence.get("phase") in {"check", "review"}
        }
        if set(state.get("independent_pass_sessions", [])) != actual_independent_sessions:
            errors.append(f"{knowledge_id}: independent_pass_sessions do not match evidence")
        if set(state.get("review_pass_sessions", [])) != actual_review_sessions:
            errors.append(f"{knowledge_id}: review_pass_sessions do not match evidence")
        if state.get("state") == "independent" and not actual_independent_sessions:
            errors.append(f"{knowledge_id}: independent state needs an independent pass")
        if state.get("state") == "placement_credited" and not any(
            evidence_is_placement_credit(evidence) for evidence in state_evidence
        ):
            errors.append(f"{knowledge_id}: placement credit needs independent placement evidence")

        errors.extend(
            _skill_dimension_errors(knowledge_id, state, state_evidence, curricula, session_dates)
        )

        if curricula and knowledge_id in curriculum_knowledge:
            owner_unit, _ = curriculum_knowledge[knowledge_id]
            if state.get("unit_id") != owner_unit:
                errors.append(f"{knowledge_id}: knowledge state unit must be {owner_unit}")
            if state.get("state") == "mastered":
                required_sessions = units[owner_unit]["completion_criteria"]["mastery_requires_distinct_sessions"]
                if len(actual_independent_sessions) < required_sessions or not knowledge_mastery_satisfied(
                    state_evidence, session_dates, required_sessions
                ):
                    errors.append(
                        f"{knowledge_id}: mastery needs the configured sessions and a later-dated check or review"
                    )
        elif curricula:
            errors.append(f"profile knowledge {knowledge_id} is not in the curriculum")

    weaknesses = profile.get("skill_weaknesses", {})
    if not isinstance(weaknesses, dict):
        errors.append("skill_weaknesses must be an object")
        weaknesses = {}
    for skill in ("listening", "speaking", "pronunciation"):
        entries = weaknesses.get(skill)
        if not isinstance(entries, list):
            errors.append(f"skill_weaknesses.{skill} must be a list")
            continue
        for weakness in entries:
            weakness_id = weakness.get("weakness_id")
            weakness_evidence_ids = weakness.get("evidence_ids", [])
            unknown_evidence = set(weakness_evidence_ids) - evidence_ids
            if unknown_evidence:
                errors.append(f"{weakness_id}: unknown evidence IDs {sorted(unknown_evidence)}")
            if skill == "pronunciation":
                forbidden = {
                    key
                    for key in weakness
                    if any(token in key.lower() for token in ("score", "percent", "accuracy"))
                }
                if forbidden:
                    errors.append(f"{weakness_id}: exact pronunciation scores are not allowed")
                observation = str(weakness.get("observation", ""))
                if re.search(r"\b\d+(?:\.\d+)?\s*(?:%|/\s*100|points?|score|band)\b", observation, re.IGNORECASE):
                    errors.append(f"{weakness_id}: numeric pronunciation claims are not allowed in observations")
                basis = weakness.get("evidence_basis")
                if basis == "transcript_only" and weakness.get("status") != "not_assessed":
                    errors.append(f"{weakness_id}: transcript-only pronunciation must be not_assessed")
                if basis == "direct_live_audio":
                    supporting = [evidence_by_id[eid] for eid in weakness_evidence_ids if eid in evidence_by_id]
                    if not supporting or any(
                        evidence.get("pronunciation_evidence_basis") != "direct_live_audio"
                        or evidence.get("modality") not in {"voice", "mixed"}
                        for evidence in supporting
                    ):
                        errors.append(f"{weakness_id}: direct-audio weakness needs matching voice evidence")

    repertoire = profile.get("active_repertoire", [])
    if not isinstance(repertoire, list):
        errors.append("active_repertoire must be a list")
    else:
        item_ids: set[str] = set()
        for item in repertoire:
            item_id = item.get("item_id")
            if not item_id or item_id in item_ids:
                errors.append(f"invalid or duplicate repertoire item_id {item_id!r}")
            item_ids.add(item_id)
            if item.get("status") not in {"active", "mastered"}:
                errors.append(f"{item_id}: invalid status")
            if not isinstance(item.get("stage"), int) or not 0 <= item["stage"] <= 5:
                errors.append(f"{item_id}: stage must be 0..5")
            _parse_iso_date(item.get("next_review_date"), f"{item_id}.next_review_date", errors)
            _parse_iso_date(item.get("last_review_date"), f"{item_id}.last_review_date", errors, allow_none=True)

    listed_session_evidence: dict[str, set[str]] = {}
    for session in session_log:
        session_id = session.get("session_id")
        listed = set(session.get("evidence_ids", []))
        listed_session_evidence[session_id] = listed
        for evidence_id in listed:
            if evidence_id not in evidence_ids:
                errors.append(f"{session_id}: unknown session evidence {evidence_id}")
            elif evidence_by_id[evidence_id].get("session_id") != session_id:
                errors.append(f"{session_id}: evidence {evidence_id} belongs to another session")
        for outcome in session.get("review_outcomes", []):
            evidence_id = outcome.get("evidence_id")
            if evidence_id is not None and evidence_id not in evidence_ids:
                errors.append(f"{session_id}: unknown review evidence {evidence_id}")
            elif evidence_id is not None and evidence_by_id[evidence_id].get("session_id") != session_id:
                errors.append(f"{session_id}: review evidence {evidence_id} belongs to another session")
    for evidence in evidence_entries:
        evidence_id = evidence.get("evidence_id")
        session_id = evidence.get("session_id")
        if evidence_id not in listed_session_evidence.get(session_id, set()):
            errors.append(f"{evidence_id}: evidence is not listed by its session")

    assessment = profile.get("scientific_assessment", {})
    legacy_path = "$.scientific_assessment.ielts_dimensions.pronunciation"
    pronunciation_numeric_paths = _pronunciation_numeric_paths(profile)
    for numeric_path in pronunciation_numeric_paths:
        if numeric_path != legacy_path:
            errors.append(f"current numeric pronunciation claim is not allowed at {numeric_path}")
    legacy_pronunciation = assessment.get("ielts_dimensions", {}).get("pronunciation") if isinstance(assessment, dict) else None
    if isinstance(legacy_pronunciation, (int, float)) and not isinstance(legacy_pronunciation, bool):
        migrated_from_v21 = any(
            entry.get("from_version") == "2.1" for entry in profile.get("migration_history", [])
        )
        if not migrated_from_v21 or not assessment.get("legacy_pronunciation_notice"):
            errors.append("numeric pronunciation data is allowed only as labeled historical v2.1 data")

    if curricula:
        track = profile.get("learning_track", {})
        position = profile.get("current_course_position", {})
        mode = track.get("mode")
        if mode == "structured_curriculum":
            if track.get("curriculum_id") != CURRICULUM_ID or track.get("curriculum_version") not in SUPPORTED_CURRICULUM_VERSIONS:
                errors.append("learning_track does not match a supported curriculum release")
            if track.get("current_level") not in CURRICULUM_LEVELS:
                errors.append("structured curriculum level must be PRE_A1 through B1")
        elif mode == "legacy_conversation" and position.get("unit_status") != "not_applicable":
            errors.append("legacy_conversation course position must be not_applicable")
        if track.get("placement_basis") not in PLACEMENT_BASES:
            errors.append(f"learning_track.placement_basis must be one of {list(PLACEMENT_BASES)}")
        if track.get("current_level") != position.get("level_id"):
            errors.append("learning_track current level must match current_course_position")

        unit_id = position.get("unit_id")
        if unit_id is not None:
            if unit_id not in units:
                errors.append(f"current course unit {unit_id} is not in the curriculum")
            else:
                if position.get("level_id") != unit_levels[unit_id]:
                    errors.append("current course level does not match current unit")
                if track.get("current_level") != unit_levels[unit_id]:
                    errors.append("learning track level does not match current unit")
                if unit_id not in position.get("unlocked_unit_ids", []):
                    errors.append("current course unit must be unlocked")
        elif mode == "structured_curriculum" and position.get("unit_status") not in {"needs_curriculum_mapping"}:
            errors.append("structured curriculum without a unit must need curriculum mapping")

        unlocked = set(position.get("unlocked_unit_ids", []))
        completed = set(position.get("completed_unit_ids", []))
        placement_credited = set(position.get("placement_credited_unit_ids", []))
        for label, identifiers in (
            ("unlocked", unlocked),
            ("completed", completed),
            ("placement credited", placement_credited),
        ):
            unknown = identifiers - units.keys()
            if unknown:
                errors.append(f"unknown {label} unit IDs {sorted(unknown)}")
        if completed & placement_credited:
            errors.append("units cannot be both completed and placement credited")
        if not completed <= unlocked:
            errors.append(f"completed units must also be unlocked: {sorted(completed - unlocked)}")
        current_status = position.get("unit_status")
        if unit_id is not None and current_status in {"completed", "mastered"} and unit_id not in completed:
            errors.append("completed current status requires the current unit in completed_unit_ids")
        if unit_id is not None and unit_id in completed and current_status not in {"completed", "mastered"}:
            errors.append("completed current unit needs completed or mastered status")

        errors.extend(placement_credit_errors(profile, curricula))

        known_segments = {
            segment["segment_id"]
            for unit_identifier in units
            for segment in unit_lesson_segments(units[unit_identifier])
        }
        for segment_id in position.get("completed_lesson_segment_ids", []):
            if segment_id not in known_segments:
                errors.append(f"unknown completed lesson segment {segment_id}")
        active_segment = position.get("lesson_segment_id")
        if active_segment is not None:
            if unit_id is None or unit_id not in units:
                errors.append("lesson_segment_id requires a current unit")
            elif active_segment not in {
                segment["segment_id"] for segment in unit_lesson_segments(units[unit_id])
            }:
                errors.append(f"lesson_segment_id {active_segment} does not belong to {unit_id}")

        for completed_unit in sorted(completed & units.keys()):
            complete, missing_objectives, missing_knowledge = unit_completion(profile, units[completed_unit])
            if not complete:
                details: list[str] = []
                if missing_objectives:
                    details.append(f"objectives {missing_objectives}")
                if missing_knowledge:
                    details.append(f"knowledge {missing_knowledge}")
                errors.append(f"{completed_unit}: completed without evidence for {'; '.join(details)}")
            elif current_status == "mastered" and completed_unit == unit_id:
                required_knowledge = unit_knowledge_requirements(units[completed_unit])
                if any(
                    knowledge_state_by_id.get(knowledge_id, {}).get("state") != "mastered"
                    for knowledge_id in required_knowledge
                ):
                    errors.append(f"{completed_unit}: mastered status needs every required knowledge item mastered")

        qualified_knowledge = {
            knowledge_id
            for knowledge_id, state in knowledge_state_by_id.items()
            if state.get("state") in QUALIFIED_KNOWLEDGE_STATES
        }
        satisfied_units = completed | placement_credited
        for unlocked_unit in sorted(unlocked & units.keys()):
            unit = units[unlocked_unit]
            missing_units = set(unit["prerequisite_units"]) - satisfied_units
            missing_knowledge = set(unit["prerequisite_knowledge_ids"]) - qualified_knowledge
            if missing_units:
                errors.append(f"{unlocked_unit}: unlocked before prerequisite units {sorted(missing_units)}")
            if missing_knowledge:
                errors.append(f"{unlocked_unit}: unlocked before prerequisite knowledge {sorted(missing_knowledge)}")

    if errors:
        raise ValidationError(errors)


def _skill_dimension_errors(
    knowledge_id: str,
    state: dict[str, Any],
    state_evidence: Sequence[dict[str, Any]],
    curricula: Sequence[dict[str, Any]] | None,
    session_dates: dict[str, str],
) -> list[str]:
    """Check that the aggregate state really follows from the per-skill evidence."""
    errors: list[str] = []
    skill_states = state.get("skill_states")
    required_dimensions = state.get("required_dimensions")
    if skill_states is None and required_dimensions is None:
        return errors
    if not isinstance(skill_states, dict):
        return [f"{knowledge_id}: skill_states must be an object"]
    for dimension, value in skill_states.items():
        if dimension not in SKILL_DIMENSIONS:
            errors.append(f"{knowledge_id}: unknown skill dimension {dimension!r}")
        if value not in KNOWLEDGE_STATES:
            errors.append(f"{knowledge_id}: invalid {dimension} state {value!r}")
    if not isinstance(required_dimensions, list) or not required_dimensions:
        errors.append(f"{knowledge_id}: required_dimensions must be a non-empty list when skill_states is present")
        return errors
    if curricula:
        expected = sorted(knowledge_required_dimensions(knowledge_id, curricula))
        if sorted(required_dimensions) != expected:
            errors.append(f"{knowledge_id}: required_dimensions must be {expected}")
        observed: dict[str, str] = {}

        def bump(dimension: str, level: str) -> None:
            if STATE_RANK.get(level, 0) > STATE_RANK.get(observed.get(dimension, "not_started"), 0):
                observed[dimension] = level

        for evidence in state_evidence:
            if evidence_is_placement_credit(evidence):
                level = "placement_credited"
            elif evidence_is_independent(evidence):
                level = "independent"
            elif evidence.get("result") in {"PASS", "PARTIAL", "PRACTICED"}:
                level = "supported"
            else:
                continue
            for dimension in evidence_skill_dimensions(evidence, knowledge_id, curricula):
                bump(dimension, level)
        for dimension in required_dimensions:
            declared = skill_states.get(dimension, "not_started")
            if declared in {"independent", "mastered"} and observed.get(dimension) not in {
                "independent",
                "placement_credited",
            }:
                errors.append(
                    f"{knowledge_id}: {dimension} state {declared} has no independent {dimension} evidence"
                )
    aggregate = aggregate_knowledge_state(skill_states, required_dimensions)
    if state.get("state") != aggregate:
        errors.append(
            f"{knowledge_id}: state {state.get('state')!r} must equal the weakest required skill dimension {aggregate!r}"
        )
    return errors


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def next_export_path(source_path: Path, export_date: date, output_dir: Path | None = None) -> Path:
    output_dir = output_dir or source_path.parent
    base = f"English_Learning_Profile_updated_{export_date.isoformat()}"
    candidate = output_dir / f"{base}.json"
    suffix = 2
    while candidate.exists() or candidate.resolve() == source_path.resolve():
        candidate = output_dir / f"{base}_{suffix}.json"
        suffix += 1
    return candidate


def export_profile(
    profile: dict[str, Any],
    source_path: Path,
    export_date: date,
    output_dir: Path | None = None,
    curricula: list[dict[str, Any]] | None = None,
    profile_schema: dict[str, Any] | None = None,
    sync: bool = True,
) -> Path:
    """Validate, write a new file, then reopen and re-validate it.

    `sync` recomputes knowledge states and the course position from evidence
    before writing. It never adds evidence, so it cannot fabricate progress.
    """
    curricula = curricula or load_curricula(ROOT)
    profile_schema = profile_schema or load_json(ROOT / "schemas" / "learning-profile.schema.json")
    working = deepcopy(profile)
    if sync:
        sync_profile(working, curricula)
    validate_profile(working, curricula, profile_schema)
    destination = next_export_path(source_path, export_date, output_dir)
    destination.write_text(json.dumps(working, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    exported = load_json(destination)
    validate_profile(exported, curricula, profile_schema)
    if exported != working:
        raise ValidationError(["exported profile does not match the validated profile"])
    return destination


# ---------------------------------------------------------------------------
# First profile creation
# ---------------------------------------------------------------------------


def init_profile(
    placement: dict[str, Any],
    curricula: Sequence[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the first v3.0 profile from a placement/screening record.

    Only records that satisfy the placement-credit rules can skip a level. A
    learner whose screening is thin stays `provisional` at the lower unit and
    receives a bridge check instead of an unlocked upper level.
    """
    now = now or datetime.now(timezone.utc)
    for field in ("timezone", "target_english_variety", "screening_session", "screening_evidence"):
        if field not in placement:
            raise ValidationError([f"placement input missing {field}"])
    session = placement["screening_session"]
    session_id = session.get("session_id")
    session_date = session.get("date")
    if not session_id or not session_date:
        raise ValidationError(["placement screening_session needs session_id and date"])

    evidence: list[dict[str, Any]] = []
    for index, entry in enumerate(placement["screening_evidence"]):
        record = deepcopy(entry)
        record.setdefault("evidence_id", f"evidence_placement_{index + 1:04d}")
        record.setdefault("session_id", session_id)
        record.setdefault("date", session_date)
        record.setdefault("unit_id", None)
        record.setdefault("objective_id", None)
        record.setdefault("phase", "placement")
        record.setdefault("pronunciation_evidence_basis", "not_applicable")
        record.setdefault("prompt_novelty", "unseen")
        record.setdefault("text_shown_before_response", False)
        if record.get("phase") != "placement":
            raise ValidationError([f"screening evidence {record['evidence_id']} must use phase placement"])
        if record.get("objective_id") is not None:
            raise ValidationError([f"screening evidence {record['evidence_id']} must not target an objective"])
        evidence.append(record)

    referenced = sorted({knowledge_id for record in evidence for knowledge_id in record.get("knowledge_ids", [])})
    owner_of: dict[str, str] = {}
    for document in curricula:
        for unit in document["units"]:
            for item in unit["knowledge"]:
                owner_of[item["knowledge_id"]] = unit["unit_id"]
    unknown = [knowledge_id for knowledge_id in referenced if knowledge_id not in owner_of]
    if unknown:
        raise ValidationError([f"placement evidence references unknown knowledge {unknown}"])

    profile: dict[str, Any] = {
        "schema_version": "3.0",
        "profile_revision": 1,
        "created_at": now.isoformat(timespec="seconds"),
        "updated_at": now.isoformat(timespec="seconds"),
        "timezone": placement["timezone"],
        "target_english_variety": placement["target_english_variety"],
        "scientific_assessment": {
            "assessment_status": "provisional",
            "overall_cefr": "PRE_A1",
            "cefr_range": ["PRE_A1"],
            "confidence": placement.get("assessment_confidence", "low"),
            "assessment_basis": "short independent listening and speaking screening",
            "pronunciation_assessment": "qualitative_only",
            "learner_goal_zh": placement.get("learner_goal_zh"),
        },
        "learning_track": {
            "curriculum_id": CURRICULUM_ID,
            "curriculum_version": DEFAULT_CURRICULUM_VERSION,
            "current_level": "PRE_A1",
            "mode": "structured_curriculum",
            "placement_basis": "initial_screening",
            "support_language": "zh-CN",
        },
        "current_course_position": {
            "level_id": "PRE_A1",
            "unit_id": None,
            "unit_status": "needs_curriculum_mapping",
            "lesson_phase": None,
            "lesson_segment_id": None,
            "unlocked_unit_ids": [],
            "completed_unit_ids": [],
            "placement_credited_unit_ids": [],
        },
        "knowledge_state": [
            {
                "knowledge_id": knowledge_id,
                "unit_id": owner_of[knowledge_id],
                "state": "not_started",
                "evidence_ids": [],
                "independent_pass_sessions": [],
                "review_pass_sessions": [],
                "last_review_date": None,
                "next_review_date": None,
            }
            for knowledge_id in referenced
        ],
        "skill_weaknesses": {"listening": [], "speaking": [], "pronunciation": []},
        "practice_evidence": evidence,
        "active_repertoire": list(placement.get("active_repertoire", [])),
        "session_log": [
            {
                "session_id": session_id,
                "date": session_date,
                "level_id": "PRE_A1",
                "unit_id": None,
                "completed_phases": ["course_goal", "placement"],
                "evidence_ids": [record["evidence_id"] for record in evidence],
                "review_outcomes": [],
                "new_item_ids": [],
                "assessment_observations": placement.get("screening_notes", []),
                "verified_topic_brief": None,
            }
        ],
        "migration_history": [],
    }
    if placement.get("learner_pace"):
        profile["learner_preferences"] = {"pace": placement["learner_pace"]}

    recompute_knowledge_states(profile, curricula)

    credited: list[str] = []
    for level, exit_unit in exit_unit_by_level(curricula).items():
        probe = deepcopy(profile)
        probe["current_course_position"]["placement_credited_unit_ids"] = [exit_unit]
        if not placement_credit_errors(probe, curricula):
            credited.append(exit_unit)
    credited.sort(key=lambda unit_id: ordered_unit_ids(curricula).index(unit_id))

    if credited:
        profile["learning_track"]["placement_basis"] = "independent_level_check"
    profile["current_course_position"]["placement_credited_unit_ids"] = credited

    highest = "PRE_A1"
    course_level = CURRICULUM_LEVELS[0]
    for document in curricula:
        level = document["level_id"]
        exit_unit = document["units"][-1]["unit_id"]
        if exit_unit in credited:
            highest = level
            continue
        course_level = level
        break
    else:
        course_level = CURRICULUM_LEVELS[-1]

    profile["scientific_assessment"]["overall_cefr"] = highest
    profile["learning_track"]["current_level"] = course_level
    profile["current_course_position"]["level_id"] = course_level

    sync_course_position(profile, curricula)
    return profile


# ---------------------------------------------------------------------------
# Repository check and CLI
# ---------------------------------------------------------------------------


def repository_check(root: Path = ROOT) -> None:
    curricula = load_curricula(root)
    curriculum_schema = load_json(root / "schemas" / "curriculum.schema.json")
    profile_schema = load_json(root / "schemas" / "learning-profile.schema.json")
    validate_curricula(curricula, curriculum_schema)
    audit = audit_curriculum_prerequisites(curricula)
    if not audit["ok"]:
        raise ValidationError(audit["issues"])
    profile = load_json(root / "tests" / "fixtures" / "English_Learning_Profile.example.json")
    validate_profile(profile, curricula, profile_schema)


def _print(obj: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        print(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate, plan and export GPT Live English Teacher learning data."
    )
    parser.add_argument("command", choices=["validate", "audit", "prepare", "plan", "export", "init-profile"], nargs="?", default="validate")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--profile", type=Path, help="path to the learner profile JSON")
    parser.add_argument("--placement", type=Path, help="path to a placement/screening JSON for init-profile")
    parser.add_argument("--out", type=Path, help="output file (init-profile) or output directory (export)")
    parser.add_argument("--date", type=str, help="lesson/export date, YYYY-MM-DD")
    parser.add_argument("--unit", type=str, help="override the unit used by plan")
    parser.add_argument("--no-sync", action="store_true", help="export without recomputing derived fields")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    root: Path = args.root
    curricula = load_curricula(root)
    profile_schema = load_json(root / "schemas" / "learning-profile.schema.json")
    curriculum_schema = load_json(root / "schemas" / "curriculum.schema.json")
    today = date.fromisoformat(args.date) if args.date else date.today()

    try:
        if args.command == "validate":
            validate_curricula(curricula, curriculum_schema)
            audit = audit_curriculum_prerequisites(curricula)
            if not audit["ok"]:
                raise ValidationError(audit["issues"])
            profile = load_json(root / "tests" / "fixtures" / "English_Learning_Profile.example.json")
            validate_profile(profile, curricula, profile_schema)
            print("Curriculum schemas, prerequisite audit and example profile are valid.")
            return 0

        if args.command == "audit":
            validate_curricula(curricula, curriculum_schema)
            _print(audit_curriculum_prerequisites(curricula), args.json)
            return 0

        if args.command == "init-profile":
            if not args.placement or not args.out:
                raise ValidationError(["init-profile requires --placement and --out"])
            placement = load_json(args.placement)
            profile = init_profile(placement, curricula)
            validate_profile(profile, curricula, profile_schema)
            args.out.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            reloaded = load_json(args.out)
            validate_profile(reloaded, curricula, profile_schema)
            _print(
                {
                    "written": str(args.out),
                    "current_level": reloaded["learning_track"]["current_level"],
                    "unit_id": reloaded["current_course_position"]["unit_id"],
                    "unit_status": reloaded["current_course_position"]["unit_status"],
                    "unlocked_unit_ids": reloaded["current_course_position"]["unlocked_unit_ids"],
                    "placement_credited_unit_ids": reloaded["current_course_position"]["placement_credited_unit_ids"],
                },
                args.json,
            )
            return 0

        if not args.profile:
            raise ValidationError([f"{args.command} requires --profile"])
        profile = load_json(args.profile)
        version = str(profile.get("schema_version", ""))
        if version != "3.0":
            profile = migrate_profile(profile)
            _print(f"Migrated profile schema {version} -> 3.0", args.json)
        if args.command == "prepare":
            recompute_knowledge_states(profile, curricula)
            sync_course_position(profile, curricula, advance=False)
        validate_profile(profile, curricula, profile_schema)

        if args.command == "prepare":
            plan = plan_lesson(profile, curricula, today=today)
            _print(
                {
                    "profile_revision": profile["profile_revision"],
                    "position": profile["current_course_position"],
                    "plan": plan,
                },
                args.json,
            )
            return 0

        if args.command == "plan":
            _print(plan_lesson(profile, curricula, today=today, unit_id=args.unit), args.json)
            return 0

        if args.command == "export":
            updated = deepcopy(profile)
            updated["profile_revision"] = int(updated.get("profile_revision", 1)) + 1
            updated["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            destination = export_profile(
                updated,
                args.profile,
                today,
                args.out,
                curricula,
                profile_schema,
                sync=not args.no_sync,
            )
            exported = load_json(destination)
            _print(
                {
                    "written": str(destination),
                    "profile_revision": exported["profile_revision"],
                    "unit_id": exported["current_course_position"]["unit_id"],
                    "unit_status": exported["current_course_position"]["unit_status"],
                    "revalidated": True,
                },
                args.json,
            )
            return 0
    except ValidationError as error:
        print("VALIDATION FAILED")
        for item in error.errors:
            print(f"- {item}")
        return 2

    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
