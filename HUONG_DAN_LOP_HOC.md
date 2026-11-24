# Lớp học trong MolSnap: đăng nhập, giao bài, xem kết quả

## Giáo viên (một lần)
1. Đặt `TEACHER_CODE` trong Secrets (và nên nối Google Sheets, xem HUONG_DAN_GOOGLE_SHEETS.md, để dữ liệu không mất).
2. Mở **Lịch sử tra cứu > Tất cả học sinh (giáo viên)**, nhập mã giáo viên.
3. Tab **Lớp & tài khoản**: tạo lớp (mã lớp ví dụ `10A1`). Đưa mã lớp cho học sinh.
4. Tab **Giao bài**: chọn lớp, đặt tên bài, chọn dạng (vẽ công thức / gọi tên / cả hai), chọn chất hoặc để ngẫu nhiên, đặt hạn, bật/tắt gợi ý.
5. Tab **Kết quả bài**: bảng ai làm đúng lần đầu, đúng sau mấy lần, sai, chưa làm; tải CSV.
6. Tab **Chỗ hay sai**: chủ đề và câu cả lớp hay sai nhất, và cả lớp tra cứu nhiều ở tab nào.
7. Quên PIN: tab **Lớp & tài khoản > Đặt lại PIN** (lịch sử và bài nộp vẫn giữ).

## Học sinh
- Thanh bên > **Đăng nhập lớp học**: nhập mã lớp, tên, PIN (4-12 ký tự). Lần đầu app tạo tài khoản với PIN đó; lần sau nhập đúng PIN.
- Tab **Luyện tập**: "Tự luyện" hoặc "Bài giáo viên giao". Mỗi câu có 3 gợi ý tăng dần và 3 lần nộp; hết lần mới hiện đáp án.
- Trợ lý AI mặc định ở chế độ gợi ý từng bước (không đưa đáp án ngay); có công tắc để tắt.
- Đăng nhập được giữ khi tải lại trang (mã ký trong địa chỉ, không chứa PIN). Gửi nguyên địa chỉ cho bạn khác là cho họ dùng tài khoản của mình.

## Chi phí và ổn định (Secrets, đều tùy chọn)
- `MAX_PER_SESSION`: số lượt gọi AI mỗi phiên (mặc định 15).
- `MAX_PER_DAY`: số lượt tra cứu mỗi học sinh có tên mỗi ngày (mặc định 0 = không giới hạn).
- Kết quả AI giống hệt nhau (cùng ảnh/câu hỏi, cùng ngôn ngữ) được nhớ 24 giờ, không tốn thêm lượt gọi.
- `GEMINI_FALLBACK_MODEL`: mô hình dự phòng khi mô hình chính quá tải hoặc hết hạn mức.
- `APP_SECRET`: khóa ký mã đăng nhập (không đặt thì dùng TEACHER_CODE).

## Giới hạn hiện tại
- Chấm tự động áp dụng cho ngân hàng đề có sẵn (khoảng 44 chất: gọi tên và vẽ công thức), chưa có cân bằng phương trình hay đồng phân.
- Chưa có hạn mức theo lớp, chỉ theo phiên và theo học sinh.
