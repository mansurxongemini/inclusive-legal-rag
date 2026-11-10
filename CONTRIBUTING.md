# Contributing

Thanks for helping make legal information accessible. This guide covers the practical steps.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Python 3.11 or newer is required. The test suite needs no API key and no network: it runs against a
temporary store with mocked external APIs.

## Before you open a pull request

```bash
ruff check .
pytest -q
```

Both run in CI on every pull request and must pass.

## Ground rules

- **Legal accuracy comes first.** Corpus text is built from official Lex.uz sources by
  `scripts/build_disability_corpus.py`; never type or paraphrase statutory text by hand.
- **Changes to retrieval, prompts or validation need evidence.** Run the relevant evaluation
  (`scripts/evaluate_retrieval.py`, `scripts/run_eval.py`) and put the before/after numbers in the PR.
- **Add a test** for every bug fix and behavior change.
- **No secrets in the repository.** Configuration goes in `.env` (see `.env.example`).
- Keep pull requests focused: one logical change per PR.

## Reporting problems

- Bugs and feature requests: open a GitHub issue.
- A wrong or outdated legal answer: include the question, the answer you received and the Lex.uz
  link to the correct provision.
- Security issues: see [SECURITY.md](SECURITY.md); do not open a public issue.
