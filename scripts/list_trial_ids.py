"""Print the trial IDs logged for one experiment in docs/modeling/TRIALS.csv.

IDs are printed space-separated on one line, ready to paste as literal
arguments to scripts/link_models.sh:

    python3 scripts/list_trial_ids.py S1
"""

import argparse
import csv
import sys
from pathlib import Path

TRIALS_CSV = Path(__file__).resolve().parent.parent / "docs" / "modeling" / "TRIALS.csv"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("experiment_id", help="exact experiment_id, e.g. S1 (does not match S1b)")
    args = parser.parse_args()

    with TRIALS_CSV.open(newline="") as f:
        ids = [row["trial_id"] for row in csv.DictReader(f) if row["experiment_id"] == args.experiment_id]
    if not ids:
        print(f"no trials for experiment_id {args.experiment_id!r} in {TRIALS_CSV}", file=sys.stderr)
        return 1
    print(" ".join(ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())
