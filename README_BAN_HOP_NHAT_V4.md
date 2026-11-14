# MolSnap V4 — bản hợp nhất tập trung tính mới có thể chứng minh

## Nội dung mới

1. **Cầu nối ảnh → sửa lỗi**: Trong `Công thức cấu tạo`, sau khi nhận dạng bằng Gemini, nút **Chuyển kết quả nhận dạng sang phòng tự sửa** chuyển SMILES sang `Kiểm chứng & sửa lỗi`. Không gọi lại Gemini khi chỉ kiểm chứng. Ứng dụng cảnh báo rõ SMILES do AI suy ra có thể khác ảnh gốc.
2. **Phòng thực hành**: RDKit kiểm tra cú pháp, hóa trị trong phạm vi hỗ trợ, đối chiếu với cấu trúc tham chiếu, tô sáng nguyên tử nghi vấn trên hình **dựng từ SMILES**, không giả làm ảnh gốc; lưu nhật ký phiên và cho phép thử lại.
3. **Thử thách có chấm bài**: năm bài mẫu do người biên soạn, kiểm chứng cấu tạo bằng RDKit, gợi ý ba mức, không cần Gemini. Bài chỉ chấm cấu tạo, không chấm đồng phân lập thể.
4. **Minh chứng khoa học**: tab mới chạy 11 ca tham chiếu ngay trong ứng dụng, hiển thị ca đạt/chưa đạt, thời gian xử lý, phiên bản RDKit, xuất JSON.
5. **Các chức năng cũ**: giữ nguyên `Công thức cấu tạo`, `Phương trình phản ứng`, `Đồng phân`, `Dụng cụ hóa học`, `Sơ đồ tư duy`, `Trợ lý AI` và các chức năng tham khảo.

## Cập nhật Streamlit Cloud — làm một lần

1. Sao lưu GitHub repository hiện tại.
2. Giải nén ZIP, **sao chép toàn bộ nội dung bên trong thư mục `streamlit_gemini/`** vào **thư mục đang chứa `app.py` trên GitHub**, giữ đúng đường dẫn các thư mục con. Không đặt nguyên thư mục `streamlit_gemini` lồng thêm một cấp nếu Cloud đang chạy `app.py` ở gốc repository.
3. Commit và để Streamlit Cloud triển khai lại. Kiểm tra menu có **Minh chứng khoa học** và **Kiểm chứng & sửa lỗi**.
4. Trong Streamlit Secrets, nhập `GEMINI_API_KEY = "..."` với khóa **mới**, không tải tệp secrets chứa khóa lên GitHub. Nếu khóa cũ từng xuất hiện trong ảnh chụp, phải thu hồi.
5. Thử theo kịch bản dưới đây. Nếu ứng dụng báo lỗi, xem **Manage app → Logs**, không chụp Secrets.

## Cài đặt cục bộ

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

Tự động kiểm thử:

```bash
python -m pip install pytest
python -m pytest -q
python research_suite.py --output results/research_suite_latest.json
```

## Kịch bản trình diễn hội đồng (5–7 phút)

1. **Ảnh viết tay**: Vào Công thức cấu tạo → tải ảnh → Phân tích → xem kết quả AI → bấm **Chuyển kết quả nhận dạng sang phòng tự sửa**. Bước này cần API Gemini và ảnh rõ; **không đảm bảo** Gemini nhận dạng đúng mọi ảnh.
2. **Lỗi hóa trị**: Trong Kiểm chứng & sửa lỗi → SMILES tự do, nhập `CC(=O)(O)O`, để trống tham chiếu → Kiểm chứng → xem nguyên tử nghi vấn và gợi ý. Hình tô sáng được dựng từ SMILES.
3. **Cấu trúc hợp lệ nhưng sai yêu cầu**: Nhập `COC`, tham chiếu `CCO` → phát hiện khác cấu tạo dù cùng công thức phân tử.
4. **Cách viết tương đương**: Nhập `OCC`, tham chiếu `CCO` → cùng cấu tạo.
5. **Học sinh tự sửa**: Mở Thử thách có chấm bài, thử sai, mở dần 3 mức gợi ý, sửa lại và xuất nhật ký phiên.
6. **Chứng minh bằng dữ liệu**: Mở Minh chứng khoa học → chạy bộ ca → xem từng ca và tải JSON. Không gọi đó là độ chính xác AI nhận dạng ảnh.

## Đã kiểm tra và chưa kiểm tra

- **Đã chạy trong môi trường phát triển**: `pytest` 25/25 bài đạt, bộ tham chiếu 11/11 ca đạt; kiểm tra cú pháp Python và kiểm tra tĩnh liên kết các tab.
- **Chưa thể xác nhận ở môi trường phát triển này**: khởi chạy Streamlit end-to-end vì môi trường không cài `streamlit`; Gemini API thật, kết quả ảnh viết tay, triển khai Cloud và tương thích từng phiên bản giao diện.
- **Chưa chứng minh**: độ chính xác trên ảnh thực, tính đầy đủ của thuật toán sinh đồng phân, hiệu quả giáo dục so với cách dạy khác, tính mới khoa học chưa từng có.

## Các giới hạn hóa học cần trình bày đúng

RDKit kiểm tra biểu diễn cấu trúc và quy tắc hóa trị trong phạm vi thư viện; không chứng minh chất có thể tổng hợp, phản ứng xảy ra, hoặc AI đã chép ảnh đúng. Khi so sánh SMILES, cùng cấu tạo không đồng nghĩa cùng cấu hình lập thể. Bộ ca minh chứng nhỏ, được biên soạn trước, không phải tập kiểm thử độc lập đại diện học sinh.

## Cấu trúc chính

- `app.py`: giao diện gốc, kết nối điều hướng và nút chuyển kết quả nhận dạng.
- `chem_verification.py`: kiểm chứng hóa học.
- `learning_lab.py`, `learning_ui.py`: chẩn đoán và phòng thực hành.
- `challenge_engine.py`, `challenge_ui.py`: thử thách, gợi ý và nhật ký.
- `research_suite.py`, `research_ui.py`: thực thi và báo cáo kiểm thử.
- `tests/`: kiểm thử tự động.
