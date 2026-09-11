"""Entry point for the bid code mapping workflow.

Runs the local-algorithm component first (deterministic, rule-based matching
against mapping_template.csv), then the LLM-judge component for whatever
rows are still unmatched afterward. The LLM step skips itself gracefully if
OPENROUTER_API_KEY isn't configured.
"""

import local_matching
import llm_matching


def main() -> None:
    print("=" * 70)
    print("STEP 1: local algorithm (rule-based matching)")
    print("=" * 70)
    local_matching.main()

    print()
    print("=" * 70)
    print("STEP 2: LLM judge (semantic matching for the remainder)")
    print("=" * 70)
    llm_matching.main()


if __name__ == "__main__":
    main()
