"""Join bid_code_2014.csv and bid_code_2024.csv on SPEC_CD, DESCRIPTION, UNIT,
and record the exact matches into mapping_template.csv."""

import pandas as pd

JOIN_COLS = ["SPEC_CD", "DESCRIPTION", "UNIT"]
EXACT_MATCH_NOTE = "Exact match in all three columns other than ITEM_CD"


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

    print(f"2014 rows:    {len(df_2014)}")
    print(f"2024 rows:    {len(df_2024)}")
    print(f"exact matches: {len(matches)}")
    print("written to bid_code_joined.csv and mapping_template.csv")


def apply_to_mapping_template(matches: pd.DataFrame) -> None:
    """Fill in still-blank rows of mapping_template.csv from exact matches."""
    template = pd.read_csv("mapping_template.csv", dtype=str).fillna("")

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


if __name__ == "__main__":
    main()
