async def test_read_only_server_exposes_only_read_tools(open_session):
    async with open_session() as s:
        names = {t.name for t in (await s.client.list_tools()).tools}
    assert names == {"list_invoices", "review_queue", "get_invoice", "accuracy_stats"}


async def test_every_read_tool_is_annotated_read_only(open_session):
    async with open_session() as s:
        tools = (await s.client.list_tools()).tools
    assert all(t.annotations.read_only_hint and not t.annotations.destructive_hint for t in tools)


async def test_list_invoices_returns_short_summaries_newest_first(open_session):
    async with open_session() as s:
        data = (await s.call("list_invoices", limit=3)).data
    assert data["total"] == 5 and data["returned"] == 3
    assert [i["id"] for i in data["items"]] == [5, 4, 3]
    assert "document_text" not in data["items"][0]


async def test_list_invoices_filters_by_review_status(open_session):
    async with open_session() as s:
        data = (await s.call("list_invoices", review_status="ok")).data
    assert [i["id"] for i in data["items"]] == [1]


async def test_invalid_arguments_are_rejected_before_reaching_the_api(open_session):
    async with open_session() as s:
        assert (await s.call("list_invoices", limit=500)).is_error
        assert (await s.call("list_invoices", review_status="banana")).is_error
        assert (await s.call("get_invoice", extraction_id="abc")).is_error


async def test_review_queue_is_oldest_first_and_explains_why(open_session):
    async with open_session() as s:
        data = (await s.call("review_queue")).data
    assert [i["id"] for i in data["items"]] == [2, 3, 4, 5]
    assert data["waiting_total"] == 4
    assert data["items"][1]["review_reasons"] == ["same vendor and invoice number as extraction #1"]


async def test_get_invoice_keeps_original_and_correction_apart_and_omits_text_by_default(open_session):
    async with open_session() as s:
        data = (await s.call("get_invoice", extraction_id=2)).data
    assert data["invoice"]["vendor"] == "Acme Ltd" and data["corrected_invoice"] is None
    assert "document_text" not in data


async def test_get_invoice_not_found_is_a_clean_tool_error(open_session):
    async with open_session() as s:
        r = await s.call("get_invoice", extraction_id=999)
    assert r.is_error and "Extraction 999 not found" in r.text and "Traceback" not in r.text


async def test_accuracy_stats_passes_the_api_answer_through(open_session):
    async with open_session() as s:
        data = (await s.call("accuracy_stats")).data
    assert data["providers"][0]["accuracy"] == 0.75


async def test_resource_and_prompt_are_available(open_session):
    async with open_session() as s:
        prompts = (await s.client.list_prompts()).prompts
        templates = (await s.client.list_resource_templates()).resource_templates
        content = await s.client.read_resource("invoice://2")
    assert [p.name for p in prompts] == ["review_next_invoice"]
    assert [t.uri_template for t in templates] == ["invoice://{extraction_id}"]
    assert '"id": 2' in content.contents[0].text
    assert "document_text" not in content.contents[0].text


async def test_server_tells_the_client_that_invoice_text_is_untrusted(open_session):
    async with open_session() as s:
        text = s.client.instructions
    assert "DATA" in text and "confirm" in text
