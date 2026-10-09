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
- Preserve the single operational instruction file and non-overwriting JSON export.
- Do not add a backend, database, or application framework without an explicit scope decision.
- Keep curriculum IDs stable after release; add new IDs rather than silently changing their meaning.
- Every objective needs explicit prerequisites, target knowledge, and independent completion evidence.
- Repetition and revealing prompts must never advance independent mastery.
- Transcript-only data must never produce a pronunciation score or phonetic diagnosis.
- Preserve compatible unknown profile fields during migration.
- Update tests whenever scheduling, schema, curriculum, or evidence semantics change.

Run before submitting:

```bash
python tools/learning_data.py validate
python -m unittest discover -s tests -v
```
