#!/usr/bin/env python3
"""
imd_scraper.py -- Download IMD district Agromet Advisory Bulletins (PDF) for CropCompass.

These twice-weekly district bulletins (e.g. the Krishnagiri / Tamil Nadu sample) pair a
5-day weather forecast with crop/livestock advisories -- ideal grounding documents for the
ChromaDB RAG knowledge base.

------------------------------------------------------------------------------------------
HOW IT WORKS (endpoints verified live on 2026-06-18)
------------------------------------------------------------------------------------------
The public page https://mausam.imd.gov.in/responsive/agromet_adv_ser_district_past_en.php is
a JS dropdown front-end. Two backend calls do the real work:

1) District list for a state (STATIC per state -- the date is ignored for the list itself):
     GET https://mausam.imd.gov.in/responsive/agrometinformation/district_past_en_get.php
         ?s=<State>&d=<YYYY-MM-DD>&step1=true
     -> HTML <select> whose <option value="..."> are the district names.

2) The actual bulletin PDF (this is the real download URL the page hands you):
     GET https://imdagrimet.gov.in/Services/DistrictBulletin.php
         ?state=<State>&district=<District>&date=<YYYY-MM-DD>&language=English
     -> Content-Type: application/pdf  when a bulletin exists for that day.
     -> Otherwise HTTP 200 (NOT 404) with a ~96-byte text/html stub. We therefore detect a
        real bulletin by Content-Type + the %PDF magic bytes + a minimum size, never by
        the status code. An empty date= returns the most recent bulletin.

------------------------------------------------------------------------------------------
DATE STRATEGY
------------------------------------------------------------------------------------------
Bulletins are issued twice a week -- Tuesday and Friday -- and are occasionally skipped on
public holidays (verified gaps: Fri 2026-06-05, Fri 2026-05-01, Tue 2026-04-14, all flanked
by normal bulletins). So we only request Tuesdays and Fridays and quietly skip the misses.
The archive goes back at least ~6 months (confirmed PDFs back to Dec 2025).

------------------------------------------------------------------------------------------
USAGE
------------------------------------------------------------------------------------------
    pip install requests

    # Tamil Nadu, last 90 days (recommended starting point for CropCompass)
    python -m ingestion.imd_scraper --states "Tamil Nadu" --days 90

    # A few states, explicit date window
    python -m ingestion.imd_scraper --states "Tamil Nadu" "Karnataka" --start 2025-12-01 --end 2026-06-16

    # Everything, last 30 days
    python -m ingestion.imd_scraper --days 30

    # See what would download without fetching anything
    python -m ingestion.imd_scraper --states "Tamil Nadu" --days 30 --dry-run

    # List the known states / a state's districts and exit
    python -m ingestion.imd_scraper --list-states
    python -m ingestion.imd_scraper --list-districts "Tamil Nadu"

Re-runs are cheap: existing PDFs are skipped, so scheduling this with --days 10 twice a week
keeps the corpus current. Files are saved as:
    <out>/<State>/<State>_<District>_<Language>_<YYYY-MM-DD>.pdf
which matches the existing naming convention (e.g. "Tamil Nadu_Krishnagiri_English_2026-06-16.pdf").
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover - very old urllib3
    from requests.packages.urllib3.util.retry import Retry  # type: ignore


# --------------------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------------------

DISTRICT_LIST_URL = "https://mausam.imd.gov.in/responsive/agrometinformation/district_past_en_get.php"
BULLETIN_URL = "https://imdagrimet.gov.in/Services/DistrictBulletin.php"

# Exact dropdown values from the IMD page (these strings are reused verbatim as the
# `state=` parameter for the PDF endpoint, so do not "tidy" them).
STATES = [
    "Andaman and Nicobar", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar",
    "Chandigarh", "Chhattisgarh", "Dadra And Nagar Haveli", "Daman And Diu", "Goa",
    "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand",
    "Karnataka", "Kerala", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "New Delhi", "Odisha", "Puducherry", "Punjab",
    "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh",
    "Uttarakhand", "West Bengal",
]

# Python weekday(): Monday=0 ... Sunday=6.  Bulletins issue on Tuesday(1) and Friday(4).
ISSUE_WEEKDAYS = {1, 4}

# The "no bulletin" stub is ~96 bytes; real bulletins are >100 KB. 1 KB is a safe floor.
MIN_PDF_BYTES = 1024

DEFAULT_OUT = "data/raw/imd_agromet"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CropCompass-AgrometScraper/1.0"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------------------

def make_session() -> requests.Session:
    """A requests session with sane retries/backoff for a sometimes-flaky gov server."""
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def looks_like_pdf(resp: requests.Response) -> bool:
    """True only for a genuine bulletin PDF (filters out the tiny HTML 'missing' stub)."""
    ctype = resp.headers.get("Content-Type", "").lower()
    body = resp.content
    return "pdf" in ctype and body[:4] == b"%PDF" and len(body) >= MIN_PDF_BYTES


# --------------------------------------------------------------------------------------
# Discovery + date logic
# --------------------------------------------------------------------------------------

def recent_issue_dates(n: int, end: date | None = None) -> list[date]:
    """The last `n` Tue/Fri dates on/before `end` (today by default)."""
    end = end or date.today()
    out, d = [], end
    while len(out) < n:
        if d.weekday() in ISSUE_WEEKDAYS:
            out.append(d)
        d -= timedelta(days=1)
    return out


def get_districts(session: requests.Session, state: str) -> list[str]:
    """Fetch the (static) district list for a state via the step1 endpoint."""
    for probe in recent_issue_dates(4):
        try:
            r = session.get(
                DISTRICT_LIST_URL,
                params={"s": state, "d": probe.isoformat(), "step1": "true"},
                timeout=30,
            )
        except requests.RequestException:
            continue
        if not r.ok:
            continue
        values = re.findall(r'value="([^"]+)"', r.text)
        districts = [v.strip() for v in values if v.strip() and "select" not in v.lower()]
        if districts:
            # de-dup, preserve order
            seen, uniq = set(), []
            for d in districts:
                if d not in seen:
                    seen.add(d)
                    uniq.append(d)
            return uniq
    return []


def issue_dates(start: date, end: date) -> list[date]:
    """All Tuesdays and Fridays in [start, end], newest first."""
    days = []
    d = start
    while d <= end:
        if d.weekday() in ISSUE_WEEKDAYS:
            days.append(d)
        d += timedelta(days=1)
    return list(reversed(days))


def safe_component(s: str) -> str:
    """Make a string safe for use as a path component (keep spaces, kill separators)."""
    return re.sub(r'[\\/:*?"<>|]+', "_", s).strip()


# --------------------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------------------

def target_path(out_dir: Path, state: str, district: str, language: str, d: date) -> Path:
    fname = f"{safe_component(state)}_{safe_component(district)}_{language}_{d.isoformat()}.pdf"
    return out_dir / safe_component(state) / fname


def download_one(session, state, district, d, language, out_dir, overwrite, delay):
    """Returns (status, path|None, nbytes). status in {saved, skip-exists, missing, error}."""
    path = target_path(out_dir, state, district, language, d)
    if path.exists() and path.stat().st_size >= MIN_PDF_BYTES and not overwrite:
        return ("skip-exists", path, path.stat().st_size)

    params = {"state": state, "district": district, "date": d.isoformat(), "language": language}
    try:
        if delay:
            time.sleep(delay)
        r = session.get(BULLETIN_URL, params=params, timeout=45)
    except requests.RequestException as e:
        return ("error", None, 0)

    if not r.ok or not looks_like_pdf(r):
        return ("missing", None, 0)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    return ("saved", path, len(r.content))


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Download IMD district Agromet Advisory Bulletins (PDF).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--states", nargs="+", metavar="STATE",
                   help="State names to scrape (default: all). Use exact IMD spelling; "
                        "see --list-states.")
    p.add_argument("--days", type=int, default=90,
                   help="Look back this many days from today (default: 90). Ignored if "
                        "--start is given.")
    p.add_argument("--start", help="Start date YYYY-MM-DD (overrides --days).")
    p.add_argument("--end", help="End date YYYY-MM-DD (default: today).")
    p.add_argument("--language", default="English",
                   help="Bulletin language param (default: English).")
    p.add_argument("--out", default=DEFAULT_OUT,
                   help=f"Output directory, relative to project root (default: {DEFAULT_OUT}).")
    p.add_argument("--workers", type=int, default=5,
                   help="Concurrent download workers (default: 5; be gentle on the server).")
    p.add_argument("--delay", type=float, default=0.2,
                   help="Per-request delay in seconds, per worker (default: 0.2).")
    p.add_argument("--overwrite", action="store_true",
                   help="Re-download even if the file already exists.")
    p.add_argument("--dry-run", action="store_true",
                   help="List every (state, district, date) that would be fetched, then exit.")
    p.add_argument("--yes", action="store_true",
                   help="Skip the volume confirmation prompt.")
    p.add_argument("--manifest", action="store_true",
                   help="Write a manifest CSV of results into the output directory.")
    p.add_argument("--list-states", action="store_true", help="Print known states and exit.")
    p.add_argument("--list-districts", metavar="STATE",
                   help="Print the districts for STATE and exit.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    session = make_session()

    if args.list_states:
        print("\n".join(STATES))
        return 0

    if args.list_districts:
        ds = get_districts(session, args.list_districts)
        if not ds:
            print(f"No districts found for {args.list_districts!r}.", file=sys.stderr)
            return 1
        print(f"{args.list_districts} ({len(ds)} districts):")
        print("\n".join("  " + d for d in ds))
        return 0

    # Resolve date window
    end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else date.today()
    if args.start:
        start = datetime.strptime(args.start, "%Y-%m-%d").date()
    else:
        start = end - timedelta(days=args.days)
    dates = issue_dates(start, end)
    if not dates:
        print("No Tuesday/Friday dates in the requested window.", file=sys.stderr)
        return 1

    states = args.states or STATES
    # validate state names early
    unknown = [s for s in states if s not in STATES]
    if unknown:
        print(f"Unknown state name(s): {unknown}\nUse --list-states for valid values.",
              file=sys.stderr)
        return 1

    out_dir = (PROJECT_ROOT / args.out).resolve()

    # Build the full task list (resolve districts per state first -- cheap, ~1 req/state).
    print(f"Resolving districts for {len(states)} state(s)...", file=sys.stderr)
    tasks = []  # (state, district, date)
    for st in states:
        ds = get_districts(session, st)
        if not ds:
            print(f"  ! no districts for {st!r} (skipped)", file=sys.stderr)
            continue
        for di in ds:
            for d in dates:
                tasks.append((st, di, d))
        print(f"  {st}: {len(ds)} districts", file=sys.stderr)

    print(f"\nWindow: {start} -> {end}  ({len(dates)} Tue/Fri dates)", file=sys.stderr)
    print(f"Planned requests: {len(tasks)}  (states x districts x dates)", file=sys.stderr)
    print(f"Output: {out_dir}", file=sys.stderr)

    if args.dry_run:
        for st, di, d in tasks:
            print(f"{st} | {di} | {d.isoformat()} -> {target_path(out_dir, st, di, args.language, d).name}")
        print(f"\n[dry-run] {len(tasks)} requests planned. Nothing downloaded.", file=sys.stderr)
        return 0

    if not args.yes and len(tasks) > 500:
        resp = input(f"About to make up to {len(tasks)} requests. Continue? [y/N] ").strip().lower()
        if resp not in ("y", "yes"):
            print("Aborted.", file=sys.stderr)
            return 1

    counts = {"saved": 0, "skip-exists": 0, "missing": 0, "error": 0}
    rows = []
    t0 = time.time()

    def run(task):
        st, di, d = task
        status, path, nbytes = download_one(
            session, st, di, d, args.language, out_dir, args.overwrite, args.delay
        )
        return st, di, d, status, path, nbytes

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futures = [ex.submit(run, t) for t in tasks]
        for i, fut in enumerate(as_completed(futures), 1):
            st, di, d, status, path, nbytes = fut.result()
            counts[status] += 1
            if status == "saved":
                print(f"[{i}/{len(tasks)}] saved {st}/{di} {d}  ({nbytes//1024} KB)")
            rows.append((st, di, d.isoformat(), status, str(path) if path else "", nbytes))

    dt = time.time() - t0
    print("\n--- summary ---", file=sys.stderr)
    print(f"saved={counts['saved']}  skipped={counts['skip-exists']}  "
          f"missing={counts['missing']}  errors={counts['error']}", file=sys.stderr)
    print(f"elapsed={dt:.1f}s  -> {out_dir}", file=sys.stderr)

    if args.manifest and rows:
        out_dir.mkdir(parents=True, exist_ok=True)
        mpath = out_dir / f"manifest_{datetime.now():%Y%m%d_%H%M%S}.csv"
        with open(mpath, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["state", "district", "date", "status", "path", "bytes"])
            w.writerows(rows)
        print(f"manifest: {mpath}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
