"""Local-algorithm component of the bid code mapping workflow: rule-based,
deterministic matching between bid_code_2014.csv and bid_code_2024.csv.

Applies four steps in order, each only touching rows still unmatched in
mapping_template.csv: exact match on SPEC_CD+DESCRIPTION+UNIT, no-pair
detection, non-numeric high text similarity, and numeric-mandate one-to-one
matching. See llm_matching.py for the semantic-judgment component that
handles whatever remains after this."""

import difflib
import re

import pandas as pd

JOIN_COLS = ["SPEC_CD", "DESCRIPTION", "UNIT"]
EXACT_MATCH_NOTE = "Exact match in all three columns other than ITEM_CD"
NO_PAIR_NOTE = "No matching spec_cd, unit pair"
HIGH_SIMILARITY_NOTE = "High non-numeric string similarity (>0.9)"
NUMERIC_MANDATE_NOTE = (
    "Numeric text, matching specs_cd, unit pair and presence of the same "
    "number(s) in desc, similarity >0.5"
)

NUM_RE = re.compile(r"\d+(?:\.\d+)?")
SIMILARITY_THRESHOLD = 0.90
NUMERIC_MANDATE_SIMILARITY_MIN = 0.5


def numbers_in(text: str) -> set:
    return set(NUM_RE.findall(text))


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.upper(), b.upper()).ratio()


def load_mapping_template() -> pd.DataFrame:
    # keep_default_na=False: mapping_template.csv uses the literal string "N/A"
    # as a real sentinel value (no-pair rows). Without this, pandas silently
    # parses "N/A" as a missing value and .fillna("") erases it on the next save.
    return pd.read_csv("mapping_template.csv", dtype=str, keep_default_na=False)


def main() -> None:
    df_2014 = pd.read_csv("bid_code_2014.csv", dtype=str)
    df_2024 = pd.read_csv("bid_code_2024.csv", dtype=str)

    matches = df_2014.merge(
        df_2024,
        on=JOIN_COLS,
        how="inner",
        suffixes=("_2014", "_2024"),
    )

    matches = matches[
        ["SPEC_CD", "ITEM_CD_2014", "ITEM_CD_2024", "DESCRIPTION", "UNIT"]
    ]
    matches.to_csv("bid_code_joined.csv", index=False)

    apply_to_mapping_template(matches)
    no_pair_count = apply_no_pair_rows(df_2024)
    high_sim_count = apply_no_numeric_high_similarity(df_2024)
    numeric_mandate_count = apply_numeric_mandate_matches(df_2024)

    print(f"2014 rows:    {len(df_2014)}")
    print(f"2024 rows:    {len(df_2024)}")
    print(f"exact matches: {len(matches)}")
    print(f"no spec_cd+unit pair in 2024: {no_pair_count}")
    print(f"non-numeric high similarity (>{SIMILARITY_THRESHOLD:.0%}): {high_sim_count}")
    print(f"numeric-mandate one-to-one (sim > {NUMERIC_MANDATE_SIMILARITY_MIN}): {numeric_mandate_count}")
    print("written to bid_code_joined.csv and mapping_template.csv")


def apply_to_mapping_template(matches: pd.DataFrame) -> None:
    """Fill in still-blank rows of mapping_template.csv from exact matches."""
    template = load_mapping_template()

    for _, row in matches.iterrows():
        mask = (
            (template["spec_cd"] == row["SPEC_CD"])
            & (template["item_cd_2014"] == row["ITEM_CD_2014"])
            & (template["desc_2014"] == row["DESCRIPTION"])
            & (template["unit"] == row["UNIT"])
            & (template["spec_cd_2024"] == "")
        )
        template.loc[mask, "spec_cd_2024"] = row["SPEC_CD"]
        template.loc[mask, "item_cd_2024"] = row["ITEM_CD_2024"]
        template.loc[mask, "desc_2024"] = row["DESCRIPTION"]
        template.loc[mask, "confidence"] = "High"
        template.loc[mask, "notes"] = EXACT_MATCH_NOTE

    template.to_csv("mapping_template.csv", index=False)


def apply_no_pair_rows(df_2024: pd.DataFrame) -> int:
    """Mark still-blank mapping_template.csv rows whose SPEC_CD+UNIT combo
    doesn't exist anywhere in the 2024 data as N/A / High confidence."""
    template = load_mapping_template()

    pairs_2024 = set(zip(df_2024["SPEC_CD"], df_2024["UNIT"]))
    unmatched = template["spec_cd_2024"] == ""
    has_pair = template.apply(
        lambda r: (r["spec_cd"], r["unit"]) in pairs_2024, axis=1
    )
    no_pair_mask = unmatched & ~has_pair

    template.loc[no_pair_mask, ["spec_cd_2024", "item_cd_2024", "desc_2024"]] = "N/A"
    template.loc[no_pair_mask, "confidence"] = "High"
    template.loc[no_pair_mask, "notes"] = NO_PAIR_NOTE

    template.to_csv("mapping_template.csv", index=False)
    return int(no_pair_mask.sum())


def apply_no_numeric_high_similarity(df_2024: pd.DataFrame) -> int:
    """For still-blank rows whose desc_2014 has no numeric qualifier, match
    the best-scoring same-SPEC_CD+UNIT 2024 candidate when its text similarity
    exceeds SIMILARITY_THRESHOLD."""
    template = load_mapping_template()

    used = template[(template["item_cd_2024"] != "") & (template["item_cd_2024"] != "N/A")]
    already_used_2024 = set(zip(used["spec_cd_2024"], used["item_cd_2024"]))

    matched_count = 0
    for idx, row in template[template["spec_cd_2024"] == ""].iterrows():
        desc_2014 = row["desc_2014"]
        if numbers_in(desc_2014):
            continue

        spec, unit = row["spec_cd"], row["unit"]
        candidates = df_2024[
            (df_2024["SPEC_CD"] == spec)
            & (df_2024["UNIT"] == unit)
            & (
                ~df_2024[["SPEC_CD", "ITEM_CD"]]
                .apply(tuple, axis=1)
                .isin(already_used_2024)
            )
        ]
        if candidates.empty:
            continue

        scored = sorted(
            (
                (similarity(desc_2014, c["DESCRIPTION"]), c["ITEM_CD"], c["DESCRIPTION"])
                for _, c in candidates.iterrows()
            ),
            reverse=True,
        )
        best_sim, best_item, best_desc = scored[0]
        if best_sim <= SIMILARITY_THRESHOLD:
            continue

        template.loc[idx, "spec_cd_2024"] = spec
        template.loc[idx, "item_cd_2024"] = best_item
        template.loc[idx, "desc_2024"] = best_desc
        template.loc[idx, "confidence"] = "Medium-High"
        template.loc[idx, "notes"] = HIGH_SIMILARITY_NOTE
        already_used_2024.add((spec, best_item))
        matched_count += 1

    template.to_csv("mapping_template.csv", index=False)
    return matched_count


def apply_numeric_mandate_matches(df_2024: pd.DataFrame) -> int:
    """For still-blank rows whose desc_2014 has a numeric qualifier, mandate
    that the same number(s) appear in the 2024 candidate's DESCRIPTION (same
    SPEC_CD + UNIT). Resolved one-to-one: the highest-similarity claimant wins
    any 2024 item contested by multiple 2014 rows. No mandate relaxation --
    only accepted when similarity also exceeds NUMERIC_MANDATE_SIMILARITY_MIN."""
    template = load_mapping_template()

    used = template[(template["item_cd_2024"] != "") & (template["item_cd_2024"] != "N/A")]
    claimed_earlier = set(zip(used["spec_cd_2024"], used["item_cd_2024"]))

    row_candidates = {}
    for idx, row in template[template["spec_cd_2024"] == ""].iterrows():
        desc_2014 = row["desc_2014"]
        nums_2014 = numbers_in(desc_2014)
        if not nums_2014:
            continue

        spec, unit = row["spec_cd"], row["unit"]
        key = (spec, row["item_cd_2014"])

        pool = df_2024[(df_2024["SPEC_CD"] == spec) & (df_2024["UNIT"] == unit)]
        cands = []
        for _, c in pool.iterrows():
            if (spec, c["ITEM_CD"]) in claimed_earlier:
                continue
            if numbers_in(c["DESCRIPTION"]) != nums_2014:
                continue
            cands.append((similarity(desc_2014, c["DESCRIPTION"]), c["ITEM_CD"], c["DESCRIPTION"]))
        cands.sort(reverse=True)
        row_candidates[key] = (idx, cands)

    mandate_pairs = [
        (sim, key, item, desc)
        for key, (idx, cands) in row_candidates.items()
        for sim, item, desc in cands
    ]
    mandate_pairs.sort(key=lambda x: x[0], reverse=True)

    winners = {}
    target_owner = {}
    for sim, key, item, desc in mandate_pairs:
        if key in winners or sim <= NUMERIC_MANDATE_SIMILARITY_MIN:
            continue
        target = (key[0], item)
        if target in target_owner:
            continue
        winners[key] = (item, desc)
        target_owner[target] = key

    for key, (item, desc) in winners.items():
        spec, _ = key
        idx, _ = row_candidates[key]
        template.loc[idx, "spec_cd_2024"] = spec
        template.loc[idx, "item_cd_2024"] = item
        template.loc[idx, "desc_2024"] = desc
        template.loc[idx, "confidence"] = "Medium-High"
        template.loc[idx, "notes"] = NUMERIC_MANDATE_NOTE

    template.to_csv("mapping_template.csv", index=False)
    return len(winners)


if __name__ == "__main__":
    main()
