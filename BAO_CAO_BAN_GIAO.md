# MolSnap – Nâng cấp quản lý nhiệm vụ học tập theo hoạt động (báo cáo bàn giao)

## 1. Cài đặt
1. Chép **cả bốn tệp** `app.py`, `classroom.py`, `history_store.py`, `requirements.txt` vào repo (thay bản cũ). Ba tệp .py phải cùng một bản; app tự kiểm tra và báo lỗi tiếng Việt nếu lệch.
2. `pip install -r requirements.txt` (đã thêm `openpyxl` để xuất .xlsx). Streamlit Cloud tự cài khi Reboot.
3. Không cần di chuyển dữ liệu: các bảng mới tự tạo khi dùng lần đầu; bảng và bài giao cũ giữ nguyên.
4. Kiểm thử: `python tests/test_hoat_dong.py` (chạy trên bản sao, không đụng dữ liệu thật).

## 2. Tệp đã chỉnh sửa / thêm
- `classroom.py`: mô hình hoạt động, tiến độ, thành thạo, quiz, nộp tệp theo hoạt động, AI chấm lỗi sai, lưu mức thành thạo.
- `app.py`: bảng soạn hoạt động, lộ trình học sinh, bảng điều khiển giáo viên, AI đề xuất hoạt động, chấm tệp, xuất .xlsx, kiểm tra lệch phiên bản, chỉnh màu giao diện tối.
- `history_store.py`: giảm đọc Google Sheets (nhớ 45 giây, dùng bản nhớ khi bị giới hạn 429).
- `requirements.txt` (thêm openpyxl), `HUONG_DAN_LOP_HOC.md`, `tests/test_hoat_dong.py`, `BAO_CAO_BAN_GIAO.md`.

## 3. Bảng dữ liệu mới (liên kết theo `id_bai`, lớp và học sinh)
`activities` (hoạt động: loại, mục tiêu, phút, điểm, trọng số, ngưỡng, số lần, chủ đề, mức, bắt buộc, hạn) · `activity_done` (học sinh tự bấm) · `activity_attempts` (từng lần làm: thời điểm, thời gian, điểm, câu sai, muộn) · `activity_questions` · `activity_grades` (giáo viên chấm tệp) · `activity_subs` (tệp nộp thuộc hoạt động nào) · `activity_files` (tài liệu của hoạt động) · `activity_reviews` (nhận xét AI) · `knowledge_mastery` (thành thạo đã lưu) · `lesson_cfg` (học tuần tự/tự do). Xóa bài giao xóa luôn các bản ghi liên quan.

## 4. Thuật toán
**Tiến độ (Learning Progress)** = Σ trọng số hoạt động bắt buộc đã *hoàn thành* / Σ trọng số hoạt động bắt buộc × 100. Trọng số bằng nhau thì là tỷ lệ số hoạt động (3/5 = 60%). Hoạt động hoàn thành chỉ khi có dữ liệu thật: tự bấm (đọc/xem), nộp phiếu hoặc làm quiz đạt ngưỡng, hoặc giáo viên chấm đạt (nộp tệp). Mở tài liệu không làm hoàn thành. Tính phía máy chủ từ bảng dữ liệu.

**Trạng thái**: chưa bắt đầu · đang thực hiện · chờ giáo viên đánh giá · hoàn thành · cần thực hiện lại (điểm dưới ngưỡng). Ma trận giáo viên: xanh hoàn thành, vàng đang làm, xám chưa bắt đầu, đỏ quá hạn.

**Thành thạo (Knowledge Mastery)**, tách riêng khỏi tiến độ: theo từng chủ đề, trung bình có trọng số của % điểm tốt nhất các hoạt động đã chấm; trọng số = độ khó (nhận biết 1, thông hiểu 1,5, vận dụng 2) × 0,7^k (k = số kết quả mới hơn, nên kết quả gần nhất và làm lại có ảnh hưởng lớn nhất). Chủ đề có dưới 2 kết quả đã chấm thì hiển thị "chưa đủ dữ liệu", không tự tạo điểm.

**Gợi ý học tiếp** theo quy tắc, luôn kèm lý do: làm lại hoạt động chưa đạt, củng cố chủ đề dưới 60%, rồi hoạt động bắt buộc kế tiếp.

**AI (Gemini)**: (a) đề xuất chia tài liệu thành hoạt động và câu hỏi nháp, chỉ giao khi giáo viên tick xác nhận; (b) nhận xét lỗi sai bài nộp tệp, điểm đề xuất chỉ giáo viên thấy; (c) phân tích lỗi và bài luyện thêm cho học sinh, không tính vào tiến độ/thành thạo. AI không phải cơ chế duy nhất xác nhận đáp án: câu trắc nghiệm do máy chủ chấm theo đáp án giáo viên đã duyệt.

## 5. Kết quả kiểm thử thực tế (19/19 đạt, `tests/test_hoat_dong.py`)
Tiến độ có trọng số và khi đổi trọng số · mở hoạt động không tự hoàn thành · thành thạo "chưa đủ dữ liệu" · không lộ đáp án quiz · đáp án ngắn nhiều cách viết · 6 lượt nộp đồng thời chỉ nhận đúng số lần cho phép · nộp quá hạn ghi nhãn muộn · giáo viên cho làm lại · tệp nộp tính đúng hoạt động · giáo viên chấm đạt → hoàn thành · quyền riêng tư nhận xét AI · học sinh không sửa hoạt động/không tự bấm hoạt động tự chấm · ma trận quá hạn · làm sạch JSON AI · dự phòng khi Google Sheets trả 429.

## 6. Phần chưa hoàn thành / hạn chế (báo cáo trung thực)
- Chưa chạy được giao diện Streamlit và lệnh gọi Gemini thật trong môi trường phát triển (không có mạng); cần thử trên app thật.
- Chưa có hoạt động xem video theo % thời gian, và hoạt động phân tích phân tử/nhận diện chất bằng RDKit dưới dạng riêng (hiện dùng trắc nghiệm/trả lời ngắn do giáo viên nhập). Chưa kiểm chứng bài luyện thêm của AI bằng RDKit.
- Gợi ý học tiếp tính tức thời, chưa lưu bảng riêng. Chưa thử mất kết nối Google Sheets thật (chỉ kiểm thử bằng mô phỏng lỗi 429).
- Hạn mức Google Sheets (60 lượt đọc/phút) vẫn có thể bị chạm khi cả lớp dùng cùng lúc; nên xin tăng hạn mức nếu cần.

## 7. Cải tiến và đóng góp
1. Chuyển giao bài từ "một tệp để đọc" sang lộ trình nhiều hoạt động có trạng thái, hạn, số lần và điều kiện hoàn thành do giáo viên đặt.
2. Tách hai chỉ số: tiến độ hoàn thành (công thức công khai, kiểm thử được) và mức thành thạo (có trọng số độ khó và độ mới, từ chối kết luận khi thiếu dữ liệu), tránh nhầm "làm xong 100%" với "hiểu 100%".
3. Bảng Learning Analytics cho giáo viên (ma trận học sinh × hoạt động, quá hạn, lịch sử làm bài, xuất Excel) trên chính dữ liệu lớp học sẵn có.
4. Dùng AI có kiểm soát: mọi nội dung AI tạo ra là bản nháp cần giáo viên duyệt; điểm chính thức do máy chủ hoặc giáo viên quyết định.
5. Kiến trúc tương thích ngược, chống ghi trùng khi nộp đồng thời, kiểm tra quyền phía máy chủ, chịu được giới hạn Google Sheets.
(Các đóng góp trên là mô tả thiết kế; chưa có dữ liệu lớp học thực để đánh giá hiệu quả học tập.)
