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
    load_json,
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


if __name__ == "__main__":
    unittest.main()
