# MolSnap V2 – Phòng thực hành kiểm chứng và tự sửa cấu trúc

## Thay đổi trực tiếp trên mã nguồn cũ
- Giữ nguyên các mục Công thức cấu tạo, Phương trình phản ứng, Đồng phân, Dụng cụ hóa học, Sơ đồ tư duy và Trợ lý AI.
- Thêm mục **Kiểm chứng & sửa lỗi** ở đầu menu và nút truy cập trên trang chủ.
- Thêm `learning_lab.py`: kiểm chứng SMILES, phân loại sai khác với đáp án tham chiếu, 3 gợi ý sửa theo mức, hình tô sáng nguyên tử nghi vấn (nếu RDKit dựng được).
- Thêm `learning_ui.py`: biểu mẫu thực hành, nút xem gợi ý, sửa và kiểm tra lại, bảng nhật ký trong phiên và tải JSON.
- Tận dụng `chem_verification.py` từ bản nâng cấp trước, không cần Gemini API để kiểm chứng SMILES.
- Thêm 8 kiểm thử mới trong `tests/test_learning_lab.py`.

## Cài đặt và chạy
```bash
python -m pip install -r requirements.txt
streamlit run app.py
```
Chạy kiểm thử:
```bash
python -m pip install pytest
python -m pytest -q
python evaluation.py --output results/latest.json
```

## Kiểm thử trong môi trường biên tập 2026-11-14
- `python -m pytest -q`: **15 passed** (7 bài cũ, 8 bài mới).
- `python evaluation.py --output results/v2_reference.json`: **8/8** ca tham chiếu.
- `python -m compileall -q app.py learning_ui.py learning_lab.py`: đạt.
- **Chưa kiểm thử chạy giao diện Streamlit thật**: môi trường kiểm thử không có gói `streamlit`; chưa có API key để kiểm thử Gemini.
- Các số liệu này không đại diện cho độ chính xác trên ảnh viết tay hay tác động giáo dục.

## Thử chức năng mới
1. Chọn **Kiểm chứng & sửa lỗi** trên menu.
2. Nhập `CC(=O)(O)O`, nhấn **Kiểm chứng**: dự kiến cảnh báo hóa trị carbon, 3 mức gợi ý; kiểm tra trực tiếp trên máy triển khai.
3. Nhập `CCO`, để trống đáp án: kết quả chỉ là hợp lệ về cấu trúc, **không chấm đúng bài**.
4. Nhập `OCC`, đáp án `CCO`: đối chiếu cùng cấu trúc.
5. Nhập `COC`, đáp án `CCO`: cùng công thức C2H6O nhưng khác cấu tạo.
6. Sửa lại SMILES, kiểm tra lại, tải nhật ký JSON.

## Triển khai lên Streamlit Cloud
Đưa **nội dung** thư mục `streamlit_gemini/` vào đúng thư mục mà Streamlit Cloud đang chạy `app.py` (hoặc cập nhật đường dẫn entrypoint), commit lên nhánh GitHub đã cấu hình. Trong trang quản lý ứng dụng, chọn reboot/redeploy nếu cần. Sau đó kiểm tra menu có mục **Kiểm chứng & sửa lỗi**. Nếu không thấy, website vẫn chạy mã cũ hoặc sai nhánh/thư mục.

Với các tính năng Gemini, cấu hình `GEMINI_API_KEY` trong Streamlit Secrets, không đưa khóa vào GitHub. Nếu khóa đã lộ qua ảnh, phải thu hồi và tạo khóa mới.

## Giới hạn nghiên cứu
- Chỉ kiểm tra cấu trúc biểu diễn bởi SMILES; không suy ra rằng hình vẽ gốc của học sinh sai.
- RDKit không xác nhận tên, điều kiện phản ứng, tính khả thi tổng hợp hoặc đáp án đúng khi không có đề bài.
- Việc so sánh lập thể dựa trên biểu diễn SMILES và không thay thế đánh giá hóa học chuyên sâu.
- Các gợi ý được xây dựng theo quy tắc và không tự động sửa thành đáp án; học sinh tự thử lại.
- Nhật ký chỉ giữ trong session Streamlit, không phải cơ sở dữ liệu lớp học.
- Chưa có nghiên cứu thực nghiệm trên học sinh, chưa có kiểm thử nhận dạng ảnh đầu-cuối.
