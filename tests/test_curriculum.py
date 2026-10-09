#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from tools.learning_data import (
    CURRICULUM_LEVELS,
    LESSON_FLOW,
    ValidationError,
    audit_curriculum_prerequisites,
    load_json,
    unit_knowledge_requirements,
    unit_lesson_segments,
    validate_curricula,
    validate_schema_instance,
)

ROOT = Path(__file__).resolve().parents[1]
CURRICULUM_SCHEMA = load_json(ROOT / "schemas" / "curriculum.schema.json")


def load_curricula() -> list[dict]:
    return [load_json(ROOT / "curriculum" / f"{level}.json") for level in CURRICULUM_LEVELS]


class CurriculumIntegrityTests(unittest.TestCase):
    def test_all_curricula_are_valid(self) -> None:
        validate_curricula(load_curricula(), CURRICULUM_SCHEMA)

    def test_schema_files_are_valid_and_applied(self) -> None:
        profile_schema = json.loads((ROOT / "schemas" / "learning-profile.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(CURRICULUM_SCHEMA["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(profile_schema["properties"]["schema_version"]["const"], "3.0")
        broken = deepcopy(load_curricula()[0])
        del broken["units"][0]["completion_criteria"]["repeat_after_model_counts_as_independent"]
        with self.assertRaises(ValidationError):
            validate_schema_instance(broken, CURRICULUM_SCHEMA)

    def test_each_level_has_eight_units_and_required_flow(self) -> None:
        for curriculum in load_curricula():
            self.assertEqual(len(curriculum["units"]), 8)
            self.assertEqual(tuple(curriculum["lesson_flow"]), LESSON_FLOW)

    def test_cross_level_prerequisites_are_explicit(self) -> None:
        curricula = load_curricula()
        self.assertEqual(curricula[0]["units"][0]["prerequisite_units"], [])
        self.assertEqual(curricula[1]["units"][0]["prerequisite_units"], ["PRE_A1-U08"])
        self.assertEqual(curricula[2]["units"][0]["prerequisite_units"], ["A1-U08"])
        self.assertEqual(curricula[3]["units"][0]["prerequisite_units"], ["A2-U08"])

    def test_english_input_increases_by_level(self) -> None:
        starts = [curriculum["support_policy"]["english_input_percent_start"] for curriculum in load_curricula()]
        ends = [curriculum["support_policy"]["english_input_percent_end"] for curriculum in load_curricula()]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(ends, sorted(ends))

    def test_forward_prerequisite_is_rejected(self) -> None:
        curricula = load_curricula()
        broken = deepcopy(curricula)
        broken[0]["units"][0]["prerequisite_units"] = ["PRE_A1-U08"]
        with self.assertRaises(ValidationError):
            validate_curricula(broken)

    def test_unknown_knowledge_reference_is_rejected(self) -> None:
        curricula = load_curricula()
        broken = deepcopy(curricula)
        broken[0]["units"][0]["objectives"][0]["target_knowledge_ids"] = ["PRE_A1-K999"]
        with self.assertRaises(ValidationError):
            validate_curricula(broken)

    def test_untargeted_local_knowledge_is_rejected(self) -> None:
        curricula = load_curricula()
        broken = deepcopy(curricula)
        knowledge_id = broken[0]["units"][0]["knowledge"][0]["knowledge_id"]
        for objective in broken[0]["units"][0]["objectives"]:
            objective["target_knowledge_ids"] = [
                target for target in objective["target_knowledge_ids"] if target != knowledge_id
            ]
        with self.assertRaises(ValidationError):
            validate_curricula(broken)

    def test_repetition_and_transcript_cannot_satisfy_completion(self) -> None:
        curricula = load_curricula()
        broken_repeat = deepcopy(curricula)
        broken_repeat[0]["units"][0]["completion_criteria"]["repeat_after_model_counts_as_independent"] = True
        with self.assertRaises(ValidationError):
            validate_curricula(broken_repeat)

        broken_transcript = deepcopy(curricula)
        broken_transcript[0]["units"][0]["completion_criteria"]["transcript_only_pronunciation_scoring_allowed"] = True
        with self.assertRaises(ValidationError):
            validate_curricula(broken_transcript)


class PrerequisiteAuditTests(unittest.TestCase):
    """P0 regression: unit completion and the next unit's unlock must agree."""

    def test_full_curriculum_audit_is_clean(self) -> None:
        audit = audit_curriculum_prerequisites(load_curricula())
        self.assertTrue(audit["ok"], audit["issues"])
        self.assertEqual(audit["units"], 32)
        self.assertEqual(audit["knowledge_items"], 128)
        self.assertEqual(audit["prerequisite_knowledge_edges"], 89)

    def test_every_prerequisite_knowledge_is_inside_the_owners_completion_requirements(self) -> None:
        curricula = load_curricula()
        requirements = {
            unit["unit_id"]: set(unit_knowledge_requirements(unit))
            for document in curricula
            for unit in document["units"]
        }
        owner = {
            entry["knowledge_id"]: unit["unit_id"]
            for document in curricula
            for unit in document["units"]
            for entry in unit["knowledge"]
        }
        for document in curricula:
            for unit in document["units"]:
                for knowledge_id in unit["prerequisite_knowledge_ids"]:
                    self.assertIn(
                        knowledge_id,
                        requirements[owner[knowledge_id]],
                        f"{unit['unit_id']} requires {knowledge_id}, which its owner unit never requires",
                    )

    def test_prerequisite_knowledge_outside_the_closure_is_rejected(self) -> None:
        curricula = load_curricula()
        broken = deepcopy(curricula)
        broken[1]["units"][0]["prerequisite_units"] = []
        with self.assertRaises(ValidationError) as context:
            validate_curricula(broken)
        self.assertTrue(
            any("outside the prerequisite closure" in error for error in context.exception.errors)
        )


class LessonSegmentTests(unittest.TestCase):
    """P1 regression: a unit may span several lessons without losing coverage."""

    def test_pre_a1_units_are_segmented_and_cover_everything(self) -> None:
        pre_a1 = load_curricula()[0]
        for unit in pre_a1["units"]:
            segments = unit_lesson_segments(unit)
            self.assertGreaterEqual(len(segments), 2, unit["unit_id"])
            covered = {knowledge_id for segment in segments for knowledge_id in segment["knowledge_ids"]}
            self.assertEqual(covered, {entry["knowledge_id"] for entry in unit["knowledge"]})
            for segment in segments:
                self.assertLessEqual(segment["max_new_items"], 5)

    def test_letters_and_numbers_are_staged_over_several_lessons(self) -> None:
        pre_a1 = load_curricula()[0]
        units = {unit["unit_id"]: unit for unit in pre_a1["units"]}
        letters = unit_lesson_segments(units["PRE_A1-U03"])
        numbers = unit_lesson_segments(units["PRE_A1-U04"])
        self.assertEqual(len(letters), 4)
        self.assertEqual(len(numbers), 3)
        self.assertTrue(any("A–M" in segment["focus_zh"] for segment in letters))
        self.assertTrue(any("N–Z" in segment["focus_zh"] for segment in letters))
        self.assertTrue(any("0–10" in segment["focus_zh"] for segment in numbers))

    def test_auto_segmentation_applies_to_units_without_authored_segments(self) -> None:
        a1_unit = load_curricula()[1]["units"][0]
        segments = unit_lesson_segments(a1_unit)
        self.assertGreaterEqual(len(segments), 1)
        self.assertTrue(all(segment["auto_generated"] for segment in segments))
        covered = {knowledge_id for segment in segments for knowledge_id in segment["knowledge_ids"]}
        self.assertEqual(covered, set(unit_knowledge_requirements(a1_unit)))

    def test_segment_that_misses_knowledge_is_rejected(self) -> None:
        broken = deepcopy(load_curricula())
        broken[0]["units"][0]["lesson_segments"][0]["knowledge_ids"] = ["PRE_A1-K001"]
        broken[0]["units"][0]["lesson_segments"][1]["knowledge_ids"] = ["PRE_A1-K002"]
        with self.assertRaises(ValidationError) as context:
            validate_curricula(broken)
        self.assertTrue(any("must cover every local knowledge item" in error for error in context.exception.errors))

    def test_segment_over_the_level_limit_is_rejected(self) -> None:
        broken = deepcopy(load_curricula())
        broken[0]["units"][0]["lesson_segments"][0]["max_new_items"] = 9
        with self.assertRaises(ValidationError) as context:
            validate_curricula(broken)
        self.assertTrue(any("exceeds level limit" in error for error in context.exception.errors))

    def test_segment_with_unknown_knowledge_is_rejected(self) -> None:
        broken = deepcopy(load_curricula())
        broken[0]["units"][0]["lesson_segments"][0]["knowledge_ids"] = ["PRE_A1-K001", "PRE_A1-K999"]
        with self.assertRaises(ValidationError):
            validate_curricula(broken)


if __name__ == "__main__":
    unittest.main()
