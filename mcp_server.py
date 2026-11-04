from __future__ import annotations

import os
import secrets
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from companies_house import CompaniesHouseClient

load_dotenv()
mcp = FastMCP("UK Construction Companies House", json_response=True)


def client() -> CompaniesHouseClient:
    return CompaniesHouseClient()


@mcp.tool()
def search_construction_companies(sic_code: str, max_results: int = 100, company_status: str = "active") -> dict[str, Any]:
    """Search UK companies by a single SIC code. Limit max_results to 1-5000. Use this for targeted research, not full 10k bulk extraction."""
    if len(sic_code) != 5 or not sic_code.isdigit():
        raise ValueError("sic_code must be a five-digit UK SIC code.")
    if not 1 <= max_results <= 5000:
        raise ValueError("max_results must be between 1 and 5000.")
    api = client()
    results = []
    start = 0
    while len(results) < max_results:
        page_size = min(500, max_results - len(results))
        payload = api.search_companies([sic_code], company_status=company_status, size=page_size, start_index=start)
        items = payload.get("items", []) or []
        if not items:
            break
        results.extend(items)
        start += len(items)
        total = payload.get("total_results")
        if total is not None and start >= int(total):
            break
        if len(items) < page_size:
            break
    return {"sic_code": sic_code, "count": len(results), "total_results_reported": payload.get("total_results", 0) if results else 0, "companies": results[:max_results]}


@mcp.tool()
def get_company_profile(company_number: str) -> dict[str, Any]:
    """Retrieve the official Companies House profile for a UK company number."""
    return client().company_profile(company_number)


@mcp.tool()
def list_company_officers(company_number: str) -> dict[str, Any]:
    """Retrieve available officer appointments for a company. Companies House does not provide officers' business email addresses or phone numbers."""
    officers = client().company_officers(company_number)
    return {"company_number": company_number, "count": len(officers), "officers": officers}


@mcp.tool()
def search_company_officers(query: str, limit: int = 20) -> dict[str, Any]:
    """Search the Companies House officer index by name."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100.")
    return client().search_officers(query, items_per_page=limit)


async def health(request: Request):
    return JSONResponse({"status": "ok", "service": "uk-construction-companies-house-mcp"})


app = mcp.streamable_http_app()
app.routes.append(Route("/health", health, methods=["GET"]))


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/mcp"):
            expected = os.getenv("MCP_API_KEY", "")
            supplied = request.headers.get("x-mcp-api-key", "")
            if not expected:
                return JSONResponse({"error": "MCP_API_KEY is not configured"}, status_code=503)
            if not secrets.compare_digest(supplied, expected):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


app.add_middleware(APIKeyMiddleware)


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    if transport == "http":
        mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
    else:
        mcp.run()
