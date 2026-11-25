"""python -m mcp_invoice [--transport stdio|streamable-http]

stdio is the default: the client (Claude Desktop, Claude Code, an IDE) starts this process itself. Logs go to
stderr, because stdout carries the protocol.
"""

import argparse
import logging
import sys

from .backend import InvoiceBackend
from .server import build_server
from .settings import Settings


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per API call is noise on stderr
    settings = Settings.from_env()
    backend = InvoiceBackend(settings.api_base_url, settings.api_key, settings.timeout_seconds)
    server = build_server(settings, backend)
    log = logging.getLogger("mcp_invoice")
    log.info("backend %s, writes %s", settings.api_base_url, "ENABLED" if settings.enable_writes else "disabled")
    if args.transport == "streamable-http":
        log.warning("streamable-http has no authentication here: keep it on localhost or behind your own gateway")
        server.run("streamable-http", host=args.host, port=args.port)
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
