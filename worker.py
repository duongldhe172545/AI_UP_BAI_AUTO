\
import os
import io
import json
import uuid
import base64
import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from openai import OpenAI
import imageio.v3 as iio

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
    load_dotenv()

    def req(key: str) -> str:
        v = os.getenv(key)
        if not v:
            raise RuntimeError(f"Missing env var: {key}")
        return v

    cfg = AppConfig(
        openai_api_key=req("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        openai_temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.7")),
        openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
        serpapi_key=os.getenv("SERPAPI_KEY") or None,
        fb_page_access_token=req("FB_PAGE_ACCESS_TOKEN"),
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


def _uploads_dir(cfg: AppConfig) -> str:
    base = os.path.dirname(cfg.db_path) or "."
    path = os.path.join(base, "uploads")
    os.makedirs(path, exist_ok=True)
    return path


def generate_ai_media(post_id: int, need_image: bool = True, need_video: bool = False) -> Dict[str, Any]:
    cfg = load_config()
    post = get_post(cfg.db_path, post_id)
    if not post:
        raise RuntimeError("Post not found")

    topic = str(post.get("topic", "")).strip()
    main = str(post.get("main", "")).strip()
    if not (topic and main):
        raise RuntimeError("Missing topic/main")

    if need_video and not need_image:
        need_image = True  # video generation builds from the AI image

    updates: Dict[str, Any] = {}
    result: Dict[str, Any] = {}

    if need_image:
        prompt = (
            "Tạo 1 ảnh minh họa bắt mắt, phong cách chuyên nghiệp, màu sắc hài hòa cho chủ đề: "
            f"{topic}. Ý chính: {main}. Phong cách hiện đại, rõ sản phẩm, không chữ lên ảnh."
        )
        client = OpenAI(api_key=cfg.openai_api_key, base_url=cfg.openai_base_url)
        try:
            img_resp = client.images.generate(
                model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
                prompt=prompt,
                size=os.getenv("OPENAI_IMAGE_SIZE", "1024x1024"),
                response_format="b64_json",
                n=1,
            )
            b64 = img_resp.data[0].b64_json
            img_bytes = base64.b64decode(b64)
            img_arr = iio.imread(io.BytesIO(img_bytes), extension=".png")
        except Exception as e:
            raise RuntimeError(f"AI image generation failed: {e}")

        uploads = _uploads_dir(cfg)
        image_file_name = f"ai_{uuid.uuid4().hex}.png"
        image_path = os.path.join(uploads, image_file_name)
        iio.imwrite(image_path, img_arr)
        updates["ai_image_file_name"] = image_file_name
        result["ai_image_file_name"] = image_file_name

        # Auto-fill image for posting if none provided
        if not post.get("image_file_name") and not post.get("image_url"):
            updates["image_file_name"] = image_file_name

        if need_video:
            fps = 24
            duration = 4
            frames = [img_arr for _ in range(fps * duration)]
            video_file_name = f"ai_{uuid.uuid4().hex}.mp4"
            video_path = os.path.join(uploads, video_file_name)
            try:
                iio.imwrite(video_path, frames, fps=fps)
            except Exception as e:
                raise RuntimeError(f"AI video rendering failed: {e}")
            updates["ai_video_file_name"] = video_file_name
            result["ai_video_file_name"] = video_file_name

            if not post.get("video_file_name") and not post.get("video_url"):
                updates["video_file_name"] = video_file_name

    if updates:
        update_post(cfg.db_path, post_id, {**updates, "last_error": ""})

    return {"post_id": post_id, **result}


def generate_preview(post_id: int) -> Dict[str, Any]:
    cfg = load_config()
    post = get_post(cfg.db_path, post_id)
    if not post:
        raise RuntimeError("Post not found")

    topic = str(post.get("topic", "")).strip()
    main = str(post.get("main", "")).strip()
    mandatory = str(post.get("mandatory", "")).strip()
    if not (topic and main):
        raise RuntimeError("Missing topic/main")

    seo: List[str] = []
    if cfg.serpapi_key:
        try:
            seo = serpapi_keywords(cfg.serpapi_key, topic)
        except Exception as e:
            seo = [f"(SerpAPI lỗi: {e})"]

    ai = generate_ai_json(cfg, topic, main, mandatory, seo)
    caption = build_caption(ai["title"], ai["content"], mandatory)

    update_post(cfg.db_path, post_id, {
        "seo_keywords_json": json.dumps(seo, ensure_ascii=False),
        "ai_title": ai["title"],
        "ai_content": ai["content"],
        "caption": caption,
        "last_error": "",
    })

    return {"post_id": post_id, "seo_keywords": seo, "ai": ai, "caption": caption}


def post_to_facebook(post_id: int) -> Dict[str, Any]:
    cfg = load_config()
    post = get_post(cfg.db_path, post_id)
    if not post:
        raise RuntimeError("Post not found")

    status = str(post.get("status", "")).strip()
    if status not in ("APPROVED",):
        raise RuntimeError("Post must be APPROVED before posting")

    page_id = (str(post.get("page_id", "")).strip() or cfg.default_page_id)
    if not page_id:
        raise RuntimeError("Missing page_id (set in post or DEFAULT_PAGE_ID)")

    caption = str(post.get("caption", "")).strip()
    if not caption:
        generate_preview(post_id)
        post = get_post(cfg.db_path, post_id) or post
        caption = str(post.get("caption", "")).strip()

    image_url = str(post.get("image_url", "")).strip()
    image_file_name = str(post.get("image_file_name", "")).strip()
    video_url = str(post.get("video_url", "")).strip()
    video_file_name = str(post.get("video_file_name", "")).strip()

    try:
        upload_dir = _uploads_dir(cfg)
        fb_resp: Dict[str, Any]

        if video_file_name or video_url:
            if video_file_name:
                file_path = os.path.join(upload_dir, video_file_name)
                fb_resp = post_video_by_file(page_id, cfg.fb_page_access_token, file_path, caption)
            else:
                fb_resp = post_video_by_url(page_id, cfg.fb_page_access_token, video_url, caption)
        elif image_file_name:
            file_path = os.path.join(upload_dir, image_file_name)
            fb_resp = post_photo_by_file(page_id, cfg.fb_page_access_token, file_path, caption)
        else:
            if not image_url:
                raise RuntimeError("Missing media (image/video)")
            fb_resp = post_photo_by_url(page_id, page_access_token=cfg.fb_page_access_token, image_url=image_url, message=caption)

        post_id_fb = fb_resp.get("post_id") or fb_resp.get("id") or ""
        post_url = f"https://www.facebook.com/{post_id_fb}" if post_id_fb else ""

        posted_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
        update_post(cfg.db_path, post_id, {
            "status": "POSTED",
            "page_id": page_id,
            "fb_post_id": str(post_id_fb),
            "fb_post_url": post_url,
            "posted_at": posted_at,
            "last_error": "",
        })

        return {"status": "posted", "post_id": post_id, "fb": fb_resp, "post_url": post_url}
    except Exception as e:
        set_status(cfg.db_path, post_id, "FAILED", str(e))
        raise


def post_next_approved() -> Dict[str, Any]:
    cfg = load_config()
    approved = list_posts(cfg.db_path, status="APPROVED", limit=1)
    if not approved:
        return {"status": "no_approved_posts"}
    return post_to_facebook(int(approved[0]["id"]))
