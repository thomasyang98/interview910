# Bid Code Crosswalk: 2014 → 2024

Maps each item in `bid_code_2014.csv` to its counterpart in `bid_code_2024.csv`
(joined on `SPEC_CD`, `DESCRIPTION`, `UNIT`), producing `mapping_template.csv` as
the final crosswalk. Descriptions and item codes were reworded and renumbered
between years, so most of the work is judging what counts as "the same
real-world pay item" once exact text matching runs out.

## Overview

The pipeline runs in two stages, orchestrated by `main.py`:

1. **`local_matching.py`** — deterministic, rule-based. Four steps, each only
   touching rows still unmatched by the previous one:
   - Exact match on `SPEC_CD` + `DESCRIPTION` + `UNIT` → **High**
   - No `SPEC_CD`+`UNIT` pair exists anywhere in 2024 → marked `N/A` → **High**
   - No numeric qualifier in the description, best same-`SPEC_CD`+`UNIT`
     candidate scores >90% text similarity → **Medium-High**
   - Numeric qualifier present (dimensions, grades, thicknesses) — mandates the
     *same* number(s) appear in both descriptions, resolved one-to-one
     (highest similarity wins any contested 2024 item), similarity >0.5 →
     **Medium-High**
2. **`llm_matching.py`** — for whatever's left, builds the top-5 unclaimed
   2024 candidates per row and asks a hosted LLM (via OpenRouter, free tier)
   to judge the best semantic match or `N/A`, with its own confidence
   (High/Medium/Low). Both outcomes are written back: a real match gets
   `spec_cd_2024`/`item_cd_2024`/`desc_2024` filled in, an explicit `N/A`
   judgment gets all three set to `N/A` so "the LLM concluded no match" is
   recorded rather than left indistinguishable from "never checked."
   Confidence is suffixed `-LLM` either way; notes are left blank for manual
   annotation.

Current state: **all 66 rows resolved** (17 High, 20 Medium-High, 26
High-LLM, 2 Medium-LLM, 1 Low-LLM — the LLM tier splits into 9 real matches
and 20 explicit `N/A` judgments). The 20 `N/A` rows reflect the LLM's
original judgment, made before the prompt was corrected to include full
`SPEC_CD`+`UNIT` context on both sides — see "what we'd do next."

Run with `.venv\Scripts\python.exe main.py` (requires `OPENROUTER_API_KEY` in
`.env` for the LLM stage; that stage skips itself gracefully if the key is
missing).

## What we tried

- **`ITEM_CD` as a matching signal** — hypothesized a fixed offset (2024 =
  2014 + 1000) and checked rank-within-`SPEC_CD` as an alternative. Neither
  held up against `known_pairs.csv` ground truth (offsets ranged from -4 to
  +1020; ranks shifted because items were added/removed between years, not
  just appended). Concluded `ITEM_CD` carries no cross-year meaning on its
  own — `SPEC_CD` narrows candidates, but the numeric suffix doesn't.
- **Plain text similarity (`difflib`) as a ranking signal** — worked well
  once restricted to the `SPEC_CD`+`UNIT` candidate pool, correctly
  surfacing the true match as top hit in most cases even through reworded
  or abbreviated text.
- **Splitting out numeric qualifiers** — extracted numbers via regex and
  used them first as a priority signal, then as a hard mandate (exact
  number-set equality) once we found a case where plain similarity picked a
  same-wording-but-wrong-dimension candidate over the real match.
- **One-to-one resolution for the numeric mandate** — when two 2014 rows
  independently satisfied the mandate against the same 2024 item, resolved
  it as highest-similarity-wins, with the loser explicitly flagged rather
  than silently dropped or silently assigned.
- **A high-similarity-only step for non-numeric descriptions** — descriptions
  with no numeric qualifier were matched by plain similarity above a 90%
  threshold, catching a clean abbreviation pattern (`REMOVING X` → `REMOV X`).
- **LLM-judge for the remainder** — the rule-based approach was either too
  strict (exact number-set equality missed genuine range-containment
  matches, e.g. 7"-12" fully inside a 6"-12" candidate) or too loose (plain
  similarity alone picked semantically wrong candidates). Prompted a hosted
  model with the full record (`SPEC_CD`, `ITEM_CD`, `DESCRIPTION`, `UNIT`)
  for both the 2014 row and each 2024 candidate, explicit range-containment
  reasoning for numeric qualifiers, and a self-rated confidence. It caught
  matches the rule-based mandate missed and correctly returned `N/A` on a
  case where similarity alone would have produced a false positive.

## What we rejected

- **Token-order-insensitive / bag-of-words similarity** (Jaccard, token-sort)
  as a replacement for `difflib`'s sequence-based ratio — held off on this;
  reordering wasn't clearly a problem in this dataset and added complexity
  without demonstrated benefit.
- **Relaxing the numeric mandate to a best-available fallback** — tried it,
  but it surfaced weak matches (similarity as low as 0.27) that were closer
  to noise than to a real match. Reverted to no relaxation: only clean,
  one-to-one, mandate-satisfying matches get auto-accepted; everything else
  is left for the LLM step or manual review rather than force-fit.
- **Widening the 2024 candidate pool past the `UNIT` filter** for the
  LLM step, to catch possible unit-redefinition matches — rejected; unit is
  treated as a hard match criterion, not something the LLM should weigh in.
  We instead made sure the actual `UNIT` value (and the rest of the record)
  is shown explicitly to the LLM for full-row transparency.

## What we'd do next

Given prior experience with LLM-judge setups in research, the highest-value
next step is **getting a small human-labeled dataset** — built by someone
with domain knowledge of these pay items and the business logic behind the
2014→2024 revision — and using it to tune the prompt for maximum accuracy
against that ground truth, rather than continuing to eyeball individual
cases.

Since **matching nothing is preferable to matching incorrectly** in this
crosswalk, that tuning should explicitly bias toward `N/A`: either as a
direct instruction in the prompt ("when in doubt, prefer N/A"), or by
raising the similarity/confidence threshold required before a match is
auto-accepted.

Other concrete open items from this pass:
- Re-check the 20 `N/A-LLM` rows with the corrected full-record-context
  prompt once the OpenRouter quota resets (or by switching providers) — the
  re-run using that prompt got 19 of 20 through before hitting the rate
  limit, but crashed before saving, so those judgments were lost and the
  rows still reflect the original, less-complete prompt.
- Decide how to handle the small number of many-to-one collisions in the LLM
  output (multiple 2014 rows resolving to the same 2024 item) — could be
  genuine consolidation, or could need the same one-to-one resolution used
  in the numeric-mandate step.
- Add the manual `notes` for the LLM-judged rows (left blank intentionally).
