import os
from dataclasses import dataclass


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_base_url: str = "http://localhost:8000"
    api_key: str = ""
    enable_writes: bool = False  # off by default: approve / correct / reject are not even listed
    max_writes_per_session: int = 20  # a runaway loop cannot approve the whole queue
    audit_log: str = "mcp_audit.jsonl"
    max_document_chars: int = 4000
    timeout_seconds: float = 15.0

    @classmethod
    def from_env(cls, env=None) -> "Settings":
        env = os.environ if env is None else env
        d = cls()
        return cls(
            api_base_url=env.get("INVOICE_API_URL", d.api_base_url).rstrip("/"),
            api_key=env.get("INVOICE_API_KEY", d.api_key),
            enable_writes=_bool(env.get("MCP_ENABLE_WRITES", str(d.enable_writes))),
            max_writes_per_session=int(env.get("MCP_MAX_WRITES", d.max_writes_per_session)),
            audit_log=env.get("MCP_AUDIT_LOG", d.audit_log),
            max_document_chars=int(env.get("MCP_MAX_DOC_CHARS", d.max_document_chars)),
            timeout_seconds=float(env.get("INVOICE_API_TIMEOUT", d.timeout_seconds)),
        )
