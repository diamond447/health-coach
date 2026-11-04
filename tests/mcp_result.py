"""Reading MCP tool results the way a client does."""

import json
from typing import Any

from mcp.types import CallToolResult, TextContent


def json_result(result: CallToolResult) -> dict[str, Any]:
    """The tool's JSON payload: one compact text block, no duplicate structuredContent."""
    assert not result.is_error, result.content
    assert result.structured_content is None
    assert len(result.content) == 1
    block = result.content[0]
    assert isinstance(block, TextContent)
    assert "\n" not in block.text  # compact, not indented
    content: dict[str, Any] = json.loads(block.text)
    return content
