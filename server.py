from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from browser_x import post_x, browser_status

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
