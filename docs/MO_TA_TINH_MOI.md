# Mô tả tính mới khoa học (trạng thái trung thực)

**Nguyên tắc:** tài liệu này KHÔNG khẳng định "đầu tiên", "duy nhất" hay "chính xác tuyệt đối". Một đóng góp chỉ được gọi là mới sau khi (1) đối chiếu tài liệu đầy đủ và (2) có kết quả thực nghiệm. Hiện cả hai đều chưa hoàn tất, nên mọi mục dưới đây là **đề xuất cần kiểm chứng**.

## 1. Vấn đề nghiên cứu

> Kết hợp nhận dạng hình ảnh bằng AI, kiểm chứng cấu trúc bằng thuật toán hóa học và hướng dẫn sửa lỗi theo từng bước như thế nào để học sinh THPT tự phát hiện và khắc phục sai sót khi viết công thức cấu tạo?

## 2. Bảng so sánh với giải pháp hiện có

Cột "Đã đối chiếu" ghi nguồn tôi đã thật sự tra cứu trong phiên làm việc này (chỉ tóm tắt, chưa đọc toàn văn từng bài). Các công trình khác trong tệp nghiên cứu bạn cung cấp (ví dụ nhận dạng hình vẽ tay, mô hình ngôn ngữ đa phương thức cho hóa học, hệ dạy học thông minh) **tôi chưa đối chiếu nguyên văn**, nên chưa đưa vào bảng.

| Giải pháp | Chức năng tương đồng | Hạn chế đối với bài toán này | Đã đối chiếu |
|---|---|---|---|
| OSRA (Filippov và Nicklaus, 2009), MolVec (Peryea và cộng sự, 2019) | Nhận dạng ảnh cấu trúc hóa học bằng quy tắc xử lý ảnh | Nhắm vào hình in trong tài liệu, trả cấu trúc chứ không chẩn đoán lỗi của người vẽ | Có (qua danh mục tài liệu của bài MolScribe) |
| MolScribe (Qian và cộng sự, JCIM 2023) | Ảnh sang đồ thị nguyên tử, liên kết; căn chỉnh mức nguyên tử với ảnh; có ước lượng độ tự tin; kết hợp quy tắc hóa học; tác giả báo cáo độ chính xác 76–93% trên các bộ dữ liệu công khai | Đánh giá trên ảnh cấu trúc trong tài liệu, không phải bài vẽ sai của học sinh; không có bước dạy sửa lỗi | Có (tóm tắt và bản arXiv) |
| ChemGrapher, MolMiner, SwinOCSR, MolGrapher | Các hướng nhận dạng ảnh bằng học sâu (phân đoạn, phát hiện đối tượng, Swin Transformer, đồ thị) | Như trên | Có (nêu trong bài MolScribe và danh sách bài liên quan) |
| ChatGPT, Gemini dùng độc lập | Đọc ảnh và nhận xét đúng sai bằng ngôn ngữ tự nhiên | Có thể "sửa ngầm" bài sai thành đúng khi đọc, kết luận không kiểm chứng được, không có cơ chế từ chối kết luận | **Chưa đo** (đây chính là phương án A cần đối chứng) |

**Điều tôi có thể nói:** trong phạm vi tra cứu giới hạn này, tôi chưa tìm thấy công cụ nào được mô tả là ghép đủ các thành phần (đọc ảnh bài làm thành đồ thị giữ nguyên lỗi, đối chứng nhiều lần đọc, quy kết nguồn lỗi, chẩn đoán theo phân loại lỗi, gợi ý ba mức, hồ sơ lỗi). **Đây không phải bằng chứng rằng chưa ai làm.** Cần tra cứu có hệ thống thêm trước khi viết như vậy trong báo cáo.

## 3. Phân loại đóng góp

| Loại | Nội dung |
|---|---|
| Công nghệ đã có (dùng lại) | Gemini đọc ảnh; RDKit; SQLite; Streamlit; hồi quy logistic, Brier, ECE; tinh chỉnh màu Weisfeiler–Lehman |
| Cách tích hợp đã có | Dùng mô hình ngôn ngữ để đọc ảnh rồi kiểm tra bằng công cụ hóa tin học là cách làm phổ biến |
| Cải tiến kỹ thuật đề xuất (do nhóm tự phát triển) | (a) đồ thị bài làm **giữ nguyên lỗi** thay vì chuẩn hóa, (b) quy kết nguồn lỗi máy đọc / học sinh / chưa rõ dựa trên đồng thuận nhiều lần đọc, (c) **từ chối kết luận** khi nguồn bất đồng, (d) phân loại lỗi thuật toán theo quan hệ đồng phân (khung nguyên tử, nhóm chức, khung cacbon), (e) gợi ý ba mức sinh từ lỗi đã xác minh, (f) chọn bài theo quy tắc minh bạch từ hồ sơ lỗi |
| Đóng góp được chứng minh thực nghiệm | **Chưa có.** Cần chạy `evaluation/` trên bộ dữ liệu thật |

## 4. Những tuyên bố còn cần thực nghiệm

1. Quy kết nguồn lỗi bằng đồng thuận nhiều lần đọc cải thiện so với một lần đọc (đối chứng B/C và C2, đo độ chính xác khi trả lời, độ phủ, và đường cong độ phủ–độ chính xác).
2. Bộ quy tắc ErrorLab phân loại đúng lỗi trên **bài vẽ thật** của học sinh (hiện mới kiểm trên 40 ca gõ tay do người soạn tạo).
3. Từ chối kết luận làm giảm số kết luận sai mà không từ chối quá nhiều.
4. Gợi ý ba mức giúp học sinh tự sửa tốt hơn chỉ hiện đáp án (cần thiết kế trước/sau hoặc nhóm đối chứng).
5. Quy tắc chọn bài giúp giảm lỗi lặp lại.
6. Các ngưỡng quyết định trong `cvr.py` còn **chưa hiệu chuẩn**; hiệu chuẩn cần dữ liệu thật (`molsnap_core/calibration.py` đã có mã, chưa có dữ liệu).

## 5. Thành phần do nhóm tự phát triển

Toàn bộ thư mục `molsnap_core/` (đồ thị, bộ đọc đầu vào, ErrorLab, StepCoach, CVR, phiên luyện tập, hồ sơ, chọn bài, đánh giá, đối chứng), `voice_component/`, các sửa đổi trong `app.py`, và bộ kiểm thử `tests/`.
