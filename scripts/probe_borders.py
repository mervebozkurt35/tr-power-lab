"""List the border directions that EPİAŞ publishes for interconnection line capacities and capacity auctions.

The site only uses Bulgaria and Greece (TRBG, BGTR, TRGR, GRTR) because the eptr2 package accepts only those four
codes. The platform has its own direction lists; this prints them so we can see whether other borders exist.

  python scripts/probe_borders.py            # needs EPTR_USERNAME and EPTR_PASSWORD (Colab Secrets or environment)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_core as fc  # noqa: E402

eptr = fc.connect()
for key in ("intl-direction-list", "intl-capacity-demand-direction-list"):
    print(f"\n== {key}")
    try:
        print(eptr.call(key))
    except Exception as exc:  # report and go on
        print(f"failed: {type(exc).__name__}: {exc}")
