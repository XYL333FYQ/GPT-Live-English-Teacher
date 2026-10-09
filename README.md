# GPT Live English Coach

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <strong>A ChatGPT Project + GPT Live personal tutor designed for true Pre-A1 beginners.</strong>
</p>

This repository is not a standalone app or backend. It provides project-ready teaching instructions, curriculum JSON, a learner-profile schema, and lightweight Python validation tools.

## What v3.0 adds

The original GPT Live voice lesson, correction, spaced-review, JSON memory, and file-export workflow remain. This version adds:

- 32 ordered units across `PRE_A1 → A1 → A2 → B1`;
- explicit prerequisites, Can-Do objectives, language scope, and completion criteria for every unit;
- a required lesson sequence: **Goal → Demonstration → Repeat → Guided practice → Independent expression → Check → Review**;
- Chinese support by default at Pre-A1, reduced as English ability grows;
- current course position, knowledge state, listening/speaking/pronunciation weaknesses, and practice evidence in profile v3.0;
- strict separation of repetition from independent mastery;
- no precise pronunciation claims from speech transcripts;
- lossless v2.1 migration, non-overwriting export, and automated integrity tests.

## Quick start

### Create a ChatGPT Project

Add these static files to one Project:

- `English_Learning_Instructions.md`
- `curriculum/PRE_A1.json`
- `curriculum/A1.json`
- `curriculum/A2.json`
- `curriculum/B1.json`
- `schemas/learning-profile.schema.json`

### First class

1. Start a conversation in the Project.
2. Send `Start my first class.`
3. Enter GPT Live when invited. A beginner may use Chinese.
4. Return to Text Mode and send `Test finished`.
5. Download `English_Learning_Profile.json`.

Placement starts with the lowest-demand tasks. It does not ask a zero beginner for a narrative, abstract opinion, or debate.

### Later classes

1. Upload the latest profile JSON.
2. Send `Prepare for class`.
3. Enter GPT Live after reviewing the goal.
4. Return to Text Mode and send `Class is over, export data.`
5. Download the new `English_Learning_Profile_updated_YYYY-MM-DD.json`.

The source profile is never overwritten. Existing export names receive `_2`, `_3`, and so on.

## Levels

| Level | Focus | Chinese support | Target English input |
|---|---|---|---:|
| Pre-A1 | Classroom repair, names, letters, numbers, basic needs, survival interaction | Default | 20% → 45% |
| A1 | Personal details, routines, places, shopping, past events, plans | On request or when blocked | 45% → 70% |
| A2 | Short narratives, comparison, experience, advice, service problems, opinions | Brief and on request | 70% → 85% |
| B1 | Connected stories, cause, evidence, negotiation, register, real-world topics | Exceptional support | 85% → 95% |

A unit unlocks only when prior units are complete or explicitly placement-credited by an unseen integrated check, and its knowledge prerequisites are independently qualified. Placement never fabricates ordinary lesson completion, and repetition never supplies placement evidence.

The structure takes inspiration from [FreeLingo](https://github.com/artcc/freelingo)'s ordered CEFR units, prerequisites, competency checklists, and integrity tests. This curriculum and evidence model are independently authored; FreeLingo's backend, database, XP, and dynamic exercise system are not included.

## Evidence rules

Knowledge progresses through:

`not_started → introduced → supported → independent → mastered`

`placement_credited` is reserved for independently demonstrated placement evidence.

- Demonstration can establish only `introduced`.
- Repetition and answer-revealing prompts can establish at most `supported`.
- A new task without answer-revealing support is required for `independent`.
- `mastered` requires independent passes in at least two sessions, including a later check or review.

Pronunciation records are qualitative and require direct Live audio. A transcript alone must be marked `not_assessed`. This version never reports numeric, percentage, phoneme-level, or acoustic pronunciation scores.

## Profile v3.0

The original `scientific_assessment`, `active_repertoire`, and `session_log` remain. New sections are:

- `learning_track`;
- `current_course_position`;
- `knowledge_state`;
- `skill_weaknesses` for listening, speaking, and pronunciation;
- `practice_evidence`, including prompt novelty and whether text was shown before the response;
- optional `migration_history`.

Migration preserves v2.1 fields, review stages, dates, sessions, and compatible extensions. B2–C2 profiles remain in `legacy_conversation`; Pre-A1–B1 profiles receive a bridge check before a unit is selected.

## Repository layout

```text
English_Learning_Instructions.md
curriculum/{PRE_A1,A1,A2,B1}.json
schemas/{curriculum,learning-profile}.schema.json
tools/learning_data.py
tests/
```

## Validation

No third-party dependencies are required:

```bash
python tools/learning_data.py validate
python -m unittest discover -s tests -v
```

The tests execute the JSON Schemas and cover curriculum references, the seven-phase flow, cross-level placement, unseen-listening evidence, v2.1 migration, the deterministic review queue, pronunciation limits, and export revalidation.

## Limitations

- This is not an official CEFR, IELTS, or pronunciation assessment.
- GPT Live, file tools, and voice behavior may change with ChatGPT.
- No audio is stored and no acoustic analysis is performed.
- B1 current-topic work depends on web search; Pre-A1 and A1 do not depend on news discussion.

## Version and license

- Instruction: **v3.0.0**
- Profile schema: **3.0**
- Curriculum: **1.0.0**
- Instructions, curriculum, documentation, schemas, and example profile use CC BY 4.0 under `LICENSE`.
- Python files under `tools/` and `tests/` use the MIT license under `tests/LICENSE`.
