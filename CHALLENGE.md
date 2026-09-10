# TxDOT bid-code crosswalk

**Time:** 60 minutes live, then continue in your own repo after.

**Goal:** We want to see how you arrive at a solution. A complete, perfect mapping is not expected in one hour. A wrong match is worse than leaving a row unmatched.

---

## The problem

TxDOT publishes a new *Standard Specifications* book about every 10 years (2014, 2024). Construction work is bid as **bid items**, each identified by two numbers:

```
0247 - 7001
────   ────
Item   Descriptive code
number ("which variant of Item 247")
```

- **Item number** (`SPEC_CD`) is the spec-book chapter (Item 247 = Flexible Base). For standard items 100–800 it is stable across editions.
- **Descriptive code** (`ITEM_CD`) identifies the variant — size, type, grade, unit of measure. It is **resequenced every edition**.
- The leading digit of `ITEM_CD` is an edition stamp: `6xxx` = 2014 book, `7xxx` = 2024 book. The remaining digits have **no guaranteed relationship** between editions.

Our estimating app stores both years in one table with no spec-year column. 2024 codes have almost no price history. The same work was bid for about ten years under 2014 codes. We need a translator: given a 2014 bid code, return its 2024 equivalent — or honestly say there isn’t one.

## What you have

| File | What it is |
|---|---|
| `bid_code_2014.csv` | 2014 catalog extract (`SPEC_CD`, `ITEM_CD`, `DESCRIPTION`, `UNIT`) |
| `bid_code_2024.csv` | 2024 catalog extract, same columns |
| `known_pairs.csv` | Five verified 2014→2024 pairs you may use to check your work. They are **not** the full answer. |
| `mapping_template.csv` | Empty mapping with the 2014 side filled in. Copy it into your repo if you want. |

This is a slice of real production data, not a toy. Some 2014 codes have no 2024 counterpart. That is a valid answer.

## 60-minute checkpoint

By the end of the hour, in **your own git repo** (create it at the start; do not fork an existing project):

1. A mapping table: each 2014 code → a 2024 code **or blank**, plus a confidence/reason column.
2. A `README.md` of what you tried, what you rejected, and what you would do next.
3. A link to the repo, even if the work is rough.

Suggested mapping columns (see `mapping_template.csv`):

```
spec_cd, item_cd_2014, desc_2014, unit, spec_cd_2024, item_cd_2024, desc_2024, confidence, notes
```

Use any confidence labels you like (`high` / `medium` / `low` / `none` is fine). What matters is that they mean something you can explain.

## Constraints

- Do not assume `6006` maps to `7006`. Check.
- Python is fine. You may use the standard library plus whatever is reasonable (`difflib`, pandas, etc.).
- Do not train a model in this hour. Do not build a web app in this hour.
- The five rows in `known_pairs.csv` are ground truth. If your method gets one of them wrong, the method is wrong — fix the method, not the pair.

## After the hour

Keep going in the same repo. We will read the commit history and the README, not a slide deck. A short take-home note will be sent at minute 60.

## Example of a finished row (one of the known pairs)

```
0100, 6001, PREPARING ROW, AC, 0100, 7001, PREPARING ROW, high, identical description and unit
```
