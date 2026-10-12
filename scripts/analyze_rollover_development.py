#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research_lab.research import write_json
from rollover_bridge.analysis import development_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tape", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = json.loads(args.tape.read_text())
    report = development_report(source["rows"])
    report["source"] = source.get("manifest", {})
    write_json(args.output, report)
    print(json.dumps({
        "output": str(args.output),
        "probability_comparison": report["probability_comparison"],
        "results": {key: value for key, value in report["results"].items() if key != "trades"},
    }, sort_keys=True))


if __name__ == "__main__":
    main()
