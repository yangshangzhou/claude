import os
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

@app.post("/mcp/create_post")
def create_post(post: Post):
    text = post.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text cannot be empty")
    if len(text) > 280:
        raise HTTPException(status_code=422, detail="X post is limited to 280 characters")

    result = post_x(text)
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result)
    return result
