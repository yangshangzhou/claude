import base64
import os
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from browser_x_fix import post_x

PUBLIC_HOST = os.getenv("PUBLIC_HOST", "x-service-69x7.onrender.com")

security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[PUBLIC_HOST, f"{PUBLIC_HOST}:*"],
    allowed_origins=[f"https://{PUBLIC_HOST}"],
)

# MCP SDK 2.x: FastMCP was renamed to MCPServer and transport settings
# moved from the constructor to streamable_http_app().
mcp = MCPServer("X Browser MCP")


@mcp.tool()
def x_post(
    text: str,
    image_base64: str | None = None,
    image_filename: str = "image.png",
) -> dict[str, Any]:
    """Publish one post to X using the verified browser session.

    text is the post text. image_base64 is optional raw base64 or a data URL.
    The browser layer verifies the editor/media state and only clicks Post when
    X enables the Post button.
    """
    text = text.strip()
    if not text:
        return {"success": False, "stage": "validation", "message": "text cannot be empty"}
    if len(text) > 280:
        return {"success": False, "stage": "validation", "message": "X post is limited to 280 characters"}
    if image_base64:
        try:
            base64.b64decode(image_base64.split(",", 1)[-1], validate=True)
        except Exception:
            return {"success": False, "stage": "validation", "message": "image_base64 is not valid base64"}
    return post_x(text, image_base64=image_base64, image_filename=image_filename)


@mcp.tool()
def x_status() -> dict[str, Any]:
    """Return the current X browser session/task status."""
    from browser_x import browser_status
    return browser_status()


# The FastAPI host mounts this ASGI application at /mcp, so the public
# Streamable HTTP endpoint is exactly /mcp.
mcp_app = mcp.streamable_http_app(
    streamable_http_path="/",
    stateless_http=True,
    json_response=True,
    transport_security=security,
)
