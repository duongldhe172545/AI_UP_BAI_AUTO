from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from worker import generate_preview, post_to_facebook, post_next_approved, load_config
from db import create_post, list_posts, update_post

app = FastAPI(title="ADG AI FB Poster API (DB)", version="2.0.0")

class CreatePostIn(BaseModel):
    topic: str
    main: str
    mandatory: str | None = ""
    image_url: str | None = ""
    page_id: str | None = ""
    status: str | None = "DRAFT"

@app.get("/health")
def health():
    cfg = load_config()
    return {"ok": True, "db_path": cfg.db_path}

@app.get("/posts")
def posts(status: str | None = None, limit: int = 200):
    cfg = load_config()
    return list_posts(cfg.db_path, status=status, limit=limit)

@app.post("/posts")
def create_post_api(inp: CreatePostIn):
    cfg = load_config()
    pid = create_post(cfg.db_path, inp.model_dump())
    return {"id": pid}

@app.post("/posts/{post_id}/approve")
def approve(post_id: int):
    cfg = load_config()
    update_post(cfg.db_path, post_id, {"status": "APPROVED", "last_error": ""})
    return {"ok": True}

@app.post("/posts/{post_id}/preview")
def preview(post_id: int):
    try:
        return generate_preview(post_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/posts/{post_id}/post")
def post(post_id: int):
    try:
        return post_to_facebook(post_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/post-next-approved")
def post_next():
    try:
        return post_next_approved()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
