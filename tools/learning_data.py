#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any, Iterable

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
INDEPENDENT_PHASES = {"independent_expression", "check", "review"}
INDEPENDENT_SUPPORT = {"none", "non_revealing_context"}
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
    if curriculum_ids != {"gpt-live-english-foundations"}:
        errors.append("all levels must share curriculum_id gpt-live-english-foundations")
    if len(curriculum_versions) != 1 or None in curriculum_versions:
        errors.append("all levels must share one non-empty curriculum_version")

    previous_english_end = -1
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

            known_units.add(unit_id)
            known_knowledge.update(local_knowledge)
            known_objectives.update(local_objectives)

    if errors:
        raise ValidationError(errors)


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
        "curriculum_id": "gpt-live-english-foundations" if structured else "legacy-conversation",
        "curriculum_version": "1.0.0",
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


def apply_knowledge_evidence(
    state: dict[str, Any], evidence: dict[str, Any], mastery_requires_distinct_sessions: int = 2
) -> dict[str, Any]:
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
    if evidence_is_placement_credit(evidence):
        session_id = evidence["session_id"]
        if session_id not in updated["independent_pass_sessions"]:
            updated["independent_pass_sessions"].append(session_id)
        updated["state"] = "placement_credited"
        return updated

    if phase in {"demonstration", "course_goal"}:
        if updated["state"] == "not_started":
            updated["state"] = "introduced"
        return updated

    if phase in {"repeat_after_model", "guided_practice"}:
        if result in {"PASS", "PARTIAL", "PRACTICED"} and updated["state"] in {"not_started", "introduced"}:
            updated["state"] = "supported"
        return updated

    if evidence_is_independent(evidence):
        session_id = evidence["session_id"]
        prior_sessions = set(updated["independent_pass_sessions"])
        if session_id not in updated["independent_pass_sessions"]:
            updated["independent_pass_sessions"].append(session_id)
        if phase in {"check", "review"} and session_id not in updated["review_pass_sessions"]:
            updated["review_pass_sessions"].append(session_id)
        previous_state = updated["state"]
        updated["state"] = "mastered" if previous_state == "mastered" else "independent"
        later_check = phase in {"check", "review"} and bool(prior_sessions - {session_id})
        if len(set(updated["independent_pass_sessions"])) >= mastery_requires_distinct_sessions and later_check:
            updated["state"] = "mastered"
    elif phase in INDEPENDENT_PHASES and result == "FAIL":
        if updated["state"] == "mastered":
            updated["state"] = "independent"
        elif updated["state"] in {"independent", "placement_credited"}:
            updated["state"] = "supported"
    return updated


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


def unit_completion(profile: dict[str, Any], unit: dict[str, Any]) -> tuple[bool, list[str]]:
    required = unit["completion_criteria"]["minimum_independent_passes_per_objective"]
    objectives = {objective["objective_id"]: objective for objective in unit["objectives"]}
    missing: list[str] = []
    for objective_id in unit["completion_criteria"]["required_objective_ids"]:
        if len(_objective_passes(profile, unit, objectives[objective_id])) < required:
            missing.append(objective_id)
    return not missing, missing


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


def _curriculum_indexes(curricula: list[dict[str, Any]]) -> tuple[dict, dict, dict, dict]:
    units: dict[str, dict[str, Any]] = {}
    objectives: dict[str, tuple[str, dict[str, Any]]] = {}
    knowledge: dict[str, tuple[str, dict[str, Any]]] = {}
    levels: dict[str, str] = {}
    for document in curricula:
        for unit in document["units"]:
            units[unit["unit_id"]] = unit
            levels[unit["unit_id"]] = document["level_id"]
            for objective in unit["objectives"]:
                objectives[objective["objective_id"]] = (unit["unit_id"], objective)
            for entry in unit["knowledge"]:
                knowledge[entry["knowledge_id"]] = (unit["unit_id"], entry)
    return units, objectives, knowledge, levels


def _has_later_review(state_evidence: list[dict[str, Any]], required_sessions: int) -> bool:
    prior_sessions: set[str] = set()
    for evidence in state_evidence:
        if not evidence_is_independent(evidence):
            continue
        session_id = evidence["session_id"]
        if evidence.get("phase") in {"check", "review"} and prior_sessions - {session_id}:
            if len(prior_sessions | {session_id}) >= required_sessions:
                return True
        prior_sessions.add(session_id)
    return False


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

    session_log = profile.get("session_log", [])
    if not isinstance(session_log, list):
        errors.append("session_log must be a list")
        session_log = []
    session_ids: set[str] = set()
    session_order: dict[str, int] = {}
    previous_session_date: date | None = None
    for index, session in enumerate(session_log):
        session_id = session.get("session_id")
        if not session_id or session_id in session_ids:
            errors.append(f"session_log[{index}] has a missing or duplicate session_id")
        else:
            session_ids.add(session_id)
            session_order[session_id] = index
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
        units, objectives, curriculum_knowledge, unit_levels = _curriculum_indexes(curricula)
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

        if curricula and knowledge_id in curriculum_knowledge:
            owner_unit, _ = curriculum_knowledge[knowledge_id]
            if state.get("unit_id") != owner_unit:
                errors.append(f"{knowledge_id}: knowledge state unit must be {owner_unit}")
            if state.get("state") == "mastered":
                required_sessions = units[owner_unit]["completion_criteria"]["mastery_requires_distinct_sessions"]
                if len(actual_independent_sessions) < required_sessions or not _has_later_review(
                    state_evidence, required_sessions
                ):
                    errors.append(f"{knowledge_id}: mastery needs the configured sessions and a later check or review")
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
            versions = {document["curriculum_version"] for document in curricula}
            if track.get("curriculum_id") != "gpt-live-english-foundations" or track.get("curriculum_version") not in versions:
                errors.append("learning_track does not match the loaded curriculum")
            if track.get("current_level") not in CURRICULUM_LEVELS:
                errors.append("structured curriculum level must be PRE_A1 through B1")
        elif mode == "legacy_conversation" and position.get("unit_status") != "not_applicable":
            errors.append("legacy_conversation course position must be not_applicable")
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

        final_units = {document["units"][-1]["unit_id"] for document in curricula}
        for credited_unit in placement_credited & units.keys():
            if credited_unit not in final_units:
                errors.append(f"{credited_unit}: only a level-exit unit may receive placement credit")
            if not any(
                evidence.get("unit_id") == credited_unit and evidence_is_placement_credit(evidence)
                for evidence in evidence_entries
            ):
                errors.append(f"{credited_unit}: placement credit needs an independent placement check")

        for completed_unit in completed & units.keys():
            complete, missing_objectives = unit_completion(profile, units[completed_unit])
            if not complete:
                errors.append(f"{completed_unit}: completed without evidence for {missing_objectives}")

        qualified_knowledge = {
            knowledge_id
            for knowledge_id, state in knowledge_state_by_id.items()
            if state.get("state") in {"independent", "mastered", "placement_credited"}
        }
        satisfied_units = completed | placement_credited
        for unlocked_unit in unlocked & units.keys():
            unit = units[unlocked_unit]
            missing_units = set(unit["prerequisite_units"]) - satisfied_units
            missing_knowledge = set(unit["prerequisite_knowledge_ids"]) - qualified_knowledge
            if missing_units:
                errors.append(f"{unlocked_unit}: unlocked before prerequisite units {sorted(missing_units)}")
            if missing_knowledge:
                errors.append(f"{unlocked_unit}: unlocked before prerequisite knowledge {sorted(missing_knowledge)}")

    if errors:
        raise ValidationError(errors)


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
) -> Path:
    curricula = curricula or load_curricula(ROOT)
    profile_schema = profile_schema or load_json(ROOT / "schemas" / "learning-profile.schema.json")
    validate_profile(profile, curricula, profile_schema)
    destination = next_export_path(source_path, export_date, output_dir)
    destination.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    exported = load_json(destination)
    validate_profile(exported, curricula, profile_schema)
    if exported != profile:
        raise ValidationError(["exported profile does not match the validated profile"])
    return destination


def repository_check(root: Path) -> None:
    curricula = load_curricula(root)
    curriculum_schema = load_json(root / "schemas" / "curriculum.schema.json")
    profile_schema = load_json(root / "schemas" / "learning-profile.schema.json")
    validate_curricula(curricula, curriculum_schema)
    profile = load_json(root / "tests" / "fixtures" / "English_Learning_Profile.example.json")
    validate_profile(profile, curricula, profile_schema)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate GPT Live English Coach learning data.")
    parser.add_argument("command", choices=["validate"], nargs="?", default="validate")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    repository_check(args.root)
    print("Curriculum schemas and example profile are valid.")


if __name__ == "__main__":
    main()
