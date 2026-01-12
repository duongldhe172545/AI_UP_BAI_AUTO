\
import os
import json
import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from openai import OpenAI

from db import init_db, get_post, list_posts, update_post, set_status


@dataclass
class AppConfig:
    openai_api_key: str
    openai_model: str
    openai_temperature: float
    openai_base_url: Optional[str]

    serpapi_key: Optional[str]

    fb_page_access_token: str
    default_page_id: str

    timezone: str
    db_path: str

    prompt_template: Optional[str]


DEFAULT_PROMPT_TEMPLATE = """\
Bạn là 1 Content Creator của công ty ADG, chuyên về các sản phẩm thiết bị trong nhà (cửa cuốn, bếp, cửa sổ, solar...).
Bạn viết nội dung để đăng tải lên 1 trang Facebook Fanpage.

Hãy viết cho tôi 1 Status Facebook chia sẻ về chủ đề: {topic}
Bao gồm các nội dung chính sau:
{main}

Yêu cầu bắt buộc:
- Trả kết quả bằng tiếng Việt.
- Xuống dòng ở tiêu đề.
- Status là văn bản thuần, không dùng in đậm/in nghiêng/ký hiệu * hoặc **.
- Nếu có danh sách ý chính, hãy dùng emoji ở ĐẦU dòng để làm nổi bật (ví dụ: ♥️, 🍀, 🏵️, ⭐), không chèn emoji ở cuối câu.
- Giữ nội dung ngắn gọn, thu hút, dễ đọc, câu không quá dài.
- Đảm bảo đúng chính tả, ngữ pháp tiếng Việt.
- Luôn kèm 5 hashtag phù hợp và phổ biến.
- Tham khảo gợi ý từ khóa SEO (nếu có): {seo_keywords}

Đoạn “Nội dung bắt buộc” (nếu có) sẽ được nối ở cuối bài, không chỉnh sửa nội dung đó.
"""


def load_config() -> AppConfig:
    dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
    load_dotenv(dotenv_path=dotenv_path, override=True)

    def opt(key: str) -> str:
        return (os.getenv(key) or "").strip()

    cfg = AppConfig(
        openai_api_key=opt("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        openai_temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.7")),
        openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
        serpapi_key=os.getenv("SERPAPI_KEY") or None,
        fb_page_access_token=(os.getenv("FB_PAGE_ACCESS_TOKEN") or "").strip(),
        default_page_id=os.getenv("DEFAULT_PAGE_ID", "").strip(),
        timezone=os.getenv("TIMEZONE", "Asia/Bangkok"),
        db_path=os.getenv("DB_PATH", "./data/app.db"),
        prompt_template=os.getenv("PROMPT_TEMPLATE") or None,
    )

    init_db(cfg.db_path)
    return cfg


def serpapi_keywords(serpapi_key: str, query: str, max_keywords: int = 8) -> List[str]:
    url = "https://serpapi.com/search.json"
    params = {"engine": "google", "q": query, "hl": "vi", "gl": "vn", "api_key": serpapi_key}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    kws: List[str] = []
    for item in data.get("related_searches", []) or []:
        q = item.get("query")
        if q and q not in kws:
            kws.append(q)

    for item in data.get("organic_results", []) or []:
        t = item.get("title")
        if t and t not in kws:
            kws.append(t)

    cleaned: List[str] = []
    for k in kws:
        k2 = str(k).strip()
        if k2 and k2 not in cleaned:
            cleaned.append(k2)

    return cleaned[:max_keywords]


def _extract_json_str(s: str) -> str:
    s = s.strip()
    if s.startswith("{") and s.endswith("}"):
        return s
    a = s.find("{")
    b = s.rfind("}")
    if a != -1 and b != -1 and b > a:
        return s[a:b + 1]
    return s


def generate_ai_json(cfg: AppConfig, topic: str, main: str, mandatory: str, seo_keywords: List[str]) -> Dict[str, str]:
    if not cfg.openai_api_key:
        raise RuntimeError("Missing OPENAI_API_KEY (required for text generation)")
    if str(cfg.openai_api_key).startswith("gsk_") and ("openai.com" in (cfg.openai_base_url or "")):
        raise RuntimeError(
            "You are using a Groq key ('gsk_...') with OpenAI base URL. "
            "Fix: set OPENAI_BASE_URL to https://api.groq.com/openai/v1 (or your OpenAI-compatible provider), "
            "or use an OpenAI API key (sk-...) with https://api.openai.com/v1."
        )
    client = OpenAI(api_key=cfg.openai_api_key, base_url=cfg.openai_base_url)

    prompt_template = cfg.prompt_template or DEFAULT_PROMPT_TEMPLATE
    prompt = prompt_template.format(
        topic=topic,
        main=main,
        mandatory=mandatory,
        seo_keywords=", ".join(seo_keywords) if seo_keywords else "(không có)",
    )

    system = (
        "Bạn là trợ lý viết nội dung mạng xã hội. "
        "BẮT BUỘC trả về đúng 1 JSON object hợp lệ, không thêm văn bản nào khác. "
        "JSON phải có đúng 2 key: title, content (đều là string)."
    )

    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]

    last_err = None
    for _ in range(2):
        resp = client.chat.completions.create(
            model=cfg.openai_model,
            temperature=cfg.openai_temperature,
            messages=messages,
            response_format={"type": "json_object"},
        )
        txt = resp.choices[0].message.content or ""
        try:
            j = json.loads(_extract_json_str(txt))
            title = str(j.get("title", "")).strip()
            content = str(j.get("content", "")).strip()
            if not title or not content:
                raise ValueError("Missing title/content")
            return {"title": title, "content": content}
        except Exception as e:
            last_err = e
            messages.append({
                "role": "user",
                "content": 'Chỉ trả về JSON hợp lệ, không markdown, không giải thích. Schema: {"title":"...","content":"..."}'
            })

    raise RuntimeError(f"Failed to parse JSON from model. Last error: {last_err}")


def build_caption(title: str, content: str, mandatory: str) -> str:
    mandatory = (mandatory or "").strip()
    base = f"{title}\n\n{content}".strip()
    return f"{base}\n{mandatory}" if mandatory else base


def post_photo_by_url(page_id: str, page_access_token: str, image_url: str, message: str, graph_api_version: str = "v20.0") -> Dict[str, Any]:
    endpoint = f"https://graph.facebook.com/{graph_api_version}/{page_id}/photos"
    payload = {"url": image_url, "message": message, "access_token": page_access_token}
    resp = requests.post(endpoint, data=payload, timeout=60)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}
    if resp.status_code >= 400:
        raise RuntimeError(f"Facebook API error {resp.status_code}: {data}")
    return data


def upload_photo_unpublished_by_url(
    page_id: str,
    page_access_token: str,
    image_url: str,
    graph_api_version: str = "v20.0",
) -> Dict[str, Any]:
    endpoint = f"https://graph.facebook.com/{graph_api_version}/{page_id}/photos"
    payload = {
        "url": image_url,
        "published": "false",
        "access_token": page_access_token,
    }
    resp = requests.post(endpoint, data=payload, timeout=120)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}
    if resp.status_code >= 400:
        raise RuntimeError(f"Facebook API error {resp.status_code}: {data}")
    return data


def upload_photo_unpublished_by_file(
    page_id: str,
    page_access_token: str,
    file_path: str,
    graph_api_version: str = "v20.0",
) -> Dict[str, Any]:
    endpoint = f"https://graph.facebook.com/{graph_api_version}/{page_id}/photos"
    with open(file_path, "rb") as f:
        files = {"source": f}
        data = {
            "published": "false",
            "access_token": page_access_token,
        }
        resp = requests.post(endpoint, data=data, files=files, timeout=180)
    try:
        out = resp.json()
    except Exception:
        out = {"raw": resp.text}
    if resp.status_code >= 400:
        raise RuntimeError(f"Facebook API error {resp.status_code}: {out}")
    return out


def create_feed_post_with_attached_media(
    page_id: str,
    page_access_token: str,
    message: str,
    media_fbids: List[str],
    graph_api_version: str = "v20.0",
) -> Dict[str, Any]:
    if not media_fbids:
        raise RuntimeError("No media ids for attached_media")
    endpoint = f"https://graph.facebook.com/{graph_api_version}/{page_id}/feed"
    payload: Dict[str, Any] = {
        "message": message,
        "access_token": page_access_token,
    }
    for idx, mid in enumerate(media_fbids):
        payload[f"attached_media[{idx}]"] = json.dumps({"media_fbid": mid})

    resp = requests.post(endpoint, data=payload, timeout=120)
    try:
        out = resp.json()
    except Exception:
        out = {"raw": resp.text}
    if resp.status_code >= 400:
        raise RuntimeError(f"Facebook API error {resp.status_code}: {out}")
    return out


def post_photo_by_file(page_id: str, page_access_token: str, file_path: str, message: str, graph_api_version: str = "v20.0") -> Dict[str, Any]:
    endpoint = f"https://graph.facebook.com/{graph_api_version}/{page_id}/photos"
    with open(file_path, "rb") as f:
        files = {"source": f}
        data = {"message": message, "access_token": page_access_token}
        resp = requests.post(endpoint, data=data, files=files, timeout=120)

    try:
        out = resp.json()
    except Exception:
        out = {"raw": resp.text}
    if resp.status_code >= 400:
        raise RuntimeError(f"Facebook API error {resp.status_code}: {out}")
    return out


def post_video_by_url(page_id: str, page_access_token: str, video_url: str, message: str, graph_api_version: str = "v20.0") -> Dict[str, Any]:
    endpoint = f"https://graph.facebook.com/{graph_api_version}/{page_id}/videos"
    payload = {"file_url": video_url, "description": message, "access_token": page_access_token}
    resp = requests.post(endpoint, data=payload, timeout=300)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}
    if resp.status_code >= 400:
        raise RuntimeError(f"Facebook API error {resp.status_code}: {data}")
    return data


def post_video_by_file(page_id: str, page_access_token: str, file_path: str, message: str, graph_api_version: str = "v20.0") -> Dict[str, Any]:
    endpoint = f"https://graph.facebook.com/{graph_api_version}/{page_id}/videos"
    with open(file_path, "rb") as f:
        files = {"source": f}
        data = {"description": message, "access_token": page_access_token}
        resp = requests.post(endpoint, data=data, files=files, timeout=300)

    try:
        out = resp.json()
    except Exception:
        out = {"raw": resp.text}
    if resp.status_code >= 400:
        raise RuntimeError(f"Facebook API error {resp.status_code}: {out}")
    return out


def get_page_info_from_token(page_access_token: str, graph_api_version: str = "v20.0") -> Dict[str, str]:
    """Best-effort resolve Page id/name from a Page access token.

    For a Page access token, /me returns the Page object.
    """
    token = (page_access_token or "").strip()
    if not token:
        raise RuntimeError("Empty page access token")

    endpoint = f"https://graph.facebook.com/{graph_api_version}/me"
    params = {"fields": "id,name", "access_token": token}
    resp = requests.get(endpoint, params=params, timeout=30)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}
    if resp.status_code >= 400:
        raise RuntimeError(f"Facebook API error {resp.status_code}: {data}")

    pid = str(data.get("id", "")).strip()
    name = str(data.get("name", "")).strip()
    if not pid:
        raise RuntimeError(f"Could not resolve Page id from token: {data}")
    return {"id": pid, "name": name}


def _uploads_dir(cfg: AppConfig) -> str:
    base = os.path.dirname(cfg.db_path) or "."
    path = os.path.join(base, "uploads")
    os.makedirs(path, exist_ok=True)
    return path


def generate_preview(post_id: int) -> Dict[str, Any]:
    cfg = load_config()
    post = get_post(cfg.db_path, post_id)
    if not post:
        raise RuntimeError("Post not found")

    topic = str(post.get("topic", "")).strip()
    main = str(post.get("main", "")).strip()
    extra_requirements = str(post.get("extra_requirements", "")).strip()
    mandatory = str(post.get("mandatory", "")).strip()
    if not (topic and main):
        raise RuntimeError("Missing topic/main")

    combined_main = main
    if extra_requirements:
        combined_main = f"{main}\n\nYêu cầu bổ sung (từ trang duyệt):\n{extra_requirements}".strip()

    seo: List[str] = []
    if cfg.serpapi_key:
        try:
            seo = serpapi_keywords(cfg.serpapi_key, topic)
        except Exception as e:
            seo = [f"(SerpAPI lỗi: {e})"]

    ai = generate_ai_json(cfg, topic, combined_main, mandatory, seo)
    caption = build_caption(ai["title"], ai["content"], mandatory)

    update_post(cfg.db_path, post_id, {
        "seo_keywords_json": json.dumps(seo, ensure_ascii=False),
        "ai_title": ai["title"],
        "ai_content": ai["content"],
        "caption": caption,
        "last_error": "",
    })

    return {"post_id": post_id, "seo_keywords": seo, "ai": ai, "caption": caption}


def post_to_facebook(post_id: int, page_access_token_override: Optional[str] = None) -> Dict[str, Any]:
    cfg = load_config()
    post = get_post(cfg.db_path, post_id)
    if not post:
        raise RuntimeError("Post not found")

    status = str(post.get("status", "")).strip()
    if status not in ("APPROVED",):
        raise RuntimeError("Post must be APPROVED before posting")

    page_access_token = (page_access_token_override or "").strip() or cfg.fb_page_access_token
    if not page_access_token:
        raise RuntimeError(
            "Missing FB page access token (provide it from UI per post, or set FB_PAGE_ACCESS_TOKEN in .env)"
        )

    page_id = (str(post.get("page_id", "")).strip() or cfg.default_page_id)
    if not page_id:
        # If user provides a Page token, we can resolve the Page id automatically.
        page_id = get_page_info_from_token(page_access_token).get("id", "").strip()
    if not page_id:
        raise RuntimeError("Missing page_id (set in post or DEFAULT_PAGE_ID)")

    caption = str(post.get("caption", "")).strip()
    if not caption:
        generate_preview(post_id)
        post = get_post(cfg.db_path, post_id) or post
        caption = str(post.get("caption", "")).strip()

    image_url = str(post.get("image_url", "")).strip()
    image_file_name = str(post.get("image_file_name", "")).strip()
    image_urls: List[str] = []
    image_file_names: List[str] = []

    try:
        image_urls = [str(x).strip() for x in (json.loads(post.get("image_urls_json") or "[]") or []) if str(x).strip()]
    except Exception:
        image_urls = []
    try:
        image_file_names = [
            str(x).strip()
            for x in (json.loads(post.get("image_file_names_json") or "[]") or [])
            if str(x).strip()
        ]
    except Exception:
        image_file_names = []

    # Backward compatibility
    if not image_urls and image_url:
        image_urls = [image_url]
    if not image_file_names and image_file_name:
        image_file_names = [image_file_name]
    video_url = str(post.get("video_url", "")).strip()
    video_file_name = str(post.get("video_file_name", "")).strip()

    video_urls: List[str] = []
    video_file_names: List[str] = []
    try:
        video_urls = [str(x).strip() for x in (json.loads(post.get("video_urls_json") or "[]") or []) if str(x).strip()]
    except Exception:
        video_urls = []
    try:
        video_file_names = [
            str(x).strip()
            for x in (json.loads(post.get("video_file_names_json") or "[]") or [])
            if str(x).strip()
        ]
    except Exception:
        video_file_names = []

    # Backward compatibility
    if not video_urls and video_url:
        video_urls = [video_url]
    if not video_file_names and video_file_name:
        video_file_names = [video_file_name]

    try:
        upload_dir = _uploads_dir(cfg)
        fb_resp: Dict[str, Any]

        fb_resps: List[Dict[str, Any]] = []
        post_ids: List[str] = []
        post_urls: List[str] = []

        if video_file_names or video_urls:
            # Facebook only supports 1 video per post. If user provides multiple videos,
            # we post them sequentially as multiple posts.
            if video_file_names:
                for fn in video_file_names:
                    file_path = os.path.join(upload_dir, fn)
                    r = post_video_by_file(page_id, page_access_token, file_path, caption)
                    fb_resps.append(r)
            else:
                for u in video_urls:
                    r = post_video_by_url(page_id, page_access_token, u, caption)
                    fb_resps.append(r)

            for r in fb_resps:
                pid_fb = str(r.get("post_id") or r.get("id") or "").strip()
                post_ids.append(pid_fb)
                post_urls.append(f"https://www.facebook.com/{pid_fb}" if pid_fb else "")

            fb_resp = fb_resps[-1] if fb_resps else {}
        else:
            # Images only (single or multiple)
            if image_file_names:
                if len(image_file_names) == 1:
                    file_path = os.path.join(upload_dir, image_file_names[0])
                    fb_resp = post_photo_by_file(page_id, page_access_token, file_path, caption)
                else:
                    media_ids: List[str] = []
                    for fn in image_file_names:
                        file_path = os.path.join(upload_dir, fn)
                        up = upload_photo_unpublished_by_file(page_id, page_access_token, file_path)
                        mid = str(up.get("id") or "").strip()
                        if not mid:
                            raise RuntimeError(f"Upload photo returned no id: {up}")
                        media_ids.append(mid)
                    fb_resp = create_feed_post_with_attached_media(page_id, page_access_token, caption, media_ids)
            elif image_urls:
                if len(image_urls) == 1:
                    fb_resp = post_photo_by_url(page_id, page_access_token=page_access_token, image_url=image_urls[0], message=caption)
                else:
                    media_ids = []
                    for u in image_urls:
                        up = upload_photo_unpublished_by_url(page_id, page_access_token, u)
                        mid = str(up.get("id") or "").strip()
                        if not mid:
                            raise RuntimeError(f"Upload photo returned no id: {up}")
                        media_ids.append(mid)
                    fb_resp = create_feed_post_with_attached_media(page_id, page_access_token, caption, media_ids)
            else:
                raise RuntimeError("Missing media (image/video)")

        post_id_fb = str(fb_resp.get("post_id") or fb_resp.get("id") or "")
        post_url = f"https://www.facebook.com/{post_id_fb}" if post_id_fb else ""
        if post_ids:
            post_id_fb = post_ids[0]
            post_url = post_urls[0]

        posted_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
        update_post(cfg.db_path, post_id, {
            "status": "POSTED",
            "page_id": page_id,
            "fb_post_id": str(post_id_fb),
            "fb_post_url": post_url,
            "fb_post_ids_json": json.dumps([p for p in post_ids if p], ensure_ascii=False) if post_ids else json.dumps([str(post_id_fb)], ensure_ascii=False),
            "fb_post_urls_json": json.dumps([u for u in post_urls if u], ensure_ascii=False) if post_urls else json.dumps([post_url], ensure_ascii=False),
            "posted_at": posted_at,
            "last_error": "",
        })

        out: Dict[str, Any] = {"status": "posted", "post_id": post_id, "fb": fb_resp, "post_url": post_url}
        if post_urls:
            out["post_urls"] = post_urls
            out["fb_list"] = fb_resps
        return out
    except Exception as e:
        set_status(cfg.db_path, post_id, "FAILED", str(e))
        raise


def post_to_facebook_multi(post_id: int, page_access_tokens: List[str]) -> Dict[str, Any]:
    """Post the same content to multiple fanpages, one per Page access token.

    Tokens are NOT stored in DB. DB status is set to POSTED only if all succeed.
    """
    cfg = load_config()
    post = get_post(cfg.db_path, post_id)
    if not post:
        raise RuntimeError("Post not found")

    status = str(post.get("status", "")).strip()
    if status not in ("APPROVED",):
        raise RuntimeError("Post must be APPROVED before posting")

    tokens = [str(t or "").strip() for t in (page_access_tokens or []) if str(t or "").strip()]
    if not tokens:
        raise RuntimeError("No FB_PAGE_ACCESS_TOKEN provided")

    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []

    for token in tokens:
        try:
            info = get_page_info_from_token(token)
            out = post_to_facebook(post_id, page_access_token_override=token)
            results.append({
                "page_id": info.get("id"),
                "page_name": info.get("name"),
                "post_url": out.get("post_url", ""),
                "fb": out.get("fb", {}),
                "ok": True,
            })
        except Exception as e:
            # Keep going so user can see partial results.
            failures.append({"ok": False, "error": str(e)})
            results.append({"ok": False, "error": str(e)})

    if failures:
        set_status(cfg.db_path, post_id, "FAILED", f"Multi-post failures: {len(failures)}/{len(tokens)}")
    else:
        # Store a quick summary of URLs for convenience.
        urls = [r.get("post_url", "") for r in results if r.get("ok") and r.get("post_url")]
        update_post(cfg.db_path, post_id, {"status": "POSTED", "fb_post_url": "\n".join(urls), "last_error": ""})

    return {"status": "multi_posted", "post_id": post_id, "results": results, "failed": len(failures)}


def post_next_approved() -> Dict[str, Any]:
    cfg = load_config()
    approved = list_posts(cfg.db_path, status="APPROVED", limit=1)
    if not approved:
        return {"status": "no_approved_posts"}
    return post_to_facebook(int(approved[0]["id"]))
