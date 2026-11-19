# Báo cáo kiểm thử

Lệnh chạy: `python -m unittest discover -s tests -v` (không cần cài thêm gì cho phần lớn phép thử).

## Kết quả lần chạy cuối trên máy tôi

**92 phép thử chạy, 91 đạt, 1 bỏ qua, 0 lỗi.** Mọi tệp `.py` biên dịch được (`python -m compileall`).

| Nhóm | Phép thử | Nội dung |
|---|---|---|
| `test_core_chem` | 15 | Hóa trị, công thức, dạng chuẩn bất biến khi đánh số lại, SMILES, công thức thu gọn, dữ liệu AI xấu, **43 bài trong ngân hàng đều đúng công thức phân tử chuẩn viết tay** |
| `test_diagnosis_dataset` | 3 | **40 ca tổng hợp có đáp án gán tay**, 7 loại lỗi và ca đúng |
| `test_coach_session` | 12 | Gợi ý ba mức riêng từng lỗi, không lộ đáp án; phiên luyện tập; hồ sơ SQLite; quy tắc chọn bài và mức khó |
| `test_cvr_evidence` | 24 | Đối chứng nhiều lần đọc, từ chối khi bất đồng, hiệu chuẩn (Brier, ECE, đẳng hướng), P/R/F1, kappa, Wilson, bootstrap |
| `test_ablation` | 5 | Bốn phương án đối chứng, bảng trống không bịa số (dữ liệu tổng hợp) |
| `test_isomers` | 6 | **18 số liệu chuẩn độc lập**, so cả tập cấu trúc C₄H₁₀O, giới hạn nitro, hết thời gian báo lỗi |
| `test_app_regression` | 7 | Hàm thuần của `app.py`: khớp thí nghiệm, cân bằng phương trình, `sim_clean`, lọc đồng phân theo tính chất, oxi hóa khử |
| `test_app_glue` | 7 | Gắn kết giao diện và benchmark trong `app.py` bằng Streamlit giả |
| `test_ui_flow` | 9 | Luồng giao diện CVR bằng Streamlit giả, gồm **kịch bản tiêu chí thành công** |
| `test_movie` | 3 | Phim chạy trong Chromium thật: 6 thí nghiệm không lỗi JS, khung hình không trống, bật tắt cô giáo, thời gian giữa các bước |
| `test_ui_smoke` | 1 (bỏ qua) | Cần cài `streamlit` và `rdkit` |

## Lỗi tìm thấy khi kiểm thử và cách xử lý

* Ca tổng hợp S19 lệch ban đầu: **nhãn của tôi sai** (`CH3-CH(CH3)-CH3` có 4 C, không phải 3). Máy đúng; đã sửa nhãn.
* Đáp án tôi gõ sai cho glyxin lưỡng cực (C₂H₅NO₂); mã đúng. Đã sửa đáp án.
* SMILES chứa nguyên tố lạ (`[Xx]`) bị nhận im lặng: đã báo lỗi.
* but-1-en bị xếp nhầm là "sai bậc liên kết" thay vì "sai vị trí liên kết bội": đã sửa quy tắc.
* Khi các lần đọc ảnh bất đồng nhưng cùng loại lỗi, hệ thống đang kết luận kèm cờ: đã siết thành từ chối cho đến khi học sinh xác nhận.
* Halogen có chỉ số (`CCl3`, `CHCl3`) và dấu liên kết thừa cuối chuỗi: đã xử lý.
* `_tts_chunks`: test hồi quy bị gỡ vì chức năng đã bị loại ở bản trả về giọng gốc.

## Chưa chạy được, và vì sao (giới hạn môi trường)

| Chưa kiểm thử | Lý do |
|---|---|
| **Giao diện Streamlit thật** (bố cục, `st.data_editor`, thành phần ghi âm, `AppTest`) | Máy tôi không có Streamlit. Luồng đã chạy bằng đối tượng giả nên **logic đúng nhưng hình thức hiển thị chưa xem** |
| **Mọi hàm dùng RDKit trong `app.py`**: `graph_draw`, `enumerate_isomers`, `grade_structure`, benchmark đếm đồng phân | Máy tôi không có RDKit. Riêng **logic** sinh đồng phân đã kiểm bằng bản sao thuần Python |
| **Gemini thật** (đọc ảnh nhiều lần, soạn kịch bản, giọng đọc, chép lời) | Không gọi được từ môi trường này, và không có khóa. Chưa biết độ chính xác đọc ảnh |
| Quy kết nguồn lỗi với đầu ra thật của Gemini | Các phép thử dùng đồ thị dựng sẵn. Chưa biết Gemini bất đồng với nhau thường xuyên cỡ nào |
| Điện thoại thật, trình duyệt khác Chromium, Streamlit Cloud | Không có |
| Hiệu năng với nhiều người dùng cùng lúc | Không có |

## Phạm vi của các con số

Các kết quả 40/40 và 18/18 là **kiểm thử hồi quy trên dữ liệu do người soạn tạo**, rất dễ đạt vì cùng người viết quy tắc và gán nhãn. **Không được trích chúng làm độ chính xác của MolSnap ngoài thực tế.**
