# MolSnap V2.1 – Sửa lỗi hiển thị SVG

## Vấn đề
Ở V2, khi nhập `CC(=O)(O)O`, RDKit phát hiện lỗi hóa trị nhưng `learning_ui.py` gọi `st.image(svg_bytes)`, khiến Pillow ném `PIL.UnidentifiedImageError` vì SVG không phải ảnh raster được Pillow đọc trực tiếp.

## Đã sửa
`learning_ui.py` chuyển SVG do RDKit dựng sang base64 và hiển thị bằng thẻ `<img>` trong Streamlit Markdown; không gọi Pillow để giải mã SVG. Có chú thích phân biệt hình RDKit với ảnh đầu vào.

## Cập nhật trên GitHub
**Cách nhanh nhất:** chỉ thay tệp `learning_ui.py` ở thư mục gốc đang chứa `app.py` bằng bản trong ZIP, commit và chờ Streamlit Cloud cập nhật. Không cần thay đổi API key. Nếu muốn cài toàn bộ bản, sao chép các tệp từ `streamlit_gemini/` vào đúng thư mục chứa `app.py`.

## Kiểm thử
Chạy `python -m pytest -q` từ thư mục chứa `app.py`. Chạy `streamlit run app.py` để kiểm thử giao diện. Trường hợp `CC(=O)(O)O` cần cảnh báo hóa trị và hiển thị hình tô sáng, không còn lỗi Pillow. Kiểm thử tự động không thay thế kiểm thử giao diện trên Streamlit Cloud.

## Các mục khác
Trang chủ, Công thức cấu tạo, Phương trình phản ứng, Đồng phân, Dụng cụ hóa học, Sơ đồ tư duy và Trợ lý AI vẫn là các chức năng trước đó. Bản V2.1 này chỉ sửa lỗi hiển thị ở tab Kiểm chứng & sửa lỗi, không chứng minh mọi mục cũ hoạt động hoàn hảo.
