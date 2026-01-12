# ADG | AI Facebook Poster (DB-backed, no Google Sheets)

Bản này bỏ Google Sheets theo yêu cầu:
- Nhập input trực tiếp trên web (Streamlit)
- Nhờ AI tạo nội dung bài viết (caption) trước khi duyệt
- Duyệt trên web (DRAFT → APPROVED)
- Sau khi APPROVED có thể upload ảnh/video trước khi đăng
- Đăng thật lên Facebook (photo post)
- Lưu toàn bộ vào SQLite (1 bảng `posts`), gồm trạng thái, caption, link bài, thời gian đăng.

## Chạy nhanh

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Tạo file .env và điền các thông tin cần thiết

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
