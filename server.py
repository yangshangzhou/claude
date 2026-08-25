import os
from fastapi import FastAPI
from pydantic import BaseModel
from browser_x import post_x

app = FastAPI(title="X Post MCP Browser")

class Post(BaseModel):
    text: str

@app.get("/")
def health():
    return {"status":"X Browser MCP running"}

@app.post("/mcp/create_post")
def create_post(post: Post):
    result = post_x(post.text)
    return result
