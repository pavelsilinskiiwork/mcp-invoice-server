import json
from dataclasses import dataclass

import httpx
import pytest
from fake_backend import make_app
from mcp import Client

from mcp_invoice.audit import AuditLog
from mcp_invoice.backend import InvoiceBackend
from mcp_invoice.server import build_server
from mcp_invoice.settings import Settings


@dataclass
class Result:
    is_error: bool
    text: str

    @property
    def data(self):
        return json.loads(self.text)


class Session:
    """An MCP client connected in memory to a server wired to a fake doc-extraction API."""

    def __init__(self, client, app, audit_path):
        self.client, self.app, self.audit_path = client, app, audit_path

    async def call(self, name, **arguments) -> Result:
        r = await self.client.call_tool(name, arguments)
        return Result(bool(r.is_error), r.content[0].text if r.content else "")

    def audit(self):
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text().splitlines()]


@pytest.fixture
def open_session(tmp_path):
    """open_session(writes=False, api_key=None, ...) is an async context manager yielding a Session."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def make(
        writes=False, api_key=None, key_sent="", storage=True, backend_app=None, audit_path=None, **settings
    ):
        app = backend_app or make_app(api_key=api_key, storage=storage)
        backend = InvoiceBackend("http://api", key_sent, transport=httpx.ASGITransport(app=app))
        audit_path = audit_path or tmp_path / "audit.jsonl"
        s = Settings(enable_writes=writes, audit_log=str(audit_path), **settings)
        server = build_server(s, backend, AuditLog(str(audit_path)))
        async with Client(server) as client:
            yield Session(client, app, audit_path)
        await backend.aclose()

    return make
