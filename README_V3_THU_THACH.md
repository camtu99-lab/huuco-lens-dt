# MolSnap V3 – Thử thách nhà hóa học

## Điểm mới thực sự
- Chế độ **Thử thách có chấm bài** trong menu **Kiểm chứng & sửa lỗi**; 5 bài tập cấu trúc đã biên soạn với đáp án SMILES tham chiếu.
- Đối chiếu cấu tạo bằng RDKit, không chấm theo so sánh chuỗi ký tự: `CCO` và `OCC` đều đúng cho ethanol, `COC` sai vì khác cấu tạo.
- Phản hồi phân loại: cú pháp, hóa trị, công thức phân tử, khác cấu tạo; học sinh mở gợi ý và thử lại.
- Ghi nhật ký từng lần thử, số bài đã thử, số bài từng làm đúng, số lượt cần sửa; xuất JSON. Dữ liệu chỉ lưu trong Streamlit session; không khẳng định đây là bằng chứng về hiệu quả giáo dục.
- Chế độ **Kiểm chứng SMILES tự do** từ V2.1 vẫn giữ nguyên, cùng tất cả tab gốc.

## Tệp thay đổi
- `learning_ui.py`: thêm lựa chọn chế độ và điều hướng sang thử thách.
- `challenge_engine.py`: bộ bài tập, logic chấm bằng RDKit, ghi nhận kết quả.
- `challenge_ui.py`: giao diện thử thách, gợi ý, tiến độ, tải JSON.
- `tests/test_challenge_engine.py`: kiểm thử hồi quy bổ sung.

## Cập nhật Streamlit Cloud
1. Sao lưu repository trước khi thay đổi.
2. Đặt `challenge_engine.py`, `challenge_ui.py` và `learning_ui.py` ở **cùng thư mục với `app.py`** trên GitHub. Nếu muốn chạy kiểm thử, thêm tệp `tests/test_challenge_engine.py`.
3. Commit lên nhánh đang được Streamlit Cloud triển khai; khởi động lại ứng dụng nếu cần.
4. Mở **Kiểm chứng & sửa lỗi → Thử thách có chấm bài**.
5. Không đẩy khóa API lên GitHub; tính năng mới không cần Gemini key.

## Chạy cục bộ
```bash
pip install -r requirements.txt
pip install pytest
python -m pytest -q
streamlit run app.py
```

## Trình diễn trước hội đồng
1. Chọn bài T01 (ethanol), nhập `COC` → cảnh báo cùng công thức nhưng khác cấu tạo.
2. Mở gợi ý; tự sửa thành `OCC` → được công nhận đúng dù khác chuỗi `CCO`.
3. Chọn T02 (axit axetic), nhập `CC(=O)(O)O` → báo lỗi hóa trị; sửa thành `CC(=O)O` → đúng.
4. Hiển thị tiến độ và xuất nhật ký JSON. **Đây là dữ liệu phiên thực hành**, không phải thực nghiệm chứng minh hiệu quả học tập.

## Giới hạn khoa học
- 5 bài là ví dụ demo, không phải bộ đề đã thẩm định sư phạm hay dữ liệu đánh giá độc lập.
- Đối chiếu chủ yếu theo **cấu tạo**, không chấm cấu hình lập thể trong thử thách.
- RDKit không chứng minh một cấu trúc khớp với ảnh viết tay, tên chất hay điều kiện phản ứng.
- Chưa tích hợp ảnh viết tay trực tiếp vào thử thách; phần nhận dạng Gemini vẫn thuộc tab **Công thức cấu tạo**.
- Chưa xác minh giao diện chạy end-to-end trên Streamlit Cloud trong môi trường này.
