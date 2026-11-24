# Lớp học trong MolSnap: đăng nhập, giao bài, xem kết quả

## Giáo viên (một lần)
1. Đặt `TEACHER_CODE` trong Secrets (và nên nối Google Sheets, xem HUONG_DAN_GOOGLE_SHEETS.md, để dữ liệu không mất).
2. Thanh bên > **Đăng nhập / Tham gia lớp** > chọn **Giáo viên**, nhập mã giáo viên. Sau đó mở tab **Lịch sử tra cứu** (hoặc nút **Quản lý lớp**). Tải lại trang thì phải nhập lại mã (không lưu trong địa chỉ trang).
3. Tab **Lớp & tài khoản**: tạo lớp (mã lớp ví dụ `10A1`). Đưa mã lớp cho học sinh.
4. Tab **Giao bài**: chọn lớp, đặt tên bài, chọn dạng (vẽ công thức / gọi tên / cả hai), chọn chất hoặc để ngẫu nhiên, đặt hạn, bật/tắt gợi ý.
5. Tab **Kết quả bài**: bảng ai làm đúng lần đầu, đúng sau mấy lần, sai, chưa làm; tải CSV.
6. Tab **Chỗ hay sai**: chủ đề và câu cả lớp hay sai nhất, và cả lớp tra cứu nhiều ở tab nào.
7. Quên PIN: tab **Lớp & tài khoản > Đặt lại PIN** (lịch sử và bài nộp vẫn giữ; học sinh đăng ký lại với PIN mới). Đổi PIN thì các địa chỉ đăng nhập cũ hết hiệu lực.

## Học sinh
- Dùng các công cụ Hóa học không cần đăng nhập (khách; lịch sử chỉ lưu trong phiên). Cần đăng nhập để làm bài giáo viên giao và lưu lịch sử, kết quả.
- Thanh bên > **Đăng nhập / Tham gia lớp** > **Học sinh**. Lần đầu chọn **Đăng ký lần đầu** (mã lớp, họ tên, PIN 4-12 ký tự, nhập lại PIN); những lần sau chọn **Đã có tài khoản**. Mỗi tên chỉ có một tài khoản trong lớp.
- Sau khi đăng nhập, thanh bên hiện tên, lớp, trạng thái kết nối, số bài hoàn thành và độ chính xác (tính từ bài nộp thật). Nút **Hồ sơ** cho xem chủ đề hay sai, gợi ý ôn tập và đổi PIN.
- Tab **Luyện tập**: "Tự luyện" hoặc "Bài giáo viên giao". Mỗi câu có 3 gợi ý tăng dần và 3 lần nộp; hết lần mới hiện đáp án.
- Trợ lý AI mặc định ở chế độ gợi ý từng bước (không đưa đáp án ngay); có công tắc để tắt.
- Đăng nhập học sinh được giữ khi tải lại trang (mã ký trong địa chỉ, không chứa PIN). Gửi nguyên địa chỉ cho bạn khác là cho họ dùng tài khoản của mình.

## Chi phí và ổn định (Secrets, đều tùy chọn)
- `MAX_PER_SESSION`: số lượt gọi AI mỗi phiên (mặc định 15).
- `MAX_PER_DAY`: số lượt tra cứu mỗi học sinh có tên mỗi ngày (mặc định 0 = không giới hạn).
- Kết quả AI giống hệt nhau (cùng ảnh/câu hỏi, cùng ngôn ngữ) được nhớ 24 giờ, không tốn thêm lượt gọi.
- `GEMINI_FALLBACK_MODEL`: mô hình dự phòng khi mô hình chính quá tải hoặc hết hạn mức.
- `APP_SECRET`: khóa ký mã đăng nhập (không đặt thì dùng TEACHER_CODE).

## Giới hạn hiện tại
- Chấm tự động áp dụng cho ngân hàng đề có sẵn (khoảng 44 chất: gọi tên và vẽ công thức), chưa có cân bằng phương trình hay đồng phân.
- Chưa có hạn mức theo lớp, chỉ theo phiên và theo học sinh.

## Giao bài kèm tệp (tải lên / tải về)
- **Giáo viên:** tab *Lịch sử tra cứu → Giao bài*, mục "📎 Đính kèm tệp" khi giao bài (tối đa 5 tệp, mỗi tệp 1 MB). Có thể giao bài **chỉ gồm tệp**, không cần chọn chất. Bài đã giao có thể thêm/xóa tệp trong mục "📎 Tệp đính kèm".
- **Học sinh:** tab *Luyện tập → Bài giáo viên giao*: bấm **👁️ Xem** để đọc yêu cầu ngay trên trang (ảnh, PDF, txt, Word) hoặc **⬇️ Tải về**; Excel/PowerPoint chỉ tải về. Học sinh cũng có thể tải tài liệu của giáo viên và nộp tệp bài làm (ảnh, PDF, Word…).
- **Giáo viên xem bài nộp:** tab *Kết quả bài → 📥 Tệp học sinh nộp*, bấm Tải về từng tệp.
- Định dạng nhận: pdf, doc, docx, xls, xlsx, ppt, pptx, txt, csv, png, jpg, jpeg, gif, zip.
- Ảnh png/jpg tới 20 MB được tự nén xuống dưới 1 MB (đổi thành .jpg); các định dạng khác vẫn giới hạn 1 MB.
- Tệp được lưu cùng nơi với bài giao (Google Sheets nếu đã cấu hình, ngược lại thư mục data/tables/), nên giữ tệp nhỏ.
