from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from browser_x import post_x, browser_status, test_x_browser

app = FastAPI(title="X Post MCP Browser")


class Post(BaseModel):
    text: str


@app.get("/")
def health():
    return {"status": "X Browser MCP running"}


@app.get("/mcp/status")
def status():
    return browser_status()


@app.get("/mcp/post_status")
def post_status():
    return browser_status().get("task", {})


@app.get("/mcp/test")
def test_api():
    """Fast, side-effect-free diagnostic endpoint.

    This deliberately does not touch Playwright or X. If this returns 200,
    Render -> Uvicorn -> FastAPI routing is healthy and any remaining failure
    is downstream of the basic HTTP application layer.
    """
    return {
        "success": True,
        "message": "FastAPI routing is working.",
        "playwright_touched": False,
    }


@app.get("/mcp/test_x")
def test_x():
    """Diagnostic endpoint for Playwright + saved X session.

    This launches Playwright and opens X only. It does NOT open the composer
    and does NOT create a post.
    """
    result = test_x_browser()
    if result.get("success"):
        return result
    if result.get("busy"):
        raise HTTPException(status_code=409, detail=result)
    return result


@app.post("/mcp/create_post")
def create_post(post: Post):
    text = post.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text cannot be empty")
    if len(text) > 280:
        raise HTTPException(status_code=422, detail="X post is limited to 280 characters")

    result = post_x(text)
    if result.get("success"):
        return result

    # A second request while Playwright is already processing a post is a
    # conflict, not a server failure. Returning 409 makes this distinguishable
    # from a genuine X/Playwright failure (503).
    if result.get("busy"):
        raise HTTPException(status_code=409, detail=result)

    raise HTTPException(status_code=503, detail=result)
