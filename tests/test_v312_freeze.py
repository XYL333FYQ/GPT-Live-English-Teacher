#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""v3.1.2 freeze regressions.

Three confirmed defects plus one systematic end-to-end check of the real loop:
first profile -> prepare -> live evidence -> export -> reload -> continue.

Each test below failed against v3.1.1 and passes against v3.1.2.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.support import objective_evidence, placement_input  # noqa: E402
from tools.learning_data import (  # noqa: E402
    CURRICULUM_LEVELS,
    ValidationError,
    ambiguous_objective_skill_records,
    evidence_is_placement_credit,
    evidence_is_strict_unseen_listening,
    evidence_skill_conflicts_with_objective,
    evidence_skill_dimensions,
    export_profile,
    init_profile,
    load_json,
    normalize_profile,
    objective_skill,
    objective_requires_unseen_listening,
    placement_condition_gaps,
    profile_sort_key,
    screening_verification_status,
    select_latest_profile,
    unit_completion,
    validate_profile,
)

PROFILE_SCHEMA = load_json(ROOT / "schemas" / "learning-profile.schema.json")
EXAMPLE = ROOT / "tests" / "fixtures" / "English_Learning_Profile.example.json"
PLACEMENT_FIXTURE = ROOT / "tests" / "fixtures" / "placement.zero-beginner.example.json"


def curricula() -> list[dict]:
    return [load_json(ROOT / "curriculum" / f"{level}.json") for level in CURRICULUM_LEVELS]


def units_index() -> dict[str, dict]:
    return {unit["unit_id"]: unit for document in curricula() for unit in document["units"]}


def objectives_index() -> dict[str, tuple[str, dict]]:
    return {
        objective["objective_id"]: (unit["unit_id"], objective)
        for document in curricula()
        for unit in document["units"]
        for objective in unit["objectives"]
    }


class ObjectiveSkillConsistencyTests(unittest.TestCase):
    """Defect 1: an objective accepted evidence of the wrong skill."""

    def profile_with(self, objective_id: str, **overrides: object) -> dict:
        """A fresh zero-beginner profile plus one probe record for the objective."""
        profile = init_profile(load_json(PLACEMENT_FIXTURE), curricula())
        unit_id, objective = objectives_index()[objective_id]
        profile["session_log"].append(
            {"session_id": "session_0001", "date": "2026-10-09", "evidence_ids": [], "review_outcomes": [], "new_item_ids": []}
        )
        record = objective_evidence(
            unit_id, objective, evidence_id="evidence_skill_probe", session_id="session_0001"
        )
        record.update(overrides)
        profile["practice_evidence"].append(record)
        profile["session_log"][-1]["evidence_ids"].append(record["evidence_id"])
        return profile

    def test_speaking_objective_built_on_unseen_audio_needs_no_listening_grade(self) -> None:
        """B1-O013 is a speaking task whose prompt is unseen audio, not a listening check.

        Gating it on `listening_check_grade` made B1-U07 impossible to complete, which
        blocked the whole course at B1.
        """
        _unit_id, objective = objectives_index()["B1-O013"]
        self.assertEqual(objective["mode"], "speaking")
        self.assertIn("unseen_audio", objective["evidence_requirement"])
        self.assertFalse(objective_requires_unseen_listening(objective))

        profile = self.profile_with("B1-O013")
        unit = units_index()["B1-U07"]
        _complete, missing_objectives, _missing_knowledge = unit_completion(profile, unit)
        self.assertNotIn("B1-O013", missing_objectives)

    def test_listening_objectives_still_require_the_strict_gate(self) -> None:
        for objective_id in ("PRE_A1-O001", "A1-O004", "A2-O016", "B1-O014"):
            with self.subTest(objective_id=objective_id):
                _unit_id, objective = objectives_index()[objective_id]
                self.assertEqual(objective["mode"], "listening")
                self.assertTrue(objective_requires_unseen_listening(objective))

    def test_listening_objective_rejects_production_evidence(self) -> None:
        profile = self.profile_with("PRE_A1-O001", skill="speaking", listening_check_grade="not_applicable")
        unit = units_index()["PRE_A1-U01"]
        complete, missing_objectives, _missing_knowledge = unit_completion(profile, unit)
        self.assertIn("PRE_A1-O001", missing_objectives)
        self.assertFalse(complete)

    def test_interaction_objective_rejects_listening_evidence(self) -> None:
        profile = self.profile_with("PRE_A1-O003", skill="listening")
        unit = units_index()["PRE_A1-U02"]
        _complete, missing_objectives, _missing_knowledge = unit_completion(profile, unit)
        self.assertIn("PRE_A1-O003", missing_objectives)

    def test_speaking_objective_rejects_listening_evidence(self) -> None:
        profile = self.profile_with("PRE_A1-O007", skill="listening")
        unit = units_index()["PRE_A1-U04"]
        _complete, missing_objectives, _missing_knowledge = unit_completion(profile, unit)
        self.assertIn("PRE_A1-O007", missing_objectives)

    def test_matching_skill_still_passes(self) -> None:
        profile = self.profile_with("PRE_A1-O003", skill="speaking")
        unit = units_index()["PRE_A1-U02"]
        _complete, missing_objectives, _missing_knowledge = unit_completion(profile, unit)
        self.assertNotIn("PRE_A1-O003", missing_objectives)

    def test_absent_skill_still_uses_the_objective_mode(self) -> None:
        profile = self.profile_with("PRE_A1-O003")
        profile["practice_evidence"][-1].pop("skill")
        unit = units_index()["PRE_A1-U02"]
        _complete, missing_objectives, _missing_knowledge = unit_completion(profile, unit)
        self.assertNotIn("PRE_A1-O003", missing_objectives)

    def test_conflict_credits_no_dimension(self) -> None:
        profile = self.profile_with("PRE_A1-O003", skill="listening")
        record = profile["practice_evidence"][-1]
        self.assertEqual(evidence_skill_dimensions(record, "PRE_A1-K005", curricula()), ())
        self.assertTrue(evidence_skill_conflicts_with_objective(record, objectives_index()["PRE_A1-O003"][1]))
        self.assertEqual(objective_skill(objectives_index()["PRE_A1-O003"][1]), "speaking")
        self.assertEqual(
            [entry["evidence_id"] for entry in ambiguous_objective_skill_records(profile, curricula())],
            ["evidence_skill_probe"],
        )

    def test_conflict_does_not_raise_the_knowledge_state(self) -> None:
        profile = self.profile_with("PRE_A1-O003", skill="listening")
        normalize_profile(profile, curricula(), advance=False)
        states = {entry["knowledge_id"]: entry["state"] for entry in profile["knowledge_state"]}
        self.assertNotIn(states.get("PRE_A1-K005"), {"independent", "mastered", "placement_credited"})

    def test_validation_rejects_the_conflict(self) -> None:
        profile = self.profile_with("PRE_A1-O003", skill="listening")
        with self.assertRaises(ValidationError) as context:
            validate_profile(profile, curricula(), PROFILE_SCHEMA)
        self.assertTrue(
            any("contradicts objective" in error for error in context.exception.errors)
        )

    def test_normalization_detaches_and_preserves_history(self) -> None:
        profile = self.profile_with("PRE_A1-O003", skill="listening")
        before = deepcopy(profile["practice_evidence"][-1])
        normalize_profile(profile, curricula(), advance=False)
        record = next(e for e in profile["practice_evidence"] if e["evidence_id"] == "evidence_skill_probe")
        self.assertIsNone(record["objective_id"])
        self.assertEqual(record["phase"], "guided_practice")
        self.assertEqual(record["learner_response_summary"], before["learner_response_summary"])
        self.assertEqual(record["date"], before["date"])
        self.assertEqual(record["skill"], "listening")
        self.assertIn("detached from its objective", record["notes"])
        validate_profile(profile, curricula(), PROFILE_SCHEMA)
        self.assertTrue(
            any(
                entry.get("downgraded_evidence_ids") == ["evidence_skill_probe"]
                for entry in profile["migration_history"]
            )
        )

    def test_repetition_and_guided_practice_semantics_are_unchanged(self) -> None:
        profile = load_json(EXAMPLE)
        unit_id, objective = objectives_index()["PRE_A1-O003"]
        shadowed = objective_evidence(
            unit_id, objective, evidence_id="evidence_shadow", session_id="session_0001"
        )
        shadowed.update(
            {
                "phase": "repeat_after_model",
                "support_level": "model_immediately_before",
                "result": "PRACTICED",
                "prompt_novelty": "rehearsed",
            }
        )
        guided = objective_evidence(
            unit_id, objective, evidence_id="evidence_guided", session_id="session_0001"
        )
        guided.update({"phase": "guided_practice", "support_level": "sentence_starter", "result": "PASS"})
        profile["practice_evidence"].extend([shadowed, guided])
        profile["session_log"][0]["evidence_ids"].extend(["evidence_shadow", "evidence_guided"])
        _complete, missing_objectives, _missing_knowledge = unit_completion(
            profile, units_index()["PRE_A1-U02"]
        )
        self.assertIn("PRE_A1-O003", missing_objectives)
        normalize_profile(profile, curricula(), advance=False)
        states = {entry["knowledge_id"]: entry["state"] for entry in profile["knowledge_state"]}
        self.assertIn(states["PRE_A1-K005"], {"introduced", "supported"})
        self.assertNotIn(states["PRE_A1-K005"], {"independent", "mastered"})


class ScreeningLabelConsistencyTests(unittest.TestCase):
    """Defect 2: the status label said strict while the rule said otherwise."""

    def record(self, **overrides: object) -> dict:
        record = {
            "evidence_id": "e1",
            "session_id": "placement_0001",
            "date": "2026-10-09",
            "unit_id": "PRE_A1-U08",
            "objective_id": None,
            "phase": "placement",
            "knowledge_ids": ["PRE_A1-K006"],
            "modality": "voice",
            "support_level": "none",
            "result": "PASS",
            "prompt_novelty": "unseen",
            "text_shown_before_response": False,
            "skill": "speaking",
            "listening_check_grade": "not_applicable",
        }
        record.update(overrides)
        return record

    def test_label_and_credit_agree_across_every_field(self) -> None:
        variants = [
            {},
            {"text_shown_before_response": True},
            {"text_shown_before_response": None},
            {"prompt_novelty": "unknown"},
            {"prompt_novelty": "rehearsed"},
            {"prompt_novelty": None},
            {"support_level": "sentence_starter"},
            {"support_level": "answer_revealed"},
            {"modality": "text"},
            {"result": "PARTIAL"},
            {"result": "FAIL"},
            {"skill": None},
            {"skill": "listening"},
            {"skill": "listening", "listening_check_grade": "strict_unseen"},
            {"skill": "listening", "listening_check_grade": "unknown"},
            {"skill": "listening", "listening_check_grade": "text_supported_practice"},
            {"knowledge_ids": []},
            {"phase": "check"},
            {"objective_id": "PRE_A1-O003"},
        ]
        for overrides in variants:
            with self.subTest(overrides=overrides):
                record = self.record(**overrides)
                label = screening_verification_status(record)
                credit = evidence_is_placement_credit(record)
                self.assertEqual(
                    label == "strict_independent",
                    credit,
                    f"label {label!r} disagrees with credit {credit} for {overrides}",
                )

    def test_visible_answer_is_practice_not_a_strict_pass(self) -> None:
        record = self.record(text_shown_before_response=True)
        self.assertEqual(screening_verification_status(record), "practice_only")
        self.assertFalse(evidence_is_placement_credit(record))

    def test_unknown_text_exposure_is_unverified(self) -> None:
        record = self.record(text_shown_before_response=None)
        self.assertEqual(screening_verification_status(record), "unverified_conditions")
        self.assertFalse(evidence_is_placement_credit(record))

    def test_missing_conditions_are_unverified(self) -> None:
        record = self.record()
        record.pop("prompt_novelty")
        record.pop("text_shown_before_response")
        record.pop("skill")
        self.assertEqual(screening_verification_status(record), "unverified_conditions")
        self.assertFalse(evidence_is_placement_credit(record))
        self.assertIn("prompt_novelty_unknown", placement_condition_gaps(record))
        self.assertIn("text_exposure_unknown", placement_condition_gaps(record))
        self.assertIn("skill_missing", placement_condition_gaps(record))

    def test_listening_without_strict_grade_never_credits(self) -> None:
        record = self.record(skill="listening", listening_check_grade="unknown")
        self.assertFalse(evidence_is_placement_credit(record))
        self.assertEqual(screening_verification_status(record), "unverified_conditions")
        record["listening_check_grade"] = "text_supported_practice"
        self.assertEqual(screening_verification_status(record), "practice_only")

    def test_strict_listening_and_speaking_records_credit(self) -> None:
        listening = self.record(
            skill="listening",
            listening_check_grade="strict_unseen",
            knowledge_ids=["PRE_A1-K004"],
        )
        self.assertTrue(evidence_is_strict_unseen_listening(listening))
        self.assertTrue(evidence_is_placement_credit(listening))
        self.assertEqual(screening_verification_status(listening), "strict_independent")
        speaking = self.record()
        self.assertTrue(evidence_is_placement_credit(speaking))
        self.assertEqual(screening_verification_status(speaking), "strict_independent")

    def test_failed_attempt_is_labelled_failed(self) -> None:
        record = self.record(result="FAIL")
        self.assertEqual(screening_verification_status(record), "failed")
        self.assertFalse(evidence_is_placement_credit(record))

    def test_placed_credit_still_needs_two_skills(self) -> None:
        """The label fix must not weaken the two-skill placement requirement."""
        profile = init_profile(load_json(PLACEMENT_FIXTURE), curricula())
        self.assertEqual(profile["current_course_position"]["placement_credited_unit_ids"], [])
        promoted = init_profile(placement_input(curricula(), ["PRE_A1"]), curricula())
        validate_profile(promoted, curricula(), PROFILE_SCHEMA)
        self.assertEqual(promoted["current_course_position"]["placement_credited_unit_ids"], ["PRE_A1-U08"])


class ProfileOrderingTests(unittest.TestCase):
    """Defect 3: timestamps were compared as strings."""

    def write(self, directory: Path, name: str, **overrides: object) -> Path:
        profile = load_json(EXAMPLE)
        profile.update(overrides)
        path = directory / name
        path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def test_mixed_timezones_compare_by_real_instant(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            # 23:00+08:00 is 15:00Z; 20:00+00:00 is later in real time.
            self.write(output, "a_shanghai.json", updated_at="2026-10-08T23:00:00+08:00", profile_revision=1)
            self.write(output, "b_utc.json", updated_at="2026-10-08T20:00:00+00:00", profile_revision=1)
            chosen, _ranking = select_latest_profile(output)
            self.assertEqual(chosen.name, "b_utc.json")

            output2 = Path(directory) / "second"
            output2.mkdir()
            # 02:00+08:00 == 2026-10-08T18:00Z, earlier than 22:00-04:00 == 18:00Z? no:
            # 22:00-04:00 is 2026-10-09T02:00Z, so it is the later one.
            self.write(output2, "c_shanghai.json", updated_at="2026-10-09T02:00:00+08:00", profile_revision=1)
            self.write(output2, "d_newyork.json", updated_at="2026-10-08T22:00:00-04:00", profile_revision=1)
            chosen2, _ranking2 = select_latest_profile(output2)
            self.assertEqual(chosen2.name, "d_newyork.json")

    def test_same_instant_prefers_higher_revision(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            self.write(output, "aaa.json", updated_at="2026-10-08T20:00:00+00:00", profile_revision=1)
            self.write(output, "zzz.json", updated_at="2026-10-08T22:00:00+02:00", profile_revision=5)
            chosen, ranking = select_latest_profile(output)
            self.assertEqual(chosen.name, "zzz.json")
            self.assertEqual(ranking[0]["profile_revision"], 5)

    def test_missing_timezone_never_outranks_an_aware_profile(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            self.write(output, "naive.json", updated_at="2026-12-31T23:59:59", profile_revision=9)
            self.write(output, "aware.json", updated_at="2026-01-01T00:00:00+00:00", profile_revision=1)
            chosen, ranking = select_latest_profile(output)
            self.assertEqual(chosen.name, "aware.json")
            naive = next(entry for entry in ranking if entry["filename"] == "naive.json")
            self.assertFalse(naive["offset_known"])
            self.assertEqual(naive["status"], "missing_timezone")

    def test_invalid_timestamp_is_reported_not_chosen(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            self.write(output, "broken_time.json", updated_at="yesterday-ish", profile_revision=99)
            self.write(output, "good.json", updated_at="2026-01-01T00:00:00+00:00", profile_revision=1)
            chosen, ranking = select_latest_profile(output)
            self.assertEqual(chosen.name, "good.json")
            broken = next(entry for entry in ranking if entry["filename"] == "broken_time.json")
            self.assertEqual(broken["status"], "invalid_updated_at")
            self.assertEqual(profile_sort_key(output / "broken_time.json")[1], 0)

    def test_damaged_and_non_profile_files_are_reported(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            self.write(output, "good.json", updated_at="2026-01-01T00:00:00+00:00", profile_revision=1)
            (output / "damaged.json").write_text("{not json", encoding="utf-8")
            (output / "notes.json").write_text('{"hello": 1}', encoding="utf-8")
            chosen, ranking = select_latest_profile(output)
            self.assertEqual(chosen.name, "good.json")
            statuses = {entry["filename"]: entry["status"] for entry in ranking}
            self.assertEqual(statuses["damaged.json"], "invalid_json")
            self.assertEqual(statuses["notes.json"], "not_a_profile")
            self.assertFalse(next(e for e in ranking if e["filename"] == "damaged.json")["is_profile"])

    def test_no_profile_at_all_reports_clearly(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "damaged.json").write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValidationError) as context:
                select_latest_profile(output)
            self.assertTrue(any("no learner profile found" in error for error in context.exception.errors))

    def test_ambiguous_tie_refuses_to_guess(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            first = load_json(EXAMPLE)
            first["profile_revision"] = 3
            first["updated_at"] = "2026-10-08T20:00:00+00:00"
            (output / "one.json").write_text(json.dumps(first, ensure_ascii=False), encoding="utf-8")
            second = deepcopy(first)
            second["practice_evidence"] = second["practice_evidence"][:2]
            (output / "two.json").write_text(json.dumps(second, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValidationError) as context:
                select_latest_profile(output)
            message = " ".join(context.exception.errors)
            self.assertIn("cannot tell which profile is newest", message)
            self.assertIn("one.json", message)
            self.assertIn("two.json", message)

    def test_identical_duplicate_is_not_ambiguous(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            self.write(output, "copy_a.json", updated_at="2026-10-08T20:00:00+00:00", profile_revision=3)
            self.write(output, "copy_b.json", updated_at="2026-10-08T20:00:00+00:00", profile_revision=3)
            chosen, _ranking = select_latest_profile(output)
            self.assertIn(chosen.name, {"copy_a.json", "copy_b.json"})

    def test_export_is_still_non_overwriting(self) -> None:
        profile = init_profile(load_json(PLACEMENT_FIXTURE), curricula())
        with TemporaryDirectory() as directory:
            output = Path(directory)
            source = output / "English_Learning_Profile.json"
            source.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            first = export_profile(profile, source, date(2026, 10, 8), output)
            second = export_profile(profile, first, date(2026, 10, 8), output)
            self.assertNotEqual(first, second)
            self.assertEqual(second.name, "English_Learning_Profile_updated_2026-10-08_2.json")
            self.assertEqual(json.loads(source.read_text(encoding="utf-8"))["profile_revision"], 1)


class FullLoopRegressionTests(unittest.TestCase):
    """Systematic check of the real loop: build -> prepare -> teach -> export -> continue."""

    def test_every_unit_can_progress_through_the_whole_curriculum(self) -> None:
        """A perfect learner completes all 32 units in prerequisite order."""
        profile = init_profile(load_json(PLACEMENT_FIXTURE), curricula())
        all_curricula = curricula()
        ordered = [unit for document in all_curricula for unit in document["units"]]
        counter = 0
        for index, unit in enumerate(ordered):
            session_id = f"session_{index + 1:04d}"
            day = (date(2026, 10, 9) + timedelta(days=index)).isoformat()
            profile["session_log"].append(
                {"session_id": session_id, "date": day, "evidence_ids": [], "review_outcomes": [], "new_item_ids": []}
            )
            for objective in unit["objectives"]:
                counter += 1
                record = objective_evidence(
                    unit["unit_id"],
                    objective,
                    evidence_id=f"evidence_walk_{counter:04d}",
                    session_id=session_id,
                    date_value=day,
                )
                profile["practice_evidence"].append(record)
                profile["session_log"][-1]["evidence_ids"].append(record["evidence_id"])
            normalize_profile(profile, all_curricula)
            complete, missing_objectives, missing_knowledge = unit_completion(profile, unit)
            self.assertTrue(
                complete,
                f"{unit['unit_id']} could not be completed: objectives {missing_objectives}, "
                f"knowledge {missing_knowledge}",
            )
            self.assertIn(unit["unit_id"], profile["current_course_position"]["completed_unit_ids"])
            if index + 1 < len(ordered):
                next_unit = ordered[index + 1]
                self.assertIn(
                    next_unit["unit_id"],
                    profile["current_course_position"]["unlocked_unit_ids"],
                    f"{next_unit['unit_id']} did not unlock after {unit['unit_id']}",
                )
        validate_profile(profile, all_curricula, PROFILE_SCHEMA)
        self.assertEqual(len(profile["current_course_position"]["completed_unit_ids"]), 32)

    def test_full_loop_keeps_history_and_is_idempotent(self) -> None:
        all_curricula = curricula()
        profile = init_profile(load_json(PLACEMENT_FIXTURE), all_curricula)
        with TemporaryDirectory() as directory:
            output = Path(directory)
            source = output / "English_Learning_Profile.json"
            source.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")

            # Lesson 1: record real evidence, export, reload.
            unit = units_index()["PRE_A1-U01"]
            profile["session_log"].append(
                {"session_id": "session_0001", "date": "2026-10-09", "evidence_ids": [], "review_outcomes": [], "new_item_ids": []}
            )
            for position, objective in enumerate(unit["objectives"]):
                record = objective_evidence(
                    unit["unit_id"],
                    objective,
                    evidence_id=f"evidence_loop_{position:04d}",
                    session_id="session_0001",
                    date_value="2026-10-09",
                )
                profile["practice_evidence"].append(record)
                profile["session_log"][-1]["evidence_ids"].append(record["evidence_id"])
            normalize_profile(profile, all_curricula)
            first = export_profile(profile, source, date(2026, 10, 9), output)
            reloaded = load_json(first)
            validate_profile(reloaded, all_curricula, PROFILE_SCHEMA)
            evidence_count = len(reloaded["practice_evidence"])
            session_count = len(reloaded["session_log"])

            # Lesson 2: reload -> prepare -> record -> export again.
            reloaded["session_log"].append(
                {"session_id": "session_0002", "date": "2026-10-10", "evidence_ids": [], "review_outcomes": [], "new_item_ids": []}
            )
            unit_two = units_index()["PRE_A1-U02"]
            for position, objective in enumerate(unit_two["objectives"]):
                record = objective_evidence(
                    unit_two["unit_id"],
                    objective,
                    evidence_id=f"evidence_loop_{position + 10:04d}",
                    session_id="session_0002",
                    date_value="2026-10-10",
                )
                reloaded["practice_evidence"].append(record)
                reloaded["session_log"][-1]["evidence_ids"].append(record["evidence_id"])
            normalize_profile(reloaded, all_curricula)
            second = export_profile(reloaded, first, date(2026, 10, 10), output)
            final = load_json(second)
            validate_profile(final, all_curricula, PROFILE_SCHEMA)

            self.assertGreater(len(final["practice_evidence"]), evidence_count)
            self.assertGreater(len(final["session_log"]), session_count)
            self.assertIn("PRE_A1-U01", final["current_course_position"]["completed_unit_ids"])
            self.assertIn("PRE_A1-U02", final["current_course_position"]["completed_unit_ids"])
            self.assertEqual(json.loads(source.read_text(encoding="utf-8"))["profile_revision"], 1)
            self.assertEqual(first.name, "English_Learning_Profile_updated_2026-10-09.json")

    def test_normalization_and_export_are_idempotent(self) -> None:
        all_curricula = curricula()
        profile = init_profile(load_json(PLACEMENT_FIXTURE), all_curricula)
        normalize_profile(profile, all_curricula)
        once = deepcopy(profile)
        normalize_profile(profile, all_curricula)
        self.assertEqual(profile, once)
        with TemporaryDirectory() as directory:
            output = Path(directory)
            source = output / "English_Learning_Profile.json"
            source.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            first = export_profile(profile, source, date(2026, 10, 8), output)
            payload = load_json(first)
            second = export_profile(payload, first, date(2026, 10, 8), output)
            self.assertEqual(
                json.dumps(load_json(first), sort_keys=True),
                json.dumps(load_json(second), sort_keys=True),
            )

    def test_normalization_never_shrinks_history(self) -> None:
        all_curricula = curricula()
        profile = load_json(EXAMPLE)
        before_evidence = len(profile["practice_evidence"])
        before_sessions = len(profile["session_log"])
        normalize_profile(profile, all_curricula)
        self.assertGreaterEqual(len(profile["practice_evidence"]), before_evidence)
        self.assertGreaterEqual(len(profile["session_log"]), before_sessions)

    def test_python_failure_never_reports_success(self) -> None:
        from tools.learning_data import main

        with TemporaryDirectory() as directory:
            output = Path(directory)
            broken = output / "broken.json"
            broken.write_text("{not json", encoding="utf-8")
            self.assertEqual(main(["prepare", "--profile", str(broken)]), 2)
            missing = output / "missing.json"
            self.assertEqual(main(["prepare", "--profile", str(missing)]), 2)
            invalid = output / "invalid.json"
            invalid.write_text(json.dumps({"schema_version": "3.0"}), encoding="utf-8")
            self.assertEqual(main(["export", "--profile", str(invalid)]), 2)


class CrossArtifactConsistencyTests(unittest.TestCase):
    """No substantive contradiction between code, schema, curriculum and documents."""

    def read(self, name: str) -> str:
        return (ROOT / name).read_text(encoding="utf-8")

    def test_schema_enums_match_the_code_constants(self) -> None:
        from tools.learning_data import (
            INDEPENDENT_PHASES,
            INDEPENDENT_SUPPORT,
            KNOWLEDGE_STATES,
            LESSON_FLOW,
            LISTENING_CHECK_GRADES,
            SKILL_DIMENSIONS,
        )

        schema = json.loads(self.read("schemas/learning-profile.schema.json"))
        evidence = schema["$defs"]["evidence"]["properties"]
        self.assertEqual(sorted(evidence["skill"]["enum"]), sorted(SKILL_DIMENSIONS))
        self.assertEqual(sorted(evidence["listening_check_grade"]["enum"]), sorted(LISTENING_CHECK_GRADES))
        self.assertEqual(
            sorted(evidence["screening_verification"]["enum"]),
            ["failed", "practice_only", "strict_independent", "unverified_conditions"],
        )
        for field in ("phase", "modality", "support_level", "result", "prompt_novelty"):
            with self.subTest(field=field):
                self.assertTrue(evidence[field]["enum"], f"{field} must be constrained")
        phases = [value for value in evidence["phase"]["enum"] if value is not None]
        for phase in INDEPENDENT_PHASES:
            self.assertIn(phase, phases)
        for level in INDEPENDENT_SUPPORT:
            self.assertIn(level, evidence["support_level"]["enum"])
        states = schema["properties"]["knowledge_state"]["items"]["properties"]["state"]["enum"]
        self.assertEqual(sorted(states), sorted(KNOWLEDGE_STATES))
        self.assertEqual(
            schema["properties"]["current_course_position"]["properties"]["lesson_phase"]["enum"][1:],
            list(LESSON_FLOW),
        )

    def test_curriculum_metadata_matches_the_lesson_flow(self) -> None:
        from tools.learning_data import LESSON_FLOW

        for document in curricula():
            with self.subTest(level=document["level_id"]):
                self.assertEqual(tuple(document["lesson_flow"]), LESSON_FLOW)

    def test_every_objective_gate_is_mode_aware(self) -> None:
        """No objective may demand a listening grade unless it is a listening objective."""
        for document in curricula():
            for unit in document["units"]:
                for objective in unit["objectives"]:
                    with self.subTest(objective=objective["objective_id"]):
                        gated = objective_requires_unseen_listening(objective)
                        if gated:
                            self.assertEqual(objective["mode"], "listening")
                        if objective["mode"] == "listening":
                            self.assertTrue(gated)

    def test_placement_and_listening_rules_are_stated_in_every_layer(self) -> None:
        layers = ("PROJECT_INSTRUCTIONS.md", "English_Learning_Instructions.md", "README.md", "README.zh-CN.md")
        for name in layers:
            text = self.read(name).replace("*", "")
            with self.subTest(document=name):
                self.assertIn("strict_unseen", text)
                self.assertTrue(
                    "one qualifying listening record" in text
                    or ("合格" in text and "听力记录" in text),
                    f"{name} must state the two-skill placement requirement",
                )

    def test_documents_warn_that_voice_records_cannot_prove_pronunciation(self) -> None:
        for name in ("English_Learning_Instructions.md", "README.md", "README.zh-CN.md"):
            text = self.read(name)
            with self.subTest(document=name):
                self.assertTrue("pronunciation" in text or "发音" in text)

    def test_fixtures_and_examples_still_validate(self) -> None:
        for path in (
            ROOT / "tests" / "fixtures" / "English_Learning_Profile.example.json",
            ROOT / "tests" / "fixtures" / "English_Learning_Profile.v2.1.example.json",
        ):
            with self.subTest(fixture=path.name):
                data = load_json(path)
                if data.get("schema_version") == "3.0":
                    validate_profile(data, curricula(), PROFILE_SCHEMA)
                else:
                    from tools.learning_data import migrate_profile

                    validate_profile(migrate_profile(data), curricula(), PROFILE_SCHEMA)


if __name__ == "__main__":
    unittest.main()
