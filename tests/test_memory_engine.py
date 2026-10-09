#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import date
import unittest

from tools.learning_data import (
    adaptive_new_repertoire_count,
    apply_knowledge_evidence,
    evidence_is_placement_credit,
    prepare_review_queue,
    pronunciation_claim_allowed,
    update_repertoire_item,
)


class MasteryLadderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.today = date(2026, 10, 8)
        self.item = {
            "item_id": "item_0001",
            "item": "Please say it again.",
            "item_type": "core_vocabulary",
            "stage": 0,
            "status": "active",
            "next_review_date": "2026-10-08",
            "last_review_date": None,
            "last_outcome": None,
            "lapse_count": 0,
            "selection_defer_once": False,
        }

    def test_active_stage_progression(self) -> None:
        current = self.item
        current_day = self.today
        observed = []
        for _ in range(6):
            current = update_repertoire_item(current, "PASS", current_day)
            next_day = date.fromisoformat(current["next_review_date"])
            observed.append((current["status"], current["stage"], (next_day - current_day).days))
            current_day = next_day
        self.assertEqual(
            observed,
            [
                ("active", 1, 3),
                ("active", 2, 7),
                ("active", 3, 14),
                ("active", 4, 30),
                ("active", 5, 60),
                ("mastered", 5, 365),
            ],
        )

    def test_partial_fail_and_untested(self) -> None:
        partial_source = {**self.item, "stage": 4}
        partial = update_repertoire_item(partial_source, "PARTIAL", self.today)
        self.assertEqual(partial["stage"], 3)
        self.assertEqual(partial["next_review_date"], "2026-10-22")

        failed = update_repertoire_item({**self.item, "stage": 5}, "FAIL", self.today)
        self.assertEqual(failed["stage"], 0)
        self.assertEqual(failed["lapse_count"], 1)
        self.assertEqual(failed["next_review_date"], "2026-10-09")

        original = {**self.item, "stage": 3, "lapse_count": 2, "next_review_date": "2026-10-05"}
        untested = update_repertoire_item(original, "UNTESTED", self.today)
        for field in ("stage", "status", "lapse_count", "next_review_date", "last_review_date", "last_outcome"):
            self.assertEqual(untested[field], original[field])
        self.assertTrue(untested["selection_defer_once"])

    def test_mastered_recheck_rules(self) -> None:
        mastered = {**self.item, "stage": 5, "status": "mastered"}
        passed = update_repertoire_item(mastered, "PASS", self.today)
        self.assertEqual(passed["status"], "mastered")
        self.assertEqual(passed["next_review_date"], "2027-10-08")

        partial = update_repertoire_item(mastered, "PARTIAL", self.today)
        self.assertEqual((partial["status"], partial["stage"], partial["next_review_date"]), ("active", 4, "2026-11-07"))

        failed = update_repertoire_item(mastered, "FAIL", self.today)
        self.assertEqual((failed["status"], failed["stage"], failed["lapse_count"]), ("active", 0, 1))

    def test_queue_is_deterministic_and_defer_lasts_one_cycle(self) -> None:
        def item(item_id: str, item_type: str, defer: bool, lapse: int = 0) -> dict:
            return {
                **self.item,
                "item_id": item_id,
                "item_type": item_type,
                "next_review_date": "2026-10-07",
                "selection_defer_once": defer,
                "lapse_count": lapse,
            }

        items = [
            item("item_a", "chunk_&_idiom", False),
            item("item_b", "core_vocabulary", False),
            item("item_c", "chunk_&_idiom", False, lapse=2),
            {**item("item_d", "core_vocabulary", True), "next_review_date": "2026-10-01"},
        ]
        selected, working = prepare_review_queue(items, self.today, daily_review_limit=4)
        self.assertEqual([entry["item_id"] for entry in selected], ["item_c", "item_b", "item_a", "item_d"])
        self.assertFalse(next(entry for entry in working if entry["item_id"] == "item_d")["selection_defer_once"])
        self.assertTrue(next(entry for entry in items if entry["item_id"] == "item_d")["selection_defer_once"])

    def test_adaptive_new_item_count_uses_complete_due_queue(self) -> None:
        due = [{**self.item, "item_id": f"item_{index}"} for index in range(5)]
        self.assertEqual(adaptive_new_repertoire_count([], self.today), 2)
        self.assertEqual(adaptive_new_repertoire_count(due, self.today), 1)
        self.assertEqual(adaptive_new_repertoire_count(due + due[:3], self.today), 0)
        overdue = [{**self.item, "next_review_date": "2026-10-07"}]
        self.assertEqual(adaptive_new_repertoire_count(overdue, self.today), 0)


class EvidenceSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {
            "knowledge_id": "PRE_A1-K005",
            "unit_id": "PRE_A1-U02",
            "state": "not_started",
            "evidence_ids": [],
            "independent_pass_sessions": [],
            "review_pass_sessions": [],
            "last_review_date": None,
            "next_review_date": None,
        }

    def evidence(self, evidence_id: str, session_id: str, phase: str, support: str, result: str) -> dict:
        return {
            "evidence_id": evidence_id,
            "session_id": session_id,
            "phase": phase,
            "objective_id": None if phase == "placement" else "PRE_A1-O003",
            "knowledge_ids": ["PRE_A1-K005"],
            "modality": "voice",
            "support_level": support,
            "result": result,
            "prompt_novelty": "unseen" if phase in {"placement", "independent_expression", "check", "review"} else "rehearsed",
            "text_shown_before_response": False,
        }

    def test_repetition_never_becomes_independent(self) -> None:
        repeated = apply_knowledge_evidence(
            self.state,
            self.evidence("e1", "s1", "repeat_after_model", "model_immediately_before", "PRACTICED"),
        )
        self.assertEqual(repeated["state"], "supported")
        self.assertEqual(repeated["independent_pass_sessions"], [])

    def test_guided_success_never_becomes_independent(self) -> None:
        guided = apply_knowledge_evidence(
            self.state,
            self.evidence("e1", "s1", "guided_practice", "sentence_starter", "PASS"),
        )
        self.assertEqual(guided["state"], "supported")

    def test_mastery_needs_a_later_review(self) -> None:
        first = apply_knowledge_evidence(
            self.state,
            self.evidence("e1", "s1", "check", "none", "PASS"),
        )
        second = apply_knowledge_evidence(
            first,
            self.evidence("e2", "s2", "independent_expression", "none", "PASS"),
        )
        self.assertEqual(second["state"], "independent")
        third = apply_knowledge_evidence(
            second,
            self.evidence("e3", "s3", "review", "non_revealing_context", "PASS"),
            mastery_requires_distinct_sessions=3,
        )
        self.assertEqual(third["state"], "mastered")
        self.assertEqual(third["independent_pass_sessions"], ["s1", "s2", "s3"])

    def test_placement_credit_requires_independent_unseen_evidence(self) -> None:
        credited = apply_knowledge_evidence(
            self.state,
            self.evidence("e1", "placement_1", "placement", "none", "PASS"),
        )
        self.assertEqual(credited["state"], "placement_credited")

    def test_placement_rejects_text_or_visible_answers(self) -> None:
        evidence = self.evidence("e1", "placement_1", "placement", "none", "PASS")
        evidence["modality"] = "text"
        self.assertFalse(evidence_is_placement_credit(evidence))
        evidence["modality"] = "voice"
        evidence["text_shown_before_response"] = True
        self.assertFalse(evidence_is_placement_credit(evidence))

    def test_failure_does_not_promote_unstarted_knowledge(self) -> None:
        failed = apply_knowledge_evidence(
            self.state,
            self.evidence("e1", "s1", "check", "none", "FAIL"),
        )
        self.assertEqual(failed["state"], "not_started")

    def test_mastered_state_survives_an_independent_pass(self) -> None:
        mastered = {**self.state, "state": "mastered", "independent_pass_sessions": ["s1", "s2"]}
        passed = apply_knowledge_evidence(
            mastered,
            self.evidence("e3", "s3", "independent_expression", "none", "PASS"),
        )
        self.assertEqual(passed["state"], "mastered")

    def test_revealing_prompt_does_not_count(self) -> None:
        supported = apply_knowledge_evidence(
            self.state,
            self.evidence("e1", "s1", "check", "sentence_starter", "PASS"),
        )
        self.assertNotEqual(supported["state"], "independent")
        self.assertEqual(supported["independent_pass_sessions"], [])

    def test_pronunciation_claim_boundary(self) -> None:
        self.assertFalse(pronunciation_claim_allowed("transcript_only", "word_stress"))
        self.assertFalse(pronunciation_claim_allowed("direct_live_audio", "numeric_score"))
        self.assertTrue(pronunciation_claim_allowed("direct_live_audio", "intelligibility"))


if __name__ == "__main__":
    unittest.main()
