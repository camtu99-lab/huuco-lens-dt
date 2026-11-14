# MolSnap – Gói nâng cấp kiểm chứng hóa học (14/11/2026)

## Phạm vi và tính trung thực của kiểm chứng

Bản nâng cấp giữ nguyên giao diện và hầu hết chức năng trong `app.py` gốc; bổ sung `chem_verification.py`, `evaluation.py` và `tests/`. Đây là kiểm thử **mô-đun hóa học độc lập**, không phải phép đo độ chính xác ảnh, hiệu quả giáo dục hoặc kiểm thử tích hợp Gemini/Streamlit. Không có API key được sử dụng trong các lần chạy kiểm thử ở đây.

### Phân tích hiện trạng dựa trên mã nguồn

| Hạng mục | Đã tìm thấy trong mã gốc | Rủi ro/giới hạn |
|---|---|---|
| Nhận dạng ảnh cấu tạo | `transcribe_student`, `GRAPH_PROMPT`, `graph_to_smiles`, `analyze_image_strict` | Gemini có thể đọc sai ảnh; bản gốc chưa kiểm tra schema đồ thị đủ chặt |
| SMILES, hóa trị | `parse_student`, `chem_numbers`, `grade_structure` | RDKit chỉ kiểm tra biểu diễn, không xác minh ảnh gốc, danh pháp và tính chất |
| Phản ứng | `analyze_reaction`, `rx_balance_formulas`, `redox_analysis` | Cân bằng nguyên tử không xác nhận phản ứng xảy ra |
| Đồng phân | `enumerate_isomers`, `iso_enumerate`, `stereo_split` | Chưa có chứng minh đầy đủ với mọi công thức; giới hạn thời gian/số nguyên tử |
| Dụng cụ/thí nghiệm | `analyze_equipment`, `sim_match_builtin`, `sim_html` | Nhận dạng và mô phỏng không thay thế kiểm tra an toàn thực tế |
| Sơ đồ tư duy | `mindmap_ui`, các hàm xuất PNG/PPTX/SVG/draw.io | Nội dung do AI sinh vẫn cần rà soát |
| Trợ lý | `chat_ai`, `assistant_ui` | Không có bộ kiểm chứng phổ quát cho mọi câu trả lời |
| Luyện tập/benchmark | `practice_ui`, `bench_ui`, `bench_row` | Có xử lý thật nhưng chưa thấy được đưa vào điều hướng chính; kết quả benchmark chỉ có sau khi chạy |

### Các thay đổi đã thực hiện

1. Thêm `verify_smiles`: trạng thái `valid`, `invalid`, `unknown`; phân loại cú pháp, hóa trị, thơm, lỗi khác, giới hạn; gợi ý từng bước và vị trí nguyên tử nếu xác định được.
2. Thêm `validate_graph` trước `graph_to_smiles`: từ chối ID trùng, liên kết trùng, bậc sai, nguyên tử không tồn tại, ký hiệu nguyên tố không hỗ trợ và số H bất hợp lệ. **Không tự ý sửa** bản chép AI.
3. Thêm `verify_ai_proposal`, `compare_to_target`, `verify_isomer_candidates` để đánh giá kết quả theo quy tắc độc lập. Cần phân biệt `same_constitution` với `same_stereochemical_representation`.
4. Giao diện cấu trúc có mục kiểm chứng RDKit, chỉ ra giới hạn ảnh→SMILES, hiển thị gợi ý. SMILES sửa sai được kiểm tra trước khi gọi API.
5. `analyze_smiles` giữ nguyên SMILES đầu vào đã nhập thay vì tin SMILES Gemini trả về, loại bỏ `do_tin_cay=1` tự gán; `get_client` nhận API key từ biến môi trường hoặc Streamlit secrets.
6. Thay tuyên bố phạm vi “mọi cấu trúc” ở màn đồng phân bằng “trong giới hạn thuật toán”; không khẳng định đầy đủ nếu chưa chứng minh.
7. Thêm bộ dữ liệu tham chiếu `tests/cases.json`, kiểm thử pytest và công cụ CLI lưu `results/latest.json` theo từng lần chạy thực tế.

### Cài đặt và chạy

Yêu cầu Python tương thích với RDKit, Streamlit, google-genai, Pillow, python-pptx. Trong thư mục `streamlit_gemini`:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install pytest
```

Cấu hình khóa Gemini bằng một trong hai cách:

- Windows PowerShell: `$env:GEMINI_API_KEY="..."`
- Linux/macOS: `export GEMINI_API_KEY="..."`
- Hoặc tạo `.streamlit/secrets.toml` theo `secrets.toml.example` (không commit khóa thật).

```bash
streamlit run app.py
```

Kiểm thử độc lập, **không cần khóa Gemini**:

```bash
python -m pytest -q
python evaluation.py --cases tests/cases.json --output results/latest.json
```

Đọc `results/latest.json`: `n` là số ca chạy, `passed` số ca khớp kỳ vọng, `pass_rate` chỉ phản ánh tập ca hiện có. Thời gian đo phụ thuộc máy và tải hệ thống. **Không dùng 8/8 làm tỷ lệ đúng chung của sản phẩm**.

### Những gì chưa thể xác nhận / chưa hoàn thành

- Chưa chạy toàn bộ UI Streamlit tại môi trường thực thi này (thiếu thư viện `streamlit`; môi trường không truy cập được nguồn cài đặt).
- Chưa gọi Gemini thật hoặc đánh giá ảnh viết tay; chưa có tập ảnh gán nhãn và xác nhận của giáo viên.
- Chưa kiểm chứng tính đầy đủ của thuật toán đồng phân trên tập tham chiếu rộng; kiểm tra ứng viên không phải chứng minh liệt kê hết.
- Chưa đánh giá tính đúng hóa học của các phương trình AI đề xuất, tính an toàn của kịch bản thí nghiệm hoặc hiệu quả sư phạm trên học sinh.
- Chưa tách toàn bộ `app.py` (hơn 5.000 dòng); tránh tái cấu trúc lớn khi chưa có kiểm thử hồi quy UI.
- Chưa chứng minh mức bảo mật triển khai nhiều người dùng, chống lạm dụng API hoặc lưu trữ dữ liệu cá nhân; phải đánh giá riêng trước triển khai trường học.

### Thực nghiệm cần bổ sung trước khi báo cáo hội đồng

1. Bộ ảnh viết tay có đáp án đồ thị do giáo viên đối chiếu; đo exact graph match, atom/bond F1, lỗi nhận dạng vs lỗi học sinh.
2. Bộ SMILES sai/cấu trúc hợp lệ đa dạng (ion, vòng thơm, lập thể, ngoại lệ hóa trị), gán nhãn chuyên gia; đo precision/recall theo loại lỗi.
3. Bộ công thức đồng phân có phạm vi xác định, đáp án độc lập, kiểm tra tính đầy đủ, trùng lặp và timeout.
4. Cùng một tập đầu vào cho MolSnap, Gemini trực tiếp và Gemini+RDKit; so sánh có kiểm soát và ghi nhận số lần phải từ chối.
5. Kiểm thử tích hợp giao diện và API với khóa hợp lệ; ghi nhận lỗi API, thời gian phản hồi, chi phí; tuyệt đối không đưa khóa vào dữ liệu công bố.
6. Nghiên cứu lớp học có đồng thuận phù hợp, nhóm đối chứng và bài kiểm tra trước/sau, chưa được thực hiện.

### Câu hỏi phản biện trọng tâm

1. RDKit kiểm tra điều gì và không kiểm tra điều gì?
2. Nếu Gemini đọc sai nét vẽ nhưng sinh SMILES hợp lệ, MolSnap có phát hiện được không?
3. Tại sao SMILES hợp lệ không đồng nghĩa đáp án đúng?
4. Làm sao chứng minh thuật toán sinh đủ đồng phân trong phạm vi đã tuyên bố?
5. Cách phân biệt đồng phân cấu tạo, hình học và quang học?
6. Chỉ số 8/8 trong bộ kiểm thử nói lên điều gì, và không nói lên điều gì?
7. Vì sao cần đối chứng Gemini thuần và cùng Gemini có RDKit?
8. Nếu RDKit từ chối một biểu diễn hóa học đặc biệt thì xử lý thế nào?
9. Làm sao tránh AI tự sửa bài học sinh trước khi chấm?
10. Bằng chứng nào cho thấy gợi ý từng bước giúp học sinh hiểu tốt hơn?
11. Chức năng nào là đóng góp phương pháp, chức năng nào chỉ tích hợp API?
12. Có cách nào ngăn một lời giải AI sai xuất hiện với nhãn “đã kiểm chứng”?
