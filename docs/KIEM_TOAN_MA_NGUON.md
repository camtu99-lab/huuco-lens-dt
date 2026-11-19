# Kiểm toán mã nguồn MolSnap (Giai đoạn 1)

Đối tượng: `app.py` bản bạn đang dùng (khoảng 4.700 dòng, 154 hàm) cộng các thay đổi tôi đã làm trong cuộc trò chuyện. Cột "Đã chạy thử" ghi trung thực nơi tôi đã thật sự chạy.

| Chức năng | Phụ thuộc | Tình trạng | Đã chạy thử |
|---|---|---|---|
| Phim mô phỏng thí nghiệm (6 thí nghiệm, cô giáo, giọng đọc) | JavaScript trong trình duyệt; Gemini TTS | Hoạt động | Phim: có (Chromium, 3 phép thử). Giọng Gemini: **không** |
| Soạn kịch bản thí nghiệm bằng AI | Gemini | Hoạt động; có bộ lọc `sim_clean` | `sim_clean`: có. Gọi Gemini: không |
| Nhận biết dụng cụ qua ảnh | Gemini | Hoạt động | Không |
| Phân tích phương trình, oxi hóa khử | Gemini + Python | Số oxi hóa do AI cho, máy kiểm tra | Phần Python: có. Gemini: không |
| Công thức cấu tạo từ ảnh | Gemini + RDKit | Hoạt động | RDKit: **không** (máy tôi không có) |
| Đếm đồng phân (`enumerate_isomers`) | RDKit | Hoạt động; xem lỗi 4 và 5 bên dưới | Logic: có, bằng bản sao thuần Python. Lớp RDKit: **không** |
| Luyện tập (cũ): chấm bằng `grade_structure` | Gemini + RDKit | Còn dùng cho dạng "gọi tên chất" | Không |
| Benchmark nhận dạng ảnh (cũ) | Gemini + RDKit | Hoạt động | Không |
| Sơ đồ tư duy, trợ lý AI, ghi âm giọng nói | Gemini | Hoạt động | Một phần |

## Lỗi và rủi ro đã phát hiện khi đọc mã

1. **`practice_ui` lộ đáp án ngay sau lần nộp đầu và khóa bài**, không sửa và nộp lại được. *Đã thay* bằng quy trình CVR có gợi ý ba mức.
2. **`grade_structure` phân loại lỗi thô**; RDKit không báo lỗi khi nguyên tử thiếu hóa trị (coi là gốc tự do). *Đã bổ sung* kiểm tra hóa trị thuần Python và phân loại lỗi chi tiết có vị trí.
3. **Hồ sơ luyện tập mất khi tải lại trang.** *Đã thêm* SQLite, mã học sinh ẩn danh, xuất/nạp CSV, xóa theo mã.
4. **Thuật toán đếm đồng phân chỉ sinh cấu trúc trung hòa với hóa trị cố định (N = 3, S = 2).** Nitro (N⁺(=O)O⁻) và S hóa trị cao không bao giờ được sinh, mà app trước đây báo tổng số không cảnh báo (ví dụ C₂H₅NO₂ thiếu nitroetan). *Đã thêm* cảnh báo phạm vi; **chưa mở rộng thuật toán**.
5. **Cấu trúc RDKit không chuẩn hóa được bị bỏ qua im lặng** trong bước chuẩn hóa của bộ sinh. *Chưa sửa* (cần RDKit để kiểm tra); đã ghi vào giới hạn.
6. **App hiển thị phần trăm "độ tin cậy" do chính AI tự khai** ở hai nơi (công thức cấu tạo, nhận biết dụng cụ). *Đã bỏ*, thay bằng thông báo trung thực.
7. **Khớp thí nghiệm có sẵn quá lỏng**: "Gly-Ala-Gly + CuSO4 + NaOH" bị ghép nhầm với kịch bản "CuSO4 + NaOH". *Đã sửa trước đó.*
8. **Cảnh báo "chưa cân bằng" sai** vì dựa vào SMILES do AI viết cho chất vô cơ. *Đã sửa trước đó* bằng đếm nguyên tử từ chính phương trình.
9. Phương trình cân bằng dễ bị hiểu là "phản ứng chắc chắn xảy ra". *Đã thêm* câu nhắc ở phần phương trình.
10. Kịch bản thí nghiệm do AI soạn có thể nguy hiểm. *Đã thêm* cảnh báo "chưa được giáo viên thẩm định"; bộ lọc `sim_clean` và lời dặn từ chối thí nghiệm nguy hiểm vẫn giữ nguyên.
11. Khóa API: không có khóa trong mã nguồn (đọc từ `st.secrets`). Rủi ro còn lại: ai có đường dẫn đều dùng hạn mức Gemini của bạn; nên đặt `TEACHER_CODE` và giới hạn lượt.
12. Lưu trữ trên Streamlit Cloud có thể bị xóa khi khởi động lại: đã cảnh báo trong giao diện và có xuất CSV.

## Chức năng trùng lặp hoặc ít giá trị

Giọng nói và sơ đồ tư duy không thuộc đóng góp cốt lõi nên **được giữ nguyên, không đầu tư thêm** theo đúng yêu cầu "không dàn trải". Tôi chưa gỡ chức năng nào.
