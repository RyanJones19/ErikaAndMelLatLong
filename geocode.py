"""Geocode addresses from a CSV using OpenStreetMap Nominatim.

Reads addresses.csv (columns: name, street, city, state, zip) and writes
addresses_geocoded.csv with lat, lon, and matched_address columns added.
"""

import csv
import re
import sys
from pathlib import Path

from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim


def strip_suite(street: str) -> str:
    """Remove suite/unit fragments like '# 200', 'Ste 4', 'Unit B' that Nominatim mishandles."""
    return re.sub(r"\s*(#|Ste\.?|Suite|Unit|Apt\.?)\s*\S+\s*$", "", street, flags=re.IGNORECASE).strip()

INPUT = Path(__file__).parent / "addresses.csv"
OUTPUT = Path(__file__).parent / "addresses_geocoded.csv"


def main() -> int:
    geolocator = Nominatim(user_agent="latlong-batch-geocoder/1.0 (ryan.jones@postera.ai)")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.1)

    with INPUT.open(newline="") as f_in:
        rows = list(csv.DictReader(f_in))

    out_fields = ["name", "street", "city", "state", "zip", "lat", "lon", "matched_address"]
    successes = 0
    failures = []

    with OUTPUT.open("w", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=out_fields)
        writer.writeheader()

        for i, row in enumerate(rows, 1):
            print(f"[{i}/{len(rows)}] {row['name']!r:40s} -> ", end="", flush=True)
            queries = [f"{row['street']}, {row['city']}, {row['state']} {row['zip']}, USA"]
            stripped = strip_suite(row["street"])
            if stripped != row["street"]:
                queries.append(f"{stripped}, {row['city']}, {row['state']} {row['zip'].split('-')[0]}, USA")
            loc = None
            for q in queries:
                try:
                    loc = geocode(q)
                except Exception as e:
                    print(f"ERROR ({e}) ", end="", flush=True)
                    loc = None
                if loc:
                    break
            if loc:
                row["lat"] = loc.latitude
                row["lon"] = loc.longitude
                row["matched_address"] = loc.address
                successes += 1
                print(f"{loc.latitude:.5f}, {loc.longitude:.5f}")
            else:
                row["lat"] = ""
                row["lon"] = ""
                row["matched_address"] = ""
                failures.append(row["name"])
                if not loc:
                    print("NOT FOUND")
            writer.writerow(row)

    print(f"\nDone. {successes}/{len(rows)} geocoded. Output: {OUTPUT}")
    if failures:
        print(f"Failed ({len(failures)}): {', '.join(failures)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
