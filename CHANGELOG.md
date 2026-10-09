# Changelog

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
