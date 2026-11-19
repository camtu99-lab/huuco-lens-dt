# Hướng dẫn chạy trên Windows

1. Cài Python 3.10 trở lên từ python.org, tick **Add Python to PATH**.
2. Mở thư mục chứa `app.py`, gõ `cmd` vào thanh địa chỉ rồi Enter.
3. Tạo môi trường riêng (nên làm):
   ```
   python -m venv .venv
   .venv\Scripts\activate
   ```
4. Cài thư viện:
   ```
   pip install -r requirements.txt
   ```
   Nếu `rdkit` báo lỗi, thử `pip install rdkit` riêng hoặc dùng Python 3.11 hoặc 3.12.
5. Tạo tệp `.streamlit\secrets.toml` (xem `secrets.toml.example`), tối thiểu:
   ```
   GEMINI_API_KEY = "khóa-của-bạn"
   ```
   Không đưa tệp này lên GitHub.
6. Chạy app:
   ```
   streamlit run app.py
   ```
7. Chạy bộ kiểm thử:
   ```
   python -m unittest discover -s tests -v
   ```
   Phép thử phim cần thêm `pip install playwright` rồi `playwright install chromium`; không cài thì phép thử tự bỏ qua.
8. Chạy đối chứng A–D khi đã có dữ liệu:
   ```
   python evaluation\run_ablation.py --cases bo_du_lieu.csv --records gemini_da_ghi.json --out ket_qua
   ```

## Khóa cấu hình tùy chọn trong secrets.toml
`CVR_READS` (số lần đọc ảnh, 1 đến 3, mặc định 2), `MOLSNAP_DB` (đường dẫn SQLite), `STUDENT_SALT` (muối băm mã học sinh, **nên đổi**), `TEACHER_CODE`, `GEMINI_MODEL`, `GEMINI_TTS_MODEL`, `GEMINI_TTS_VOICE`.

## Lưu ý quyền riêng tư
App không lưu ảnh học sinh và không lưu tên; chỉ lưu bản băm của mã học sinh cùng kết quả luyện tập. Học sinh có thể tải CSV và xóa toàn bộ dữ liệu của mã mình trong mục "Hồ sơ kỹ năng". Ảnh được gửi tới Gemini để đọc, hãy báo cho học sinh và phụ huynh theo quy định của nhà trường.
