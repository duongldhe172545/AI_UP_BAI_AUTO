import os
import uuid
import json
from typing import Any, Dict

import streamlit as st
from dotenv import load_dotenv

from db import init_db, create_post, list_posts, get_post, update_post
from worker import load_config, generate_preview, post_to_facebook, post_to_facebook_multi

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=True)
cfg = load_config()
init_db(cfg.db_path)

st.set_page_config(page_title="ADG | AI Facebook Poster (DB)", page_icon="🧩", layout="wide")

CUSTOM_CSS = """
<style>
.block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
h1, h2, h3 { letter-spacing: -0.02em; }
.small-muted { color: rgba(229,231,235,0.75); font-size: 0.92rem; }
.kpi { border: 1px solid rgba(255,255,255,0.10); background: rgba(17,27,46,0.70); padding: 14px; border-radius: 16px; }
.card { border: 1px solid rgba(255,255,255,0.10); background: rgba(17,27,46,0.65); padding: 16px; border-radius: 18px; }
.badge { display: inline-block; padding: 4px 10px; border-radius: 999px; border: 1px solid rgba(255,255,255,0.12); background: rgba(14,165,233,0.10); }
.badge-green { background: rgba(34,197,94,0.12); }
.badge-red { background: rgba(239,68,68,0.12); }
.hr { height: 1px; background: rgba(255,255,255,0.08); margin: 10px 0 14px; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def badge(status: str) -> str:
    status = (status or "").upper()
    cls = "badge"
    if status == "POSTED":
        cls += " badge-green"
    elif status == "FAILED":
        cls += " badge-red"
    return f"<span class='{cls}'>{status}</span>"


def ensure_upload_dir() -> str:
    db_dir = os.path.dirname(cfg.db_path) or "."
    up = os.path.join(db_dir, "uploads")
    os.makedirs(up, exist_ok=True)
    return up


def save_upload(file) -> str:
    up = ensure_upload_dir()
    ext = ""
    if file.name and "." in file.name:
        ext = "." + file.name.split(".")[-1]
    fn = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(up, fn)
    with open(path, "wb") as f:
        f.write(file.getbuffer())
    return fn


def _parse_multi_urls(raw: str) -> list[str]:
    lines = []
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s:
            continue
        lines.append(s)
    out: list[str] = []
    for u in lines:
        if u not in out:
            out.append(u)
    return out


def _json_list(val: str) -> list[str]:
    try:
        arr = json.loads(val or "[]")
        if isinstance(arr, list):
            return [str(x) for x in arr if str(x).strip()]
    except Exception:
        pass
    return []


def render_post_row(p: Dict[str, Any]) -> None:
    st.markdown(f"#### Post #{p['id']}  {badge(p.get('status',''))}", unsafe_allow_html=True)
    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown(f"**Chủ đề**: {p.get('topic','')}")
        main = str(p.get("main",""))
        st.markdown(f"**Nội dung chính**: {main[:200]}{'...' if len(main)>200 else ''}")
        if p.get("mandatory"):
            st.markdown("**Nội dung bắt buộc**: có")
        if p.get("fb_post_url"):
            st.markdown(f"**Link bài**: {p.get('fb_post_url')}")
        media_bits = []
        if p.get("image_file_name") or p.get("image_url"):
            media_bits.append("ảnh")
        if p.get("video_file_name") or p.get("video_url"):
            media_bits.append("video")
        if media_bits:
            st.markdown(f"**Media:** {', '.join(media_bits)}")
    with c2:
        if p.get("posted_at"):
            st.markdown(f"**Đăng lúc**: {p.get('posted_at')}")
        if p.get("last_error"):
            st.markdown("**Lỗi gần nhất**:")
            st.code(str(p.get("last_error"))[:500])
    st.markdown('</div>', unsafe_allow_html=True)


st.markdown("## ADG | AI Facebook Poster (DB)")
st.markdown('<div class="small-muted">Nhập input trên web → duyệt trên web → đăng lên Facebook → lưu lịch sử trong SQLite.</div>', unsafe_allow_html=True)

with st.sidebar:
    nav = st.radio("Điều hướng", ["Tạo bài", "Duyệt", "Preview & Đăng"], index=0)
    if st.button("Làm mới", use_container_width=True):
        st.rerun()


if nav == "Tạo bài":
    st.markdown("### Tạo bài (Input trên web)")
    st.markdown('<div class="small-muted">Bước 1: tạo DRAFT và sinh nội dung bằng AI → Bước 2: duyệt/điều chỉnh nội dung → Bước 3: sau khi APPROVED upload ảnh/video (nếu cần) để đăng.</div>', unsafe_allow_html=True)

    with st.form("create_form", clear_on_submit=True):
        topic = st.text_input("Chủ đề", placeholder="VD: Lợi ích của cửa cuốn thông minh cho nhà phố")
        main = st.text_area("Yêu cầu / Nội dung chính", height=160, placeholder="Gạch đầu dòng ý chính, giọng văn mong muốn, pain points, CTA, ...")
        mandatory = st.text_area("Nội dung bắt buộc (tuỳ chọn)", height=120, placeholder="VD: Hotline/địa chỉ/CTA (sẽ nối nguyên văn ở cuối).")

        want_ai_caption = st.checkbox("Nhờ AI tạo nội dung bài viết (caption)", value=True)

        c1, c2 = st.columns(2)
        with c1:
            image_urls_raw = st.text_area(
                "Link ảnh (nhiều URL, mỗi dòng 1 link) - tuỳ chọn",
                height=120,
                placeholder="https://...\nhttps://...",
            )
        with c2:
            video_urls_raw = st.text_area(
                "Link video (nhiều URL, mỗi dòng 1 link) - tuỳ chọn",
                height=120,
                placeholder="https://...mp4\nhttps://...mp4",
            )

        st.markdown("**Upload media (tuỳ chọn)**")
        col_up1, col_up2 = st.columns(2)
        with col_up1:
            uploads = st.file_uploader(
                "Chọn file ảnh (có thể chọn nhiều)",
                type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=True,
            )
        with col_up2:
            upload_videos = st.file_uploader(
                "Chọn file video (có thể chọn nhiều)",
                type=["mp4", "mov", "mkv", "webm"],
                accept_multiple_files=True,
            )

        page_id = st.text_input("Page_ID (tuỳ chọn nếu có DEFAULT_PAGE_ID)", value=os.getenv("DEFAULT_PAGE_ID",""))

        submitted = st.form_submit_button("Tạo bài (DRAFT)", type="primary")
        if submitted:
            if not topic.strip() or not main.strip():
                st.error("Thiếu 'Chủ đề' hoặc 'Nội dung chính'.")
            else:
                image_file_names: list[str] = []
                image_urls = _parse_multi_urls(image_urls_raw)
                video_file_names: list[str] = []
                video_urls = _parse_multi_urls(video_urls_raw)

                if uploads:
                    for f in uploads:
                        if f is not None:
                            image_file_names.append(save_upload(f))
                    # If user uploaded files, treat image URLs as empty for posting.
                    image_urls = []

                if upload_videos:
                    for f in upload_videos:
                        if f is not None:
                            video_file_names.append(save_upload(f))
                    # If user uploaded files, treat video URLs as empty for posting.
                    video_urls = []

                legacy_image_file_name = image_file_names[0] if image_file_names else ""
                legacy_image_url = image_urls[0] if image_urls else ""
                legacy_video_file_name = video_file_names[0] if video_file_names else ""
                legacy_video_url = video_urls[0] if video_urls else ""

                pid = create_post(cfg.db_path, {
                    "topic": topic,
                    "main": main,
                    "mandatory": mandatory,
                    "image_url": legacy_image_url,
                    "image_file_name": legacy_image_file_name,
                    "image_urls_json": json.dumps(image_urls, ensure_ascii=False),
                    "image_file_names_json": json.dumps(image_file_names, ensure_ascii=False),
                    "video_url": legacy_video_url,
                    "video_file_name": legacy_video_file_name,
                    "video_urls_json": json.dumps(video_urls, ensure_ascii=False),
                    "video_file_names_json": json.dumps(video_file_names, ensure_ascii=False),
                    "page_id": page_id,
                    "status": "DRAFT",
                })

                if want_ai_caption:
                    with st.spinner("Đang nhờ AI tạo nội dung bài viết..."):
                        try:
                            generate_preview(int(pid))
                        except Exception as e:
                            st.warning(f"AI tạo nội dung lỗi: {e}")

                st.success(f"Đã tạo Post #{pid} (DRAFT). Qua tab Duyệt để xem/sửa nội dung rồi Approve.")
                st.balloons()

elif nav == "Duyệt":
    st.markdown("### Duyệt (Approval trên web)")
    st.markdown('<div class="small-muted">Duyệt nội dung (caption) của các bài DRAFT → chỉnh sửa nếu cần → Approve để chuyển sang APPROVED.</div>', unsafe_allow_html=True)

    drafts = list_posts(cfg.db_path, status="DRAFT", limit=200)
    st.markdown(f"**DRAFT:** {len(drafts)} bài")
    if not drafts:
        st.info("Không có bài DRAFT.")
    else:
        for p in drafts:
            render_post_row(p)
            caption_val = str(p.get("caption", "") or "")
            widget_key = f"cap_draft_{p['id']}"
            pending_key = f"cap_draft_pending_{p['id']}"

            st.markdown("**Yêu cầu bổ sung (dùng khi AI sinh lại caption)**")
            extra_req = st.text_area(
                " ",
                value=str(p.get("extra_requirements", "") or ""),
                height=120,
                key=f"req_draft_{p['id']}",
                label_visibility="collapsed",
                placeholder="Nhập thêm yêu cầu (giọng văn, điểm nhấn, CTA, hạn chế dùng từ..., v.v). Khi bấm 'AI sinh nội dung', AI sẽ kết hợp yêu cầu cũ + mới."
            )

            # If AI generated a new caption on the previous run, apply it BEFORE the widget is created.
            if pending_key in st.session_state:
                st.session_state[widget_key] = st.session_state.pop(pending_key)
            edited_caption = st.text_area(
                "Nội dung (caption)",
                value=caption_val,
                height=220,
                key=widget_key,
                placeholder="Nếu trống, bạn có thể bấm 'AI sinh nội dung' để tạo nhanh."
            )
            colA, colB, colC = st.columns([1, 1, 1])
            with colA:
                if st.button(f"Approve #{p['id']}", key=f"ap_{p['id']}", type="primary"):
                    if not str(edited_caption or "").strip():
                        st.error("Caption đang trống. Hãy nhập nội dung hoặc bấm 'AI sinh nội dung' trước khi Approve.")
                    else:
                        update_post(cfg.db_path, int(p["id"]), {
                            "extra_requirements": str(extra_req or "").strip(),
                            "caption": edited_caption.strip(),
                            "status": "APPROVED",
                            "last_error": "",
                        })
                    st.rerun()
            with colB:
                if st.button(f"AI sinh nội dung #{p['id']}", key=f"gen_cap_{p['id']}"):
                    with st.spinner("Đang sinh nội dung AI..."):
                        try:
                            update_post(cfg.db_path, int(p["id"]), {"extra_requirements": str(extra_req or "").strip()})
                            out = generate_preview(int(p["id"]))
                            # Defer updating the textarea value until the next rerun.
                            # Streamlit does not allow modifying a widget's session_state key
                            # after the widget has been instantiated in the same run.
                            st.session_state[pending_key] = str(out.get("caption", "") or "")
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))
            with colC:
                if st.button(f"Mark Deleted #{p['id']}", key=f"del_{p['id']}"):
                    update_post(cfg.db_path, int(p["id"]), {"status": "FAILED", "last_error": "Deleted by user"})
                    st.rerun()

elif nav == "Preview & Đăng":
    st.markdown("### Preview & Đăng")
    approved = list_posts(cfg.db_path, status="APPROVED", limit=200)
    st.markdown(f"**APPROVED:** {len(approved)} bài")

    if not approved:
        st.info("Không có bài APPROVED.")
    else:
        ids = [int(p["id"]) for p in approved]
        selected_id = st.selectbox("Chọn Post để xử lý", ids, index=0)
        p = get_post(cfg.db_path, int(selected_id))
        if p:
            render_post_row(p)

            p = get_post(cfg.db_path, int(selected_id)) or p
            caption = str(p.get("caption",""))
            if caption:
                st.markdown("#### Caption")
                st.text_area(" ", value=caption, height=320, label_visibility="collapsed")
            else:
                st.info("Bài này chưa có caption. Bạn có thể quay lại tab Duyệt để sinh và Approve.")

            st.markdown("#### Media preview")
            up_dir = ensure_upload_dir()
            image_file_names = _json_list(str(p.get("image_file_names_json", "") or ""))
            image_urls = _json_list(str(p.get("image_urls_json", "") or ""))
            # Backward compatibility if DB row doesn't have JSON fields populated.
            if not image_file_names and p.get("image_file_name"):
                image_file_names = [str(p.get("image_file_name"))]
            if not image_urls and p.get("image_url"):
                image_urls = [str(p.get("image_url"))]

            if image_file_names:
                for idx, fn in enumerate(image_file_names, start=1):
                    img_path = os.path.join(up_dir, fn)
                    cimg1, cimg2 = st.columns([6, 1])
                    with cimg1:
                        if os.path.isfile(img_path):
                            st.image(img_path, caption=f"Ảnh upload #{idx}")
                        else:
                            st.warning(f"Ảnh upload không tìm thấy trên đĩa: {fn}")
                    with cimg2:
                        if st.button("Bỏ", key=f"rm_img_file_{p['id']}_{idx}"):
                            new_files = [x for x in image_file_names if x != fn]
                            update_post(cfg.db_path, int(p["id"]), {
                                "image_file_names_json": json.dumps(new_files, ensure_ascii=False),
                                "image_urls_json": json.dumps(image_urls, ensure_ascii=False),
                                "image_file_name": new_files[0] if new_files else "",
                                "image_url": image_urls[0] if (not new_files and image_urls) else "",
                                "last_error": "",
                            })
                            st.rerun()
            elif image_urls:
                for idx, u in enumerate(image_urls, start=1):
                    cimg1, cimg2 = st.columns([6, 1])
                    with cimg1:
                        st.image(u, caption=f"Ảnh URL #{idx}")
                    with cimg2:
                        if st.button("Bỏ", key=f"rm_img_url_{p['id']}_{idx}"):
                            new_urls = [x for x in image_urls if x != u]
                            update_post(cfg.db_path, int(p["id"]), {
                                "image_file_names_json": json.dumps(image_file_names, ensure_ascii=False),
                                "image_urls_json": json.dumps(new_urls, ensure_ascii=False),
                                "image_file_name": image_file_names[0] if (not new_urls and image_file_names) else "",
                                "image_url": new_urls[0] if new_urls else "",
                                "last_error": "",
                            })
                            st.rerun()

            video_file_names = _json_list(str(p.get("video_file_names_json", "") or ""))
            video_urls = _json_list(str(p.get("video_urls_json", "") or ""))
            if not video_file_names and p.get("video_file_name"):
                video_file_names = [str(p.get("video_file_name"))]
            if not video_urls and p.get("video_url"):
                video_urls = [str(p.get("video_url"))]

            if video_file_names:
                for idx, fn in enumerate(video_file_names, start=1):
                    vid_path = os.path.join(up_dir, fn)
                    cv1, cv2 = st.columns([6, 1])
                    with cv1:
                        if os.path.isfile(vid_path):
                            st.video(vid_path, format="video/mp4")
                            st.caption(f"Video upload #{idx}")
                        else:
                            st.warning(f"Video upload không tìm thấy trên đĩa: {fn}")
                    with cv2:
                        if st.button("Bỏ", key=f"rm_vid_file_{p['id']}_{idx}"):
                            new_files = [x for x in video_file_names if x != fn]
                            update_post(cfg.db_path, int(p["id"]), {
                                "video_file_names_json": json.dumps(new_files, ensure_ascii=False),
                                "video_urls_json": json.dumps(video_urls, ensure_ascii=False),
                                "video_file_name": new_files[0] if new_files else "",
                                "video_url": video_urls[0] if (not new_files and video_urls) else "",
                                "last_error": "",
                            })
                            st.rerun()
            elif video_urls:
                for idx, u in enumerate(video_urls, start=1):
                    cv1, cv2 = st.columns([6, 1])
                    with cv1:
                        st.video(u, format="video/mp4")
                        st.caption(f"Video URL #{idx}")
                    with cv2:
                        if st.button("Bỏ", key=f"rm_vid_url_{p['id']}_{idx}"):
                            new_urls = [x for x in video_urls if x != u]
                            update_post(cfg.db_path, int(p["id"]), {
                                "video_file_names_json": json.dumps(video_file_names, ensure_ascii=False),
                                "video_urls_json": json.dumps(new_urls, ensure_ascii=False),
                                "video_file_name": video_file_names[0] if (not new_urls and video_file_names) else "",
                                "video_url": new_urls[0] if new_urls else "",
                                "last_error": "",
                            })
                            st.rerun()
            else:
                st.info("Chưa có video cho bài này.")

            has_images = bool(image_file_names or image_urls)
            has_videos = bool(video_file_names or video_urls)

            st.markdown("#### Cập nhật media (sau khi duyệt)")
            st.markdown('<div class="small-muted">Bạn có thể upload/đổi ảnh hoặc video ở đây trước khi đăng.</div>', unsafe_allow_html=True)
            col_upd1, col_upd2 = st.columns(2)
            with col_upd1:
                new_imgs = st.file_uploader(
                    "Upload ảnh mới (có thể chọn nhiều)",
                    type=["png", "jpg", "jpeg", "webp"],
                    accept_multiple_files=True,
                    key=f"upd_imgs_{p['id']}"
                )
                new_urls_raw = st.text_area(
                    "Hoặc nhập link ảnh (nhiều URL, mỗi dòng 1 link)",
                    height=120,
                    key=f"upd_img_urls_{p['id']}",
                    placeholder="https://...\nhttps://...",
                )

                # Live preview for newly selected images
                if new_imgs:
                    st.markdown("**Xem trước ảnh upload mới**")
                    for f in new_imgs[:10]:
                        if f is not None:
                            st.image(f)
                    if len(new_imgs) > 10:
                        st.caption(f"(Đang hiển thị 10/{len(new_imgs)} ảnh)")
                new_urls_preview = _parse_multi_urls(new_urls_raw)
                if new_urls_preview:
                    st.markdown("**Xem trước ảnh URL mới**")
                    for u in new_urls_preview[:10]:
                        st.image(u)
                    if len(new_urls_preview) > 10:
                        st.caption(f"(Đang hiển thị 10/{len(new_urls_preview)} ảnh URL)")

                disabled_apply = (not new_imgs) and (not str(new_urls_raw or "").strip())
                if st.button("Áp dụng ảnh cho bài này", key=f"use_up_imgs_{p['id']}", disabled=disabled_apply):
                    fns: list[str] = []
                    urls = _parse_multi_urls(new_urls_raw)
                    if new_imgs:
                        for f in new_imgs:
                            if f is not None:
                                fns.append(save_upload(f))
                        urls = []

                    update_post(cfg.db_path, int(p["id"]), {
                        "image_file_names_json": json.dumps(fns, ensure_ascii=False),
                        "image_urls_json": json.dumps(urls, ensure_ascii=False),
                        # legacy single-image fields
                        "image_file_name": fns[0] if fns else "",
                        "image_url": urls[0] if urls else "",
                        "last_error": "",
                    })
                    st.rerun()

                if st.button("Bỏ toàn bộ ảnh", key=f"clear_imgs_{p['id']}", disabled=not has_images):
                    update_post(cfg.db_path, int(p["id"]), {
                        "image_file_names_json": "[]",
                        "image_urls_json": "[]",
                        "image_file_name": "",
                        "image_url": "",
                        "last_error": "",
                    })
                    st.rerun()
            with col_upd2:
                new_vids = st.file_uploader(
                    "Upload video mới (có thể chọn nhiều)",
                    type=["mp4", "mov", "mkv", "webm"],
                    accept_multiple_files=True,
                    key=f"upd_vids_{p['id']}"
                )
                new_vid_urls_raw = st.text_area(
                    "Hoặc nhập link video (nhiều URL, mỗi dòng 1 link)",
                    height=120,
                    key=f"upd_vid_urls_{p['id']}",
                    placeholder="https://...mp4\nhttps://...mp4",
                )

                # Live preview for newly selected videos
                if new_vids:
                    st.markdown("**Xem trước video upload mới**")
                    for f in new_vids[:3]:
                        if f is not None:
                            try:
                                st.video(f.getvalue(), format="video/mp4")
                            except Exception:
                                st.caption(f"(Không preview được file: {getattr(f, 'name', '')})")
                    if len(new_vids) > 3:
                        st.caption(f"(Đang hiển thị 3/{len(new_vids)} video)")
                new_vid_urls_preview = _parse_multi_urls(new_vid_urls_raw)
                if new_vid_urls_preview:
                    st.markdown("**Xem trước video URL mới**")
                    for u in new_vid_urls_preview[:3]:
                        st.video(u, format="video/mp4")
                    if len(new_vid_urls_preview) > 3:
                        st.caption(f"(Đang hiển thị 3/{len(new_vid_urls_preview)} video URL)")

                disabled_apply_vid = (not new_vids) and (not str(new_vid_urls_raw or "").strip())
                if st.button("Áp dụng video cho bài này", key=f"use_up_vids_{p['id']}", disabled=disabled_apply_vid):
                    fns: list[str] = []
                    urls = _parse_multi_urls(new_vid_urls_raw)
                    if new_vids:
                        for f in new_vids:
                            if f is not None:
                                fns.append(save_upload(f))
                        urls = []

                    update_post(cfg.db_path, int(p["id"]), {
                        "video_file_names_json": json.dumps(fns, ensure_ascii=False),
                        "video_urls_json": json.dumps(urls, ensure_ascii=False),
                        # legacy single-video fields
                        "video_file_name": fns[0] if fns else "",
                        "video_url": urls[0] if urls else "",
                        "last_error": "",
                    })
                    st.rerun()

                if st.button("Bỏ toàn bộ video", key=f"clear_vids_{p['id']}", disabled=not has_videos):
                    update_post(cfg.db_path, int(p["id"]), {
                        "video_file_names_json": "[]",
                        "video_urls_json": "[]",
                        "video_file_name": "",
                        "video_url": "",
                        "last_error": "",
                    })
                    st.rerun()




            st.markdown("#### Đăng thật")
            st.markdown("**Fanpage tokens**")
            tokens_key = f"fb_tokens_{p['id']}"
            if tokens_key not in st.session_state:
                st.session_state[tokens_key] = [""]

            for i in range(len(st.session_state[tokens_key])):
                st.session_state[tokens_key][i] = st.text_input(
                    f"FB_PAGE_ACCESS_TOKEN #{i+1}",
                    value=st.session_state[tokens_key][i],
                    type="password",
                    help="Không lưu vào DB.",
                    key=f"fb_token_{p['id']}_{i}",
                )

            col_tok1, col_tok2, col_tok3 = st.columns([1, 1, 2])
            with col_tok1:
                if st.button("+ Thêm ô token", key=f"add_tok_{p['id']}"):
                    st.session_state[tokens_key].append("")
                    st.rerun()
            with col_tok2:
                if st.button("- Xoá ô token cuối", key=f"rm_tok_{p['id']}", disabled=len(st.session_state[tokens_key]) <= 1):
                    st.session_state[tokens_key].pop()
                    st.rerun()
            with col_tok3:
                st.caption("Dán nhiều token → hệ thống sẽ đăng lên tất cả fanpage tương ứng.")
            confirm1 = st.checkbox("Tôi đã kiểm tra caption và muốn đăng thật")
            confirm2 = st.text_input("Gõ POST để xác nhận", value="", max_chars=8)
            can_post = confirm1 and confirm2.strip().upper() == "POST"

            if st.button("ĐĂNG NGAY", type="secondary", disabled=not can_post):
                try:
                    tokens = [str(t or "").strip() for t in st.session_state.get(tokens_key, []) if str(t or "").strip()]
                    if len(tokens) >= 2:
                        out = post_to_facebook_multi(int(selected_id), tokens)
                        st.success(f"Đã đăng xong: {len(tokens)-int(out.get('failed',0))}/{len(tokens)} fanpage")
                        st.json(out)
                    elif len(tokens) == 1:
                        out = post_to_facebook(int(selected_id), page_access_token_override=tokens[0])
                        st.success("Đăng thành công.")
                        st.write("Link bài:", out.get("post_url"))
                        st.json(out.get("fb", {}))
                    else:
                        out = post_to_facebook(int(selected_id))
                        st.success("Đăng thành công.")
                        st.write("Link bài:", out.get("post_url"))
                        st.json(out.get("fb", {}))
                    st.rerun()
                except Exception as e:
                    st.error(str(e))