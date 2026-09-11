"""LLM-judge component of the bid code mapping workflow: for rows still
unmatched in mapping_template.csv after local_matching.py, builds a
shortlist of the top-5 unclaimed 2024 candidates (same SPEC_CD + UNIT,
ranked by difflib similarity), asks a hosted LLM (via OpenRouter) to judge
the best semantic match or "N/A", and writes real matches into
mapping_template.csv with confidence suffixed "-LLM" (e.g. "High-LLM").

Notes are intentionally left blank for LLM-judged rows -- add manually.
Full audit trail (including N/A judgments and raw model output) is written
to llm_judge_results.csv. Requires OPENROUTER_API_KEY in .env; skips
gracefully if it's not set.
"""

import difflib
import json
import os
import time

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
REQUEST_DELAY_SECONDS = 1.5
TOP_N = 5

PROMPT_TEMPLATE = """Match the 2014 bid item record below to the correct 2024 candidate, or answer "N/A" if none is a genuine match. Judge by real-world meaning, not text similarity. Numeric qualifiers (diameter, thickness, grade, dimensions) define distinct pay items -- a candidate only matches if its numeric qualifier is the same as, or fully covers, the 2014 record's. Wording differences alone (abbreviations, reordering, filler words) do not disqualify a match.

2014 record:
- SPEC_CD: {spec_cd}
- ITEM_CD: {item_cd_2014}
- DESCRIPTION: {desc_2014}
- UNIT: {unit}

2024 candidates:
{candidate_lines}
{na_option}. N/A - none of the above

Rate your confidence: High (unambiguous), Medium (plausible but uncertain), Low (weak guess, needs review).

Respond ONLY with JSON: {{"item_cd_2024": "<ITEM_CD above, or N/A>", "confidence": "<High|Medium|Low>"}}"""


def load_mapping_template() -> pd.DataFrame:
    # keep_default_na=False: mapping_template.csv uses the literal string "N/A"
    # as a real sentinel value (no-pair rows). Without this, pandas silently
    # parses "N/A" as a missing value and .fillna("") erases it on the next save.
    return pd.read_csv("mapping_template.csv", dtype=str, keep_default_na=False)


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.upper(), b.upper()).ratio()


def build_candidates(template: pd.DataFrame, df_2024: pd.DataFrame) -> list:
    unmatched = template[template["spec_cd_2024"] == ""]
    used = template[(template["item_cd_2024"] != "") & (template["item_cd_2024"] != "N/A")]
    claimed = set(zip(used["spec_cd_2024"], used["item_cd_2024"]))

    records = []
    for _, row in unmatched.iterrows():
        spec, unit, desc_2014, item_2014 = row["spec_cd"], row["unit"], row["desc_2014"], row["item_cd_2014"]

        pool = df_2024[
            (df_2024["SPEC_CD"] == spec)
            & (df_2024["UNIT"] == unit)
            & (~df_2024[["SPEC_CD", "ITEM_CD"]].apply(tuple, axis=1).isin(claimed))
        ]
        scored = sorted(
            (
                {
                    "item_cd_2024": c["ITEM_CD"],
                    "desc_2024": c["DESCRIPTION"],
                    "unit_2024": c["UNIT"],
                    "similarity": round(similarity(desc_2014, c["DESCRIPTION"]), 3),
                }
                for _, c in pool.iterrows()
            ),
            key=lambda c: c["similarity"],
            reverse=True,
        )[:TOP_N]

        records.append(
            {
                "spec_cd": spec,
                "item_cd_2014": item_2014,
                "desc_2014": desc_2014,
                "unit": unit,
                "candidates": scored,
            }
        )
    return records


def build_prompt(record: dict) -> str:
    candidates = record["candidates"]
    candidate_lines = "\n".join(
        f"{i}. SPEC_CD: {record['spec_cd']}, ITEM_CD: {c['item_cd_2024']}, "
        f"DESCRIPTION: {c['desc_2024']}, UNIT: {c['unit_2024']}"
        for i, c in enumerate(candidates, start=1)
    )
    return PROMPT_TEMPLATE.format(
        spec_cd=record["spec_cd"],
        item_cd_2014=record["item_cd_2014"],
        desc_2014=record["desc_2014"],
        unit=record["unit"],
        candidate_lines=candidate_lines,
        na_option=len(candidates) + 1,
    )


def call_model(prompt: str, api_key: str) -> str:
    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise requests.HTTPError(body["error"].get("message", str(body["error"])), response=resp)
    return body["choices"][0]["message"]["content"]


def desc_for(record: dict, item_cd_2024: str) -> str:
    for c in record["candidates"]:
        if c["item_cd_2024"] == item_cd_2024:
            return c["desc_2024"]
    return ""


def judge_records(records: list, api_key: str) -> list:
    rows = []
    for i, record in enumerate(records, start=1):
        base = {
            "spec_cd": record["spec_cd"],
            "item_cd_2014": record["item_cd_2014"],
            "desc_2014": record["desc_2014"],
            "unit": record["unit"],
        }
        print(f"[{i}/{len(records)}] {record['item_cd_2014']}  {record['desc_2014']}")

        if not record["candidates"]:
            rows.append(
                {**base, "item_cd_2024": "N/A", "desc_2024": "", "confidence": "", "status": "skipped_no_candidates", "raw_output": ""}
            )
            continue

        prompt = build_prompt(record)
        try:
            raw_output = call_model(prompt, api_key)
        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            if status_code == 429:
                print(f"  rate limited -- stopping, {len(records) - i + 1} record(s) left unprocessed")
                rows.append({**base, "item_cd_2024": "", "desc_2024": "", "confidence": "", "status": "skipped_rate_limited", "raw_output": ""})
                for remaining in records[i:]:
                    rows.append(
                        {
                            "spec_cd": remaining["spec_cd"],
                            "item_cd_2014": remaining["item_cd_2014"],
                            "desc_2014": remaining["desc_2014"],
                            "unit": remaining["unit"],
                            "item_cd_2024": "",
                            "desc_2024": "",
                            "confidence": "",
                            "status": "skipped_rate_limited",
                            "raw_output": "",
                        }
                    )
                break
            rows.append({**base, "item_cd_2024": "", "desc_2024": "", "confidence": "", "status": f"api_error: {e}", "raw_output": ""})
            time.sleep(REQUEST_DELAY_SECONDS)
            continue
        except Exception as e:
            rows.append({**base, "item_cd_2024": "", "desc_2024": "", "confidence": "", "status": f"error: {e}", "raw_output": ""})
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        try:
            parsed = json.loads(raw_output)
            item_cd_2024 = parsed["item_cd_2024"]
            confidence = parsed["confidence"]
            status = "judged"
        except (json.JSONDecodeError, KeyError):
            item_cd_2024, confidence, status = "", "", "parse_error"

        rows.append(
            {
                **base,
                "item_cd_2024": item_cd_2024,
                "desc_2024": desc_for(record, item_cd_2024),
                "confidence": confidence,
                "status": status,
                "raw_output": raw_output,
            }
        )
        time.sleep(REQUEST_DELAY_SECONDS)
    return rows


def apply_llm_matches(rows: list) -> int:
    """Write real (non-N/A) LLM matches into mapping_template.csv. Confidence
    is suffixed "-LLM" to distinguish it from the rule-based tiers. Notes are
    intentionally left blank."""
    template = load_mapping_template()

    matched_count = 0
    for r in rows:
        if r.get("status") != "judged" or r["item_cd_2024"] in ("", "N/A"):
            continue

        mask = (
            (template["spec_cd"] == r["spec_cd"])
            & (template["item_cd_2014"] == r["item_cd_2014"])
            & (template["spec_cd_2024"] == "")
        )
        template.loc[mask, "spec_cd_2024"] = r["spec_cd"]
        template.loc[mask, "item_cd_2024"] = r["item_cd_2024"]
        template.loc[mask, "desc_2024"] = r["desc_2024"]
        template.loc[mask, "confidence"] = f"{r['confidence']}-LLM"
        matched_count += int(mask.sum())

    template.to_csv("mapping_template.csv", index=False)
    return matched_count


def main() -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY not found -- check .env. Skipping LLM judge step.")
        return

    df_2024 = pd.read_csv("bid_code_2024.csv", dtype=str)
    template = load_mapping_template()

    records = build_candidates(template, df_2024)
    if not records:
        print("no unmatched rows -- nothing for the LLM judge to do")
        return

    rows = judge_records(records, api_key)

    out = pd.DataFrame(rows)
    out.to_csv("llm_judge_results.csv", index=False)

    applied_count = apply_llm_matches(rows)

    print(f"\ntotal records:        {len(out)}")
    print(out["status"].value_counts().to_string())
    if "judged" in out["status"].values:
        judged = out[out["status"] == "judged"]
        print(judged["confidence"].value_counts().to_string())
    print(f"applied to mapping_template.csv: {applied_count}")
    print("written to llm_judge_results.csv and mapping_template.csv")


if __name__ == "__main__":
    main()
