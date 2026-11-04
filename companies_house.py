from __future__ import annotations

import os
import time
import logging
from typing import Any, Iterator

import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

BASE_URL = "https://api.company-information.service.gov.uk"


class CompaniesHouseError(RuntimeError):
    pass


class CompaniesHouseClient:
    def __init__(self, api_key: str | None = None, delay: float | None = None):
        self.api_key = api_key or os.getenv("COMPANIES_HOUSE_API_KEY")
        if not self.api_key:
            raise ValueError("Set COMPANIES_HOUSE_API_KEY in your .env file.")
        self.delay = float(delay if delay is not None else os.getenv("CH_REQUEST_DELAY", "0.55"))
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(self.api_key, "")
        self.session.headers.update({"Accept": "application/json", "User-Agent": "UK-Construction-Leadgen/1.0"})
        self._last_request = 0.0

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        for attempt in range(7):
            wait = self.delay - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                response = self.session.get(url, params=params, timeout=45)
                self._last_request = time.monotonic()
            except requests.RequestException as exc:
                if attempt == 6:
                    raise CompaniesHouseError(f"Network error calling {path}: {exc}") from exc
                time.sleep(min(2 ** attempt, 30))
                continue

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                pause = float(retry_after) if retry_after and retry_after.isdigit() else min(5 * (attempt + 1), 60)
                log.warning("Rate limited by Companies House; waiting %s seconds", pause)
                time.sleep(pause)
                continue

            if response.status_code in (500, 502, 503, 504):
                if attempt == 6:
                    raise CompaniesHouseError(f"Companies House server error {response.status_code}: {response.text[:500]}")
                time.sleep(min(2 ** attempt, 30))
                continue

            if response.status_code == 404:
                return {}
            if not response.ok:
                raise CompaniesHouseError(f"Companies House returned {response.status_code}: {response.text[:1000]}")
            try:
                return response.json()
            except ValueError as exc:
                raise CompaniesHouseError(f"Invalid JSON response from {path}") from exc

        raise CompaniesHouseError(f"Request retries exhausted for {path}")

    def search_companies(
        self,
        sic_codes: list[str],
        company_status: str = "active",
        size: int = 500,
        start_index: int = 0,
    ) -> dict[str, Any]:
        if not 1 <= size <= 5000:
            raise ValueError("size must be between 1 and 5000.")
        return self._get(
            "/advanced-search/companies",
            {
                "company_status": company_status,
                "sic_codes": ",".join(sic_codes),
                "size": size,
                "start_index": start_index,
            },
        )

    def iter_companies_for_sic(self, sic_code: str, page_size: int = 500) -> Iterator[dict[str, Any]]:
        start = 0
        while True:
            payload = self.search_companies([sic_code], size=page_size, start_index=start)
            items = payload.get("items", []) or []
            if not items:
                break
            for item in items:
                yield item
            start += len(items)
            total = payload.get("total_results")
            if total is not None and start >= int(total):
                break
            if len(items) < page_size:
                break

    def company_profile(self, company_number: str) -> dict[str, Any]:
        return self._get(f"/company/{company_number}")

    def company_officers(self, company_number: str, page_size: int = 100) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        start = 0
        while True:
            payload = self._get(
                f"/company/{company_number}/officers",
                {"items_per_page": page_size, "start_index": start},
            )
            items = payload.get("items", []) or []
            results.extend(items)
            if not items or len(items) < page_size:
                break
            start += len(items)
            total = payload.get("total_results")
            if total is not None and start >= int(total):
                break
        return results

    def search_officers(self, query: str, items_per_page: int = 20, start_index: int = 0) -> dict[str, Any]:
        return self._get(
            "/search/officers",
            {"q": query, "items_per_page": items_per_page, "start_index": start_index},
        )
