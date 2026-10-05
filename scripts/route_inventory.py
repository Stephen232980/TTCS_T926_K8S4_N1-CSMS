"""Run: python -m scripts.route_inventory > route-inventory.csv (no database access)."""

import argparse
import csv
import sys
from pathlib import Path

from src.entrypoints.http import app
from src.modules.identity.route_inventory import route_inventory


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = route_inventory(app.routes)
    output = (
        args.output.open("w", encoding="utf-8", newline="")
        if args.output
        else sys.stdout
    )
    writer = csv.DictWriter(
        output,
        fieldnames=["method", "path", "kind", "permission", "scope", "roles", "note"],
    )
    writer.writeheader()
    writer.writerows(rows)
    if args.output:
        output.close()


if __name__ == "__main__":
    main()
