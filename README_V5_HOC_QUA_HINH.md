# MolSnap V5 — Học qua hình, không bắt học sinh nhập SMILES

## Những thay đổi thật trong mã nguồn
- Thay trải nghiệm mặc định của mục học tập bằng 5 câu hỏi trắc nghiệm có hình công thức cấu tạo 2D được RDKit tạo từ cấu trúc đã biên soạn.
- RDKit chấm dựa trên sự tương đương cấu tạo, không so khớp chữ cái A/B với đáp án cứng; trả lời sai có giải thích và gợi ý, cho phép chọn lại.
- Ghi tiến độ trong phiên và cho phép xuất JSON. Đây KHÔNG phải dữ liệu nghiên cứu hiệu quả giáo dục.
- Chế độ nhập SMILES vẫn còn trong phần **Kiểm chứng nâng cao (giáo viên)**, không phải giao diện mặc định của học sinh.
- Kết quả từ tab nhận dạng ảnh cũ vẫn có thể chuyển sang phần kiểm chứng nâng cao; cần người dùng xác nhận Gemini đọc đúng hình.
- Đổi tên tab minh chứng thành **Báo cáo kiểm thử**, xác định rõ dành cho giáo viên/hội đồng. Không khẳng định đã đo chính xác ảnh hoặc tác động giáo dục.
- Không xóa chức năng cũ hoặc thay đổi API Gemini.

## Cập nhật GitHub Desktop một lần
1. Giải nén ZIP, vào thư mục `streamlit_gemini`.
2. Sao chép toàn bộ nội dung vào thư mục repository GitHub đang chứa `app.py`, chọn Replace khi Windows hỏi.
3. GitHub Desktop: kiểm tra Changes, không commit `secrets.toml` hoặc khóa thật; Commit và Push origin.
4. Streamlit Cloud sẽ triển khai lại nếu dùng đúng nhánh. Nếu lỗi, xem Manage app > Logs.

## Kiểm thử đã thực hiện
`python -m pytest -q`: 29 passed (môi trường chạy kiểm thử có RDKit). `python -m compileall -q .`: không có lỗi cú pháp.
Chưa kiểm thử đầu-cuối trên Streamlit Cloud hoặc Gemini API. Chưa có nghiên cứu với học sinh.

## Giới hạn khoa học
5 câu hỏi là bài tập minh họa có đáp án biên soạn, không phải bộ đánh giá độ chính xác AI. Hình được dựng từ SMILES hợp lệ, không phải ảnh viết tay. Kiểm chứng RDKit chỉ chứng minh tương đương cấu tạo trong phạm vi kiểm tra; không tự suy ra hiệu quả học tập.
