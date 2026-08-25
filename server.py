import os
from fastapi import FastAPI
from pydantic import BaseModel
import tweepy

app = FastAPI(title="X Post MCP")

class Post(BaseModel):
    text: str


def client():
    return tweepy.Client(
        consumer_key=os.getenv("X_API_KEY"),
        consumer_secret=os.getenv("X_API_SECRET"),
        access_token=os.getenv("X_ACCESS_TOKEN"),
        access_token_secret=os.getenv("X_ACCESS_SECRET")
    )

@app.get("/")
def health():
    return {"status":"X MCP running"}

@app.post("/mcp/create_post")
def create_post(post: Post):
    result = client().create_tweet(text=post.text)
    return {"success":True,"id":result.data["id"]}

@app.get("/mcp/profile")
def profile():
    user = client().get_me()
    return user.data.data
