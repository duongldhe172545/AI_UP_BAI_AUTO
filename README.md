# ADG | AI Facebook Poster (DB-backed, no Google Sheets)

Bản này bỏ Google Sheets theo yêu cầu:
- Nhập input trực tiếp trên web (Streamlit)
- Duyệt trên web (DRAFT → APPROVED)
- Preview caption AI (title + content JSON)
- Đăng thật lên Facebook (photo hoặc video post)
- Lưu toàn bộ vào SQLite (1 bảng `posts`), gồm trạng thái, caption, link bài, thời gian đăng.
- Tùy chọn nhờ AI tạo ảnh hoặc video preview ngay trên web, kèm màn hình xem lại trước khi đăng.

## Chạy nhanh

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
# điền OPENAI_API_KEY và FB_PAGE_ACCESS_TOKEN
# (tuỳ chọn) DEFAULT_PAGE_ID

streamlit run app.py
```

## CLI

```bash
python main.py post-next-approved
python main.py generate-preview --id 12
python main.py post --id 12
```

## API (tuỳ chọn)

```bash
uvicorn api:app --reload --port 8000
```
