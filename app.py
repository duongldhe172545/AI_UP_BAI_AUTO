import os
import uuid
from typing import Any, Dict

import streamlit as st
from dotenv import load_dotenv

from db import init_db, create_post, list_posts, get_post, update_post
from worker import load_config, generate_preview, post_to_facebook, generate_ai_media

load_dotenv()
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


def render_post_row(p: Dict[str, Any]) -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
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
    nav = st.radio("Điều hướng", ["Tạo bài", "Duyệt", "Preview & Đăng", "Lịch sử"], index=0)
    if st.button("Làm mới", use_container_width=True):
        st.rerun()


if nav == "Tạo bài":
    st.markdown("### Tạo bài (Input trên web)")
    st.markdown('<div class="small-muted">Tạo bài ở trạng thái DRAFT. Sau đó qua tab Duyệt để APPROVED.</div>', unsafe_allow_html=True)

    with st.form("create_form", clear_on_submit=True):
        topic = st.text_input("Chủ đề", placeholder="VD: Lợi ích của cửa cuốn thông minh cho nhà phố")
        main = st.text_area("Nội dung chính", height=160, placeholder="Gạch đầu dòng ý chính, lợi ích, pain points, ...")
        mandatory = st.text_area("Nội dung bắt buộc (tuỳ chọn)", height=120, placeholder="VD: Hotline/địa chỉ/CTA (sẽ nối nguyên văn ở cuối).")

        c1, c2 = st.columns(2)
        with c1:
            image_url = st.text_input("Link ảnh (URL công khai) - tuỳ chọn", placeholder="https://...")
        with c2:
            video_url = st.text_input("Link video (URL công khai) - tuỳ chọn", placeholder="https://...mp4")

        st.markdown("**Upload media (tuỳ chọn)**")
        col_up1, col_up2 = st.columns(2)
        with col_up1:
            upload = st.file_uploader("Chọn file ảnh", type=["png", "jpg", "jpeg", "webp"])
        with col_up2:
            upload_video = st.file_uploader("Chọn file video", type=["mp4", "mov", "mkv", "webm"])

        ai_col1, ai_col2 = st.columns(2)
        with ai_col1:
            want_ai_image = st.checkbox("Nhờ AI tạo ảnh", value=False)
        with ai_col2:
            want_ai_video = st.checkbox("Nhờ AI tạo video (beta)", value=False)

        page_id = st.text_input("Page_ID (tuỳ chọn nếu có DEFAULT_PAGE_ID)", value=os.getenv("DEFAULT_PAGE_ID",""))

        submitted = st.form_submit_button("Tạo bài (DRAFT)", type="primary")
        if submitted:
            if not topic.strip() or not main.strip():
                st.error("Thiếu 'Chủ đề' hoặc 'Nội dung chính'.")
            else:
                image_file_name = ""
                video_file_name = ""
                if upload is not None:
                    image_file_name = save_upload(upload)
                    image_url = ""
                if upload_video is not None:
                    video_file_name = save_upload(upload_video)
                    video_url = ""
                pid = create_post(cfg.db_path, {
                    "topic": topic,
                    "main": main,
                    "mandatory": mandatory,
                    "image_url": image_url,
                    "image_file_name": image_file_name,
                    "video_url": video_url,
                    "video_file_name": video_file_name,
                    "page_id": page_id,
                    "status": "DRAFT",
                })
                if want_ai_image or want_ai_video:
                    with st.spinner("Đang nhờ AI tạo media..."):
                        try:
                            generate_ai_media(pid, need_image=want_ai_image or want_ai_video, need_video=want_ai_video)
                        except Exception as e:
                            st.warning(f"AI media lỗi: {e}")
                st.success(f"Đã tạo Post #{pid} (DRAFT). Qua tab Duyệt để duyệt.")
                st.balloons()

elif nav == "Duyệt":
    st.markdown("### Duyệt (Approval trên web)")
    st.markdown('<div class="small-muted">Duyệt các bài DRAFT → chuyển sang APPROVED để có thể đăng.</div>', unsafe_allow_html=True)

    drafts = list_posts(cfg.db_path, status="DRAFT", limit=200)
    st.markdown(f"**DRAFT:** {len(drafts)} bài")
    if not drafts:
        st.info("Không có bài DRAFT.")
    else:
        for p in drafts:
            render_post_row(p)
            colA, colB, colC = st.columns([1, 1, 3])
            with colA:
                if st.button(f"Approve #{p['id']}", key=f"ap_{p['id']}", type="primary"):
                    update_post(cfg.db_path, int(p["id"]), {"status": "APPROVED", "last_error": ""})
                    st.rerun()
            with colB:
                if st.button(f"Mark Deleted #{p['id']}", key=f"del_{p['id']}"):
                    update_post(cfg.db_path, int(p["id"]), {"status": "FAILED", "last_error": "Deleted by user"})
                    st.rerun()
            with colC:
                st.caption("Approve xong qua tab Preview & Đăng để sinh caption và đăng.")

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

            st.markdown("#### Sinh preview (AI)")
            if st.button("Sinh/Refresh nội dung AI", type="primary"):
                try:
                    generate_preview(int(selected_id))
                    st.success("Đã sinh nội dung AI.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

            p = get_post(cfg.db_path, int(selected_id)) or p
            caption = str(p.get("caption",""))
            if caption:
                st.markdown("#### Caption")
                st.text_area(" ", value=caption, height=320, label_visibility="collapsed")

            st.markdown("#### Media preview")
            up_dir = ensure_upload_dir()
            if p.get("image_file_name"):
                img_path = os.path.join(up_dir, p.get("image_file_name"))
                if os.path.isfile(img_path):
                    st.image(img_path, caption="Ảnh đang dùng")
            if p.get("ai_image_file_name") and p.get("ai_image_file_name") != p.get("image_file_name"):
                ai_img_path = os.path.join(up_dir, p.get("ai_image_file_name"))
                if os.path.isfile(ai_img_path):
                    st.image(ai_img_path, caption="Ảnh AI đã tạo")
                    if st.button("Dùng ảnh AI này", key=f"use_ai_img_{p['id']}"):
                        update_post(cfg.db_path, int(p["id"]), {"image_file_name": p.get("ai_image_file_name"), "image_url": ""})
                        st.rerun()

            if p.get("video_file_name"):
                vid_path = os.path.join(up_dir, p.get("video_file_name"))
                if os.path.isfile(vid_path):
                    st.video(vid_path, format="video/mp4")
                else:
                    st.warning("Video upload không tìm thấy trên đĩa (có thể do xóa file).")
            elif p.get("video_url"):
                st.video(p.get("video_url"), format="video/mp4")
                st.caption("Đang dùng video URL")
            else:
                st.info("Chưa có video cho bài này.")
            if p.get("ai_video_file_name") and p.get("ai_video_file_name") != p.get("video_file_name"):
                ai_vid_path = os.path.join(up_dir, p.get("ai_video_file_name"))
                if os.path.isfile(ai_vid_path):
                    st.video(ai_vid_path, format="video/mp4")
                    if st.button("Dùng video AI này", key=f"use_ai_vid_{p['id']}"):
                        update_post(cfg.db_path, int(p["id"]), {"video_file_name": p.get("ai_video_file_name"), "video_url": "", "image_file_name": "", "image_url": ""})
                        st.rerun()

            st.markdown("#### Nhờ AI tạo ảnh/video")
            col_ai1, col_ai2 = st.columns(2)
            with col_ai1:
                need_img = st.checkbox("Tạo ảnh AI", value=not bool(p.get("ai_image_file_name")), key=f"ai_img_ck_{p['id']}")
            with col_ai2:
                need_vid = st.checkbox("Tạo video AI (beta)", value=not bool(p.get("ai_video_file_name")), key=f"ai_vid_ck_{p['id']}")
            if st.button("Generate media", key=f"gen_media_{p['id']}"):
                with st.spinner("Đang tạo media..."):
                    try:
                        generate_ai_media(int(selected_id), need_image=need_img or need_vid, need_video=need_vid)
                        st.success("Đã tạo media AI")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

            st.markdown("#### Đăng thật")
            confirm1 = st.checkbox("Tôi đã kiểm tra caption và muốn đăng thật")
            confirm2 = st.text_input("Gõ POST để xác nhận", value="", max_chars=8)
            can_post = confirm1 and confirm2.strip().upper() == "POST"

            if st.button("ĐĂNG NGAY", type="secondary", disabled=not can_post):
                try:
                    out = post_to_facebook(int(selected_id))
                    st.success("Đăng thành công.")
                    st.write("Link bài:", out.get("post_url"))
                    st.json(out.get("fb", {}))
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

elif nav == "Lịch sử":
    st.markdown("### Lịch sử")
    posted = list_posts(cfg.db_path, status="POSTED", limit=200)
    failed = list_posts(cfg.db_path, status="FAILED", limit=200)
    drafts = list_posts(cfg.db_path, status="DRAFT", limit=200)
    approved = list_posts(cfg.db_path, status="APPROVED", limit=200)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"<div class='kpi'><b>DRAFT</b><div class='hr'></div><span class='badge'>{len(drafts)}</span></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='kpi'><b>APPROVED</b><div class='hr'></div><span class='badge'>{len(approved)}</span></div>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div class='kpi'><b>POSTED</b><div class='hr'></div><span class='badge badge-green'>{len(posted)}</span></div>", unsafe_allow_html=True)
    with c4:
        st.markdown(f"<div class='kpi'><b>FAILED</b><div class='hr'></div><span class='badge badge-red'>{len(failed)}</span></div>", unsafe_allow_html=True)

    st.write("")
    st.markdown("#### POSTED gần nhất")
    for p in posted[:20]:
        render_post_row(p)

    st.markdown("#### FAILED gần nhất")
    for p in failed[:20]:
        render_post_row(p)
