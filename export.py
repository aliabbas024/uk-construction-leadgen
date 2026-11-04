from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

BASE = Path(__file__).resolve().parent
RAW = BASE / "data" / "raw"
OUT = BASE / "data" / "exports"
OUT.mkdir(parents=True, exist_ok=True)


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
                    continue
    return rows


def get_address(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("registered_office_address") or item.get("address") or {}


def company_rows(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for c in raw:
        address = get_address(c)
        profile = c.get("profile") or {}
        output.append({
            "company_number": c.get("company_number"),
            "company_name": c.get("company_name"),
            "company_status": c.get("company_status"),
            "company_type": c.get("company_type"),
            "date_of_creation": c.get("date_of_creation") or profile.get("date_of_creation"),
            "sic_codes": ";".join(c.get("sic_codes") or profile.get("sic_codes") or []),
            "registered_address_line_1": address.get("address_line_1"),
            "registered_address_line_2": address.get("address_line_2"),
            "locality": address.get("locality"),
            "region": address.get("region"),
            "postal_code": address.get("postal_code"),
            "country": address.get("country") or "United Kingdom",
            "website": "",
            "company_linkedin_url": "",
            "business_email": "",
            "business_phone": "",
            "employee_count": "",
            "revenue_estimate": "",
            "clay_company_category": "",
            "icp_score": "",
            "qualification_status": "Needs Clay enrichment",
            "source": c.get("source"),
            "source_url": c.get("source_url"),
            "matched_sic_query": c.get("matched_sic_query"),
        })
    return output


def main() -> None:
    companies = read_jsonl(RAW / "companies.jsonl")
    officers = read_jsonl(RAW / "officers.jsonl")

    # Deduplicate by Companies House company number; preserve first record.
    unique = {}
    for row in companies:
        number = str(row.get("company_number", "")).upper()
        if number and number not in unique:
            unique[number] = row

    companies_df = pd.DataFrame(company_rows(list(unique.values())))
    officers_df = pd.DataFrame(officers)

    # A separate Clay import template; enrich these fields in Clay and export back.
    clay_template = companies_df[[
        "company_number", "company_name", "sic_codes", "registered_address_line_1",
        "locality", "region", "postal_code", "country", "source_url"
    ]].copy()
    for col in [
        "website", "company_linkedin_url", "company_description", "services",
        "employee_count", "revenue_estimate", "business_email", "business_phone",
        "decision_maker_name", "decision_maker_title", "decision_maker_linkedin",
        "decision_maker_email", "decision_maker_phone", "email_verification_status",
        "provider", "last_verified"
    ]:
        clay_template[col] = ""

    qualified = companies_df.copy()
    qualified["icp_score"] = ""
    qualified["qualification_status"] = "Pending manual/AI qualification"

    companies_csv = OUT / "UK_Construction_Companies.csv"
    officers_csv = OUT / "UK_Company_Officers.csv"
    clay_csv = OUT / "Clay_Enrichment_Import.csv"
    qualified_csv = OUT / "UK_Qualified_Leads.csv"
    workbook = OUT / "UK_Construction_Lead_Database.xlsx"

    companies_df.to_csv(companies_csv, index=False, encoding="utf-8-sig")
    officers_df.to_csv(officers_csv, index=False, encoding="utf-8-sig")
    clay_template.to_csv(clay_csv, index=False, encoding="utf-8-sig")
    qualified.to_csv(qualified_csv, index=False, encoding="utf-8-sig")

    readme_df = pd.DataFrame([
        {"item": "Company records", "value": len(companies_df)},
        {"item": "Officer records", "value": len(officers_df)},
        {"item": "Business emails", "value": "Not supplied by Companies House; enrich and verify in Clay"},
        {"item": "Business phones", "value": "Not supplied by Companies House for every company; enrich in Clay"},
        {"item": "ICP scores", "value": "Blank until evidence-based qualification is completed"},
        {"item": "Source", "value": "Companies House Public Data API"},
    ])

    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        companies_df.to_excel(writer, sheet_name="Companies", index=False)
        officers_df.to_excel(writer, sheet_name="Officers", index=False)
        clay_template.to_excel(writer, sheet_name="Clay_Import", index=False)
        qualified.to_excel(writer, sheet_name="Qualified_Leads", index=False)
        readme_df.to_excel(writer, sheet_name="Read_Me", index=False)

        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for col_cells in ws.columns:
                max_len = max((len(str(cell.value or "")) for cell in col_cells[:300]), default=10)
                ws.column_dimensions[col_cells[0].column_letter].width = min(max(max_len + 2, 12), 42)

    print(f"Export complete: {len(companies_df)} companies; {len(officers_df)} officer rows")
    print(f"Excel: {workbook}")
    print(f"CSV: {companies_csv}, {officers_csv}, {clay_csv}, {qualified_csv}")


if __name__ == "__main__":
    main()
