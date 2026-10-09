#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""End-to-end regression tests for the 15 acceptance scenarios.

These tests exercise the deterministic data layer exactly the way ChatGPT Text
Mode uses it: record evidence, sync the profile, validate, plan, export, reload.
They do not and cannot prove that GPT Live itself behaves correctly; that part is
covered by the manual acceptance script in `docs/manual_acceptance.zh-CN.md`.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from tools.learning_data import (
    CURRICULUM_LEVELS,
    ValidationError,
    audit_curriculum_prerequisites,
    export_profile,
    init_profile,
    level_placement_requirements,
    load_json,
    migrate_profile,
    next_export_path,
    normalize_profile,
    plan_lesson,
    recompute_knowledge_states,
    segment_is_done,
    select_latest_profile,
    sync_course_position,
    sync_profile,
    unit_completion,
    unit_lesson_segments,
    unlock_blockers,
    update_repertoire_item,
    validate_profile,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.support import exit_check_records, placement_input  # noqa: E402

PROFILE_SCHEMA = load_json(ROOT / "schemas" / "learning-profile.schema.json")
PLACEMENT_FIXTURE = ROOT / "tests" / "fixtures" / "placement.zero-beginner.example.json"
DAY_1 = date(2026, 10, 8)
DAY_2 = date(2026, 10, 9)
DAY_3 = date(2026, 10, 10)


def curricula() -> list[dict]:
    return [load_json(ROOT / "curriculum" / f"{level}.json") for level in CURRICULUM_LEVELS]


class Learner:
    """Small helper that records evidence the way the coach would."""

    def __init__(self, profile: dict) -> None:
        self.profile = profile
        self.curricula = curricula()
        self.counter = 0

    @classmethod
    def zero_beginner(cls) -> "Learner":
        return cls(init_profile(load_json(PLACEMENT_FIXTURE), curricula(), now=datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)))

    def session(self, session_id: str, day: date) -> None:
        self.profile["session_log"].append(
            {
                "session_id": session_id,
                "date": day.isoformat(),
                "evidence_ids": [],
                "review_outcomes": [],
                "new_item_ids": [],
            }
        )

    def record(
        self,
        session_id: str,
        day: date,
        unit_id: str,
        objective_id: str | None,
        knowledge_ids: list[str],
        *,
        phase: str = "check",
        support: str = "none",
        result: str = "PASS",
        modality: str = "voice",
        novelty: str = "unseen",
        text_shown: bool | None = False,
        skill: str | None = None,
        grade: str | None = None,
    ) -> str:
        self.counter += 1
        evidence_id = f"evidence_w{self.counter:04d}"
        record: dict = {
            "evidence_id": evidence_id,
            "session_id": session_id,
            "date": day.isoformat(),
            "unit_id": unit_id,
            "objective_id": objective_id,
            "knowledge_ids": knowledge_ids,
            "phase": phase,
            "modality": modality,
            "support_level": support,
            "result": result,
            "learner_response_summary": "Recorded during an automated regression scenario.",
            "pronunciation_evidence_basis": "direct_live_audio" if modality in {"voice", "mixed"} else "not_applicable",
            "prompt_novelty": novelty,
            "text_shown_before_response": text_shown,
        }
        if skill:
            record["skill"] = skill
        if grade:
            record["listening_check_grade"] = grade
        self.profile["practice_evidence"].append(record)
        for session in self.profile["session_log"]:
            if session["session_id"] == session_id:
                session["evidence_ids"].append(evidence_id)
                break
        return evidence_id

    def sync(self, advance: bool = True) -> None:
        sync_profile(self.profile, self.curricula, advance=advance)

    def validate(self) -> None:
        validate_profile(self.profile, self.curricula, PROFILE_SCHEMA)

    def unit(self, unit_id: str) -> dict:
        for document in self.curricula:
            for unit in document["units"]:
                if unit["unit_id"] == unit_id:
                    return unit
        raise KeyError(unit_id)

    def plan(self, day: date, unit_id: str | None = None) -> dict:
        return plan_lesson(self.profile, self.curricula, today=day, unit_id=unit_id)

    def finish_unit_one(self, session_id: str = "session_0001", day: date = DAY_1) -> None:
        """Independently demonstrate everything PRE_A1-U01 requires."""
        self.session(session_id, day)
        self.record(session_id, day, "PRE_A1-U01", "PRE_A1-O001", ["PRE_A1-K001", "PRE_A1-K004"], grade="strict_unseen")
        self.record(session_id, day, "PRE_A1-U01", "PRE_A1-O002", ["PRE_A1-K002", "PRE_A1-K003"], skill="speaking")
        self.sync()

    def finish_unit_two(self, session_id: str = "session_0002", day: date = DAY_2) -> None:
        """Independently demonstrate everything PRE_A1-U02 requires."""
        self.session(session_id, day)
        self.record(
            session_id,
            day,
            "PRE_A1-U02",
            "PRE_A1-O003",
            ["PRE_A1-K005", "PRE_A1-K006", "PRE_A1-K008"],
            skill="speaking",
        )
        self.record(
            session_id,
            day,
            "PRE_A1-U02",
            "PRE_A1-O004",
            ["PRE_A1-K007"],
            skill="listening",
            grade="strict_unseen",
        )
        self.sync()

    def reach_unit_three(self) -> None:
        self.finish_unit_one()
        self.finish_unit_two()
        self.validate()
        self.assert_unit_unlocked("PRE_A1-U03")

    def assert_unit_unlocked(self, unit_id: str) -> None:
        assert unit_id in self.profile["current_course_position"]["unlocked_unit_ids"], unit_id


class ScenarioTests(unittest.TestCase):
    def test_scenario_01_zero_beginner_first_class(self) -> None:
        learner = Learner.zero_beginner()
        learner.validate()
        position = learner.profile["current_course_position"]
        self.assertEqual(position["unlocked_unit_ids"], ["PRE_A1-U01"])
        self.assertEqual(position["unit_id"], "PRE_A1-U01")
        self.assertEqual(position["unit_status"], "not_started")
        self.assertEqual(learner.profile["scientific_assessment"]["assessment_status"], "provisional")
        self.assertEqual(learner.profile["knowledge_state"][0]["state"], "not_started")

        plan = learner.plan(DAY_1)
        self.assertEqual(plan["next_action"], "continue")
        self.assertEqual(plan["segment"]["segment_id"], "PRE_A1-U01-S1")
        self.assertLessEqual(len(plan["new_knowledge_ids"]), 2)
        self.assertEqual(plan["remediation_plan"], [])

    def test_scenario_02_unit_one_completes_and_unit_two_unlocks(self) -> None:
        learner = Learner.zero_beginner()
        learner.finish_unit_one()
        learner.validate()
        position = learner.profile["current_course_position"]
        self.assertEqual(position["completed_unit_ids"], ["PRE_A1-U01"])
        self.assertIn("PRE_A1-U02", position["unlocked_unit_ids"])
        self.assertEqual(position["unit_id"], "PRE_A1-U02")

    def test_scenario_03_partial_unit_one_reports_gap_without_deadlock(self) -> None:
        """Only one repair phrase is independent: no false completion, no dead end."""
        learner = Learner.zero_beginner()
        learner.session("session_0001", DAY_1)
        learner.record("session_0001", DAY_1, "PRE_A1-U01", "PRE_A1-O001", ["PRE_A1-K001", "PRE_A1-K004"], grade="strict_unseen")
        learner.record("session_0001", DAY_1, "PRE_A1-U01", "PRE_A1-O002", ["PRE_A1-K002"], skill="speaking")
        learner.sync()
        learner.validate()

        complete, missing_objectives, missing_knowledge = unit_completion(learner.profile, learner.unit("PRE_A1-U01"))
        self.assertFalse(complete)
        self.assertEqual(missing_objectives, [])
        self.assertEqual(missing_knowledge, ["PRE_A1-K003"])

        position = learner.profile["current_course_position"]
        self.assertEqual(position["completed_unit_ids"], [])
        self.assertNotIn("PRE_A1-U02", position["unlocked_unit_ids"])

        blockers = unlock_blockers(learner.profile, learner.unit("PRE_A1-U02"), learner.curricula)
        self.assertFalse(blockers["unlocked"])
        self.assertEqual(blockers["missing_prerequisite_units"], ["PRE_A1-U01"])
        self.assertEqual(blockers["missing_prerequisite_knowledge"], ["PRE_A1-K003"])
        self.assertEqual([entry["knowledge_id"] for entry in blockers["remediation_plan"]], ["PRE_A1-K003"])
        self.assertEqual(blockers["deadlock_risk"], False)
        self.assertEqual(blockers["prerequisite_gaps"][0]["missing_knowledge_ids"], ["PRE_A1-K003"])

        plan = learner.plan(DAY_1)
        self.assertEqual(plan["next_action"], "remediate")
        self.assertEqual(plan["unit_id"], "PRE_A1-U01")

        # Remediation closes the gap and unlocks the next unit.
        learner.session("session_0002", DAY_2)
        learner.record("session_0002", DAY_2, "PRE_A1-U01", "PRE_A1-O002", ["PRE_A1-K003"], skill="speaking")
        learner.sync()
        learner.validate()
        self.assertEqual(learner.profile["current_course_position"]["completed_unit_ids"], ["PRE_A1-U01"])
        self.assertIn("PRE_A1-U02", learner.profile["current_course_position"]["unlocked_unit_ids"])

    def test_scenario_04_a_unit_spans_several_lessons(self) -> None:
        learner = Learner.zero_beginner()
        learner.reach_unit_three()
        unit = learner.unit("PRE_A1-U03")
        segments = unit_lesson_segments(unit)
        self.assertEqual(len(segments), 4)

        plan = learner.plan(DAY_2)
        self.assertEqual(plan["unit_id"], "PRE_A1-U03")
        self.assertEqual(plan["segment"]["segment_id"], "PRE_A1-U03-S1")
        self.assertEqual(plan["segment_index"], 1)
        self.assertEqual(plan["segment_total"], 4)
        self.assertEqual(plan["next_action"], "continue")

        # The coach marks the first staged letters lesson as taught.
        learner.profile["current_course_position"]["completed_lesson_segment_ids"] = ["PRE_A1-U03-S1"]
        plan = learner.plan(DAY_2)
        self.assertEqual(plan["segment"]["segment_id"], "PRE_A1-U03-S2")
        self.assertTrue(segment_is_done(learner.profile, unit, segments[0]))
        self.assertFalse(segment_is_done(learner.profile, unit, segments[1]))
        learner.validate()

        # Finishing a segment never completes the unit by itself.
        self.assertEqual(learner.profile["current_course_position"]["completed_unit_ids"], ["PRE_A1-U01", "PRE_A1-U02"])

    def test_scenario_05_shadowing_succeeds_but_independent_answer_fails(self) -> None:
        learner = Learner.zero_beginner()
        learner.session("session_0001", DAY_1)
        learner.record(
            "session_0001",
            DAY_1,
            "PRE_A1-U02",
            "PRE_A1-O003",
            ["PRE_A1-K005"],
            phase="repeat_after_model",
            support="model_immediately_before",
            result="PRACTICED",
            novelty="rehearsed",
            skill="speaking",
        )
        learner.record(
            "session_0001",
            DAY_1,
            "PRE_A1-U02",
            "PRE_A1-O003",
            ["PRE_A1-K005"],
            phase="check",
            support="none",
            result="FAIL",
            skill="speaking",
        )
        learner.sync()
        learner.validate()
        states = {entry["knowledge_id"]: entry for entry in learner.profile["knowledge_state"]}
        self.assertEqual(states["PRE_A1-K005"]["state"], "supported")
        self.assertEqual(states["PRE_A1-K005"]["independent_pass_sessions"], [])
        self.assertNotIn("PRE_A1-U02", learner.profile["current_course_position"]["completed_unit_ids"])

    def test_scenario_06_understands_but_cannot_produce(self) -> None:
        """PRE_A1-K009 needs both letter recognition and letter production."""
        learner = Learner.zero_beginner()
        learner.reach_unit_three()
        learner.session("session_0003", DAY_3)
        learner.record(
            "session_0003",
            DAY_3,
            "PRE_A1-U03",
            "PRE_A1-O006",
            ["PRE_A1-K009"],
            skill="listening",
            grade="strict_unseen",
        )
        learner.sync(advance=False)
        learner.validate()
        state = next(entry for entry in learner.profile["knowledge_state"] if entry["knowledge_id"] == "PRE_A1-K009")
        self.assertEqual(state["skill_states"]["listening"], "independent")
        self.assertEqual(state["skill_states"]["speaking"], "not_started")
        self.assertEqual(state["state"], "not_started")
        _complete, _missing_objectives, missing_knowledge = unit_completion(
            learner.profile, learner.unit("PRE_A1-U03")
        )
        self.assertIn("PRE_A1-K009", missing_knowledge)

    def test_scenario_07_speaking_ok_but_listening_check_failed(self) -> None:
        learner = Learner.zero_beginner()
        learner.reach_unit_three()
        learner.session("session_0003", DAY_3)
        learner.record(
            "session_0003", DAY_3, "PRE_A1-U03", "PRE_A1-O005", ["PRE_A1-K009"], skill="speaking"
        )
        learner.record(
            "session_0003",
            DAY_3,
            "PRE_A1-U03",
            "PRE_A1-O006",
            ["PRE_A1-K009"],
            result="FAIL",
            skill="listening",
            grade="strict_unseen",
        )
        learner.sync(advance=False)
        learner.validate()
        state = next(entry for entry in learner.profile["knowledge_state"] if entry["knowledge_id"] == "PRE_A1-K009")
        self.assertEqual(state["skill_states"]["speaking"], "independent")
        self.assertEqual(state["skill_states"]["listening"], "not_started")
        self.assertEqual(state["state"], "not_started")
        _complete, missing_objectives, missing_knowledge = unit_completion(
            learner.profile, learner.unit("PRE_A1-U03")
        )
        self.assertIn("PRE_A1-O006", missing_objectives)
        self.assertIn("PRE_A1-K009", missing_knowledge)

    def test_scenario_08_listening_answer_was_already_on_screen(self) -> None:
        learner = Learner.zero_beginner()
        learner.finish_unit_one()
        learner.session("session_0002", DAY_2)
        # A pass whose text exposure cannot be ruled out must not be a strict check.
        learner.record(
            "session_0002",
            DAY_2,
            "PRE_A1-U02",
            "PRE_A1-O004",
            ["PRE_A1-K007"],
            text_shown=None,
            grade="unknown",
        )
        with self.assertRaises(ValidationError) as context:
            learner.validate()
        self.assertTrue(
            any(
                "must be recorded as practice" in error or "unseen listening PASS" in error
                for error in context.exception.errors
            )
        )

        # Downgrading the same attempt to ordinary listening practice is accepted.
        learner.profile["practice_evidence"][-1].update(
            {"phase": "guided_practice", "result": "PARTIAL", "listening_check_grade": "text_supported_practice"}
        )
        learner.sync(advance=False)
        learner.validate()
        self.assertNotIn("PRE_A1-U02", learner.profile["current_course_position"]["completed_unit_ids"])

    def test_scenario_09_placement_cannot_skip_two_units_with_one_record(self) -> None:
        learner = Learner.zero_beginner()
        learner.profile["session_log"].append(
            {"session_id": "placement_0002", "date": DAY_2.isoformat(), "evidence_ids": ["evidence_skip"]}
        )
        learner.profile["practice_evidence"].append(
            {
                "evidence_id": "evidence_skip",
                "session_id": "placement_0002",
                "date": DAY_2.isoformat(),
                "unit_id": "PRE_A1-U08",
                "objective_id": None,
                "knowledge_ids": level_placement_requirements(curricula())["PRE_A1"],
                "phase": "placement",
                "modality": "mixed",
                "support_level": "none",
                "result": "PASS",
                "learner_response_summary": "One integrated record that claims every Pre-A1 item.",
                "pronunciation_evidence_basis": "not_applicable",
                "prompt_novelty": "unseen",
                "text_shown_before_response": False,
                "listening_check_grade": "strict_unseen",
            }
        )
        learner.profile["current_course_position"]["placement_credited_unit_ids"] = ["PRE_A1-U08", "A1-U08"]
        learner.profile["learning_track"]["placement_basis"] = "independent_level_check"
        with self.assertRaises(ValidationError) as context:
            learner.validate()
        errors = context.exception.errors
        self.assertTrue(any("needs a qualifying listening record" in error for error in errors))
        self.assertTrue(any("needs a qualifying speaking record" in error for error in errors))

        # A learner can still skip exactly one level with a proper two-skill check.
        promoted = init_profile(placement_input(curricula(), ["PRE_A1"]), curricula())
        validate_profile(promoted, curricula(), PROFILE_SCHEMA)
        self.assertEqual(promoted["current_course_position"]["placement_credited_unit_ids"], ["PRE_A1-U08"])
        self.assertEqual(promoted["current_course_position"]["unit_id"], "A1-U01")

    def test_scenario_10_class_interrupted_with_untested_items(self) -> None:
        learner = Learner.zero_beginner()
        learner.profile["active_repertoire"].append(
            {
                "item_id": "item_0001",
                "item": "Please say it again.",
                "item_type": "chunk_&_idiom",
                "stage": 0,
                "status": "active",
                "next_review_date": DAY_1.isoformat(),
                "last_review_date": None,
                "last_outcome": None,
                "lapse_count": 0,
                "selection_defer_once": False,
            }
        )
        learner.session("session_0001", DAY_1)
        learner.record(
            "session_0001",
            DAY_1,
            "PRE_A1-U01",
            "PRE_A1-O002",
            ["PRE_A1-K002"],
            result="UNTESTED",
            skill="speaking",
        )
        learner.sync(advance=False)
        learner.validate()
        state = next(entry for entry in learner.profile["knowledge_state"] if entry["knowledge_id"] == "PRE_A1-K002")
        self.assertEqual(state["state"], "not_started")
        self.assertEqual(state["next_review_date"], None)

        item = learner.profile["active_repertoire"][0]
        deferred = update_repertoire_item(item, "UNTESTED", DAY_1)
        self.assertEqual(deferred["stage"], item["stage"])
        self.assertEqual(deferred["next_review_date"], item["next_review_date"])
        self.assertTrue(deferred["selection_defer_once"])

        plan = learner.plan(DAY_2)
        self.assertEqual(plan["segment"]["segment_id"], "PRE_A1-U01-S1")
        self.assertEqual(plan["next_action"], "continue")

    def test_scenario_11_forgetting_reschedules_review(self) -> None:
        learner = Learner.zero_beginner()
        learner.session("session_0001", DAY_1)
        learner.session("session_0002", DAY_2)
        learner.record("session_0001", DAY_1, "PRE_A1-U01", "PRE_A1-O001", ["PRE_A1-K004"], grade="strict_unseen")
        learner.record("session_0002", DAY_2, "PRE_A1-U01", "PRE_A1-O001", ["PRE_A1-K004"], grade="strict_unseen")
        learner.sync(advance=False)
        state = next(entry for entry in learner.profile["knowledge_state"] if entry["knowledge_id"] == "PRE_A1-K004")
        self.assertEqual(state["state"], "mastered")

        learner.session("session_0003", DAY_3)
        learner.record("session_0003", DAY_3, "PRE_A1-U01", "PRE_A1-O001", ["PRE_A1-K004"], phase="review", result="FAIL", grade="strict_unseen")
        learner.sync(advance=False)
        learner.validate()
        state = next(entry for entry in learner.profile["knowledge_state"] if entry["knowledge_id"] == "PRE_A1-K004")
        self.assertEqual(state["state"], "independent")
        self.assertEqual(state["last_review_date"], DAY_3.isoformat())
        self.assertEqual(state["next_review_date"], date(2026, 10, 11).isoformat())

    def test_scenario_12_export_then_next_class_then_export_again(self) -> None:
        learner = Learner.zero_beginner()
        learner.finish_unit_one()
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            source = output_dir / "English_Learning_Profile.json"
            source.write_text(json.dumps(learner.profile, ensure_ascii=False, indent=2), encoding="utf-8")

            first = export_profile(learner.profile, source, DAY_1, output_dir)
            reloaded = load_json(first)
            validate_profile(reloaded, curricula(), PROFILE_SCHEMA)
            self.assertEqual(reloaded["profile_revision"], learner.profile["profile_revision"])

            # Next class reads the export and prepares normally.
            next_class = Learner(reloaded)
            plan = next_class.plan(DAY_2)
            self.assertEqual(plan["unit_id"], "PRE_A1-U02")

            next_class.profile["profile_revision"] += 1
            second = export_profile(next_class.profile, first, DAY_2, output_dir)
            self.assertNotEqual(first, second)
            self.assertEqual(second.name, "English_Learning_Profile_updated_2026-10-09.json")
            self.assertEqual(load_json(second)["profile_revision"], 2)
            self.assertEqual(load_json(first)["profile_revision"], 1)
            self.assertNotEqual(next_export_path(first, DAY_1, output_dir), first)

    def test_scenario_13_missing_damaged_or_incompatible_profile(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_json(Path("does-not-exist.json"))
        with self.assertRaises(json.JSONDecodeError):
            json.loads("{not json")
        with self.assertRaises(ValidationError):
            migrate_profile({"schema_version": "9.9"})
        profile = Learner.zero_beginner().profile
        del profile["learning_track"]
        with self.assertRaises(ValidationError):
            validate_profile(profile, curricula(), PROFILE_SCHEMA)

    def test_scenario_14_missing_project_files_are_reported(self) -> None:
        with TemporaryDirectory() as directory:
            empty_root = Path(directory)
            with self.assertRaises(FileNotFoundError):
                from tools.learning_data import load_curricula

                load_curricula(empty_root)
        manual = ROOT / "docs" / "manual_acceptance.zh-CN.md"
        self.assertTrue(manual.exists(), "the manual acceptance script must ship with the repository")
        self.assertTrue((ROOT / "PROJECT_INSTRUCTIONS.md").exists())

    def test_scenario_15_full_curriculum_prerequisite_audit(self) -> None:
        audit = audit_curriculum_prerequisites(curricula())
        self.assertTrue(audit["ok"], audit["issues"])
        self.assertEqual(audit["issues"], [])

        # Every unit that can be unlocked must be reachable through completed units.
        learner = Learner.zero_beginner()
        self.assertEqual(learner.profile["current_course_position"]["unlocked_unit_ids"], ["PRE_A1-U01"])
        for unit_id in ("PRE_A1-U02", "A1-U01", "A2-U01", "B1-U01"):
            blockers = unlock_blockers(learner.profile, learner.unit(unit_id), learner.curricula)
            self.assertFalse(blockers["unlocked"])

    def test_four_complete_exit_checks_land_on_b1(self) -> None:
        """A genuinely advanced learner can be credited level by level, not all at once."""
        profile = init_profile(placement_input(curricula(), ["PRE_A1", "A1", "A2", "B1"]), curricula())
        validate_profile(profile, curricula(), PROFILE_SCHEMA)
        self.assertEqual(profile["learning_track"]["current_level"], "B1")
        self.assertEqual(profile["current_course_position"]["unit_id"], "B1-U01")
        self.assertEqual(
            profile["current_course_position"]["placement_credited_unit_ids"],
            ["PRE_A1-U08", "A1-U08", "A2-U08", "B1-U08"],
        )


class DeadlockDetectionTests(unittest.TestCase):
    """The exact P0 shape: a unit looks complete while a prerequisite is missing."""

    def test_completed_unit_with_missing_prerequisite_knowledge_is_flagged(self) -> None:
        learner = Learner.zero_beginner()
        learner.session("session_0001", DAY_1)
        learner.record(
            "session_0001", DAY_1, "PRE_A1-U01", "PRE_A1-O001", ["PRE_A1-K001", "PRE_A1-K004"], grade="strict_unseen"
        )
        learner.record(
            "session_0001", DAY_1, "PRE_A1-U01", "PRE_A1-O002", ["PRE_A1-K002"], skill="speaking"
        )
        learner.sync()
        # Emulate the legacy model, which marked a unit complete from objective passes alone.
        learner.profile["current_course_position"]["completed_unit_ids"] = ["PRE_A1-U01"]

        blockers = unlock_blockers(learner.profile, learner.unit("PRE_A1-U02"), learner.curricula)
        self.assertTrue(blockers["deadlock_risk"])
        self.assertEqual(blockers["stale_owner_units"], ["PRE_A1-U01"])
        self.assertEqual(blockers["missing_prerequisite_knowledge"], ["PRE_A1-K003"])

        with self.assertRaises(ValidationError) as context:
            learner.validate()
        self.assertTrue(
            any("completed without evidence for" in error for error in context.exception.errors)
        )

    def test_sync_repairs_the_legacy_state(self) -> None:
        learner = Learner.zero_beginner()
        learner.session("session_0001", DAY_1)
        learner.record(
            "session_0001", DAY_1, "PRE_A1-U01", "PRE_A1-O001", ["PRE_A1-K001", "PRE_A1-K004"], grade="strict_unseen"
        )
        learner.record(
            "session_0001", DAY_1, "PRE_A1-U01", "PRE_A1-O002", ["PRE_A1-K002"], skill="speaking"
        )
        learner.profile["current_course_position"]["completed_unit_ids"] = ["PRE_A1-U01"]
        learner.sync()
        learner.validate()
        self.assertEqual(learner.profile["current_course_position"]["completed_unit_ids"], [])
        self.assertNotIn("PRE_A1-U02", learner.profile["current_course_position"]["unlocked_unit_ids"])


class ProfileSyncTests(unittest.TestCase):
    def test_sync_is_deterministic_and_idempotent(self) -> None:
        learner = Learner.zero_beginner()
        learner.finish_unit_one()
        once = deepcopy(learner.profile)
        sync_course_position(learner.profile, learner.curricula)
        recompute_knowledge_states(learner.profile, learner.curricula)
        self.assertEqual(learner.profile, once)

    def test_sync_never_invents_evidence(self) -> None:
        learner = Learner.zero_beginner()
        before = deepcopy(learner.profile["practice_evidence"])
        learner.sync()
        self.assertEqual(learner.profile["practice_evidence"], before)
        self.assertEqual(learner.profile["current_course_position"]["completed_unit_ids"], [])


if __name__ == "__main__":
    unittest.main()
