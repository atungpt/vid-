# Trend → Việt hóa → duyệt → đăng

Starter chạy cục bộ trên Windows. Agent-Reach hỗ trợ tìm ý tưởng/đọc dữ liệu nguồn; pipeline bắt đầu từ danh sách URL được chọn. Không tự động lấy video từ kết quả tìm kiếm vì kết quả tương tác không đồng nghĩa với quyền dùng lại.

## Cài đặt

1. Cài Python 3.11+, FFmpeg (có trong PATH), Tesseract OCR (có trong PATH), và Agent-Reach theo hướng dẫn chính thức của dự án.
2. Trong PowerShell: `py -m venv .venv`; `.\.venv\Scripts\Activate.ps1`; `pip install -r requirements.txt`.
3. Sao chép `.env.example` thành `.env` rồi điền khóa trên máy của bạn; không commit `.env`.
4. Chạy `python pipeline.py discover work/clip01 --query "brainrot meme"` để lưu kết quả Agent-Reach vào `discovery.txt`. Kiểm tra số liệu, link gốc và quyền tái sử dụng.
5. Tạo `work/<slug>/source.json` theo mẫu bên dưới. Chỉ đặt `permission_to_reuse: true` sau khi xác nhận quyền dùng nguồn.

```json
{
  "url": "https://example.com/original-video",
  "title": "Tiêu đề nguồn",
  "creator": "Tên tác giả",
  "permission_to_reuse": true,
  "source_note": "Giấy phép hoặc sự đồng ý, kèm link chứng cứ",
  "context": "Giải thích tình huống, câu đùa và nghĩa ngầm"
}
```

Chạy lần lượt:

```powershell
python pipeline.py discover work/clip01 --query "brainrot meme"
python pipeline.py prepare work/clip01
python pipeline.py localize work/clip01
# Xem và sửa work/clip01/localized.json: bảo đảm nghĩa và ngữ cảnh.
python pipeline.py render work/clip01
# Xem work/clip01/final.mp4; sửa work/clip01/post.txt nếu cần.
python pipeline.py approve work/clip01
python pipeline.py publish-facebook work/clip01
python pipeline.py publish-tiktok work/clip01
```

`prepare` tải nguồn khi có quyền, chép lời bằng faster-whisper, OCR trên các khung hình mẫu. `localize` gọi OpenAI để viết SRT tiếng Việt và caption bài đăng; giữ nguyên mốc thời gian và xuất JSON để sửa tay. `render` dùng FFmpeg burn phụ đề và xuất MP4. Chữ gắn sẵn trong hình được liệt kê tại `ocr.json` để biên tập kiểm tra; phiên bản này **chưa xóa/thay chữ gốc trong từng khung hình**. Nếu nguồn có nhiều chữ gắn sẵn, cần biên tập chúng trước khi duyệt.

`approve` lưu SHA-256 của video và caption. Lệnh đăng kiểm tra lại hai hash, tránh đăng bản đã đổi sau khi duyệt. Mỗi nền tảng có file trạng thái để hạn chế đăng trùng. Bắt đầu bằng bài thử nghiệm riêng tư khi thiết lập TikTok.

## Tích hợp API

Facebook dùng Page access token và Reels Publishing API của Meta: tạo Reel, tải file lên, hoàn tất xuất bản. TikTok dùng Content Posting API Direct Post qua `FILE_UPLOAD`; app cần quyền `video.publish`, người dùng phải ủy quyền. App TikTok chưa qua audit chỉ đăng ở chế độ riêng tư. API có thể thay đổi; xác nhận phiên bản Graph và quyền app trước khi chạy.

## Giới hạn

Lệnh discover lưu kết quả tìm kiếm thô; chưa tự chấm điểm trend theo lượt xem/tương tác hay chạy theo lịch. Token OAuth và vòng đời refresh token phải được cấu hình ở môi trường vận hành trước khi chạy lâu dài. TTS, che chữ có sẵn trong hình và tái dựng ảnh chưa được triển khai. Không cung cấp khóa/tài khoản qua chat.
