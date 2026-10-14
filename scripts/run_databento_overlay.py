from __future__ import annotations

import argparse
import json
from pathlib import Path

from databento_overlay.report import development_report


def main():
    parser = argparse.ArgumentParser(description="Run read-only Databento Futures Overlay Study 016")
    parser.add_argument("--source", default="data/settlement-research-input/seed-checkpoint.json")
    parser.add_argument("--btc", default="data/external/databento/btc_c_0_ohlcv_1m_20260920_20261013.csv")
    parser.add_argument("--mbt", default="data/external/databento/mbt_c_0_ohlcv_1m_20260920_20261013.csv")
    parser.add_argument("--output", default="docs/validation/databento-futures-overlay-study-016-development.json")
    args = parser.parse_args()
    report = development_report(args.source, {"BTC.c.0": args.btc, "MBT.c.0": args.mbt})
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "study": report["study"],
        "output": str(output),
        "report_sha256": report["report_sha256"],
        "primary_development_screen": report["primary_development_screen"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

