from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from browser_x import browser_status, test_x_browser, test_x_compose
from browser_x_fix import post_x, test_x_typing
from mcp_server import mcp, mcp_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="X Post MCP Browser", lifespan=lifespan)


class Post(BaseModel):
    text: str
    image_base64: str | None = None
    image_filename: str = "image.png"


@app.get("/")
def health():
    return {"status": "X Browser MCP running", "mcp": "/mcp"}


# Existing diagnostic REST endpoints are kept under /api so /mcp can be a real MCP endpoint.
@app.get("/api/status")
def status():
    return browser_status()


@app.get("/api/post_status")
def post_status():
    return browser_status().get("task", {})


@app.get("/api/test")
def test_api():
    return {"success": True, "message": "FastAPI routing is working.", "playwright_touched": False}


@app.get("/api/test_x")
def test_x():
    result = test_x_browser()
    if result.get("success"):
        return result
    if result.get("busy"):
        raise HTTPException(status_code=409, detail=result)
    return result


@app.get("/api/test_compose")
def test_compose():
    result = test_x_compose()
    if result.get("success"):
        return result
    if result.get("busy"):
        raise HTTPException(status_code=409, detail=result)
    return result


@app.get("/api/test_typing")
def test_typing(text: str = "LOCAL_X_TYPING_TEST"):
    result = test_x_typing(text)
    if result.get("success"):
        return result
    if result.get("busy"):
        raise HTTPException(status_code=409, detail=result)
    return result


@app.post("/api/create_post")
def create_post(post: Post):
    text = post.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text cannot be empty")
    if len(text) > 280:
        raise HTTPException(status_code=422, detail="X post is limited to 280 characters")
    result = post_x(text, image_base64=post.image_base64, image_filename=post.image_filename)
    if result.get("success"):
        return result
    if result.get("busy"):
        raise HTTPException(status_code=409, detail=result)
    raise HTTPException(status_code=503, detail=result)


# Real MCP Streamable HTTP endpoint: https://<host>/mcp
app.mount("/mcp", mcp_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)