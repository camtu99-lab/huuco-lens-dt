# Báo cáo thay đổi

## Giữ nguyên (không phá, đã kiểm lại bằng phép thử hồi quy khi có thể)
Nhận biết dụng cụ, sơ đồ tư duy, trợ lý AI, phân tích phương trình, đếm đồng phân, phim mô phỏng thí nghiệm, benchmark nhận dạng ảnh, dạng bài "gọi tên chất" trong Luyện tập, ghi âm giọng nói. Nếu thiếu thư mục `molsnap_core`, app tự quay về các chức năng cũ.

## Đã sửa
* Cảnh báo "chưa cân bằng" sai do SMILES AI viết (nay đếm nguyên tử từ chính phương trình).
* Khớp thí nghiệm có sẵn nuốt chất lạ (Gly-Ala-Gly + CuSO₄ + NaOH).
* Lọc đồng phân theo tính chất hóa học (tác dụng NaOH, Na...) do máy tự tính từ cấu tạo.
* Bỏ phần trăm "độ tin cậy" do AI tự khai ở hai nơi.
* Luyện tập vẽ công thức không còn lộ đáp án và khóa bài sau lần nộp đầu.
* Giọng đọc phim: trả về cách thu của bản đầu, thu song song có hạn chót, thiếu đoạn thì cả phim dùng giọng trình duyệt cho đồng nhất.

## Đã nâng cấp
* **Tab Công thức cấu tạo**: thêm chế độ "Kiểm tra bài em vẽ" (không thêm tab).
* **Luyện tập**: dạng vẽ công thức dùng quy trình mới; đề xuất bài theo quy tắc minh bạch; hồ sơ kỹ năng.
* **Benchmark** (mục dành cho giáo viên): thêm đánh giá chẩn đoán lỗi và đếm đồng phân, có P/R/F1, khoảng tin cậy Wilson, tải CSV kèm phiên bản và cấu hình.
* **Đồng phân**: cảnh báo trung thực khi công thức có N và O (nitro) hoặc S.
* **Phương trình**: nhắc rằng cân bằng không chứng minh phản ứng xảy ra.
* **Thí nghiệm do AI soạn**: ghi rõ chưa được giáo viên thẩm định.
* **Trợ lý AI**: nhận ngữ cảnh bài đang làm và chỉ gợi ý, không nêu đáp án.

## Chức năng mới
`molsnap_core/` (đồ thị giữ nguyên lỗi, kiểm tra hóa trị, dạng chuẩn, ba bộ đọc đầu vào, ErrorLab với 9 mã lỗi, StepCoach, đối chứng nhiều lần đọc và quy kết nguồn, phiên luyện tập, SQLite ẩn danh, chọn bài, hiệu chuẩn, chỉ số đánh giá, đối chứng A–D); bộ sinh đồng phân thuần Python để kiểm toán; `evaluation/`; `benchmarks/`; `tests/` (92 phép thử).

## Chưa hoàn thành
1. **Chưa có dữ liệu thực nghiệm nào**: chưa có ảnh bài vẽ của học sinh, chưa có đo độ chính xác đọc ảnh, chưa có nhóm đối chứng, chưa có kết quả trước/sau học.
2. **Hiệu chuẩn độ tin cậy**: có mã, chưa có dữ liệu; hệ thống dùng quy tắc chưa hiệu chuẩn.
3. **Đo độ chính xác định vị lỗi**: chưa viết (cần nhãn vị trí và ánh xạ nguyên tử giữa ảnh và đồ thị chuẩn).
4. **Chỉnh sửa trực quan trên ảnh**: học sinh chỉnh bằng bảng nguyên tử/liên kết hoặc gõ lại công thức thu gọn. **Chưa tích hợp trình soạn thảo cấu trúc dạng vẽ** như Ketcher.
5. **Bộ sinh đồng phân chưa mở rộng** cho nitro, N-oxit, S hóa trị cao, và chưa phân biệt đồng phân lập thể. Mới chỉ cảnh báo.
6. **Chưa tìm và sửa nguyên nhân** cấu trúc bị RDKit từ chối trong bộ sinh (cần RDKit).
7. Đối chiếu tài liệu để xác nhận tính mới: mới làm một phần nhỏ.
8. Prompt thứ hai của bạn bị cắt ở mục 10 ("Hãy trực tiếp chỉnh..."); tôi triển khai theo các mục 1 đến 9 và mục 7 đến 8 của prompt thứ nhất.

## Giới hạn kỹ thuật còn lại
Xem `docs/THIET_KE_CVR.md` mục "Giới hạn thiết kế" và `docs/BAO_CAO_KIEM_THU.md` mục "Chưa chạy được".
