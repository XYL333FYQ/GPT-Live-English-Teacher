# Changelog

## v3.1.1 — Evidence honesty and segment-level repair

### Fixed (P0)

- **`init_profile` invented favourable screening conditions.** Missing `prompt_novelty` was filled with `unseen` and missing `text_shown_before_response` with `false`, so an incomplete screening record could silently credit a whole level and raise the CEFR label. Missing fields are now recorded as `unknown` / `null`, the listening grade is never inferred (not even from otherwise strict-looking fields), and such a record credits nothing. Reproduced: a record with no conditions and every Pre-A1 knowledge id used to credit `PRE_A1-U08` and promote the learner to A1; it now stays `provisional` at `PRE_A1`.
- **A single placement record could satisfy both skill dimensions.** Coverage was inferred from which knowledge ids a record listed, so one `PASS` record with `modality: mixed` and a long id list skipped a level. Placement credit now requires an explicit `skill` on every record, **one qualifying listening record and one qualifying speaking record**, and per-knowledge dimension coverage: each required item must be covered by a record of the dimension that item actually needs.
- **`evidence_is_unseen_listening` accepted records with no `listening_check_grade`.** A record that never declared its conditions counted as a strict unseen pass. The grade must now be explicitly `strict_unseen`, together with `result: PASS`, `prompt_novelty: unseen`, `text_shown_before_response: false`, voice/mixed modality, and no answer-revealing support.
- `evidence_skill_dimensions` no longer infers a dimension from the knowledge classification — that inference was the root cause of the second defect.

### Fixed (P1)

- **Multi-lesson remediation targeted the wrong segment.** With all four segments of `PRE_A1-U03` taught and `PRE_A1-K009` unmastered, the plan repeated the *last* segment (S4) instead of returning to the segment that taught the letters. `plan_lesson` now locates taught-but-unmastered knowledge, maps it to the segment that taught it, and reports `remedial_knowledge_ids`, `target_segment_ids`, and a per-item `segment_id` in the remediation plan. Segment markers still never raise a knowledge state or complete a unit, and already-independent items are left untouched.
- **The newest profile was chosen by filename.** `select_latest_profile` now ranks every candidate by its own `updated_at` then `profile_revision`, reports the full ranking (including files that are not profiles), and `prepare --profile-dir` uses it.

### Added

- `normalize_profile` as the single entry point for derived-state repair: demote unverifiable listening passes to practice, withdraw placement credit the strict rules cannot confirm, rebuild knowledge states from evidence, recompute the course position. It records every downgrade in `migration_history`, never upgrades a record, and never deletes history.
- `screening_verification` on screening evidence (`strict_independent` / `practice_only` / `unverified_conditions` / `failed`), validated against what the record actually proves.
- `level_placement_evidence_gaps` for per-dimension placement diagnostics, and `knowledge_segment_map` / `taught_knowledge_ids` / `segment_is_done` as public helpers.
- `tests/support.py` with two-skill exit-check fixtures, and `tests/test_v311_fixes.py` with 32 regressions covering every scenario in the v3.1.1 brief, including document consistency between `PROJECT_INSTRUCTIONS.md`, the teaching instructions and both READMEs.
- the repository layout now lists `tools/learning_data.py` as an optional Project File so Text Mode can run the deterministic checks in its code sandbox.

### Changed

- legacy profiles carrying the old, looser credit are **downgraded** on the next `prepare` or `export`, not upgraded. A learner who was promoted by a thin screen returns to a genuinely unlocked unit and re-earns the gap.
- a `strict_unseen` grade describes the test *conditions*, so a failed strict check is a valid record (it simply does not count as a pass).
- test count 84 → 116.

## v3.1.0 — Consistency, skill separation, and multi-lesson units

### Fixed (P0)

- **unit completion and unlocking disagreed.** A unit could be completed from objective passes alone while a prerequisite knowledge item of the next unit was never independently demonstrated, which locked the next unit permanently. The repository's own example profile contained this defect (`PRE_A1-U01` complete while `PRE_A1-K001` was never independent). Unit completion now also requires every knowledge item targeted by the unit's required objectives to be `independent`, `mastered`, or `placement_credited`.
- the example profile now carries independent evidence for `PRE_A1-K001`.
- a curriculum-level lint now proves that every `prerequisite_knowledge_ids` entry is owned by a unit inside the dependent unit's prerequisite closure and is part of that owner's completion requirements (`audit_curriculum_prerequisites`).
- missing prerequisite knowledge is turned into an explicit re-teach + independent-check plan (`unlock_blockers`, `plan_lesson`) instead of a silent dead end. A profile that still contains the old inconsistent shape is detected (`deadlock_risk`, `stale_owner_units`) and repaired by `sync`.

### Added

- **`PROJECT_INSTRUCTIONS.md`**: a short, stable file for the ChatGPT Project Instructions field — identity, file load order, source priority, forbidden behaviours, the three triggers, and an explicit statement of what Project Instructions can and cannot guarantee.
- **listening/speaking dimensions** (`required_dimensions`, `skill_states`, `practice_evidence[].skill`): understanding never promotes production, and production never promotes comprehension.
- **graded listening checks** (`listening_check_grade`) and a nullable `text_shown_before_response`: a strict unseen check is the only grade that counts, and an uncertain attempt is downgraded to ordinary listening practice.
- **multi-lesson units** (`lesson_segments`, `completed_lesson_segment_ids`, `learner_preferences.pace`): 26 letters and numbers 0–20 are staged, each lesson has a new-item cap, and the learner can ask to slow down, speed up, review only, or pause.
- **hardened placement credit**: an exit check must cover the level's full exit requirement (exit unit plus the next level's first-unit prerequisites) and span both listening and speaking; `learner_choice` can never credit knowledge.
- **deterministic sync and CLI**: `init-profile`, `prepare`, `plan`, `export`, `audit`, `validate`. `export` recomputes derived fields from evidence, validates, writes a new file, reopens it, and validates again.
- `docs/manual_acceptance.zh-CN.md`: a 15-scenario manual acceptance script for real GPT Live, with an explicit "not verified end to end" marker.
- 39 new tests (83 total), including a dedicated `tests/test_workflow.py` covering all fifteen acceptance scenarios.
- a GitHub Actions workflow that runs the repository validation and the test suite.

### Changed

- knowledge review scheduling is now explicit (`introduced`/`supported` 1–3 days, `independent` 7, `mastered` 30, after a failure 1 day) and is documented separately from the Mastery Ladder.
- long-term mastery now requires a **later date**, not merely another session.
- `UNTESTED` evidence provably changes no state, session list, or review date.
- curriculum version `1.0.0` → `1.1.0`; profiles carrying `1.0.0` still validate.
- README files document the upstream attribution, the exact first-class upload list, the ordinary/review/interrupted flows, and the platform limits.

## v3.0.0 — Structured foundations

- adds an independently authored 32-unit PRE_A1, A1, A2, and B1 curriculum inspired by FreeLingo's ordered-unit structure;
- changes every new-objective lesson to Goal → Demonstration → Repeat → Guided practice → Independent expression → Check → Review;
- adds Chinese scaffolding and gradually increasing English input for true beginners;
- adds profile schema v3.0 with course position, knowledge state, skill weaknesses, and practice evidence;
- makes repetition ineligible for independent mastery and forbids precise pronunciation scoring from transcripts;
- preserves the deterministic Mastery Ladder and non-overwriting JSON export;
- adds lossless profile v2.1 migration, curriculum/profile validation, and standard-library tests.

## v2.2.3 — First public release

- ships the finalized `English_Learning_Instructions.md` v2.2.3;
- includes bilingual, product-focused README files;
- includes the hero collage, workflow poster, and GitHub social preview;
- uses CC BY 4.0 for the instruction and documentation, with MIT for test code;
- includes a lightweight test for profile data and memory-engine transitions.
