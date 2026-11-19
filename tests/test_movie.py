"""Kiểm thử phim mô phỏng trong trình duyệt thật (cần playwright và Chromium; tự bỏ qua nếu chưa cài)."""
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _appload import load

try:
    from playwright.sync_api import sync_playwright
except Exception:   # noqa
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "chưa cài playwright")
class MovieTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ns = load("SIM_TEMPLATE", "SIM_BUILTINS")
        cls.tpl, cls.B = ns["SIM_TEMPLATE"], ns["SIM_BUILTINS"]
        cls.pw = sync_playwright().start()
        try:
            cls.br = cls.pw.chromium.launch()
        except Exception as e:
            cls.pw.stop()
            raise unittest.SkipTest("chưa cài Chromium: " + str(e)[:60])

    @classmethod
    def tearDownClass(cls):
        cls.br.close()
        cls.pw.stop()

    def page(self, key):
        data = {k: v for k, v in self.B[key].items() if k != "kw"}
        html = self.tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
        pg = self.br.new_page(viewport={"width": 1000, "height": 760})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.set_content(html)
        pg.wait_for_timeout(300)
        return pg, errs

    def test_moi_thi_nghiem_co_san_chay_khong_loi(self):
        for key in self.B:
            pg, errs = self.page(key)
            total = pg.evaluate("window.__total")
            self.assertGreater(total, 10, key)
            for frac in (0.02, 0.25, 0.5, 0.75, 0.97):
                pg.evaluate(f"window.__seek({total * frac})")
            self.assertEqual(errs, [], key)
            pg.close()

    def test_khung_hinh_khong_trong_va_co_giao_hien_dien(self):
        pg, errs = self.page("zn_hcl")
        pg.evaluate("window.__seek(20)")
        def diff_pixels():
            return pg.evaluate("""() => { const c = document.getElementById('cv'), g = c.getContext('2d'); return Array.from(g.getImageData(0, 0, c.width, c.height).data); }""")
        with_t = diff_pixels()
        pg.click("#bTeach")                # tắt cô giáo
        without = diff_pixels()
        n = sum(1 for a, b in zip(with_t, without) if a != b)
        self.assertGreater(n, 5000)        # bật/tắt cô giáo làm khung hình đổi đáng kể
        self.assertGreater(len(set(with_t[::97])), 20)   # khung hình không phải một màu phẳng
        self.assertEqual(errs, [])
        pg.close()

    def test_thoi_gian_hop_ly_giua_cac_buoc(self):
        pg, errs = self.page("kmno4")
        steps = pg.evaluate("window.__steps.map(s => [s.t0, s.t1])")
        for (a0, a1), (b0, b1) in zip(steps, steps[1:]):
            self.assertAlmostEqual(a1, b0, places=3)
            self.assertGreater(a1, a0)
        self.assertGreaterEqual(steps[0][0], 1.0 - 1e-6)    # 1 giây dẫn nhập cho cô giáo bước vào
        pg.close()


if __name__ == "__main__":
    unittest.main()
