import os
from fastapi import FastAPI
from pydantic import BaseModel
import tweepy

app = FastAPI(title="X Post MCP Server")

class PostRequest(BaseModel):
    text: str


def client():
    return tweepy.Client(
        consumer_key=os.getenv("X_API_KEY"),
        consumer_secret=os.getenv("X_API_SECRET"),
        access_token=os.getenv("X_ACCESS_TOKEN"),
        access_token_secret=os.getenv("X_ACCESS_SECRET"),
    )

@app.get("/health")
def health():
    return {"status":"ok"}

@app.post("/tools/create_post")
def create_post(req: PostRequest):
    result = client().create_tweet(text=req.text)
    return {"success": True, "tweet": result.data}

@app.get("/tools/profile")
def profile():
    user = client().get_me()
    return user.data
