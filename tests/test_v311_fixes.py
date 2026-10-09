#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""v3.1.1 regressions: evidence honesty, per-skill placement, segment targeting.

Each test here reproduces a concrete defect that existed in v3.1.0 and fails
against that version.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.support import exit_check_records, placement_input  # noqa: E402
from tools.learning_data import (  # noqa: E402
    CURRICULUM_LEVELS,
    ValidationError,
    evidence_is_placement_credit,
    evidence_is_strict_unseen_listening,
    evidence_is_unseen_listening,
    init_profile,
    level_placement_evidence_gaps,
    level_placement_requirements,
    load_json,
    normalize_profile,
    plan_lesson,
    screening_verification_status,
    select_latest_profile,
    unit_completion,
    validate_profile,
)

PROFILE_SCHEMA = load_json(ROOT / "schemas" / "learning-profile.schema.json")
PLACEMENT_FIXTURE = ROOT / "tests" / "fixtures" / "placement.zero-beginner.example.json"
DAY = "2026-10-08"


def curricula() -> list[dict]:
    return [load_json(ROOT / "curriculum" / f"{level}.json") for level in CURRICULUM_LEVELS]


def placement_with(evidence: list[dict], session_id: str = "placement_0001") -> dict:
    return {
        "timezone": "Asia/Shanghai",
        "target_english_variety": "General_American",
        "assessment_confidence": "low",
        "screening_session": {"session_id": session_id, "date": DAY},
        "screening_evidence": evidence,
    }


def bare_record(**overrides: object) -> dict:
    """A screening record with the minimum fields, i.e. no stated conditions."""
    record = {
        "evidence_id": "evidence_placement_bare",
        "unit_id": "PRE_A1-U08",
        "objective_id": None,
        "phase": "placement",
        "knowledge_ids": ["PRE_A1-K004"],
        "modality": "voice",
        "support_level": "none",
        "result": "PASS",
        "learner_response_summary": "Answered a listening task.",
    }
    record.update(overrides)
    return record


class MissingFieldsAreNeverOptimisticTests(unittest.TestCase):
    """P0: absent screening fields must not become favourable assumptions."""

    def test_missing_fields_do_not_credit_a_level(self) -> None:
        profile = init_profile(placement_with([bare_record()]), curricula())
        validate_profile(profile, curricula(), PROFILE_SCHEMA)
        record = profile["practice_evidence"][0]
        self.assertEqual(record["prompt_novelty"], "unknown")
        self.assertIsNone(record["text_shown_before_response"])
        self.assertEqual(record["listening_check_grade"], "unknown")
        self.assertEqual(record["screening_verification"], "unverified_conditions")
        self.assertFalse(evidence_is_placement_credit(record))
        self.assertEqual(profile["current_course_position"]["placement_credited_unit_ids"], [])
        self.assertEqual(profile["learning_track"]["current_level"], "PRE_A1")
        self.assertEqual(profile["scientific_assessment"]["overall_cefr"], "PRE_A1")

    def test_missing_fields_never_inflate_the_cefr_level(self) -> None:
        """A record that names every knowledge item still cannot promote the learner."""
        requirements = level_placement_requirements(curricula())["PRE_A1"]
        profile = init_profile(
            placement_with([bare_record(knowledge_ids=requirements, modality="mixed")]), curricula()
        )
        self.assertEqual(profile["current_course_position"]["placement_credited_unit_ids"], [])
        self.assertEqual(profile["learning_track"]["current_level"], "PRE_A1")

    def test_explicit_strict_conditions_are_accepted(self) -> None:
        record = bare_record(
            skill="listening",
            prompt_novelty="unseen",
            text_shown_before_response=False,
            listening_check_grade="strict_unseen",
        )
        self.assertTrue(evidence_is_strict_unseen_listening(record))
        self.assertTrue(evidence_is_placement_credit(record))
        self.assertEqual(screening_verification_status(record), "strict_independent")

    def test_unknown_conditions_are_never_placement_evidence(self) -> None:
        record = bare_record(
            skill="listening",
            prompt_novelty="unknown",
            text_shown_before_response=None,
            listening_check_grade="unknown",
        )
        self.assertFalse(evidence_is_placement_credit(record))
        self.assertEqual(screening_verification_status(record), "unverified_conditions")

    def test_legitimate_existing_screening_data_is_not_misjudged(self) -> None:
        """The shipped zero-beginner example must still build a valid profile."""
        profile = init_profile(load_json(PLACEMENT_FIXTURE), curricula())
        validate_profile(profile, curricula(), PROFILE_SCHEMA)
        self.assertEqual(profile["current_course_position"]["placement_credited_unit_ids"], [])
        self.assertEqual(profile["current_course_position"]["unit_id"], "PRE_A1-U01")
        # A failed strict attempt and a supported practice attempt are both honest.
        self.assertEqual(
            [record["screening_verification"] for record in profile["practice_evidence"]],
            ["failed", "failed"],
        )
        self.assertEqual(profile["practice_evidence"][0]["listening_check_grade"], "strict_unseen")


class StrictListeningGradeTests(unittest.TestCase):
    """P0: a strict unseen check must say so explicitly."""

    def record(self, **overrides: object) -> dict:
        record = {
            "evidence_id": "e1",
            "session_id": "s1",
            "date": DAY,
            "phase": "check",
            "objective_id": "PRE_A1-O001",
            "knowledge_ids": ["PRE_A1-K004"],
            "modality": "voice",
            "support_level": "none",
            "result": "PASS",
            "prompt_novelty": "unseen",
            "text_shown_before_response": False,
        }
        record.update(overrides)
        return record

    def test_missing_grade_is_not_strict(self) -> None:
        self.assertFalse(evidence_is_unseen_listening(self.record()))

    def test_explicit_non_strict_grades_are_not_strict(self) -> None:
        for grade in ("unknown", "text_supported_practice", "not_applicable"):
            with self.subTest(grade=grade):
                self.assertFalse(evidence_is_unseen_listening(self.record(listening_check_grade=grade)))

    def test_every_condition_is_required(self) -> None:
        good = self.record(listening_check_grade="strict_unseen")
        self.assertTrue(evidence_is_unseen_listening(good))
        for field, value in (
            ("prompt_novelty", "rehearsed"),
            ("text_shown_before_response", True),
            ("text_shown_before_response", None),
            ("modality", "text"),
            ("support_level", "sentence_starter"),
            ("result", "PARTIAL"),
        ):
            with self.subTest(field=field, value=value):
                self.assertFalse(evidence_is_unseen_listening({**good, field: value}))

    def test_validation_rejects_an_unlabelled_unseen_listening_pass(self) -> None:
        profile = load_json(ROOT / "tests" / "fixtures" / "English_Learning_Profile.example.json")
        for record in profile["practice_evidence"]:
            if record["evidence_id"] == "evidence_0001":
                record.pop("listening_check_grade")
        with self.assertRaises(ValidationError) as context:
            validate_profile(profile, curricula(), PROFILE_SCHEMA)
        self.assertTrue(
            any("must state listening_check_grade explicitly" in error for error in context.exception.errors)
        )

    def test_normalization_downgrades_instead_of_upgrading(self) -> None:
        """A legacy PASS without a grade becomes practice, never a strict pass."""
        profile = load_json(ROOT / "tests" / "fixtures" / "English_Learning_Profile.example.json")
        for record in profile["practice_evidence"]:
            if record["evidence_id"] == "evidence_0001":
                record.pop("listening_check_grade")
        normalize_profile(profile, curricula())
        record = next(e for e in profile["practice_evidence"] if e["evidence_id"] == "evidence_0001")
        self.assertEqual(record["listening_check_grade"], "unknown")
        self.assertEqual(record["phase"], "guided_practice")
        # The legitimate strict record elsewhere in the fixture is left alone.
        strict = next(e for e in profile["practice_evidence"] if e["evidence_id"] == "evidence_0007")
        self.assertEqual(strict["listening_check_grade"], "strict_unseen")
        validate_profile(profile, curricula(), PROFILE_SCHEMA)
        # The learner is placed back on a unit that is still genuinely unlocked.
        self.assertEqual(profile["current_course_position"]["unit_id"], "PRE_A1-U01")
        self.assertEqual(profile["current_course_position"]["completed_unit_ids"], [])
        # The unverified pass no longer completes PRE_A1-U01: its knowledge item
        # falls back to `supported`, so the unit keeps a documented gap.
        complete, missing_objectives, missing_knowledge = unit_completion(
            profile, next(u for u in curricula()[0]["units"] if u["unit_id"] == "PRE_A1-U01")
        )
        self.assertFalse(complete)
        self.assertEqual(missing_objectives, [])
        self.assertEqual(missing_knowledge, ["PRE_A1-K004"])
        self.assertTrue(
            any(
                entry.get("downgraded_evidence_ids") == ["evidence_0001"]
                for entry in profile["migration_history"]
            )
        )


class PerSkillPlacementTests(unittest.TestCase):
    """P0: listening and speaking must each be proven by its own real task."""

    def credit(self, evidence: list[dict]) -> list[str]:
        profile = init_profile(placement_with(evidence), curricula())
        return profile["current_course_position"]["placement_credited_unit_ids"]

    def test_one_comprehensive_record_cannot_prove_both_skills(self) -> None:
        requirements = level_placement_requirements(curricula())["PRE_A1"]
        record = bare_record(
            knowledge_ids=requirements,
            modality="mixed",
            prompt_novelty="unseen",
            text_shown_before_response=False,
            listening_check_grade="strict_unseen",
        )
        self.assertEqual(self.credit([record]), [])

    def test_listening_only_cannot_skip(self) -> None:
        listening, speaking = exit_check_records(curricula(), "PRE_A1")
        self.assertEqual(self.credit([listening]), [])

    def test_speaking_only_cannot_skip(self) -> None:
        listening, speaking = exit_check_records(curricula(), "PRE_A1")
        self.assertEqual(self.credit([speaking]), [])

    def test_listening_pass_with_speaking_failure_cannot_skip(self) -> None:
        listening, speaking = exit_check_records(curricula(), "PRE_A1")
        self.assertEqual(self.credit([listening, {**speaking, "result": "FAIL"}]), [])

    def test_speaking_pass_with_listening_failure_cannot_skip(self) -> None:
        listening, speaking = exit_check_records(curricula(), "PRE_A1")
        self.assertEqual(self.credit([{**listening, "result": "FAIL"}, speaking]), [])

    def test_partial_coverage_of_either_skill_cannot_skip(self) -> None:
        listening, speaking = exit_check_records(curricula(), "PRE_A1")
        trimmed = {**speaking, "knowledge_ids": speaking["knowledge_ids"][:2]}
        self.assertEqual(self.credit([listening, trimmed]), [])

    def test_both_skills_with_full_coverage_allow_exactly_one_level(self) -> None:
        records = exit_check_records(curricula(), "PRE_A1")
        profile = init_profile(placement_with(records), curricula())
        validate_profile(profile, curricula(), PROFILE_SCHEMA)
        self.assertEqual(profile["current_course_position"]["placement_credited_unit_ids"], ["PRE_A1-U08"])
        self.assertEqual(profile["current_course_position"]["unit_id"], "A1-U01")
        self.assertFalse(level_placement_evidence_gaps(profile, curricula()))

    def test_every_level_boundary_can_be_skipped_with_two_skill_evidence(self) -> None:
        for level, expected_level in (("PRE_A1", "A1"), ("A1", "A2"), ("A2", "B1")):
            with self.subTest(level=level):
                profile = init_profile(placement_with(exit_check_records(curricula(), level)), curricula())
                validate_profile(profile, curricula(), PROFILE_SCHEMA)
                self.assertEqual(profile["learning_track"]["current_level"], expected_level)
                self.assertEqual(profile["current_course_position"]["unit_id"], f"{expected_level}-U01")

    def test_dimension_is_never_inferred_from_knowledge_classification(self) -> None:
        """A record without `skill` cannot credit anything, even with perfect ids."""
        listening, _speaking = exit_check_records(curricula(), "PRE_A1")
        without_skill = {key: value for key, value in listening.items() if key != "skill"}
        self.assertFalse(evidence_is_placement_credit(without_skill))
        self.assertEqual(self.credit([without_skill]), [])

    def test_legacy_placement_credit_is_dropped_not_upgraded(self) -> None:
        """A v3.1.0 profile with a single mixed record loses the credit on sync."""
        requirements = level_placement_requirements(curricula())["PRE_A1"]
        profile = init_profile(
            placement_with(
                [
                    bare_record(
                        knowledge_ids=requirements,
                        modality="mixed",
                        prompt_novelty="unseen",
                        text_shown_before_response=False,
                        listening_check_grade="strict_unseen",
                    )
                ]
            ),
            curricula(),
        )
        # Emulate the old, looser credit.
        profile["current_course_position"]["placement_credited_unit_ids"] = ["PRE_A1-U08"]
        profile["learning_track"]["placement_basis"] = "independent_level_check"
        with self.assertRaises(ValidationError):
            validate_profile(profile, curricula(), PROFILE_SCHEMA)

        removed = normalize_profile(profile, curricula(), advance=False)
        self.assertIsNotNone(removed)
        self.assertEqual(profile["current_course_position"]["placement_credited_unit_ids"], [])
        self.assertEqual(profile["learning_track"]["placement_basis"], "initial_screening")
        validate_profile(profile, curricula(), PROFILE_SCHEMA)
        self.assertTrue(
            any(entry.get("removed_placement_credit") for entry in profile["migration_history"])
        )


class SegmentTargetingTests(unittest.TestCase):
    """P1: taught-but-unmastered knowledge is repaired where it was taught."""

    def build_letters_profile(self) -> dict:
        """PRE_A1-U03 with all four segments taught, but K009 listening unmastered."""
        learner = LearnerStub()
        learner.complete_unit("PRE_A1-U01")
        learner.complete_unit("PRE_A1-U02")
        learner.record("PRE_A1-U03", "PRE_A1-O005", ["PRE_A1-K010", "PRE_A1-K011"], skill="speaking")
        learner.record("PRE_A1-U03", "PRE_A1-O005", ["PRE_A1-K009"], skill="speaking")
        learner.record("PRE_A1-U03", "PRE_A1-O006", ["PRE_A1-K012"], skill="listening", grade="strict_unseen")
        learner.record(
            "PRE_A1-U03", "PRE_A1-O006", ["PRE_A1-K009"], skill="listening", grade="strict_unseen", result="FAIL"
        )
        learner.profile["current_course_position"]["completed_lesson_segment_ids"] = [
            "PRE_A1-U03-S1",
            "PRE_A1-U03-S2",
            "PRE_A1-U03-S3",
            "PRE_A1-U03-S4",
        ]
        learner.sync()
        return learner.profile

    def test_remediation_targets_the_segment_that_taught_the_gap(self) -> None:
        profile = self.build_letters_profile()
        plan = plan_lesson(profile, curricula(), today=date(2026, 10, 9))
        self.assertEqual(plan["unit_id"], "PRE_A1-U03")
        self.assertFalse(plan["unit_complete"])
        self.assertEqual(plan["missing_knowledge_ids"], ["PRE_A1-K009"])
        self.assertEqual(plan["remedial_knowledge_ids"], ["PRE_A1-K009"])
        self.assertEqual(plan["segment"]["segment_id"], "PRE_A1-U03-S1")
        self.assertEqual(plan["target_segment_ids"], ["PRE_A1-U03-S1"])
        self.assertEqual(plan["next_action"], "remediate")
        self.assertEqual(plan["new_knowledge_ids"], [])
        entry = next(e for e in plan["remediation_plan"] if e["knowledge_id"] == "PRE_A1-K009")
        self.assertEqual(entry["segment_id"], "PRE_A1-U03-S1")
        self.assertEqual(entry["skill_states"], {"listening": "not_started", "speaking": "independent"})

    def test_segment_markers_never_raise_knowledge_or_complete_a_unit(self) -> None:
        profile = self.build_letters_profile()
        states = {entry["knowledge_id"]: entry for entry in profile["knowledge_state"]}
        # K009 was produced but not understood, so the aggregate stays unqualified.
        self.assertEqual(states["PRE_A1-K009"]["state"], "not_started")
        self.assertEqual(states["PRE_A1-K009"]["skill_states"]["speaking"], "independent")
        self.assertEqual(states["PRE_A1-K009"]["skill_states"]["listening"], "not_started")
        self.assertNotIn("PRE_A1-U03", profile["current_course_position"]["completed_unit_ids"])
        self.assertNotIn("PRE_A1-U04", profile["current_course_position"]["unlocked_unit_ids"])

    def test_mastered_content_is_preserved_and_the_unit_is_not_repeated(self) -> None:
        profile = self.build_letters_profile()
        before = {entry["knowledge_id"]: entry["state"] for entry in profile["knowledge_state"]}
        plan = plan_lesson(profile, curricula(), today=date(2026, 10, 9))
        self.assertEqual(plan["segment_total"], 4)
        # Only the gap is remediated; the already independent items are untouched.
        self.assertEqual([entry["knowledge_id"] for entry in plan["remediation_plan"]], ["PRE_A1-K009"])
        self.assertEqual(plan["pending_knowledge_ids"], [])
        after = {entry["knowledge_id"]: entry["state"] for entry in profile["knowledge_state"]}
        for knowledge_id in ("PRE_A1-K010", "PRE_A1-K011", "PRE_A1-K012"):
            self.assertEqual(after[knowledge_id], before[knowledge_id])

    def test_remediation_completes_the_unit_and_unlocks_the_next_one(self) -> None:
        profile = self.build_letters_profile()
        learner = LearnerStub(profile)
        learner.record(
            "PRE_A1-U03", "PRE_A1-O006", ["PRE_A1-K009"], skill="listening", grade="strict_unseen"
        )
        learner.sync()
        validate_profile(learner.profile, curricula(), PROFILE_SCHEMA)
        self.assertIn("PRE_A1-U03", learner.profile["current_course_position"]["completed_unit_ids"])
        self.assertIn("PRE_A1-U04", learner.profile["current_course_position"]["unlocked_unit_ids"])
        plan = plan_lesson(learner.profile, curricula(), today=date(2026, 10, 10))
        self.assertEqual(plan["remedial_knowledge_ids"], [])
        self.assertNotEqual(plan["next_action"], "remediate")


class LearnerStub:
    """Minimal evidence recorder used by the segment-targeting tests."""

    def __init__(self, profile: dict | None = None) -> None:
        self.curricula = curricula()
        self.profile = profile or init_profile(load_json(PLACEMENT_FIXTURE), self.curricula)
        self.counter = len(self.profile.get("practice_evidence", []))
        if not any(session["session_id"] == "session_0001" for session in self.profile["session_log"]):
            self.session("session_0001", DAY)

    def session(self, session_id: str, day: str) -> None:
        self.profile["session_log"].append(
            {"session_id": session_id, "date": day, "evidence_ids": [], "review_outcomes": [], "new_item_ids": []}
        )

    def record(
        self,
        unit_id: str,
        objective_id: str,
        knowledge_ids: list[str],
        *,
        skill: str,
        grade: str = "not_applicable",
        result: str = "PASS",
        session_id: str = "session_0001",
        day: str = DAY,
    ) -> str:
        self.counter += 1
        evidence_id = f"evidence_v311_{self.counter:03d}"
        self.profile["practice_evidence"].append(
            {
                "evidence_id": evidence_id,
                "session_id": session_id,
                "date": day,
                "unit_id": unit_id,
                "objective_id": objective_id,
                "knowledge_ids": knowledge_ids,
                "phase": "check",
                "modality": "voice",
                "support_level": "none",
                "result": result,
                "learner_response_summary": "v3.1.1 regression scenario.",
                "pronunciation_evidence_basis": "not_applicable",
                "prompt_novelty": "unseen",
                "text_shown_before_response": False,
                "skill": skill,
                "listening_check_grade": grade,
            }
        )
        for session in self.profile["session_log"]:
            if session["session_id"] == session_id:
                session["evidence_ids"].append(evidence_id)
                break
        return evidence_id

    def complete_unit(self, unit_id: str) -> None:
        if unit_id == "PRE_A1-U01":
            self.record("PRE_A1-U01", "PRE_A1-O001", ["PRE_A1-K001", "PRE_A1-K004"], skill="listening", grade="strict_unseen")
            self.record("PRE_A1-U01", "PRE_A1-O002", ["PRE_A1-K002", "PRE_A1-K003"], skill="speaking")
        elif unit_id == "PRE_A1-U02":
            self.record("PRE_A1-U02", "PRE_A1-O003", ["PRE_A1-K005", "PRE_A1-K006", "PRE_A1-K008"], skill="speaking")
            self.record("PRE_A1-U02", "PRE_A1-O004", ["PRE_A1-K007"], skill="listening", grade="strict_unseen")
        self.sync()

    def sync(self) -> None:
        normalize_profile(self.profile, self.curricula, advance=True)


class LatestProfileSelectionTests(unittest.TestCase):
    """P1: the newest profile is chosen by metadata, never by filename."""

    def test_selection_uses_revision_and_timestamp(self) -> None:
        base = load_json(ROOT / "tests" / "fixtures" / "English_Learning_Profile.example.json")
        with TemporaryDirectory() as directory:
            output = Path(directory)
            # Deliberately misleading filenames.
            newest = deepcopy(base)
            newest["profile_revision"] = 7
            newest["updated_at"] = "2026-10-09T10:00:00+08:00"
            (output / "English_Learning_Profile_updated_2026-10-08.json").write_text(
                json.dumps(newest, ensure_ascii=False), encoding="utf-8"
            )
            older = deepcopy(base)
            older["profile_revision"] = 2
            older["updated_at"] = "2026-10-08T10:00:00+08:00"
            (output / "zzz_latest.json").write_text(json.dumps(older, ensure_ascii=False), encoding="utf-8")
            (output / "notes.json").write_text('{"hello": "world"}', encoding="utf-8")

            chosen, ranking = select_latest_profile(output)
            self.assertEqual(chosen.name, "English_Learning_Profile_updated_2026-10-08.json")
            self.assertEqual(ranking[0]["profile_revision"], 7)
            self.assertFalse(next(entry for entry in ranking if entry["filename"] == "notes.json")["is_profile"])

    def test_selection_fails_clearly_when_no_profile_exists(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "notes.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ValidationError) as context:
                select_latest_profile(output)
            self.assertTrue(any("no learner profile found" in error for error in context.exception.errors))

    def test_export_then_reload_then_export_again(self) -> None:
        from tools.learning_data import export_profile, next_export_path

        profile = init_profile(placement_input(curricula(), ["PRE_A1"]), curricula())
        with TemporaryDirectory() as directory:
            output = Path(directory)
            source = output / "English_Learning_Profile.json"
            source.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
            first = export_profile(profile, source, date(2026, 10, 8), output)
            reloaded = load_json(first)
            validate_profile(reloaded, curricula(), PROFILE_SCHEMA)
            second = export_profile(reloaded, first, date(2026, 10, 9), output)
            self.assertEqual(second.name, "English_Learning_Profile_updated_2026-10-09.json")
            self.assertEqual(load_json(source)["profile_revision"], profile["profile_revision"])
            self.assertNotEqual(next_export_path(first, date(2026, 10, 8), output), first)


class DocumentConsistencyTests(unittest.TestCase):
    """P1: the instructions, the project instructions and the README must agree."""

    def read(self, name: str) -> str:
        return (ROOT / name).read_text(encoding="utf-8")

    def test_trigger_phrases_are_identical_everywhere(self) -> None:
        triggers = [
            "Start my first class.",
            "Prepare for class",
            "Class is over, export data.",
        ]
        for name in ("PROJECT_INSTRUCTIONS.md", "English_Learning_Instructions.md", "README.md", "README.zh-CN.md"):
            text = self.read(name)
            for trigger in triggers:
                with self.subTest(document=name, trigger=trigger):
                    self.assertIn(trigger, text)
        self.assertIn("Test finished", self.read("PROJECT_INSTRUCTIONS.md"))
        self.assertIn("Test finished", self.read("English_Learning_Instructions.md"))

    def test_pace_values_are_consistent(self) -> None:
        from tools.learning_data import LESSON_PACE_VALUES

        schema = json.loads(self.read("schemas/learning-profile.schema.json"))
        self.assertEqual(
            sorted(schema["properties"]["learner_preferences"]["properties"]["pace"]["enum"]),
            sorted(LESSON_PACE_VALUES),
        )
        for name in ("English_Learning_Instructions.md", "README.zh-CN.md"):
            text = self.read(name)
            for value in LESSON_PACE_VALUES:
                with self.subTest(document=name, value=value):
                    self.assertIn(value, text)

    def test_project_instructions_stay_short_and_delegate_details(self) -> None:
        text = self.read("PROJECT_INSTRUCTIONS.md")
        self.assertLess(len(text.splitlines()), 140)
        self.assertIn("English_Learning_Instructions.md", text)
        self.assertIn("cannot", text)

    def test_reading_order_is_stated_in_both_layers(self) -> None:
        for name in ("PROJECT_INSTRUCTIONS.md", "English_Learning_Instructions.md"):
            text = self.read(name)
            with self.subTest(document=name):
                self.assertIn("PROJECT_INSTRUCTIONS.md", text)
                self.assertIn("curriculum/", text)
                self.assertIn("learning-profile.schema.json", text)

    def test_python_tool_is_documented_as_not_auto_connected(self) -> None:
        patterns = ("not wired", "not automatically connected", "不会自动", "不代表它已经自动")
        for name in ("English_Learning_Instructions.md", "README.md", "README.zh-CN.md"):
            text = self.read(name).replace("*", "").replace("`", "")
            with self.subTest(document=name):
                self.assertTrue(
                    any(pattern in text for pattern in patterns),
                    f"{name} must state that the Python tools are not automatically connected to GPT Live",
                )


if __name__ == "__main__":
    unittest.main()
