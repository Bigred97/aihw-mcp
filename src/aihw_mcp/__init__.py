"""aihw-mcp — MCP server for Australian Institute of Health and Welfare statistics."""
from __future__ import annotations

try:
    from importlib.metadata import version as _v
    __version__ = _v("aihw-mcp")
except Exception:
    __version__ = "0.0.0+unknown"
