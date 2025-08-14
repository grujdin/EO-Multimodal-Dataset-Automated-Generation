#!/usr/bin/env python3
import asyncio
import argparse
import sys
from aiohttp import ClientSession
from aio_georss_gdacs import GdacsFeed
import pandas as pd

DEFAULT_CATEGORIES = [
    "Drought",
    "Earthquake",
    "Flood",
    "Tropical Cyclone",
    "Tsunami",
    "Volcano",
    "Wild Fire",
]

async def fetch_feed(home_coords, radius, categories):
    async with ClientSession() as session:
        feed = GdacsFeed(
            session,
            home_coords,
            filter_radius=radius,
            filter_categories=categories
        )
        status, entries = await feed.update()
        return feed, status, entries

def parse_args():
    p = argparse.ArgumentParser(
        description="Fetch GDACS GeoRSS feed entries via aio-georss-gdacs"
    )
    p.add_argument("--lat",   type=float, default=0.0,
                   help="Home latitude for distance filtering")
    p.add_argument("--lon",   type=float, default=0.0,
                   help="Home longitude for distance filtering")
    p.add_argument("--radius", type=float, default=None,
                   help="Radius (km) around home coords to include events")
    p.add_argument(
        "--categories", "-c", nargs="+",
        default=DEFAULT_CATEGORIES,
        help="GDACS categories to include "
             f"(default: {', '.join(DEFAULT_CATEGORIES)})"
    )
    p.add_argument("--output", "-o", type=str, default=None,
                   help="Path to output CSV file (optional)")
    return p.parse_args()

def main():
    args = parse_args()
    home = (args.lat, args.lon)

    feed, status, entries = asyncio.run(
        fetch_feed(home, args.radius, args.categories)
    )

    print(f"Feed update status: {status}")
    print(f"Number of entries returned: {len(entries)}")
    if not entries:
        print("⚠️ No entries to process.", file=sys.stderr)
        sys.exit(0)

    # pick up all public attrs from the first entry
    sample = entries[0]
    attrs = [
        a for a in dir(sample)
        if not a.startswith("_")
        and not callable(getattr(sample, a))
    ]

    # build a list of dicts with all those attributes
    records = []
    for e in entries:
        rec = {}
        for attr in attrs:
            rec[attr] = getattr(e, attr)
        records.append(rec)

    df = pd.DataFrame.from_records(records)

    # ensure we can see every column
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 0)  # auto-wrap
    print("\n=== Full Data Table ===")
    print(df.to_string(index=False))

    if args.output:
        df.to_csv(args.output, index=False)
        print(f"\n✅ Wrote {len(df)} entries to {args.output}")

if __name__ == "__main__":
    main()
