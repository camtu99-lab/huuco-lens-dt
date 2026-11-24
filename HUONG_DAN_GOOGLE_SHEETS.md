# Lưu lịch sử học sinh bằng Google Sheets (làm một lần, khoảng 10 phút)

1. Vào https://console.cloud.google.com, tạo một dự án (hoặc dùng dự án có sẵn).
2. Menu **APIs & Services > Library**: bật **Google Sheets API** và **Google Drive API**.
3. **APIs & Services > Credentials > Create credentials > Service account**, đặt tên bất kỳ, bấm Done.
4. Mở service account vừa tạo > tab **Keys > Add key > Create new key > JSON**. Máy tải về một file .json.
5. Tạo một Google Sheet trống tại https://sheets.google.com (đặt tên, ví dụ "MolSnap lịch sử").
   Bấm **Chia sẻ**, dán địa chỉ `client_email` trong file .json, chọn quyền **Người chỉnh sửa**.
6. Lấy ID bảng tính trong địa chỉ: `https://docs.google.com/spreadsheets/d/<ID>/edit`.
7. Trên Streamlit Cloud: **App > Settings > Secrets**, dán theo mẫu `secrets.toml.example`:
   - `HISTORY_SHEET_ID` = ID ở bước 6, và `TEACHER_CODE` = mã giáo viên tự đặt.
   - `GCP_SERVICE_ACCOUNT_JSON`: mở file .json bằng Notepad, chọn TOÀN BỘ, dán vào giữa hai dấu **ba nháy đơn** (ba ký tự ' liền nhau, nháy đơn chứ không phải nháy kép). Không sửa, không xóa các dấu \n trong private_key.
   - Các dòng `KEY = "..."` luôn đặt TRÊN CÙNG. Nếu dùng kiểu bảng `[gcp_service_account]` thì mọi dòng viết sau nó bị tính là thuộc bảng đó, đây là nguyên nhân lỗi TOML hay gặp.
8. Khởi động lại app. Ở tab "Lịch sử học sinh" dòng "Nơi lưu" phải ghi **Google Sheets**.
   Hai trang tính `lookups` và `visits` tự được tạo; giáo viên cũng mở bảng tính này để xem trực tiếp.

Nếu dòng "Nơi lưu" vẫn báo tệp trên máy chủ, hoặc báo lỗi đỏ: kiểm tra đã chia sẻ bảng tính cho `client_email`
và đã bật cả hai API ở bước 2.
