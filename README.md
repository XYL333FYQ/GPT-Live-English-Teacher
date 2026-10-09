# GPT Live English Teacher

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <strong>A ChatGPT Project + GPT Live personal tutor designed for true Pre-A1 beginners.</strong>
</p>

This repository is not a standalone app or backend. It provides project-ready teaching instructions, curriculum JSON, a learner-profile schema, and lightweight Python validation tools.

## Origin, attribution, and license

- **Upstream project**: [`loiqy/GPT-Live-English-Coach`](https://github.com/loiqy/GPT-Live-English-Coach) (Liqin Luo, v2.2.3, 2026-07-11). This project is a derivative: the GPT Live voice lesson, live correction, Mastery Ladder spaced review, JSON memory, and non-overwriting export all come from it.
- **Upstream license**: instructions, documentation, profile template, and images use **CC BY 4.0** (`LICENSE`); code under `tests/` uses **MIT** (`tests/LICENSE`). This repository keeps the same split.
- **Curriculum inspiration**: [FreeLingo](https://github.com/artcc/freelingo)'s ordered CEFR units, prerequisites, and competency checklists. The curriculum text, evidence model, and workflow here are independently authored.
- **What changed**: see `CHANGELOG.md`. This derivative adds a 32-unit PRE_A1–B1 curriculum, knowledge-coverage completion, separate listening/speaking evidence, multi-lesson units, strict placement credit, and deterministic tooling. It adds **no** web app, backend, database, or third-party speech API.

## What v3.1 adds

The original GPT Live voice lesson, correction, spaced-review, JSON memory, and file-export workflow remain. This version adds:

- 32 ordered units and 128 knowledge items across `PRE_A1 → A1 → A2 → B1`;
- explicit prerequisites, Can-Do objectives, language scope, and completion criteria for every unit;
- a required lesson sequence: **Goal → Demonstration → Repeat → Guided practice → Independent expression → Check → Review**, run as a teaching loop rather than a recited script;
- Chinese support by default at Pre-A1, reduced as English ability grows;
- **unit completion = objectives passed + every knowledge item those objectives target independently demonstrated**, which makes "unit complete but next unit locked" impossible to write into a profile;
- **separate listening and speaking dimensions** per knowledge item: understanding never implies production, and production never implies comprehension at another speed; an objective only accepts evidence of its own skill, and a contradictory record proves nothing;
- **multi-lesson units**: letters, numbers, and other heavy items are staged into lesson segments with a per-lesson cap on new material; a weak segment is repaired at that segment, not by repeating the whole unit;
- **strict placement (hardened in v3.1.1)**: skipping a level requires **one qualifying listening record and one qualifying speaking record**, each covering the level's real requirements. A single integrated record can never prove both;
- **missing fields are never favourable (v3.1.1)**: an unstated prompt novelty, text exposure, or listening grade is recorded as `unknown` / `null` and credits nothing, so a thin screen can never raise the CEFR level;
- **graded listening checks**: a strict unseen pass must state `listening_check_grade: strict_unseen` explicitly, and only listening objectives need it; an attempt whose text exposure cannot be ruled out is downgraded to practice;
- **status labels match the rules (v3.1.2)**: a screening record is labelled `strict_independent` exactly when it earns credit;
- **real-time profile ordering (v3.1.2)**: profiles are ordered by parsed ISO 8601 instants converted to UTC, so mixed timezones compare correctly; a missing or invalid timestamp is reported, never preferred, and two equally new profiles with different content stop the selection instead of overwriting progress;
- strict separation of repetition from independent mastery, and no precise pronunciation claims from speech transcripts;
- lossless v2.1 migration, non-overwriting export, deterministic `sync` that may downgrade unverifiable records but never upgrades them, and automated integrity tests that walk all 32 units end to end.

## Quick start

### Create a ChatGPT Project

**Project Instructions** — paste the body of `PROJECT_INSTRUCTIONS.md` into the Project's Instructions field. It sets the identity, file load order, source priority, forbidden behaviours, and the three trigger phrases. It cannot force the model to read a file, cannot execute code, and cannot change how GPT Live sounds.

**Project Files** — add these once and keep them:

- `English_Learning_Instructions.md`
- `curriculum/PRE_A1.json`
- `curriculum/A1.json`
- `curriculum/A2.json`
- `curriculum/B1.json`
- `schemas/learning-profile.schema.json`
- `tools/learning_data.py` (**optional**, useful only when Text Mode can run code — see below)

For the **first class you upload exactly those six required files**. `PROJECT_INSTRUCTIONS.md` goes into Instructions instead of being uploaded. The learner profile is created at the end of the first class and uploaded from the second class onward.

### How the Python tool is actually used

`tools/learning_data.py` is a repository script; it is **not wired into GPT Live**. It runs:

- **inside ChatGPT Text Mode's code sandbox**, when that conversation can execute code — add the file to Project Files and the model can call it for deterministic validation, pre-flight preparation, and export;
- or on your own machine if you have Python installed, which is optional.

Daily use needs no commands at all: **enter Live → `Class is over, export data.` → download the new profile and upload it next time.** Without code execution the model must validate by hand and tell you that deterministic validation and export did not run, rather than pretending they did.

### First class

1. Start a conversation in the Project.
2. Send `Start my first class.`
3. Enter GPT Live when invited. A beginner may use Chinese.
4. Return to Text Mode and send `Test finished`.
5. Download `English_Learning_Profile.json`.

Placement starts with the lowest-demand tasks. It does not ask a zero beginner for a narrative, abstract opinion, or debate. If the evidence is thin, the coach keeps the learner `provisional` and runs one short bridge check instead of promoting them.

### Ordinary class

1. Upload the latest profile JSON.
2. Send `Prepare for class`. The model picks the newest profile by its own `updated_at` and `profile_revision` — never by filename — and tells you which one it chose.
3. Read the brief: unit, **lesson segment**, today's goal, new-item cap, due reviews, and any knowledge gap.
4. Enter GPT Live and run the lesson.
5. Return to Text Mode and send `Class is over, export data.`
6. Download `English_Learning_Profile_updated_YYYY-MM-DD.json` and keep it for the next lesson.

### Review class, pacing, and interruption

- The learner can say `Slower`, `Faster`, `Review only`, or `Pause` at any time. `Faster` is still capped by the curriculum and never skips a check; `Slower` drops new material to one item; `Review only` adds nothing new.
- `Class is over` at any moment is fine: untouched checks are recorded `UNTESTED` and nothing else changes.
- The next `Prepare for class` resumes at the same lesson segment.

The source profile is never overwritten. Existing export names receive `_2`, `_3`, and so on.

## Levels

| Level | Focus | Chinese support | Target English input |
|---|---|---|---:|
| Pre-A1 | Classroom repair, names, letters, numbers, basic needs, survival interaction | Default | 20% → 45% |
| A1 | Personal details, routines, places, shopping, past events, plans | On request or when blocked | 45% → 70% |
| A2 | Short narratives, comparison, experience, advice, service problems, opinions | Brief and on request | 70% → 85% |
| B1 | Connected stories, cause, evidence, negotiation, register, real-world topics | Exceptional support | 85% → 95% |

A unit unlocks only when prior units are complete or explicitly placement-credited by an unseen integrated check, and its knowledge prerequisites are independently qualified. Placement never fabricates ordinary lesson completion, and repetition never supplies placement evidence. Because completion itself requires knowledge coverage, a profile can no longer record a completed unit whose own prerequisites are missing: the tool reports the missing items and schedules a short re-teach plus independent check.

## Evidence rules

Knowledge progresses through:

`not_started → introduced → supported → independent → mastered`

`placement_credited` is reserved for independently demonstrated placement evidence.

- Demonstration can establish only `introduced`.
- Repetition and answer-revealing prompts can establish at most `supported`.
- A new task without answer-revealing support is required for `independent`.
- `mastered` requires independent passes in at least two sessions **on different dates**, including a later check or review.
- Every knowledge item is tracked in two dimensions, `listening` and `speaking`, and its reported state is the weaker required dimension.

Pronunciation records are qualitative and require direct Live audio. A transcript alone must be marked `not_assessed`. This version never reports numeric, percentage, phoneme-level, or acoustic pronunciation scores.

## Profile v3.0

The original `scientific_assessment`, `active_repertoire`, and `session_log` remain. New sections are:

- `learning_track`;
- `current_course_position`, including the current lesson segment;
- `knowledge_state`, including per-dimension skill states;
- `skill_weaknesses` for listening, speaking, and pronunciation;
- `practice_evidence`, including skill dimension, prompt novelty, whether text was shown before the response, and the listening check grade;
- optional `learner_preferences.pace`;
- optional `migration_history`.

Migration preserves v2.1 fields, review stages, dates, sessions, and compatible extensions. B2–C2 profiles remain in `legacy_conversation`; Pre-A1–B1 profiles receive a bridge check before a unit is selected.

## Repository layout

```text
PROJECT_INSTRUCTIONS.md            # paste into ChatGPT Project Instructions
English_Learning_Instructions.md   # detailed teaching and data rules
curriculum/{PRE_A1,A1,A2,B1}.json  # PRE_A1 carries lesson_segments
schemas/{curriculum,learning-profile}.schema.json
tools/learning_data.py             # validate / audit / init-profile / prepare / plan / export
tests/                             # 156 tests, including the 15 acceptance scenarios
  support.py                       # shared two-skill exit-check fixtures
  test_v311_fixes.py               # evidence-honesty regressions
  test_v312_freeze.py              # stability-freeze regressions
docs/manual_acceptance.zh-CN.md    # real GPT Live manual acceptance script
```

## Validation

No third-party dependencies are required:

```bash
python tools/learning_data.py validate
python tools/learning_data.py audit --json
python -m unittest discover -s tests -v
```

The tests execute the JSON Schemas and cover curriculum references, the full prerequisite audit, the seven-phase flow, hardened cross-level placement, unseen-listening evidence and downgrading, per-dimension skill evidence, multi-lesson pacing, v2.1 migration, the deterministic review queue, pronunciation limits, export revalidation, all fifteen acceptance scenarios, the v3.1.1 evidence-honesty regressions, and the v3.1.2 freeze suite: objectives only accept their own skill, a screening label matches its rule, profiles are ordered by real UTC instants, all 32 units can be completed in prerequisite order, and the schema, curriculum, code and documents agree with each other.

## Limitations

- This is not an official CEFR, IELTS, or pronunciation assessment.
- GPT Live, file tools, and voice behavior may change with ChatGPT.
- The repository's Python tools are **not** wired into GPT Live. They only run when Text Mode can execute code; without it, validation and export must be done by hand and reported as such. Everyday use needs no commands.
- Project Instructions cannot force file reads and cannot verify that a file was opened.
- No audio is stored and no acoustic analysis is performed.
- B1 current-topic work depends on web search; Pre-A1 and A1 do not depend on news discussion.
- Automated tests cover the data layer only. Real GPT Live behaviour must be verified with `docs/manual_acceptance.zh-CN.md`.
- v3.1.1 / v3.1.2 tightened the rules: profiles that previously passed on missing fields are **downgraded** on the next `Prepare for class` or export (an unverifiable listening pass becomes practice, an unverifiable level skip is withdrawn, a record whose skill contradicted its objective is detached). That is intentional, not a bug.

## Version and license

- Instruction: **v3.1.2**
- Profile schema: **3.0**
- Curriculum: **1.1.0** (1.0.0 profiles still validate)
- Instructions, curriculum, documentation, schemas, and example profile use CC BY 4.0 under `LICENSE`, inherited from `loiqy/GPT-Live-English-Coach`.
- Python files under `tools/` and `tests/` use the MIT license under `tests/LICENSE` (upstream author Liqin Luo).
