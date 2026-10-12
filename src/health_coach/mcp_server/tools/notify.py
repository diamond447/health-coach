"""Group 7: push notifications."""

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from health_coach.mcp_server.common import WRITE_EXTERNAL, audited
from health_coach.notify.ntfy import NotifyError
from health_coach.notify.ntfy import send_notification as _send_notification


def send_notification(
    title: Annotated[str, Field(description="Notification title")],
    body: Annotated[str, Field(description="Notification message body")],
    priority: Annotated[
        int, Field(ge=1, le=5, description="Priority from 1 (lowest) to 5 (urgent)")
    ] = 3,
    tags: Annotated[
        list[str] | None, Field(description="Optional tags / emoji tags for ntfy")
    ] = None,
) -> dict[str, Any]:
    """Send a push notification to the user's phone via ntfy.

    Use for urgent alerts, milestone reminders, or summaries that need the user's attention.
    Fails if notifications are not configured.
    """
    try:
        return _send_notification(title=title, body=body, priority=priority, tags=tags)
    except NotifyError as exc:
        raise ToolError(str(exc)) from exc


def register(server: MCPServer) -> None:
    server.tool(annotations=WRITE_EXTERNAL)(audited(send_notification))
