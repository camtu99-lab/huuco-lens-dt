"""Giao diện quy trình MolSnap-CVR trong tab Công thức cấu tạo (và dạng bài vẽ trong Luyện tập).

Luồng: Tải ảnh -> Xem cấu trúc máy đọc được -> Xác nhận hoặc chỉnh sửa -> Kiểm tra hóa học -> Gợi ý 1/2/3 -> Tự sửa -> Kiểm tra lại.

Mô-đun không import Streamlit: hàm render nhận `st` và `deps` làm tham số để kiểm thử được bằng đối tượng giả.
deps cần có:
  read_graphs(img_bytes) -> (list[dict], list[str])   các lần đọc ảnh (đồ thị JSON) và ghi chú của máy
  draw(graph, bad_atom_ids) -> ảnh hoặc None          vẽ lại đúng cấu trúc (kể cả sai), khoanh đỏ nguyên tử nghi vấn
  draw_smiles(smiles) -> ảnh hoặc None
  budget_ok() / spend(n)                              giới hạn lượt dùng AI
  save_attempt(summary)                               lưu hồ sơ (có thể là hàm rỗng)
"""
from .parse import from_condensed, ParseError
from .graph import MolGraph
from .cvr import candidates_from, attribute_source, verify_and_diagnose
from .session import PracticeSession
from .coach import hints_for, HINT_LEVELS

HINT_LABEL = {1: "Gợi ý 1: tự tìm chỗ sai", 2: "Gợi ý 2: giải thích nguyên nhân", 3: "Gợi ý 3: cách sửa"}
SOURCE_TEXT = {
    "hoc_sinh": "Các lần đọc ảnh đồng thuận.",
    "nhan_dang_ai": "Máy có thể đã đọc nhầm một nét vẽ, em hãy kiểm tra hình bên cạnh.",
    "chua_ro": "Máy chưa chắc chắn về cách đọc hình này, em hãy kiểm tra hình bên cạnh.",
    "hop_le": "Các lần đọc ảnh đồng thuận.",
}


def graph_to_dict(g):
    return {"atoms": [{"id": i, "el": a.el, "h": a.h} for i, a in g.atoms.items()],
            "bonds": [[*sorted(b), o] for b, o in g.bonds.items()]}


def dict_to_graph(d):
    from .parse import from_ai_graph
    return from_ai_graph(d)


def _rows(x):
    if hasattr(x, "to_dict"):
        return x.to_dict("records")
    return list(x or [])


def _state(st, key):
    S = st.session_state.get(key + "_s")
    if S is None:
        S = {"stage": "nhap", "img": None, "raw": [], "notes": [], "graph": None, "hints": [], "result": None, "saved": False, "n_sub": 0, "msg": ""}
        st.session_state[key + "_s"] = S
    return S


def reset(st, key):
    st.session_state.pop(key + "_s", None)


def render(st, deps, exercise=None, key="cvr", session_factory=PracticeSession):
    """Vẽ quy trình. Trả về dict {"hoan_thanh": bool, "tom_tat": dict|None} để nơi gọi biết bài đã xong chưa."""
    S = _state(st, key)
    if exercise is not None and S.get("session") is None:
        S["session"] = session_factory(exercise)
    if S["stage"] == "nhap":
        _stage_input(st, deps, S, key, exercise)
    elif S["stage"] == "xac_nhan":
        _stage_confirm(st, deps, S, key)
    else:
        return _stage_result(st, deps, S, key, exercise)
    return {"hoan_thanh": False, "tom_tat": None}


# ---------------------------------------------------------------- bước 1: nhập
def _stage_input(st, deps, S, key, exercise):
    if S["n_sub"]:
        st.info(f"Lần nộp thứ {S['n_sub'] + 1}. Em hãy sửa bài rồi nộp lại, MolSnap sẽ kiểm tra lại từ đầu.")
    if S.get("msg"):
        st.warning(S["msg"])
        S["msg"] = ""
    how = st.radio("Cách nộp bài", ["🖼️ Ảnh bài làm", "📷 Chụp ảnh", "⌨️ Gõ công thức thu gọn"], horizontal=True, key=key + "_how")
    img, text = None, ""
    if how.startswith("🖼️"):
        f = st.file_uploader("Ảnh công thức em vẽ (viết rõ nét, nền sáng, mỗi ảnh một chất)", type=["jpg", "jpeg", "png", "webp"], key=key + "_up")
        img = f.getvalue() if f else None
    elif how.startswith("📷"):
        f = st.camera_input("Chụp công thức em vẽ", key=key + "_cam")
        img = f.getvalue() if f else None
    else:
        text = st.text_input("Công thức thu gọn", placeholder="Ví dụ: CH3-CH(OH)-CH3   hoặc   CH3-COOH   hoặc   CH2=CH-CH3", key=key + "_txt").strip()
        st.caption("Viết số H ngay sau chữ cái (CH3, OH, NH2); nhánh đặt trong ngoặc; dùng - cho liên kết đơn, = cho liên kết đôi, ≡ cho liên kết ba.")
    if st.button("Đọc bài làm" if img else "Kiểm tra", type="primary", disabled=not (img or text), key=key + "_go"):
        if img:
            if not deps.budget_ok():
                st.warning("Đã hết số lượt dùng AI của phiên này.")
                return
            with st.spinner("MolSnap đang đọc hình em vẽ…"):
                try:
                    raw, notes = deps.read_graphs(img)
                except Exception:
                    st.error("Chưa đọc được ảnh (có thể mạng chậm hoặc AI đang quá tải). MolSnap không tự đoán kết quả, em thử lại hoặc gõ công thức thu gọn nhé.")
                    return
            deps.spend(max(1, len(raw)))
            S.update(stage="xac_nhan", img=img, raw=raw, notes=notes)
            st.rerun()
        else:
            try:
                g = from_condensed(text)
            except ParseError as e:
                st.warning("Công thức chưa viết đúng: " + str(e))
                return
            S.update(graph=graph_to_dict(g), img=None, stage="ket_qua", source="go_tay")
            st.rerun()


# ---------------------------------------------------------------- bước 2: xem và xác nhận
def _stage_confirm(st, deps, S, key):
    cands, warns, fails = candidates_from(S["raw"])
    att = attribute_source(cands, confirmed=False)
    g = att["graph"]
    st.markdown("#### MolSnap đọc được hình em vẽ như sau")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Ảnh gốc của em**")
        st.image(S["img"])
    with c2:
        st.markdown("**Cấu trúc máy dựng lại**" + (" (nguyên tử nghi vấn khoanh đỏ)" if g is not None and g.valence_issues() else ""))
        im = deps.draw(g, [v["id"] for v in g.valence_issues()]) if g is not None else None
        if im is not None:
            st.image(im)
        elif g is not None:
            st.code(g.hill())
        else:
            st.warning("Máy không dựng lại được cấu trúc nào từ ảnh này.")
    if g is None:
        if st.button("Chụp hoặc tải ảnh khác", key=key + "_again0"):
            S.update(stage="nhap")
            st.rerun()
        return
    st.caption(f"Công thức phân tử máy đọc được: {g.hill()} · số lần đọc ảnh: {att['k']}" + (f" · có {fails} lần đọc thất bại" if fails else ""))
    st.info(SOURCE_TEXT.get(att["nguon"], "") + (" " + att["ly_do"] if att["ly_do"] and att["nguon"] in ("chua_ro", "nhan_dang_ai") else ""))
    for n in S["notes"]:
        if n:
            st.caption("Ghi chú của máy khi đọc ảnh: " + n)
    for w in warns:
        st.caption("Lưu ý: " + w)
    st.markdown("**Hình bên cạnh có đúng như em đã vẽ không?** MolSnap chỉ chấm bài sau khi em xác nhận, vì nếu máy đọc nhầm thì kết quả sẽ không công bằng.")
    with st.expander("✏️ Máy đọc chưa đúng? Em tự chỉnh lại cấu trúc"):
        gd = graph_to_dict(g)
        atoms = [{"Mã": a["id"], "Nguyên tố": a["el"], "Số H": a["h"] if a["h"] is not None else 0} for a in gd["atoms"]]
        bonds = [{"Từ nguyên tử": b[0], "Đến nguyên tử": b[1], "Bậc": b[2]} for b in gd["bonds"]]
        st.caption("Số H là số nguyên tử H gắn trực tiếp vào nguyên tử đó. Bậc liên kết: 1 đơn, 2 đôi, 3 ba.")
        ea = st.data_editor(atoms, num_rows="dynamic", key=key + "_ea")
        eb = st.data_editor(bonds, num_rows="dynamic", key=key + "_eb")
        txt = st.text_input("Hoặc nhập lại bằng công thức thu gọn (ví dụ CH3-CH(OH)-CH3)", key=key + "_retype").strip()
        if st.button("Dùng cấu trúc em vừa chỉnh để kiểm tra", key=key + "_edit_go"):
            try:
                if txt:
                    newg = graph_to_dict(from_condensed(txt))
                else:
                    ra, rb = _rows(ea), _rows(eb)
                    newg = {"atoms": [{"id": int(r["Mã"]), "el": str(r["Nguyên tố"]), "h": int(r["Số H"] or 0)} for r in ra if r.get("Nguyên tố")],
                            "bonds": [[int(r["Từ nguyên tử"]), int(r["Đến nguyên tử"]), int(r["Bậc"])] for r in rb if r.get("Bậc")]}
                    dict_to_graph(newg)
            except Exception as e:
                st.warning("Cấu trúc em chỉnh chưa hợp lệ: " + str(e))
                return
            S.update(graph=newg, stage="ket_qua", source="da_chinh")
            st.rerun()
    a, b = st.columns(2)
    if a.button("✅ Đúng như em vẽ, kiểm tra bài", type="primary", key=key + "_ok"):
        S.update(graph=graph_to_dict(g), stage="ket_qua", source="anh_da_xac_nhan")
        st.rerun()
    if b.button("🔄 Đọc lại ảnh khác", key=key + "_again"):
        S.update(stage="nhap")
        st.rerun()


# ---------------------------------------------------------------- bước 3: kết quả, gợi ý, sửa
def _stage_result(st, deps, S, key, exercise):
    from .parse import from_ai_graph
    g, _ = from_ai_graph(S["graph"])
    sess = S.get("session")
    if S.get("result_for") != S["n_sub"] or S["result"] is None:   # chấm đúng một lần cho mỗi lần nộp
        if sess is not None:
            res = sess.submit(g, source=S.get("source", ""), confirmed=True)
        else:
            res = verify_and_diagnose([g], None, confirmed=True)
        S["result"], S["result_for"] = res, S["n_sub"]
        S["hints"] = []
    res = S["result"]
    bad = sorted({x for e in res["loi"] for x in e["atoms"]}) if res["trang_thai"] == "sai" else []
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Hình em vẽ (máy dựng lại đúng như em xác nhận)**" + (" · chỗ cần xem lại khoanh đỏ" if bad else ""))
        im = deps.draw(g, bad)
        if im is not None:
            st.image(im)
        else:
            st.code(g.hill())
    with c2:
        _verdict(st, res, exercise)
    done = res["trang_thai"] in ("dung", "hop_le") or (sess is not None and sess.finished is not None)
    if sess is not None and sess.finished is not None and not S["saved"]:
        deps.save_attempt(sess.summary())
        S["saved"] = True
    if done:
        if res["trang_thai"] == "dung" and sess is not None:
            sm = sess.summary()
            how = {"tu_sua_dung": "em tự làm đúng, không cần gợi ý", "sua_dung_sau_goi_y": f"em sửa đúng sau {sm['hints']} gợi ý"}.get(sm["result"], "")
            st.success("Đã kiểm tra lại: đúng! " + (how.capitalize() + "." if how else ""))
        return {"hoan_thanh": True, "tom_tat": sess.summary() if sess is not None else None}
    err = (sess.current_error() if sess is not None else _primary(res))
    if res["trang_thai"] == "khong_du_thong_tin":
        st.info("MolSnap chưa đủ căn cứ để chấm, nên chưa đưa gợi ý. Em hãy nộp lại bằng ảnh rõ hơn hoặc gõ công thức thu gọn.")
    for h in S["hints"]:
        st.info(f"💡 **{HINT_LABEL[h['muc']]}**\n\n{h['noi_dung']}")
    if err is not None:
        used = len(S["hints"])
        if used < HINT_LEVELS:
            if st.button("💡 " + HINT_LABEL[used + 1], key=f"{key}_hint{S['n_sub']}_{used}"):
                h = _next_hint(sess, err, exercise, S)
                if h:
                    S["hints"].append(h)
                st.rerun()
        else:
            st.caption("Em đã xem hết 3 gợi ý cho lỗi này.")
    a, b = st.columns(2)
    if a.button("✏️ Em sửa lại và nộp lại", type="primary", key=f"{key}_resub{S['n_sub']}"):
        S.update(stage="nhap", n_sub=S["n_sub"] + 1, result=None, graph=None)
        st.rerun()
    if sess is not None:
        if sess.can_reveal():
            if b.button("👀 Xem đáp án", key=f"{key}_reveal"):
                info = sess.reveal()
                S["revealed"] = info
                st.rerun()
        else:
            b.caption("Em cần dùng hết 3 gợi ý hoặc thử sửa ít nhất 3 lần mới xem được đáp án.")
    if S.get("revealed"):
        info = S["revealed"]
        st.markdown(f"**Đáp án:** {info['ten']} · công thức phân tử {info['ct_phan_tu']}")
        im = deps.draw_smiles(info["smiles"])
        if im is not None:
            st.image(im)
        return {"hoan_thanh": True, "tom_tat": sess.summary()}
    return {"hoan_thanh": False, "tom_tat": None}


def _primary(res):
    return next((e for e in res["loi"] if e["ma"] == res["loi_chinh"]), None) if res["trang_thai"] == "sai" else None


def _next_hint(sess, err, exercise, S):
    if sess is not None:
        return sess.next_hint()
    hs = hints_for(err, "")
    n = len(S["hints"])
    if hs is None or n >= HINT_LEVELS:
        return None
    return {"muc": n + 1, "ma": err["ma"], "noi_dung": hs[n], "con_lai": HINT_LEVELS - n - 1}


def _verdict(st, res, exercise):
    t = res["trang_thai"]
    if t == "dung":
        st.success("**Đúng rồi!** Cấu trúc em vẽ trùng với chất đề bài yêu cầu.")
    elif t == "hop_le":
        st.success("**Cấu trúc hợp lệ về hóa trị.** Vì không có đề bài để so sánh nên MolSnap chưa biết đây có phải chất em cần viết hay không.")
    elif t == "khong_du_thong_tin":
        st.warning("**Chưa đủ căn cứ để kết luận.** " + res["loi"][0]["nguyen_nhan"])
    else:
        e = _primary(res)
        st.error("**" + e["ten"] + "**")
        st.markdown(e["nguyen_nhan"])
        if res.get("ghi_chu"):
            st.caption(res["ghi_chu"])
        others = [x["ten"] for x in res["loi"] if x["ma"] != e["ma"]]
        if others:
            st.caption("Ngoài ra MolSnap còn thấy: " + "; ".join(others) + ". Em sửa lỗi này trước, MolSnap sẽ kiểm tra lại tất cả.")
        with st.expander("Quy tắc hóa học dùng để phát hiện lỗi này"):
            st.markdown(e["quy_tac"])
            st.caption("Trạng thái: " + ("đã kiểm chứng bằng thuật toán trên cấu trúc em đã xác nhận." if e["da_kiem_chung"] else "chưa xác nhận hình đọc được."))
