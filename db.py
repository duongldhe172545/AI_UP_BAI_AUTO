\
import os
import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic TEXT NOT NULL,
  main TEXT NOT NULL,
    extra_requirements TEXT DEFAULT '',
  mandatory TEXT DEFAULT '',
  image_url TEXT DEFAULT '',
  image_file_name TEXT DEFAULT '',
    image_urls_json TEXT DEFAULT '[]',
    image_file_names_json TEXT DEFAULT '[]',
  video_url TEXT DEFAULT '',
  video_file_name TEXT DEFAULT '',
    video_urls_json TEXT DEFAULT '[]',
    video_file_names_json TEXT DEFAULT '[]',
  page_id TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'DRAFT', -- DRAFT | APPROVED | POSTED | FAILED
  seo_keywords_json TEXT DEFAULT '[]',
  ai_title TEXT DEFAULT '',
  ai_content TEXT DEFAULT '',
  caption TEXT DEFAULT '',
  fb_post_id TEXT DEFAULT '',
  fb_post_url TEXT DEFAULT '',
    fb_post_ids_json TEXT DEFAULT '[]',
    fb_post_urls_json TEXT DEFAULT '[]',
  posted_at TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_error TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at);
"""

def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")

def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path: str) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        # Backfill columns for existing DBs without recreating the table
        cur = conn.execute("PRAGMA table_info(posts)")
        existing = {row[1] for row in cur.fetchall()}
        missing = [
            col
            for col in [
                "extra_requirements",
                "image_urls_json",
                "image_file_names_json",
                "video_url",
                "video_file_name",
                "video_urls_json",
                "video_file_names_json",
                "fb_post_ids_json",
                "fb_post_urls_json",
            ]
            if col not in existing
        ]
        for col in missing:
            default = "''"
            if col in (
                "image_urls_json",
                "image_file_names_json",
                "video_urls_json",
                "video_file_names_json",
                "fb_post_ids_json",
                "fb_post_urls_json",
            ):
                default = "'[]'"
            conn.execute(f"ALTER TABLE posts ADD COLUMN {col} TEXT DEFAULT {default}")

        # Backfill multi-image JSON arrays from legacy single-image fields when empty.
        cur = conn.execute(
            """
            SELECT
              id,
              image_url, image_file_name, image_urls_json, image_file_names_json,
              video_url, video_file_name, video_urls_json, video_file_names_json,
              fb_post_id, fb_post_url, fb_post_ids_json, fb_post_urls_json
            FROM posts
            """
        )
        rows = cur.fetchall()
        for r in rows:
            pid = int(r[0])
            image_url = (r[1] or "").strip()
            image_file_name = (r[2] or "").strip()
            img_urls_json = (r[3] or "[]").strip() or "[]"
            img_fns_json = (r[4] or "[]").strip() or "[]"

            video_url = (r[5] or "").strip()
            video_file_name = (r[6] or "").strip()
            vid_urls_json = (r[7] or "[]").strip() or "[]"
            vid_fns_json = (r[8] or "[]").strip() or "[]"

            fb_post_id = (r[9] or "").strip()
            fb_post_url = (r[10] or "").strip()
            fb_ids_json = (r[11] or "[]").strip() or "[]"
            fb_urls_json = (r[12] or "[]").strip() or "[]"

            if img_urls_json == "[]" and image_url:
                conn.execute(
                    "UPDATE posts SET image_urls_json = ? WHERE id = ?",
                    (json.dumps([image_url], ensure_ascii=False), pid),
                )
            if img_fns_json == "[]" and image_file_name:
                conn.execute(
                    "UPDATE posts SET image_file_names_json = ? WHERE id = ?",
                    (json.dumps([image_file_name], ensure_ascii=False), pid),
                )

            if vid_urls_json == "[]" and video_url:
                conn.execute(
                    "UPDATE posts SET video_urls_json = ? WHERE id = ?",
                    (json.dumps([video_url], ensure_ascii=False), pid),
                )
            if vid_fns_json == "[]" and video_file_name:
                conn.execute(
                    "UPDATE posts SET video_file_names_json = ? WHERE id = ?",
                    (json.dumps([video_file_name], ensure_ascii=False), pid),
                )

            if fb_ids_json == "[]" and fb_post_id:
                conn.execute(
                    "UPDATE posts SET fb_post_ids_json = ? WHERE id = ?",
                    (json.dumps([fb_post_id], ensure_ascii=False), pid),
                )
            if fb_urls_json == "[]" and fb_post_url:
                conn.execute(
                    "UPDATE posts SET fb_post_urls_json = ? WHERE id = ?",
                    (json.dumps([fb_post_url], ensure_ascii=False), pid),
                )
        conn.commit()
    finally:
        conn.close()

def create_post(db_path: str, data: Dict[str, Any]) -> int:
    conn = connect(db_path)
    try:
        ts = now_iso()
        cur = conn.execute(
            """
            INSERT INTO posts(
                            topic, main, extra_requirements, mandatory,
                            image_url, image_file_name, image_urls_json, image_file_names_json,
                            video_url, video_file_name, video_urls_json, video_file_names_json,
                            page_id, status,
              created_at, updated_at
                                                ) VALUES(?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?, ?,?)
            """,
            (
                data.get("topic", "").strip(),
                data.get("main", "").strip(),
                                (data.get("extra_requirements") or "").strip(),
                (data.get("mandatory") or "").strip(),
                (data.get("image_url") or "").strip(),
                (data.get("image_file_name") or "").strip(),
                                (data.get("image_urls_json") or "[]").strip(),
                                (data.get("image_file_names_json") or "[]").strip(),
                (data.get("video_url") or "").strip(),
                (data.get("video_file_name") or "").strip(),
                                (data.get("video_urls_json") or "[]").strip(),
                                (data.get("video_file_names_json") or "[]").strip(),
                (data.get("page_id") or "").strip(),
                (data.get("status") or "DRAFT").strip(),
                ts, ts,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()

def get_post(db_path: str, post_id: int) -> Optional[Dict[str, Any]]:
    conn = connect(db_path)
    try:
        cur = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def list_posts(db_path: str, status: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    conn = connect(db_path)
    try:
        if status:
            cur = conn.execute(
                "SELECT * FROM posts WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status, limit),
            )
        else:
            cur = conn.execute("SELECT * FROM posts ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def update_post(db_path: str, post_id: int, updates: Dict[str, Any]) -> None:
    if not updates:
        return
    updates = dict(updates)
    updates["updated_at"] = now_iso()

    cols = ", ".join([f"{k} = ?" for k in updates.keys()])
    vals = list(updates.values()) + [post_id]

    conn = connect(db_path)
    try:
        conn.execute(f"UPDATE posts SET {cols} WHERE id = ?", vals)
        conn.commit()
    finally:
        conn.close()

def set_status(db_path: str, post_id: int, status: str, error: str = "") -> None:
    update_post(db_path, post_id, {"status": status, "last_error": error})
