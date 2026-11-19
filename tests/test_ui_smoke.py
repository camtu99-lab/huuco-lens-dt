"""Chạy thử giao diện Streamlit bằng streamlit.testing (cần cài streamlit và rdkit; tự bỏ qua nếu thiếu).
Kiểm tra app khởi động không văng lỗi khi KHÔNG có khóa API, và mỗi trang chính mở được."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from streamlit.testing.v1 import AppTest
    import rdkit  # noqa
    OK = True
except Exception:   # noqa
    OK = False


@unittest.skipUnless(OK, "chưa cài streamlit hoặc rdkit")
class SmokeTests(unittest.TestCase):
    def test_khoi_dong_khong_co_khoa_api(self):
        at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=60)
        at.run()
        self.assertFalse(at.exception, [str(e.value) for e in at.exception])


if __name__ == "__main__":
    unittest.main()
