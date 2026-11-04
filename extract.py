from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from companies_house import CompaniesHouseClient

load_dotenv()
BASE = Path(__file__).resolve().parent
RAW = BASE / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("extract")


def load_sic_codes(include_adjacent: bool) -> list[str]:
    config = json.loads((BASE / "sic_codes.json").read_text(encoding="utf-8"))
    codes = list(config["core_construction"])
    if include_adjacent:
        codes.extend(config["adjacent_architecture_engineering"])
    return codes


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    log.warning("Skipping malformed JSONL line in %s", path)
    return rows


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract active UK construction companies from Companies House.")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum unique companies to collect; use 10000 for the full target.")
    parser.add_argument("--page-size", type=int, default=500, help="Companies House page size (max 5000).")
    parser.add_argument("--include-adjacent-sic", action="store_true", help="Include architecture/engineering SICs as a separate adjacent segment.")
    parser.add_argument("--include-officers", action="store_true", help="Fetch officer records for each company (additional API calls).")
    parser.add_argument("--include-profiles", action="store_true", help="Fetch full company profiles (additional API calls).")
    parser.add_argument("--fresh", action="store_true", help="Start a new extraction instead of resuming existing JSONL files.")
    args = parser.parse_args()

    if args.limit < 1:
        parser.error("--limit must be at least 1.")
    if not 1 <= args.page_size <= 5000:
        parser.error("--page-size must be between 1 and 5000.")

    companies_path = RAW / "companies.jsonl"
    officers_path = RAW / "officers.jsonl"
    if args.fresh:
        companies_path.unlink(missing_ok=True)
        officers_path.unlink(missing_ok=True)

    existing_companies = read_jsonl(companies_path)
    seen = {str(row.get("company_number", "")).upper() for row in existing_companies}
    existing_officers = read_jsonl(officers_path)
    officers_done = {str(row.get("company_number", "")).upper() for row in existing_officers}

    client = CompaniesHouseClient()
    sic_codes = load_sic_codes(args.include_adjacent_sic)
    added = 0

    log.info("Starting UK construction extraction. Limit=%s, existing=%s, SIC codes=%s",
             args.limit, len(seen), len(sic_codes))

    for sic in sic_codes:
        if len(seen) >= args.limit:
            break
        log.info("Searching SIC %s", sic)
        for item in client.iter_companies_for_sic(sic, page_size=args.page_size):
            number = str(item.get("company_number", "")).upper()
            if not number:
                continue

            if number in seen:
                # Allow a later run with --include-officers / --include-profiles
                # to enrich companies that were collected in an earlier run.
                if args.include_officers and number not in officers_done:
                    try:
                        prior = next((r for r in existing_companies if str(r.get("company_number", "")).upper() == number), item)
                        prior_name = prior.get("company_name")
                        prior_url = prior.get("source_url") or f"https://find-and-update.company-information.service.gov.uk/company/{number}"
                        for officer in client.company_officers(number):
                            append_jsonl(officers_path, {
                                "company_number": number, "company_name": prior_name,
                                "officer_name": officer.get("name"),
                                "officer_role": officer.get("officer_role"),
                                "appointed_on": officer.get("appointed_on"),
                                "resigned_on": officer.get("resigned_on"),
                                "nationality": officer.get("nationality"),
                                "occupation": officer.get("occupation"),
                                "officer_status": "resigned" if officer.get("resigned_on") else "current_or_not_marked_resigned",
                                "source": "Companies House company officers", "source_url": prior_url,
                            })
                        officers_done.add(number)
                    except Exception as exc:
                        log.warning("Officer retrieval failed for existing company %s: %s", number, exc)
                continue

            row = dict(item)
            row["source"] = "Companies House advanced company search"
            row["source_url"] = f"https://find-and-update.company-information.service.gov.uk/company/{number}"
            row["matched_sic_query"] = sic

            if args.include_profiles:
                try:
                    profile = client.company_profile(number)
                    row["profile"] = profile
                    # Profile can contain more current SIC codes than the search result.
                    if profile.get("sic_codes"):
                        row["sic_codes"] = profile["sic_codes"]
                except Exception as exc:
                    row["profile_error"] = str(exc)

            append_jsonl(companies_path, row)
            seen.add(number)
            added += 1

            if args.include_officers and number not in officers_done:
                try:
                    officers = client.company_officers(number)
                    for officer in officers:
                        officer_row = {
                            "company_number": number,
                            "company_name": row.get("company_name"),
                            "officer_name": officer.get("name"),
                            "officer_role": officer.get("officer_role"),
                            "appointed_on": officer.get("appointed_on"),
                            "resigned_on": officer.get("resigned_on"),
                            "nationality": officer.get("nationality"),
                            "occupation": officer.get("occupation"),
                            "officer_status": "resigned" if officer.get("resigned_on") else "current_or_not_marked_resigned",
                            "source": "Companies House company officers",
                            "source_url": row["source_url"],
                        }
                        append_jsonl(officers_path, officer_row)
                    officers_done.add(number)
                except Exception as exc:
                    log.warning("Officer retrieval failed for %s: %s", number, exc)

            if added and added % 100 == 0:
                log.info("New companies collected: %s; total unique: %s", added, len(seen))
            if len(seen) >= args.limit:
                break

    log.info("Extraction finished. Unique companies stored: %s. New in this run: %s.", len(seen), added)
    log.info("Raw company file: %s", companies_path)
    if args.include_officers:
        log.info("Raw officer file: %s", officers_path)
    log.info("Next: run python export.py")


if __name__ == "__main__":
    main()
