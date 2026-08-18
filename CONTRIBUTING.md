# Contributing to websieve

This pipeline fails quietly. Nothing crashes; the corpus just gets worse, and
the cause surfaces later as a model regression nobody can attribute. The rules
below exist because of that, not out of ceremony.

## Before you start

**Open an issue first** for anything beyond a typo or an obvious bug. A
paragraph agreeing on the approach is cheaper than a review of the wrong
implementation. Issues labelled `good first issue` are pre-scoped and safe to
pick up without asking.

**Say on the issue that you are taking it, before you write code.** One comment
is enough. Two people have already built the same feature four hours apart
because nothing marked the issue as claimed, and one of them had their work
closed. That is a waste this project caused, and this line is how it stops.
If an issue has a recent claim on it, pick another one or ask the claimer
whether they want help.

If you claim something and then drop it, say so. Nobody minds, and it frees the
issue for the next person.

**One issue per pull request.** Exactly one `Closes #N`, or `Refs #N` if you are
only doing part of it. A PR closing several issues cannot be reviewed, reverted,
or released per issue: reverting one fix drags the others out with it, and a
reviewer has to hold several unrelated arguments at once, which is how a bad
change gets waved through alongside two good ones.

Finding a second defect while working on the first is normal and welcome. File
it as its own issue, finish what you claimed, then open the next PR. Do not
widen the branch in flight, even when the two share a root cause. A common cause
is an argument for a common explanation, not a common commit.

**A note on CI.** If this is your first contribution here, GitHub holds your
workflow runs until a maintainer approves them. Until that happens the checks
show as "no checks reported", which looks like a pass and is not one. Ping the
PR if it sits unapproved.

## Setup

```bash
git clone https://github.com/ehtishammubarik/websieve
cd websieve
pip install -e ".[dev]"
pytest
```

## The rule that governs everything

**The core has zero runtime dependencies.** `websieve/` imports stdlib only.

If a stage genuinely needs a third-party package:

1. Guard the import inside the function that uses it.
2. Raise `ImportError` naming the extra that provides it.
3. Add the extra to `pyproject.toml`.

See `export/writers.py` and `embed/encoder.py`. CI fails on module-level
third-party imports, so this is enforced rather than hoped for.

## Before you open a PR

```bash
pytest
ruff check websieve tests
ruff format websieve tests
python .github/scripts/check_no_deps.py
```

All four must pass. If a tool is not installed, say so in the PR rather than
implying it passed.

## Rules specific to this codebase

1. **Quality rules never short circuit.** Every rule runs even after one fails.
   The failure histogram is the only tuning signal users have; an early return
   in `assess` destroys it.

2. **Rules return `Rule`, not `bool`.** Carry the observed value and the
   threshold so a report can say why, and by how much.

3. **LSH candidates must be verified.** `query()` returns candidates, not
   answers. Any path treating a candidate as a duplicate without checking real
   similarity raises the false positive rate invisibly.

4. **Changing a default threshold requires evidence.** Put before and after keep
   rates from a real corpus in the PR description. "Felt too aggressive" is not
   evidence; "dropped 38% of a documentation corpus on
   `terminal_punctuation_ratio`, which API reference legitimately fails" is.

5. **Changing a hash function, seed, or shingle size invalidates every stored
   signature.** Say so explicitly in the PR.

6. **Never drop a document silently.** `adaptive_batches` must not lose a text;
   an oversized document gets its own batch. Anything that removes a document
   must increment a counter in `PipelineStats`.

## Tests

Test behaviour, not implementation. A dedup test asserting "found a duplicate"
passes against a broken MinHash that returns nonsense similarities. The existing
test asserts the estimate lands within three standard errors of true Jaccard.
Aim for that standard.

New quality rules need a test with text designed to fail that specific rule, so
a threshold change surfaces as one failing test rather than a vague regression.

## Commit messages

```
<type>(<scope>): <imperative summary, 72 chars or less>

Why this change exists. The diff already shows what.

Refs: #123
```

Types: `feat`, `fix`, `refactor`, `perf`, `docs`, `test`, `build`, `ci`, `chore`.

One logical change per commit. If the summary needs "and", split it.

## Security

Never commit credentials. Report vulnerabilities to
[contact@eprecisio.com](mailto:contact@eprecisio.com) rather than in a public
issue.

## Crawling responsibly

If your change touches crawling, respect `robots.txt`, rate limit, and identify
your bot honestly. `.claude/skills/crawl-ethics/SKILL.md` has the details.

`websieve` filters for corpus *quality*, not legal *permissibility*. It does no
PII removal and no licence detection. Do not add documentation implying
otherwise.

## If this is useful to you

Star the repo. It is the main way anyone else finds this, and a project that
looks unused gets treated as unmaintained regardless of the state of its tests.

Entirely optional, and it has nothing to do with whether your PR gets merged.
Code is reviewed on the code.

## Questions

Open a discussion, or email [contact@eprecisio.com](mailto:contact@eprecisio.com).
