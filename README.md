# UK Construction Lead Generation — Companies House + Clay + Claude

A starter project for extracting UK construction-related company records from the official Companies House Public Data API, exposing selected read-only tools through a remote MCP server, enriching records in Clay, and exporting Excel/CSV files.

## What this project does

- Searches active UK companies by SIC code.
- Deduplicates by Companies House company number.
- Can optionally fetch company profiles and officer records.
- Resumes from JSONL files after interruption.
- Retries transient errors and rate limits.
- Exposes read-only Companies House tools over MCP.
- Exports company, officer, Clay-import and qualified-lead sheets.

**Important data boundary:** Companies House does not provide a universal business email or phone field. Those fields are deliberately blank in the Companies House export and should be enriched through Clay or another provider. Officer records are not the same thing as commercial decision-maker contact records.

## 1. Prerequisites

- Python 3.11 or newer
- A Companies House API key
- A Clay account with sufficient enrichment credits
- A Claude account that supports custom connectors
- For remote MCP: a public HTTPS host (Railway, Render, Fly.io, or a comparable service)

Official documentation:
- Companies House API: https://developer.company-information.service.gov.uk/
- Companies House authentication: https://developer.company-information.service.gov.uk/authentication
- Advanced company search: https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference/search/advanced-company-search
- Claude custom remote MCP: https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
- MCP Python SDK: https://py.sdk.modelcontextprotocol.io/
- Clay CSV import: https://university.clay.com/docs/csv-import-overview
- Clay in Claude: https://university.clay.com/docs/using-clay-in-claude

## 2. Install on Windows

Open PowerShell in this project folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Paste your Companies House API key into `COMPANIES_HOUSE_API_KEY`.
Generate a long random value for `MCP_API_KEY` if you plan to host the remote MCP server.

Do not share `.env`, commit it to Git, or paste API keys into Claude conversations.

## 3. Run a small test first

```powershell
python extract.py --limit 50
python export.py
```

The first run tests company discovery and creates a resumable raw file.

To fetch officer records as well:

```powershell
python extract.py --limit 50 --include-officers
python export.py
```

To fetch full profiles too (more API requests):

```powershell
python extract.py --limit 50 --include-officers --include-profiles
python export.py
```

For a 1,000-company pilot:

```powershell
python extract.py --limit 1000 --include-officers
python export.py
```

For the 10,000-company target:

```powershell
python extract.py --limit 10000 --include-officers
python export.py
```

Resume behaviour:
- Existing `data/raw/companies.jsonl` and `officers.jsonl` are read first.
- Already collected company numbers are skipped.
- Use `--fresh` only when you intentionally want to clear the previous extraction and start over.

Optional adjacent architecture/engineering SIC codes:

```powershell
python extract.py --limit 1000 --include-adjacent-sic --include-officers
```

These are kept identifiable by the matched SIC query. Consider keeping them as a separate segment from contractors and specialist trades.

## 4. Companies House extraction logic

The project uses:

`GET https://api.company-information.service.gov.uk/advanced-search/companies`

The API uses HTTP Basic authentication with the API key as the username and a blank password. Search supports SIC codes, status, result size and `start_index`; the documented maximum `size` is 5,000.

The default extraction uses active companies and searches each SIC code separately. It deduplicates companies appearing under multiple SIC codes. If a single SIC segment has more than the API's retrievable result window, partition that segment further (for example by location or incorporation date) and reconcile by company number. Do not assume one search query represents every possible construction business: companies may use outdated, broad or secondary SIC classifications.

The script uses conservative pacing and retries HTTP 429/5xx responses. Actual request limits and policies can change; check the official developer guidelines before high-volume runs.

## 5. Build the remote MCP server

The MCP server exposes read-only tools:
- `search_construction_companies`
- `get_company_profile`
- `list_company_officers`
- `search_company_officers`

Local test (stdio):

```powershell
python mcp_server.py
```

For a local HTTP test:

```powershell
$env:MCP_TRANSPORT="http"
python mcp_server.py
```

The HTTP endpoint is `/mcp`. The project includes an `X-MCP-API-Key` header check. For remote hosting, set `MCP_API_KEY` in the host's environment variables.

### Deploy on Railway or Render

1. Create a private GitHub repository and push this project (never include `.env`).
2. Create a new Railway or Render service from the repository.
3. Set build/install command to `pip install -r requirements.txt`.
4. Set start command to `uvicorn mcp_server:app --host 0.0.0.0 --port $PORT`.
5. Add environment variables:
   - `COMPANIES_HOUSE_API_KEY`
   - `MCP_API_KEY`
   - `CH_REQUEST_DELAY=0.55`
6. Deploy and confirm `https://YOUR-HOST/health` returns `{"status":"ok",...}`.
7. Your MCP URL is `https://YOUR-HOST/mcp`.

The service must be reachable over public HTTPS because Claude's remote connector connects from Anthropic's cloud infrastructure, not from your laptop.

### Add it to Claude

1. In Claude, open **Customize → Connectors**.
2. Choose **Add custom connector**.
3. Name it `UK Companies House`.
4. Enter your HTTPS MCP URL ending in `/mcp`.
5. Configure the request header:
   - Header name: `X-MCP-API-Key`
   - Value: your `MCP_API_KEY`
6. Complete the connection.
7. Enable the connector in a conversation and test:

```text
Search Companies House for 20 active UK companies with SIC code 41201.
Return company name, company number, registered address, status and source URL.
```

Do not add the Companies House API key as a Claude request header. It stays on the server as an environment variable.

## 6. Connect Clay

Use Clay's official Claude connector as a separate connector:
https://claude.com/connectors/clay

In Claude:
1. Add and authenticate the Clay connector.
2. Keep the Companies House custom connector enabled as well.
3. Ask Claude to research or enrich a small sample before scaling.

For bulk enrichment, import the generated CSV into Clay:

1. In Clay, create a workbook named `UK Construction Lead Generation`.
2. Create a table named `UK_Companies_Raw`.
3. Choose CSV import and upload `data/exports/Clay_Enrichment_Import.csv`.
4. Map `company_number` as the stable unique identifier.
5. Choose **Save and don't run** for the first import.
6. Review the first 50 rows and correct column mappings.
7. Create a second table `UK_Company_Enrichment` or duplicate the raw table for enrichment.
8. Add company-domain/website discovery and company enrichment.
9. Add a conditional `Find People` step using the company domain or LinkedIn company URL.
10. Prioritize titles: Owner, Founder, Managing Director, CEO, Director, Commercial Director, Business Development Director, Preconstruction Director, Estimating Manager.
11. Add email-finding and verification steps only after company/contact matching.
12. Export the enriched table as CSV and retain the original Companies House company number.

### Recommended Clay table columns

Company:
- company_number
- company_name
- sic_codes
- registered address
- website/domain
- company LinkedIn URL
- company description
- services
- employee count
- business phone
- general business email
- data provider
- last verified

People:
- company_number
- contact name
- job title
- seniority
- LinkedIn profile
- work email
- email verification status
- business phone
- source/provider
- last verified

Do not label catch-all, unknown or unverified addresses as verified. Do not infer email addresses from naming patterns and present them as confirmed.

## 7. Export final Excel and CSV

After extraction:

```powershell
python export.py
```

Files are created in `data/exports/`:
- `UK_Construction_Lead_Database.xlsx`
- `UK_Construction_Companies.csv`
- `UK_Company_Officers.csv`
- `Clay_Enrichment_Import.csv`
- `UK_Qualified_Leads.csv`

After Clay enrichment, export its company and people tables as CSV and merge them using `company_number` (company table) and a stable contact identifier or normalized name + company number (people table). Keep raw registry fields and enriched fields in separate columns so provenance is visible.

## 8. Data quality and compliance

- Company records are corporate registry data; officer records can include personal data.
- Collect only fields needed for your defined B2B purpose.
- Do not export dates of birth or residential details for prospecting.
- A director's Companies House appointment does not mean they consented to marketing.
- UK B2B email marketing rules depend on subscriber type and context. Check PECR and UK GDPR before outreach; sole traders and some partnerships have different protections from corporate subscribers.
- Keep suppression/opt-out records and honor objections.
- Record source, collection date and verification status for each field.
- Set a retention/review schedule and avoid collecting unnecessary personal data.

## 9. Suggested run plan

1. Run 50 companies, inspect output.
2. Run 1,000 companies, include officers.
3. Import a 50-company sample into Clay.
4. Validate enrichment quality and credit consumption.
5. Enrich the remaining 950.
6. Review duplicates, company types and contact accuracy.
7. Increase to 5,000, then 10,000 if the data quality and credit budget justify it.

## Troubleshooting

- `401`: API key missing or invalid; verify `.env` and restart.
- `429`: reduce `CH_REQUEST_DELAY`; the client also honours numeric `Retry-After`.
- No rows: check SIC code spelling and company status; test a known SIC such as `41201`.
- Repeated records: dedupe on normalized company number, not company name.
- Missing emails/phones: expected from Companies House; enrich through Clay.
- Claude cannot connect: confirm public HTTPS, `/mcp` path, correct header name/value, and that the host is running the Streamable HTTP app.
