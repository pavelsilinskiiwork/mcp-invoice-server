import httpx
import pytest

from mcp_invoice import __main__ as cli
from mcp_invoice.backend import BackendError, InvoiceBackend
from mcp_invoice.settings import Settings


async def test_wrong_api_key_gives_an_actionable_message_without_leaking_the_key(open_session):
    async with open_session(api_key="right-key", key_sent="wrong-key-123") as s:
        r = await s.call("list_invoices")
    assert r.is_error and "INVOICE_API_KEY" in r.text
    assert "wrong-key-123" not in r.text and "right-key" not in r.text


async def test_correct_api_key_works(open_session):
    async with open_session(api_key="right-key", key_sent="right-key") as s:
        assert not (await s.call("list_invoices")).is_error


async def test_missing_storage_is_explained(open_session):
    async with open_session(storage=False) as s:
        r = await s.call("list_invoices")
    assert r.is_error and "DATABASE_URL" in r.text


async def test_unreachable_api_is_a_clear_error_not_a_crash(open_session):
    def down(request):
        raise httpx.ConnectError("refused")

    async def check():
        backend = InvoiceBackend("http://api", transport=httpx.MockTransport(down))
        with pytest.raises(BackendError, match="not reachable"):
            await backend.list_extractions()
        await backend.aclose()

    await check()


async def test_server_errors_do_not_leak_details():
    backend = InvoiceBackend(
        "http://api", transport=httpx.MockTransport(lambda r: httpx.Response(500, text="SECRET trace"))
    )
    with pytest.raises(BackendError) as e:
        await backend.get_extraction(1)
    assert "SECRET" not in str(e.value) and "500" in str(e.value)
    await backend.aclose()


async def test_validation_errors_from_the_api_are_summarised():
    body = {"detail": [{"loc": ["body", "total"], "msg": "Value error, total != subtotal"}]}
    backend = InvoiceBackend("http://api", transport=httpx.MockTransport(lambda r: httpx.Response(422, json=body)))
    with pytest.raises(BackendError, match="total: Value error, total != subtotal"):
        await backend.correct(1, {})
    await backend.aclose()


def test_settings_defaults_are_the_safe_ones():
    s = Settings.from_env({})
    assert s.enable_writes is False and s.max_writes_per_session == 20 and s.api_base_url == "http://localhost:8000"


def test_settings_from_env():
    s = Settings.from_env({"INVOICE_API_URL": "http://x:9/", "INVOICE_API_KEY": "k", "MCP_ENABLE_WRITES": "true",
                           "MCP_MAX_WRITES": "3", "MCP_AUDIT_LOG": "a.jsonl", "MCP_MAX_DOC_CHARS": "50"})  # fmt: skip
    assert (s.api_base_url, s.api_key, s.enable_writes, s.max_writes_per_session) == ("http://x:9", "k", True, 3)
    assert (s.audit_log, s.max_document_chars) == ("a.jsonl", 50)


@pytest.mark.parametrize("argv,expected", [([], ("stdio", {})), (["--transport", "streamable-http", "--port", "9000"],
                                           ("streamable-http", {"host": "127.0.0.1", "port": 9000}))])  # fmt: skip
def test_cli_picks_the_transport(monkeypatch, argv, expected):
    calls = []

    class FakeServer:
        def run(self, transport, **kwargs):
            calls.append((transport, kwargs))

    monkeypatch.setattr(cli, "build_server", lambda *a, **k: FakeServer())
    cli.main(argv)
    assert calls == [expected]
