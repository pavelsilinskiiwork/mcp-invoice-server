"""A thin async client for the doc-extraction API.

The API is the single authority: it validates corrections, decides what is allowed and stores the review
decision. This client only translates its errors into messages an assistant (and a person) can act on.
Error messages never include the API key or a stack trace.
"""

from typing import Any

import httpx


class BackendError(Exception):
    """A failure that is safe to show to the assistant."""


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return ""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):  # FastAPI validation errors
        parts = []
        for item in detail[:5]:
            where = ".".join(str(p) for p in item.get("loc", []) if p != "body")
            parts.append(f"{where}: {item.get('msg', '')}".strip(": "))
        return "; ".join(parts)
    if isinstance(detail, dict):
        return str(detail.get("message", ""))
    return ""


class InvoiceBackend:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 15.0, transport=None):
        headers = {"X-API-Key": api_key} if api_key else {}
        self.client = httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise BackendError("The invoice API is not reachable. Is it running?") from e
        status = response.status_code
        if status < 400:
            return response.json()
        detail = _detail(response)
        if status == 401:
            raise BackendError("The invoice API rejected the API key (check INVOICE_API_KEY).")
        if status == 404:
            raise BackendError(detail or "Not found.")
        if status == 409:
            raise BackendError(detail or "The invoice is in a state that does not allow this.")
        if status == 422:
            raise BackendError(f"The invoice API rejected the data: {detail or 'validation failed'}")
        if status == 503:
            raise BackendError("The invoice API has no storage configured (DATABASE_URL).")
        raise BackendError(f"The invoice API failed with status {status}.")

    async def list_extractions(self, review_status=None, status=None, limit=20, offset=0) -> dict:
        params = {"limit": limit, "offset": offset}
        if review_status:
            params["review_status"] = review_status
        if status:
            params["status"] = status
        return await self._request("GET", "/extractions", params=params)

    async def get_extraction(self, extraction_id: int) -> dict:
        return await self._request("GET", f"/extractions/{extraction_id}")

    async def accuracy(self) -> dict:
        return await self._request("GET", "/stats/accuracy")

    async def approve(self, extraction_id: int) -> dict:
        return await self._request("POST", f"/extractions/{extraction_id}/approve")

    async def correct(self, extraction_id: int, invoice: dict) -> dict:
        return await self._request("PUT", f"/extractions/{extraction_id}/correction", json=invoice)

    async def reject(self, extraction_id: int) -> dict:
        return await self._request("POST", f"/extractions/{extraction_id}/reject")
