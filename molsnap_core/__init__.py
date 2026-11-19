"""MolSnap core: lõi hóa học thuần Python (không cần Streamlit, RDKit hay Gemini).

Các mô-đun:
  graph      đồ thị phân tử, kiểm tra hóa trị, dạng chuẩn để so sánh cấu trúc
  parse      đọc SMILES rút gọn, công thức thu gọn (CH3-CH2-OH) và đồ thị do AI chép từ ảnh
  diagnose   ErrorLab: phát hiện, phân loại và định vị lỗi cấu trúc
  coach      StepCoach: gợi ý ba mức dựa trên lỗi đã xác minh
  exercises  ngân hàng bài tập có đáp án đã kiểm chứng và thẻ kỹ năng
  session    máy trạng thái một lượt luyện tập (nộp, gợi ý, sửa, nộp lại)
  store      lưu hồ sơ học tập bằng SQLite (mã học sinh ẩn danh)
  adapt      hồ sơ kỹ năng và chọn bài theo quy tắc minh bạch
  evidence   chỉ số đánh giá (Accuracy, Precision, Recall, F1) và xuất CSV
  isomers    sinh đồng phân cấu tạo thuần Python để đối chiếu với số liệu chuẩn
"""
__version__ = "1.0.0"
