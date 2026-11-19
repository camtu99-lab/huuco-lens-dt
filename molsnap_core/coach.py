"""StepCoach: gợi ý ba mức dựa trên lỗi đã được ErrorLab xác minh.

Mức 1: câu hỏi giúp học sinh tự tìm vị trí hoặc loại lỗi.
Mức 2: nêu quy tắc hóa học liên quan và nguyên nhân.
Mức 3: chỉ dẫn cách sửa. Đáp án đầy đủ không nằm trong ba mức này.
Mỗi loại lỗi có nội dung riêng; không dùng một lời giải chung cho mọi lỗi.
"""
HINT_LEVELS = 3
_EL = {"C": "cacbon", "H": "hiđro", "O": "oxi", "N": "nitơ", "Cl": "clo", "Br": "brom", "F": "flo", "I": "iot", "S": "lưu huỳnh", "P": "photpho"}
_NH = {"ancol": "ancol (–OH)", "phenol": "phenol", "ete": "ete (–O–)", "axit cacboxylic": "axit (–COOH)", "este": "este (–COO–)",
       "anđehit": "anđehit (–CHO)", "xeton": "xeton (C=O)", "amin": "amin", "amit": "amit", "nitro": "nitro (–NO₂)",
       "dẫn xuất halogen": "nguyên tử halogen", "anken (C=C)": "liên kết đôi C=C", "ankin (C≡C)": "liên kết ba C≡C"}


def _nh(n):
    return _NH.get(n, n)


def _sub_el(el):
    return _EL.get(el, el)


def hints_for(error, ten_chat=""):
    """Trả về danh sách đúng 3 chuỗi (mức 1, 2, 3) cho một lỗi (dict từ ErrorLab); None nếu lỗi này không có gợi ý."""
    code, d = error["ma"], error.get("chi_tiet") or {}
    if code == "sai_hoa_tri":
        el, actual = d.get("nguyen_to", "?"), d.get("thuc_te", "?")
        want = (d.get("cho_phep") or ["?"])[0]
        over = d.get("loai") == "thua"
        diff = abs(actual - want) if isinstance(actual, int) and isinstance(want, int) else "?"
        return [
            f"Hãy tìm nguyên tử {el} được tô đỏ trên hình. Em đếm xem có tất cả bao nhiêu nét nối vào nó (kể cả nét nối tới H, và liên kết đôi tính là 2 nét)?",
            f"Nguyên tử {el} ({_sub_el(el)}) luôn có hóa trị {want}, nghĩa là tổng số nét nối quanh nó phải bằng {want}. "
            f"Trên hình em vẽ, tổng này đang là {actual}, tức là {'vượt quá' if over else 'chưa đủ'}.",
            (f"Hãy bớt {diff} nét nối quanh nguyên tử {el}: bỏ bớt {diff} nguyên tử H, hoặc đổi liên kết bội thành liên kết đơn, sao cho tổng còn {want}."
             if over else
             f"Hãy thêm {diff} nét nối cho nguyên tử {el}: gắn thêm {diff} nguyên tử H, hoặc nâng liên kết đơn thành liên kết bội, sao cho tổng đủ {want}."),
        ]
    if code == "thieu_thua_nguyen_tu":
        ch = d.get("chenh_lech") or {}
        items = [(k, v) for k, v in ch.items() if v]
        k, v = items[0] if items else ("?", 0)
        return [
            "Hãy đếm số nguyên tử từng loại trong hình em vẽ (C, O, N, Cl...) rồi đối chiếu với tên chất: tên chất cho biết có bao nhiêu nguyên tử C và những nhóm chức nào.",
            f"Hình em vẽ đang {'thừa' if v > 0 else 'thiếu'} {abs(v)} nguyên tử {k} ({_sub_el(k)}) so với chất cần viết.",
            f"Hãy {'bớt' if v > 0 else 'thêm'} {abs(v)} nguyên tử {k}, rồi điều chỉnh số H ở các nguyên tử xung quanh cho đủ hóa trị.",
        ]
    if code == "sai_bac_lien_ket":
        kb = d.get("khac_bac") or [{}]
        f = kb[0]
        return [
            "Các nguyên tử đã sắp xếp đúng khung. Hãy xem lại các liên kết được tô đỏ: tên chất cho biết liên kết nào là đơn, đôi hay ba?",
            "Đuôi tên chất cho biết bậc liên kết: -an chỉ có liên kết đơn, -en có một liên kết đôi C=C, -in có một liên kết ba C≡C. "
            f"Liên kết em đang vẽ là liên kết {f.get('tu', '?')}.",
            f"Hãy đổi liên kết đó thành liên kết {f.get('thanh', '?')}, rồi cập nhật số H ở hai nguyên tử hai đầu cho đủ hóa trị.",
        ]
    if code == "sai_cong_thuc":
        a, b = d.get("h_hoc_sinh"), d.get("h_dap_an")
        diff = (a - b) if isinstance(a, int) and isinstance(b, int) else 0
        return [
            "Số nguyên tử C và các nguyên tử khác đã đúng. Em hãy đếm lại tổng số nguyên tử H trong hình mình vẽ.",
            f"Hình em vẽ có {a} nguyên tử H, còn chất cần viết có {b} nguyên tử H.",
            ("Số H thừa 2 thường do thiếu một liên kết bội hoặc một vòng; hãy kiểm tra lại liên kết giữa các nguyên tử C."
             if diff == 2 * (abs(diff) // 2) and diff > 0 else
             "Số H thiếu thường do vẽ thừa liên kết bội hoặc vòng; hãy kiểm tra lại liên kết giữa các nguyên tử C." if diff < 0 else
             "Hãy bổ sung hoặc bớt H ở các nguyên tử C cho đủ hóa trị 4.")]
    if code == "sai_mach_cacbon":
        ms, md, nb = d.get("mach_hoc_sinh"), d.get("mach_dung"), d.get("nhanh_dung")
        return [
            "Hãy nhìn riêng các nguyên tử C: chúng nối với nhau thành một mạch thẳng hay có nhánh? Mạch chính dài nhất có mấy nguyên tử C?",
            f"Mạch chính trong hình em vẽ dài {ms} nguyên tử C. Hãy đối chiếu với tên chất: tiền tố như 'metyl', 'iso' báo có nhánh, còn tên không có tiền tố thì mạch thẳng.",
            f"Hãy sắp xếp lại các nguyên tử C để mạch chính dài {md} nguyên tử C" + (" và không có nhánh" if nb == 0 else f" và có {nb} nhánh")
            + ", rồi gắn nhóm chức vào đúng cacbon.",
        ]
    if code == "nham_dong_phan":
        s, t = d.get("chi_hoc_sinh") or [], d.get("chi_dap_an") or []
        ns = ", ".join(_nh(x) for x in s) or "không có nhóm chức đặc trưng"
        nt = ", ".join(_nh(x) for x in t) or "không có nhóm chức đặc trưng"
        return [
            "Công thức phân tử của em đúng. Hãy xem lại tên chất: phần đuôi (-ol, -al, -on, oic, -oat, -amin...) cho biết nhóm chức nào?",
            f"Chất em vẽ thuộc loại có {ns}, còn tên chất yêu cầu {nt}. Cùng công thức phân tử nhưng khác nhóm chức thì là hai chất khác nhau.",
            f"Hãy thay phần {ns} bằng {nt}, giữ nguyên số nguyên tử C và O, rồi điều chỉnh số H cho đủ hóa trị.",
        ]
    if code == "sai_vi_tri_nhom_chuc":
        ls, lt = d.get("vi_tri_hoc_sinh"), d.get("vi_tri_dung")
        nhom = (d.get("nhom") or ["nhóm chức"])[0]
        step3 = "Hãy chuyển nhóm chức hoặc liên kết bội được tô đỏ sang đúng cacbon theo con số trong tên chất, rồi điều chỉnh số H của hai cacbon cho đủ hóa trị."
        if ls and lt:
            pairs = [(a, b) for a, b in zip(ls, lt) if a[1] != b[1] and a[0] == b[0]]
            if pairs:
                a, b = pairs[0]
                step3 = (f"Hãy chuyển {_nh(a[0])} từ cacbon số {a[1]} sang cacbon số {b[1]} "
                         "(đánh số cacbon từ đầu mạch gần nhóm chức hơn), rồi điều chỉnh số H của hai cacbon đó cho đủ hóa trị.")
        return [
            f"Mạch cacbon và loại nhóm chức em vẽ đều đúng. Hãy xem {_nh(nhom)} (tô đỏ) đang gắn vào cacbon số mấy, khi đánh số từ đầu mạch gần nhóm đó hơn?",
            "Trong tên chất, con số đứng trước tên nhóm (ví dụ -2-ol, but-2-en) cho biết nhóm chức hoặc liên kết bội ở cacbon số mấy. "
            + (f"Hãy đối chiếu với tên: {ten_chat}." if ten_chat else "Hãy đối chiếu với tên chất của đề."),
            step3,
        ]
    if code == "sai_yeu_cau_de":
        return [
            "Cấu trúc em vẽ là một chất hợp lệ. Hãy đọc lại tên chất của đề và xác định từng thành phần: mạch chính, nhóm chức, vị trí nhóm chức.",
            "Có ít nhất một thành phần trong ba thành phần đó khác với hình em vẽ. Hãy lần lượt đối chiếu từng thành phần.",
            "Hãy vẽ lại từng bước: mạch cacbon chính, rồi nhóm chức, rồi điền H cho đủ hóa trị.",
        ]
    return None   # khong_du_thong_tin: chưa có lỗi nào được xác minh nên không đưa gợi ý
