# Contributing

Thanks for improving GPT Live English Coach.

## Good contribution targets

- evidence from real PRE_A1–B1 lessons;
- curriculum sequencing and prerequisite errors;
- language that exceeds the declared unit scope;
- persona or teaching-flow drift in GPT Live;
- profile migration and Mastery Ladder edge cases;
- accessibility, onboarding, and mobile use.

## Issue reports

Please include, when relevant:

1. instruction, curriculum, and profile schema versions;
2. current level, unit, and lesson phase;
3. whether the issue happened in Text Mode or GPT Live;
4. the exact user trigger;
5. what the coach did and what was expected;
6. whether direct Live audio or only a transcript was available;
7. whether validation or export succeeded.

Do not include personal audio, private profile data, or unnecessary identifying details.

## Pull requests

- Keep the runtime limited to ChatGPT Project + GPT Live.
- Preserve the single operational instruction file, the short `PROJECT_INSTRUCTIONS.md`, and non-overwriting JSON export.
- Do not add a backend, database, or application framework without an explicit scope decision.
- Keep curriculum IDs stable after release; add new IDs rather than silently changing their meaning.
- Every objective needs explicit prerequisites, target knowledge, and independent completion evidence.
- **Unit completion must stay consistent with unlocking**: if a unit is completed, every knowledge item its required objectives target must be independently demonstrated. Never fix a lock by lowering the evidence standard.
- **Keep listening and speaking separate**: never let a listening result promote a speaking dimension or the other way round.
- **A strict unseen listening check requires proof**: if text exposure cannot be ruled out, record it as practice with `listening_check_grade: text_supported_practice` or `unknown`, never as `strict_unseen`.
- **Placement credit must cover a level's real exit requirement** and both skill dimensions. `learner_choice` never credits knowledge.
- Repetition and revealing prompts must never advance independent mastery.
- Transcript-only data must never produce a pronunciation score or phonetic diagnosis.
- Preserve compatible unknown profile fields during migration.
- `sync` may only recompute fields that follow from recorded evidence. It must never add or upgrade evidence.
- New curriculum units that need staging must declare `lesson_segments` covering every local knowledge item.
- Update tests whenever scheduling, schema, curriculum, or evidence semantics change. If you change a rule, add the regression test that would have caught the old behaviour.

Run before submitting:

```bash
python tools/learning_data.py validate
python tools/learning_data.py audit --json
python -m unittest discover -s tests -v
```

Automated tests only cover the data layer. If your change affects spoken behaviour, also note in the PR which scenarios from `docs/manual_acceptance.zh-CN.md` you ran in a real GPT Live session, and say so explicitly if you did not.
