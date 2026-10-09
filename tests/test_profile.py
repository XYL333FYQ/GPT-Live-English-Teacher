#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from tools.learning_data import (
    CURRICULUM_LEVELS,
    ValidationError,
    export_profile,
    init_profile,
    level_placement_requirements,
    load_json,
    migrate_profile,
    next_export_path,
    recompute_knowledge_states,
    unit_completion,
    validate_profile,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "tests" / "fixtures" / "English_Learning_Profile.example.json"
LEGACY_PATH = ROOT / "tests" / "fixtures" / "English_Learning_Profile.v2.1.example.json"
PROFILE_SCHEMA = load_json(ROOT / "schemas" / "learning-profile.schema.json")

sys.path.insert(0, str(ROOT))
from tests.support import placement_input  # noqa: E402


def curricula() -> list[dict]:
    return [load_json(ROOT / "curriculum" / f"{level}.json") for level in CURRICULUM_LEVELS]


class ProfileTests(unittest.TestCase):
    def test_example_profile_is_valid(self) -> None:
        validate_profile(load_json(PROFILE_PATH), curricula(), PROFILE_SCHEMA)

    def test_v21_migration_preserves_data_and_labels_legacy_score(self) -> None:
        legacy = load_json(LEGACY_PATH)
        original = deepcopy(legacy)
        migrated = migrate_profile(legacy, "2026-10-08T12:00:00+00:00")
        self.assertEqual(legacy, original)
        self.assertEqual(migrated["schema_version"], "3.0")
        self.assertEqual(migrated["profile_revision"], 2)
        self.assertEqual(migrated["active_repertoire"], legacy["active_repertoire"])
        self.assertEqual(migrated["session_log"], legacy["session_log"])
        self.assertTrue(migrated["compatible_extension"]["preserve_me"])
        self.assertEqual(migrated["learning_track"]["mode"], "legacy_conversation")
        self.assertEqual(migrated["current_course_position"]["unit_status"], "not_applicable")
        self.assertIn("legacy_pronunciation_notice", migrated["scientific_assessment"])
        validate_profile(migrated, curricula(), PROFILE_SCHEMA)

    def test_migration_is_idempotent(self) -> None:
        migrated = migrate_profile(load_json(LEGACY_PATH), "2026-10-08T12:00:00+00:00")
        self.assertEqual(migrate_profile(migrated, "2026-10-09T12:00:00+00:00"), migrated)

    def test_pre_a1_legacy_level_enters_structured_curriculum(self) -> None:
        legacy = load_json(LEGACY_PATH)
        legacy["scientific_assessment"]["overall_cefr"] = "A0"
        migrated = migrate_profile(legacy, "2026-10-08T12:00:00+00:00")
        self.assertEqual(migrated["learning_track"]["current_level"], "PRE_A1")
        self.assertEqual(migrated["learning_track"]["mode"], "structured_curriculum")
        self.assertEqual(migrated["current_course_position"]["unit_status"], "needs_curriculum_mapping")

    def test_unknown_legacy_cefr_is_rejected(self) -> None:
        legacy = load_json(LEGACY_PATH)
        legacy["scientific_assessment"]["overall_cefr"] = "beginner-ish"
        with self.assertRaises(ValidationError):
            migrate_profile(legacy, "2026-10-08T12:00:00+00:00")

    def test_repetition_cannot_be_recorded_as_pass(self) -> None:
        profile = load_json(PROFILE_PATH)
        profile["practice_evidence"][2]["result"] = "PASS"
        with self.assertRaises(ValidationError):
            validate_profile(profile, curricula(), PROFILE_SCHEMA)

    def test_transcript_only_pronunciation_is_not_assessed(self) -> None:
        profile = load_json(PROFILE_PATH)
        weakness = profile["skill_weaknesses"]["pronunciation"][0]
        weakness["evidence_basis"] = "transcript_only"
        with self.assertRaises(ValidationError):
            validate_profile(profile, curricula(), PROFILE_SCHEMA)

    def test_numeric_pronunciation_score_is_rejected_even_with_direct_audio(self) -> None:
        profile = load_json(PROFILE_PATH)
        profile["skill_weaknesses"]["pronunciation"][0]["score"] = 95
        with self.assertRaises(ValidationError):
            validate_profile(profile, curricula(), PROFILE_SCHEMA)

    def test_invalid_objective_reference_is_rejected(self) -> None:
        profile = load_json(PROFILE_PATH)
        profile["practice_evidence"][0]["objective_id"] = "PRE_A1-O999"
        with self.assertRaises(ValidationError):
            validate_profile(profile, curricula(), PROFILE_SCHEMA)

    def test_unlocked_unit_must_have_qualified_prerequisites(self) -> None:
        profile = load_json(PROFILE_PATH)
        profile["knowledge_state"] = [
            state for state in profile["knowledge_state"] if state["knowledge_id"] != "PRE_A1-K003"
        ]
        with self.assertRaises(ValidationError):
            validate_profile(profile, curricula(), PROFILE_SCHEMA)

    def test_knowledge_state_must_reference_its_own_evidence(self) -> None:
        profile = load_json(PROFILE_PATH)
        state = next(entry for entry in profile["knowledge_state"] if entry["knowledge_id"] == "PRE_A1-K002")
        state["evidence_ids"] = ["evidence_0006"]
        with self.assertRaises(ValidationError):
            validate_profile(profile, curricula(), PROFILE_SCHEMA)

    def test_locked_unit_cannot_be_marked_completed(self) -> None:
        profile = load_json(PROFILE_PATH)
        profile["current_course_position"]["completed_unit_ids"].append("A1-U08")
        with self.assertRaises(ValidationError):
            validate_profile(profile, curricula(), PROFILE_SCHEMA)

    def test_current_numeric_pronunciation_assessment_is_rejected(self) -> None:
        profile = load_json(PROFILE_PATH)
        profile["scientific_assessment"]["pronunciation_score"] = 95
        with self.assertRaises(ValidationError):
            validate_profile(profile, curricula(), PROFILE_SCHEMA)

    def test_course_levels_must_match(self) -> None:
        profile = load_json(PROFILE_PATH)
        profile["learning_track"]["current_level"] = "B2"
        with self.assertRaises(ValidationError):
            validate_profile(profile, curricula(), PROFILE_SCHEMA)

    def test_evidence_must_be_listed_by_its_own_session(self) -> None:
        profile = load_json(PROFILE_PATH)
        profile["session_log"][0]["evidence_ids"].append("evidence_0003")
        with self.assertRaises(ValidationError):
            validate_profile(profile, curricula(), PROFILE_SCHEMA)

    def test_invalid_review_date_is_rejected(self) -> None:
        profile = load_json(PROFILE_PATH)
        profile["active_repertoire"][0]["next_review_date"] = "never"
        with self.assertRaises(ValidationError):
            validate_profile(profile, curricula(), PROFILE_SCHEMA)

    def test_unit_completion_ignores_guided_evidence(self) -> None:
        profile = load_json(PROFILE_PATH)
        unit = curricula()[0]["units"][1]
        complete, missing, missing_knowledge = unit_completion(profile, unit)
        self.assertFalse(complete)
        self.assertIn("PRE_A1-O003", missing)
        self.assertIn("PRE_A1-K005", missing_knowledge)

        profile["practice_evidence"].extend(
            [
                {
                    "evidence_id": "evidence_0008",
                    "session_id": "session_0003",
                    "date": "2026-10-09",
                    "unit_id": "PRE_A1-U02",
                    "objective_id": "PRE_A1-O003",
                    "knowledge_ids": ["PRE_A1-K005", "PRE_A1-K006", "PRE_A1-K008"],
                    "phase": "check",
                    "modality": "voice",
                    "support_level": "none",
                    "result": "PASS",
                    "learner_response_summary": "Completed a new greeting exchange without prompts.",
                    "pronunciation_evidence_basis": "direct_live_audio",
                    "prompt_novelty": "unseen",
                    "text_shown_before_response": False,
                },
                {
                    "evidence_id": "evidence_0009",
                    "session_id": "session_0003",
                    "date": "2026-10-09",
                    "unit_id": "PRE_A1-U02",
                    "objective_id": "PRE_A1-O004",
                    "knowledge_ids": ["PRE_A1-K007"],
                    "phase": "check",
                    "modality": "voice",
                    "support_level": "none",
                    "result": "PASS",
                    "learner_response_summary": "Identified two new names without visible text.",
                    "pronunciation_evidence_basis": "not_applicable",
                    "prompt_novelty": "unseen",
                    "text_shown_before_response": False,
                    "listening_check_grade": "strict_unseen",
                },
            ]
        )
        profile["session_log"].append(
            {
                "session_id": "session_0003",
                "date": "2026-10-09",
                "evidence_ids": ["evidence_0008", "evidence_0009"],
            }
        )
        recompute_knowledge_states(profile, curricula())
        complete, missing, missing_knowledge = unit_completion(profile, unit)
        self.assertTrue(complete)
        self.assertEqual(missing, [])
        self.assertEqual(missing_knowledge, [])

    def test_text_pass_cannot_satisfy_unseen_listening(self) -> None:
        profile = load_json(PROFILE_PATH)
        unit = curricula()[0]["units"][1]
        profile["practice_evidence"].extend(
            [
                {
                    "evidence_id": "evidence_0008",
                    "session_id": "session_0003",
                    "unit_id": "PRE_A1-U02",
                    "objective_id": "PRE_A1-O003",
                    "phase": "check",
                    "support_level": "none",
                    "result": "PASS",
                    "modality": "voice",
                    "prompt_novelty": "unseen",
                    "text_shown_before_response": False,
                },
                {
                    "evidence_id": "evidence_0009",
                    "session_id": "session_0003",
                    "unit_id": "PRE_A1-U02",
                    "objective_id": "PRE_A1-O004",
                    "phase": "check",
                    "support_level": "none",
                    "result": "PASS",
                    "modality": "text",
                    "prompt_novelty": "unseen",
                    "text_shown_before_response": False,
                },
            ]
        )
        complete, missing, _missing_knowledge = unit_completion(profile, unit)
        self.assertFalse(complete)
        self.assertEqual(missing, ["PRE_A1-O004"])

    def test_rehearsed_voice_pass_cannot_satisfy_independent_expression(self) -> None:
        profile = load_json(PROFILE_PATH)
        unit = curricula()[0]["units"][1]
        profile["practice_evidence"].append(
            {
                "evidence_id": "evidence_0008",
                "session_id": "session_0003",
                "unit_id": "PRE_A1-U02",
                "objective_id": "PRE_A1-O003",
                "phase": "check",
                "support_level": "none",
                "result": "PASS",
                "modality": "voice",
                "prompt_novelty": "rehearsed",
                "text_shown_before_response": False,
            }
        )
        _complete, missing, _missing_knowledge = unit_completion(profile, unit)
        self.assertIn("PRE_A1-O003", missing)

    def test_thin_placement_credit_is_rejected(self) -> None:
        """One formally valid record must not skip a whole level."""
        profile = load_json(PROFILE_PATH)
        profile["session_log"].append(
            {"session_id": "placement_0001", "date": "2026-10-09", "evidence_ids": ["evidence_placement"]}
        )
        profile["practice_evidence"].append(
            {
                "evidence_id": "evidence_placement",
                "session_id": "placement_0001",
                "date": "2026-10-09",
                "unit_id": "PRE_A1-U08",
                "objective_id": None,
                "knowledge_ids": ["PRE_A1-K006", "PRE_A1-K008", "PRE_A1-K030"],
                "phase": "placement",
                "modality": "voice",
                "support_level": "none",
                "result": "PASS",
                "learner_response_summary": "Answered three personal questions.",
                "pronunciation_evidence_basis": "not_applicable",
                "prompt_novelty": "unseen",
                "text_shown_before_response": False,
                "skill": "speaking",
                "listening_check_grade": "not_applicable",
            }
        )
        for knowledge_id, unit_id in (
            ("PRE_A1-K006", "PRE_A1-U02"),
            ("PRE_A1-K008", "PRE_A1-U02"),
            ("PRE_A1-K030", "PRE_A1-U08"),
        ):
            profile["knowledge_state"].append(
                {
                    "knowledge_id": knowledge_id,
                    "unit_id": unit_id,
                    "state": "placement_credited",
                    "evidence_ids": ["evidence_placement"],
                    "independent_pass_sessions": ["placement_0001"],
                    "review_pass_sessions": [],
                    "last_review_date": "2026-10-09",
                    "next_review_date": None,
                }
            )
        profile["learning_track"].update(
            {"current_level": "A1", "placement_basis": "independent_level_check"}
        )
        profile["current_course_position"] = {
            "level_id": "A1",
            "unit_id": "A1-U01",
            "unit_status": "in_progress",
            "lesson_phase": "course_goal",
            "unlocked_unit_ids": ["A1-U01"],
            "completed_unit_ids": [],
            "placement_credited_unit_ids": ["PRE_A1-U08"],
        }
        with self.assertRaises(ValidationError) as context:
            validate_profile(profile, curricula(), PROFILE_SCHEMA)
        self.assertTrue(
            any("needs a qualifying listening record" in error for error in context.exception.errors)
        )

    def test_placement_credit_requires_a_full_listening_and_speaking_exit_check(self) -> None:
        """A complete exit check skips exactly one level and unlocks the next one."""
        placement = placement_input(curricula(), ["PRE_A1"])
        profile = init_profile(placement, curricula())
        validate_profile(profile, curricula(), PROFILE_SCHEMA)
        self.assertEqual(profile["current_course_position"]["placement_credited_unit_ids"], ["PRE_A1-U08"])
        self.assertEqual(profile["current_course_position"]["completed_unit_ids"], [])
        self.assertEqual(profile["learning_track"]["current_level"], "A1")
        self.assertEqual(profile["current_course_position"]["unit_id"], "A1-U01")
        self.assertIn("A1-U01", profile["current_course_position"]["unlocked_unit_ids"])
        requirements = set(level_placement_requirements(curricula())["PRE_A1"])
        self.assertTrue(
            all(
                entry["state"] == "placement_credited"
                for entry in profile["knowledge_state"]
                if entry["knowledge_id"] in requirements
            )
        )

    def test_zero_beginner_placement_stays_provisional(self) -> None:
        placement = load_json(ROOT / "tests" / "fixtures" / "placement.zero-beginner.example.json")
        profile = init_profile(placement, curricula())
        validate_profile(profile, curricula(), PROFILE_SCHEMA)
        self.assertEqual(profile["scientific_assessment"]["assessment_status"], "provisional")
        self.assertEqual(profile["learning_track"]["placement_basis"], "initial_screening")
        self.assertEqual(profile["current_course_position"]["placement_credited_unit_ids"], [])
        self.assertEqual(profile["current_course_position"]["unit_id"], "PRE_A1-U01")
        self.assertEqual(profile["current_course_position"]["unlocked_unit_ids"], ["PRE_A1-U01"])

    def test_learner_choice_cannot_credit_knowledge(self) -> None:
        profile = load_json(PROFILE_PATH)
        profile["learning_track"]["placement_basis"] = "learner_choice"
        profile["current_course_position"]["placement_credited_unit_ids"] = ["PRE_A1-U08"]
        with self.assertRaises(ValidationError):
            validate_profile(profile, curricula(), PROFILE_SCHEMA)

    def test_curriculum_release_1_0_0_profiles_still_validate(self) -> None:
        profile = load_json(PROFILE_PATH)
        profile["learning_track"]["curriculum_version"] = "1.0.0"
        validate_profile(profile, curricula(), PROFILE_SCHEMA)

    def test_export_never_overwrites_source_or_existing_export(self) -> None:
        profile = load_json(PROFILE_PATH)
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            source = output_dir / "English_Learning_Profile.json"
            source.write_text("source", encoding="utf-8")
            existing = output_dir / "English_Learning_Profile_updated_2026-10-08.json"
            existing.write_text("existing", encoding="utf-8")
            next_path = next_export_path(source, date(2026, 10, 8), output_dir)
            self.assertEqual(next_path.name, "English_Learning_Profile_updated_2026-10-08_2.json")
            exported = export_profile(profile, source, date(2026, 10, 8), output_dir)
            self.assertEqual(exported, next_path)
            self.assertEqual(source.read_text(encoding="utf-8"), "source")
            self.assertEqual(existing.read_text(encoding="utf-8"), "existing")
            self.assertEqual(json.loads(exported.read_text(encoding="utf-8"))["schema_version"], "3.0")


if __name__ == "__main__":
    unittest.main()
