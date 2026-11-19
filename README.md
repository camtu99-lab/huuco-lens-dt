# MolSnap

Ứng dụng Streamlit hỗ trợ học Hóa học THPT. Trọng tâm nghiên cứu: **hệ thống phát hiện, giải thích và hướng dẫn sửa lỗi công thức cấu tạo của học sinh**, kết hợp Gemini (đọc ảnh) với kiểm chứng bằng thuật toán và phản hồi theo ba mức gợi ý.

## Cấu trúc
```
app.py             giao diện Streamlit (các chức năng cũ và chế độ "Kiểm tra bài em vẽ")
molsnap_core/      lõi hóa học thuần Python, không cần Streamlit hay RDKit
voice_component/   nút ghi âm tự dừng khi im lặng (tải lên GitHub cùng app.py)
tests/             92 phép thử (unittest)
benchmarks/        bộ ca tổng hợp và số liệu đồng phân chuẩn
evaluation/        quy trình thu thập dữ liệu thật và mã đối chứng A, B, C, C2, D
docs/              thiết kế, kiểm toán, báo cáo thay đổi và kiểm thử, mô tả tính mới, hướng dẫn Windows
```
## Bắt đầu
Xem `docs/HUONG_DAN_WINDOWS.md`. Đọc `docs/BAO_CAO_KIEM_THU.md` trước khi tin vào bất kỳ con số nào: phần lớn kết quả là kiểm thử trên dữ liệu tổng hợp, **chưa có thực nghiệm trên học sinh thật**.
