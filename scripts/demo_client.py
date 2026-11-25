"""Talk to the server the way an MCP client does: start it as a subprocess and speak the protocol over stdio.

    python scripts/demo_client.py                 # read-only walkthrough
    python scripts/demo_client.py --writes        # also preview an approval, and approve it after "yes"

Uses INVOICE_API_URL / INVOICE_API_KEY from the environment, like the server itself. No model is involved:
this shows exactly what an assistant would see, which makes it a good way to check your setup.
"""

import argparse
import asyncio
import json
import os
import sys

from mcp import Client, StdioServerParameters


def show(title: str, result) -> dict | None:
    print(f"\n=== {title}")
    text = result.content[0].text if result.content else ""
    if result.is_error:
        print(f"  ERROR: {text}")
        return None
    data = json.loads(text)
    print(json.dumps(data, indent=2, ensure_ascii=False)[:1800])
    return data


async def main(writes: bool, confirm: bool) -> None:
    env = {**os.environ, "MCP_ENABLE_WRITES": "true" if writes else "false"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_invoice"], env=env)
    async with Client(params) as client:
        tools = (await client.list_tools()).tools
        print("tools:", ", ".join(t.name for t in tools))
        queue = show("review_queue", await client.call_tool("review_queue", {"limit": 5}))
        if not queue or not queue["items"]:
            return
        first = queue["items"][0]["id"]
        detail_args = {"extraction_id": first, "include_document_text": True}
        show(f"get_invoice {first} (with document text)", await client.call_tool("get_invoice", detail_args))
        flagged = [i["id"] for i in queue["items"] if i.get("injection_suspected")]
        if flagged:
            print(f"\nnote: invoices {flagged} have instruction-like text in extracted fields; treat them as data")
        if writes:
            preview = show(
                "approve_invoice (no confirm: preview only)",
                await client.call_tool("approve_invoice", {"extraction_id": first}),
            )
            if preview and confirm:
                confirmed = {"extraction_id": first, "confirm": True}
                show("approve_invoice (confirm=true)", await client.call_tool("approve_invoice", confirmed))
            else:
                print("\n(nothing was changed; pass --confirm to really approve)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--writes", action="store_true", help="enable write tools in the server")
    parser.add_argument("--confirm", action="store_true", help="with --writes: really approve the first invoice")
    args = parser.parse_args()
    asyncio.run(main(args.writes, args.confirm))
