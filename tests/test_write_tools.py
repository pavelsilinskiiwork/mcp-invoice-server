import pytest
from fake_backend import GOOD_INVOICE

from mcp_invoice.server import diff_invoices

CORRECTION = {**GOOD_INVOICE, "vendor": "Acme Limited", "invoice_number": "A-2"}  # row 2 differs only by vendor


async def test_write_tools_exist_only_when_enabled_and_are_annotated(open_session):
    async with open_session(writes=True) as s:
        tools = {t.name: t for t in (await s.client.list_tools()).tools}
    assert {"approve_invoice", "correct_invoice", "reject_invoice"} <= set(tools)
    for name in ("approve_invoice", "correct_invoice", "reject_invoice"):
        assert tools[name].annotations.read_only_hint is False
    assert (
        tools["correct_invoice"].annotations.destructive_hint and tools["reject_invoice"].annotations.destructive_hint
    )
    assert not tools["approve_invoice"].annotations.destructive_hint


async def test_confirm_defaults_to_false_in_every_write_schema(open_session):
    async with open_session(writes=True) as s:
        tools = {t.name: t for t in (await s.client.list_tools()).tools}
    for name in ("approve_invoice", "correct_invoice", "reject_invoice"):
        assert tools[name].input_schema["properties"]["confirm"]["default"] is False


@pytest.mark.parametrize(
    "tool,args",
    [
        ("approve_invoice", {"extraction_id": 2}),
        ("correct_invoice", {"extraction_id": 2, "invoice": CORRECTION}),
        ("reject_invoice", {"extraction_id": 2, "reason": "not an invoice"}),
    ],
)
async def test_without_confirm_nothing_changes_and_a_preview_comes_back(open_session, tool, args):
    async with open_session(writes=True) as s:
        r = await s.call(tool, **args)
        assert r.data["status"] == "confirmation_required" and r.data["invoice"]["id"] == 2
        assert "confirm=true" in r.data["next_step"]
        assert s.app.state.calls == []
        assert s.app.state.store[2]["review_status"] == "needs_review"
    assert [e["event"] for e in s.audit()] == ["preview"]


async def test_approve_with_confirm_writes_and_leaves_an_audit_trail_in_order(open_session):
    async with open_session(writes=True) as s:
        r = await s.call("approve_invoice", extraction_id=2, confirm=True)
        assert r.data["status"] == "approved" and r.data["invoice"]["review_status"] == "approved"
        assert s.app.state.calls == [("approve", 2)]
    assert [(e["event"], e["tool"]) for e in s.audit()] == [("attempt", "approve_invoice"), ("done", "approve_invoice")]


async def test_correction_preview_shows_exactly_what_would_change(open_session):
    async with open_session(writes=True) as s:
        r = await s.call("correct_invoice", extraction_id=2, invoice=CORRECTION)
    assert r.data["changes"] == [{"field": "vendor", "from": "Acme Ltd", "to": "Acme Limited"}]


async def test_correction_with_confirm_is_stored_beside_the_original(open_session):
    async with open_session(writes=True) as s:
        r = await s.call("correct_invoice", extraction_id=2, invoice=CORRECTION, confirm=True)
        assert r.data["status"] == "corrected"
        row = s.app.state.store[2]
        assert row["corrected_invoice"]["vendor"] == "Acme Limited" and row["invoice"]["vendor"] == "Acme Ltd"
    assert s.audit()[0]["invoice"]["vendor"] == "Acme Limited"  # the proposed data is in the audit record


async def test_a_correction_that_fails_the_apis_arithmetic_check_is_reported_not_stored(open_session):
    bad = {**CORRECTION, "total": "99.99"}
    async with open_session(writes=True) as s:
        r = await s.call("correct_invoice", extraction_id=2, invoice=bad, confirm=True)
        assert r.is_error and "total != subtotal" in r.text
        assert s.app.state.calls == [] and s.app.state.store[2]["corrected_invoice"] is None
    assert [e["event"] for e in s.audit()] == ["attempt"]  # attempted, never done


async def test_malformed_corrections_are_rejected_before_any_api_call(open_session):
    async with open_session(writes=True) as s:
        negative = {
            **CORRECTION,
            "line_items": [{"description": "x", "quantity": "-1", "unit_price": "1", "amount": "1"}],
        }
        assert (await s.call("correct_invoice", extraction_id=2, invoice=negative, confirm=True)).is_error
        assert (await s.call("correct_invoice", extraction_id=2, invoice={"vendor": "x"}, confirm=True)).is_error
        assert s.app.state.calls == []


async def test_reject_needs_a_reason_and_records_it_in_the_audit_log(open_session):
    async with open_session(writes=True) as s:
        assert (await s.call("reject_invoice", extraction_id=2, reason="x", confirm=True)).is_error
        r = await s.call("reject_invoice", extraction_id=2, reason="This is a brochure, not an invoice", confirm=True)
        assert r.data["status"] == "rejected" and s.app.state.calls == [("reject", 2)]
    assert s.audit()[-1]["reason"] == "This is a brochure, not an invoice"


async def test_approving_an_extraction_without_an_invoice_surfaces_the_apis_conflict(open_session):
    async with open_session(writes=True) as s:
        r = await s.call("approve_invoice", extraction_id=4, confirm=True)
    assert r.is_error and "submit a correction instead" in r.text


async def test_session_write_cap_stops_a_runaway_loop_but_not_previews(open_session):
    async with open_session(writes=True, max_writes_per_session=2) as s:
        for i in (2, 3):
            assert (await s.call("approve_invoice", extraction_id=i, confirm=True)).data["status"] == "approved"
        refused = await s.call("approve_invoice", extraction_id=5, confirm=True)
        assert refused.is_error and "Write limit reached" in refused.text
        assert (await s.call("approve_invoice", extraction_id=5)).data["status"] == "confirmation_required"
        assert s.app.state.calls == [("approve", 2), ("approve", 3)]
    assert "refused" in [e["event"] for e in s.audit()]


async def test_if_the_audit_log_cannot_be_written_the_write_is_refused(open_session, tmp_path):
    broken = tmp_path / "no-such-dir" / "audit.jsonl"
    async with open_session(writes=True, audit_path=broken) as s:
        r = await s.call("approve_invoice", extraction_id=2, confirm=True)
        assert r.is_error and "audit log" in r.text
        assert s.app.state.calls == []
        preview = await s.call("approve_invoice", extraction_id=2)  # previews still work
        assert preview.data["status"] == "confirmation_required"


def test_diff_ignores_number_formatting_and_reports_line_changes():
    current = {**GOOD_INVOICE}
    assert diff_invoices(current, {**GOOD_INVOICE, "total": "22.680", "tax": 1.68}) == []
    changed = {**GOOD_INVOICE, "line_items": [{**GOOD_INVOICE["line_items"][0], "quantity": "3"}]}
    diff = diff_invoices(current, changed)
    assert [d["field"] for d in diff] == ["line_items[0]"]
    added = {**GOOD_INVOICE, "line_items": GOOD_INVOICE["line_items"] * 2}
    assert [d["field"] for d in diff_invoices(current, added)] == ["line_items[1]"]
    assert diff_invoices(None, GOOD_INVOICE)  # no current invoice: everything is new
