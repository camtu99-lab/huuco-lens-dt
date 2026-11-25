import base64
import copy
import csv
import hashlib
import hmac
import html
import io
import json
import math
import random
import re
import threading
import time
import unicodedata
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import errors, types
from PIL import Image
from collections import Counter

from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, Draw, rdMolDescriptors
from rdkit.Chem.EnumerateStereoisomers import EnumerateStereoisomers, StereoEnumerationOptions

import classroom as cr
import history_store as hs
import i18n
from i18n import tx

RDLogger.DisableLog("rdApp.*")

MODEL = st.secrets.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_PER_SESSION = int(st.secrets.get("MAX_PER_SESSION", 15))
MAX_PER_DAY = int(st.secrets.get("MAX_PER_DAY", 0) or 0)   # 0 = không giới hạn; tính theo từng học sinh có tên
BENCH_MAX = int(st.secrets.get("BENCH_MAX", 30))

APP_NAME = st.secrets.get("APP_NAME", "MolSnap")
APP_ICON = st.secrets.get("APP_ICON", "🧪")

st.set_page_config(page_title=APP_NAME, page_icon=APP_ICON, layout="wide", initial_sidebar_state="auto")

# Kiểm tra đủ file cùng một phiên bản (hay quên chép lại history_store.py / classroom.py / i18n.py khi cập nhật).
_OLD = [n for n, ok in (("classroom.py", all(hasattr(cr, x) for x in ("make_auth", "is_student", "register", "profile", "read_history"))),
                        ("history_store.py", hasattr(hs, "tbl_read")), ("i18n.py", hasattr(i18n, "install"))) if not ok]
if _OLD:
    st.error("Các file của app chưa cùng phiên bản. File còn là bản cũ: " + ", ".join(_OLD) + ". Hãy chép LẠI TẤT CẢ file trong bản zip mới "
             "(app.py, classroom.py, history_store.py, i18n.py) lên cùng thư mục rồi khởi động lại app.")
    st.stop()

# Ngôn ngữ (vi / bi / en) được nhớ trong địa chỉ trang (?lang=bi) để tải lại vẫn còn.
try:
    _q_lang = st.query_params.get("lang")
except Exception:
    _q_lang = None
if "lang" not in st.session_state:
    st.session_state["lang"] = _q_lang if _q_lang in i18n.LANGS else "vi"
i18n.install()

# Lưu bền bằng Google Sheets nếu secrets có HISTORY_SHEET_ID và [gcp_service_account]; không thì dùng tệp cục bộ.
try:
    _sa = None
    if st.secrets.get("GCP_SERVICE_ACCOUNT_JSON"):      # cách dễ nhất: dán nguyên nội dung file .json vào một chuỗi
        import json as _json
        _sa = _json.loads(st.secrets["GCP_SERVICE_ACCOUNT_JSON"])
    elif "gcp_service_account" in st.secrets:            # hoặc từng trường theo bảng TOML
        _sa = dict(st.secrets["gcp_service_account"])
    if _sa and st.secrets.get("HISTORY_SHEET_ID"):
        if isinstance(_sa.get("private_key"), str):      # phòng khi dấu xuống dòng bị dán thành \\n chữ
            _sa["private_key"] = _sa["private_key"].replace("\\n", "\n")
        hs.configure_sheets(st.secrets["HISTORY_SHEET_ID"], _sa)
except Exception as _e:
    hs.last_error = f"{type(_e).__name__}: {str(_e)[:200]}"

# Danh tính duy nhất của phiên: st.session_state["auth"] = None (khách) hoặc dict từ cr.make_auth (học sinh / giáo viên).
# Học sinh giữ đăng nhập khi tải lại trang bằng mã ký (?tk=...), không chứa PIN; giáo viên luôn nhập lại mã sau khi tải lại trang.
_SECRET = str(st.secrets.get("APP_SECRET", "") or st.secrets.get("TEACHER_CODE", "") or st.secrets.get("GEMINI_API_KEY", ""))
_TEACHER_CODE = str(st.secrets.get("TEACHER_CODE", "") or "")
st.session_state.setdefault("auth", None)
if st.session_state["auth"] is None and not st.session_state.get("_tk_tried"):
    st.session_state["_tk_tried"] = True
    try:
        _tk = st.query_params.get("tk")
        _v = cr.verify_token(_SECRET, _tk) if _tk else None
    except Exception:
        _v = None
    if _v:
        st.session_state["auth"] = cr.make_auth(cr.STUDENT, _v[0], _v[1])

RULES = """Bạn là giáo viên Hóa hữu cơ Việt Nam kiêm chuyên gia nhận dạng công thức. Quy ước trong SGK Việt Nam: công thức khai triển/thu gọn (CH3-CH2-OH, CH3COOH), công thức khung (mỗi đầu mút/đỉnh là C, H gắn vào C không vẽ), vòng benzen vẽ lục giác với 3 liên kết đôi xen kẽ hoặc có vòng tròn bên trong, C6H5- hoặc Ph là phenyl, nhóm chức như -OH, -CHO, -COOH, -COO-, -CO-, -NH2, -NO2, -C≡N, -X. Đếm cẩn thận số C, vị trí nhánh và nhóm thế trên vòng (o-, m-, p-). Danh pháp dùng cách đọc tiếng Việt theo SGK (metan, etanol, propan-2-ol, axit etanoic, etanal, benzen, phenol, anilin, toluen, etyl axetat...), kèm tên thường gọi nếu có."""

FMT = """Chỉ trả về MỘT đối tượng JSON, không markdown, không lời dẫn, các khóa:
{"smiles":"SMILES chuẩn (không có H tường minh)","do_tin_cay":số 0-1,"ten_danh_phap":"tên thay thế/IUPAC đọc kiểu SGK Việt Nam","ten_thuong_goi":"tên thông thường hoặc rỗng","loai_hop_chat":"ví dụ: ancol no đơn chức","nhom_chuc":["..."],"trang_thai_nhiet_do":"thể ở điều kiện thường, nhận xét nhiệt độ sôi/tan","tinh_tan":"tính tan trong nước và trong dung môi thường gặp (etanol, ete...): nêu rõ tan nhiều, ít tan hay không tan; chỉ ghi độ tan bằng số khi chắc chắn, không chắc thì nói rõ, không bịa số","tinh_chat_vat_ly":["..."],"tinh_chat_hoa_hoc":["phản ứng đặc trưng kèm phương trình ngắn, điều kiện"],"dieu_che_ung_dung":["..."],"dong_phan":"nhận xét ngắn nếu có ý nghĩa","luu_y":["điều chưa chắc chắn trong ảnh, nét vẽ mơ hồ, cảnh báo an toàn"]}
Nếu ảnh không phải công thức hóa học hoặc không đọc được, đặt "smiles":"" và giải thích trong luu_y."""

SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


@st.cache_resource
def get_client():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])


def to_jpeg(file_bytes: bytes, max_side: int = 1400) -> bytes:
    img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


AI_CACHE_MAX, AI_CACHE_TTL = 400, 24 * 3600


@st.cache_resource
def _ai_cache():
    return {"d": {}, "lock": threading.Lock()}


def _ai_key(contents, temperature):
    h = hashlib.sha256(f"{MODEL}|{temperature}".encode())
    for c in contents:
        if isinstance(c, str):
            h.update(c.encode("utf-8"))
        else:
            data = getattr(getattr(c, "inline_data", None), "data", None)
            h.update(data if data else repr(c).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def ask_ai(contents, temperature=None, lang_note=True, cache=True):
    """Gọi Gemini có nhớ kết quả: cùng nội dung + cùng ngôn ngữ trong 24 giờ thì dùng lại, không tốn lượt gọi AI.
    lang_note: thêm chỉ thị song ngữ/tiếng Anh theo ngôn ngữ đang chọn."""
    contents = list(contents) if isinstance(contents, (list, tuple)) else [contents]
    note = i18n.ai_note() if lang_note else ""
    if note:
        contents.append(note)
    key = None
    if cache:
        try:
            key = _ai_key(contents, temperature)
        except Exception:
            key = None
    box = _ai_cache()
    if key:
        with box["lock"]:
            hit = box["d"].get(key)
        if hit and time.time() - hit[0] < AI_CACHE_TTL:
            return copy.deepcopy(hit[1])
    out = _ask_ai_raw(contents, temperature)
    if key:
        with box["lock"]:
            if len(box["d"]) >= AI_CACHE_MAX:
                box["d"].pop(next(iter(box["d"])))
            box["d"][key] = (time.time(), copy.deepcopy(out))
    return out


def _ask_ai_raw(contents, temperature=None):
    """Gọi Gemini, tự thử lại khi máy chủ quá tải (503) hoặc hết lượt tạm thời (429), rồi chuyển sang mô hình dự phòng."""
    models = [MODEL]
    fb = st.secrets.get("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
    if fb and fb != MODEL:
        models.append(fb)
    last = None
    for m in models:
        for i in range(3):
            try:
                resp = get_client().models.generate_content(
                    model=m,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        **({} if temperature is None else {"temperature": temperature}),
                    ),
                )
                text = (resp.text or "").replace("```json", "").replace("```", "").strip()
                return json.loads(text[text.index("{"): text.rindex("}") + 1])
            except errors.ServerError as e:
                last = e
                time.sleep(2 * (i + 1))
            except errors.ClientError as e:
                code = getattr(e, "code", None)
                if code == 429:
                    last = e
                    time.sleep(3 * (i + 1))
                elif code == 404:
                    last = e
                    break  # mô hình này không còn dùng được, chuyển sang mô hình tiếp theo
                else:
                    raise
    raise last


VOICE_PROMPT = ("Chép lại đúng lời nói trong đoạn ghi âm bằng tiếng Việt. Người nói là giáo viên hoặc học sinh nói về Hóa học. "
                "Chỉ trả về nội dung đã chép, không giải thích, không thêm gì. Viết công thức hóa học bằng ký hiệu chuẩn với chỉ số là số thường, "
                "ví dụ H2SO4, CuSO4, NaOH, C4H8O2, CH3COOH; nói 'cộng' thì viết +, nói 'tạo thành' hoặc 'ra' trong phương trình thì viết ->. "
                "Nếu không có lời nói hoặc không nghe rõ thì trả về chuỗi rỗng.")


def voice_to_text(audio_bytes, mime="audio/wav"):
    """Chuyển giọng nói thành chữ bằng Gemini (thử lại khi quá tải, chuyển mô hình dự phòng)."""
    models = [MODEL]
    fb = st.secrets.get("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
    if fb and fb != MODEL:
        models.append(fb)
    last = None
    for m in models:
        for i in range(2):
            try:
                resp = get_client().models.generate_content(model=m, contents=[types.Part.from_bytes(data=audio_bytes, mime_type=mime), VOICE_PROMPT + i18n.voice_note()],
                                                            config=types.GenerateContentConfig(temperature=0))
                return (resp.text or "").strip().strip('"').strip()
            except errors.ServerError as e:
                last = e; time.sleep(2 * (i + 1))
            except errors.ClientError as e:
                last = e
                if getattr(e, "code", None) == 429:
                    time.sleep(3 * (i + 1))
                else:
                    break
    raise last


def apply_voice(key):
    """Gọi ngay TRƯỚC ô nhập: đưa chữ đã nhận từ giọng nói vào ô (không sửa được ô sau khi nó đã vẽ trong cùng lần chạy)."""
    v = st.session_state.pop("_vp_" + key, None)
    if v:
        st.session_state[key] = v


def _voice_component():
    """Nút ghi âm tự dừng khi người nói im lặng (thư mục voice_component). None nếu thư mục chưa được tải lên."""
    import os
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_component")
    if not os.path.isfile(os.path.join(d, "index.html")):
        return None
    try:
        return components.declare_component("molsnap_voice", path=d)
    except Exception:
        return None


_VOICE_CMP = _voice_component()


def voice_input(key, chat=False, compact=False, msg=None):
    """Bấm micro một lần, nói xong tự dừng rồi chuyển thành chữ, điền vào ô nhập có khóa `key` (hoặc gửi vào khung chat).
    Nếu không có thư mục voice_component thì dùng ô ghi âm có sẵn của Streamlit (phải bấm dừng).
    compact: nút thu gọn để đặt cùng hàng với ô gõ; msg: khung (container) hiện thông báo/lỗi, để không bị kẹt trong cột hẹp."""
    import hashlib
    from contextlib import nullcontext
    box = msg if msg is not None else nullcontext()
    ph = st.session_state.get("vh_" + key)
    if _VOICE_CMP is not None:
        res = _VOICE_CMP(key="vc_" + key, default=None, compact=compact)
        if not res or res.get("id") == ph:
            return
        st.session_state["vh_" + key] = res.get("id")
        if res.get("err") or not res.get("wav"):
            with box:
                st.warning("Không mở được micro. Hãy cho phép trình duyệt dùng micro cho trang này.")
            return
        data = base64.b64decode(res["wav"])
    elif hasattr(st, "audio_input"):
        with st.expander("🎤 Nhập bằng giọng nói", expanded=bool(ph)):
            a = st.audio_input("Bấm micro để nói, nói xong bấm dừng", key="vi_" + key)
            if a is None:
                return
            data = a.getvalue(); h = hashlib.md5(data).hexdigest()
            if ph == h:
                return
            st.session_state["vh_" + key] = h
    else:   # bản Streamlit cũ chưa có ô ghi âm
        return
    if len(data) > 3_000_000:
        with box:
            st.warning("Đoạn ghi âm quá dài, hãy nói ngắn hơn (dưới khoảng 1 phút).")
        return
    with box:
        with st.spinner("Đang chuyển giọng nói thành chữ…"):
            try:
                text = voice_to_text(data)
            except Exception:
                text = None
                st.error("Chưa chuyển được giọng nói thành chữ (có thể Gemini đang quá tải hoặc hết hạn mức). Hãy thử lại sau.")
                return
        if not text:
            st.warning("Không nghe rõ, hãy nói lại gần micro hơn.")
            return
    st.session_state["pending_chat" if chat else "_vp_" + key] = text
    st.rerun()


def voice_text_input(key, label, placeholder=""):
    """Ô gõ tay và nút nói cùng một hàng (nút thu gọn). Không có thành phần ghi âm riêng thì nút nói nằm ngay dưới ô gõ."""
    apply_voice(key)
    if _VOICE_CMP is None:
        v = st.text_input(label, key=key, placeholder=placeholder)
        voice_input(key)
        return v
    with st.container(key="vrow_" + key):
        col_txt, col_mic = st.columns([1, 0.001], vertical_alignment="bottom", gap="small")
        with col_txt:
            v = st.text_input(label, key=key, placeholder=placeholder)
    msg = st.container()   # thông báo/lỗi của nút nói hiện đủ rộng ngay dưới hàng này
    with col_mic:
        voice_input(key, compact=True, msg=msg)
    return v


def analyze_image(file_bytes: bytes):
    prompt = (
        RULES
        + "\n\nĐây là ảnh chụp công thức cấu tạo viết tay. Hãy nhận dạng đúng một chất hữu cơ trong ảnh. "
        + "Chép ĐÚNG như hình vẽ, KHÔNG tự sửa lỗi hóa trị và không thêm hoặc bớt nguyên tử. "
        + "Nếu hình vẽ sai (ví dụ nguyên tử C có 5 liên kết) vẫn ghi SMILES đúng theo hình và nêu rõ lỗi trong luu_y.\n"
        + FMT
    )
    return ask_ai([types.Part.from_bytes(data=to_jpeg(file_bytes), mime_type="image/jpeg"), prompt], temperature=0)


def analyze_smiles(smiles: str):
    prompt = (
        RULES
        + f"\n\nChất có SMILES: {smiles}\nGiữ nguyên SMILES này trong khóa \"smiles\", đặt do_tin_cay=1 và cung cấp tên cùng tính chất.\n"
        + FMT
    )
    return ask_ai([prompt])


def chem_numbers(smiles: str):
    """Tính trực tiếp bằng RDKit, không phụ thuộc AI."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None, None
    formula = rdMolDescriptors.CalcMolFormula(mol)
    pretty = "".join(c.translate(SUB) if c.isdigit() else c for c in formula)
    molh = Chem.AddHs(mol)
    cnt = {}
    for a in molh.GetAtoms():
        cnt[a.GetSymbol()] = cnt.get(a.GetSymbol(), 0) + 1
    dbe = None
    if cnt.get("C"):
        x = sum(cnt.get(k, 0) for k in ("F", "Cl", "Br", "I"))
        dbe = (2 * cnt["C"] + 2 + cnt.get("N", 0) + cnt.get("P", 0) - cnt.get("H", 0) - x) / 2
    return mol, {"formula": pretty, "mass": Descriptors.MolWt(mol), "dbe": dbe}


def bullets(title, items):
    if items:
        st.markdown(f"**{title}**")
        for t in [items] if isinstance(items, str) else items:
            st.markdown(f"- {t}")


def render(r: dict, from_image: bool):
    smiles = (r.get("smiles") or "").strip()
    if not smiles:
        st.warning("Chưa nhận dạng được công thức trong ảnh.")
    mol, num = chem_numbers(smiles) if smiles else (None, None)
    if smiles and mol is None:
        st.error("Mã SMILES không hợp lệ. Hãy sửa ở ô bên dưới rồi bấm Phân tích lại.")
    c1, c2 = st.columns(2)
    with c1:
        if mol is not None:
            st.image(Draw.MolToImage(mol, size=(420, 300)))
    with c2:
        if smiles:
            st.markdown("**SMILES**")
            st.code(smiles, language=None)
        if r.get("ten_danh_phap"):
            st.markdown(f"**Tên (danh pháp):** {r['ten_danh_phap']}")
        if r.get("ten_thuong_goi"):
            st.markdown(f"**Tên thường gọi:** {r['ten_thuong_goi']}")
        if r.get("loai_hop_chat"):
            st.markdown(f"**Loại hợp chất:** {r['loai_hop_chat']}")
        if num:
            st.markdown(f"**Công thức phân tử:** {num['formula']}")
            st.markdown(f"**Khối lượng mol:** {num['mass']:.2f} g/mol")
            if num["dbe"] is not None:
                k = num["dbe"]
                st.markdown(f"**Độ bất bão hòa (k):** {int(k) if k == int(k) else k}")
        if r.get("tinh_tan"):
            _tt = r["tinh_tan"]
            st.markdown("**Tính tan:** " + (" ".join(str(x) for x in _tt) if isinstance(_tt, list) else str(_tt)))
    if from_image and isinstance(r.get("do_tin_cay"), (int, float)):
        p = max(0.0, min(1.0, float(r["do_tin_cay"])))
        st.progress(p, text=f"Độ tin cậy nhận dạng: {round(p * 100)}%")
    if r.get("nhom_chuc"):
        st.markdown("**Nhóm chức:** " + " · ".join(r["nhom_chuc"]))
    bullets("Trạng thái, nhiệt độ", r.get("trang_thai_nhiet_do"))
    bullets("Tính chất vật lí", r.get("tinh_chat_vat_ly"))
    bullets("Tính chất hóa học", r.get("tinh_chat_hoa_hoc"))
    bullets("Điều chế và ứng dụng", r.get("dieu_che_ung_dung"))
    bullets("Đồng phân", r.get("dong_phan"))
    if r.get("luu_y"):
        st.info("Lưu ý: " + " • ".join([r["luu_y"]] if isinstance(r["luu_y"], str) else r["luu_y"]))



# ---------------- Phản ứng hóa học ----------------
RULES_RX = """Bạn là giáo viên Hóa học Việt Nam. Hãy đọc phương trình phản ứng (viết tay hoặc gõ) và phân loại theo cách của SGK Việt Nam (Hóa 8-12). Các loại thường gặp: phản ứng thế (thế halogen, thế nitro, thế brom vào phenol...), cộng (cộng H2, Br2, HX, H2O), tách (tách H2O, tách HX, tách H2), trùng hợp, trùng ngưng, oxi hóa hoàn toàn (đốt cháy), oxi hóa không hoàn toàn, oxi hóa - khử, hóa hợp, phân hủy, trao đổi, trung hòa, este hóa, thủy phân, xà phòng hóa, tráng bạc, lên men, quang hợp, cracking, đề hiđro hóa, hiđro hóa. Một phản ứng có thể thuộc nhiều loại cùng lúc (ví dụ: cộng đồng thời là oxi hóa - khử); hãy nêu loại chính trước. Đọc kỹ hệ số và điều kiện (nhiệt độ, xúc tác, áp suất). Với muối/bazơ vô cơ dùng SMILES dạng ion, ví dụ NaOH là [Na+].[OH-], HCl là Cl, H2O là O, O2 là O=O, H2 là [H][H]."""

RFMT = """Chỉ trả về MỘT đối tượng JSON, không markdown, không lời dẫn.
QUAN TRỌNG: hãy đọc và phân tích TẤT CẢ các phương trình phản ứng có trong ảnh (kể cả khi ảnh gồm nhiều câu, nhiều bài tập hoặc một chuỗi phản ứng), theo thứ tự từ trên xuống dưới, từ trái sang phải. Mỗi phương trình là MỘT phần tử riêng trong "phan_ung". Tuyệt đối không bỏ sót, không gộp nhiều phương trình làm một và không chỉ chọn riêng một phương trình. Nếu ảnh chỉ có một phương trình thì "phan_ung" có đúng 1 phần tử.
{"phan_ung":[{"nhan":"nhãn đầy đủ của phương trình trong ảnh; nếu ảnh có nhiều câu thì ghi kèm câu, ví dụ Câu 1 - (1), Câu 2 - (3); ảnh chỉ có một câu thì ghi (1); không có nhãn thì để rỗng",
"phuong_trinh":"phương trình đọc được, viết dạng chữ, dùng -> giữa hai vế",
"chat_tham_gia":[{"he_so":số nguyên,"ten":"tên chất","cong_thuc":"công thức phân tử","smiles":"SMILES"}],
"san_pham":[{"he_so":số nguyên,"ten":"","cong_thuc":"","smiles":""}],
"dieu_kien":"nhiệt độ, xúc tác... hoặc rỗng",
"loai_phan_ung":["loại chính","loại phụ nếu có"],
"giai_thich":"2-4 câu: dựa vào sự thay đổi nào của cấu tạo/nhóm chức/số oxi hóa mà kết luận loại phản ứng",
"phuong_trinh_can_bang":"phương trình đã cân bằng đúng nếu ảnh chưa cân bằng hoặc sai, ngược lại để rỗng",
"oxi_hoa_khu":{"la_oxi_hoa_khu":true nếu có nguyên tố thay đổi số oxi hóa, ngược lại false,
 "chat_oxi_hoa":["công thức chất oxi hóa (chất nhận electron, chứa nguyên tố bị khử); mảng rỗng nếu không phải phản ứng oxi hóa - khử"],
 "chat_khu":["công thức chất khử (chất nhường electron, chứa nguyên tố bị oxi hóa); mảng rỗng nếu không phải phản ứng oxi hóa - khử"],
 "so_oxi_hoa":[{"cong_thuc":"công thức đúng như trong chat_tham_gia hoặc san_pham, mỗi chất ở cả hai vế một mục","nguyen_to":[{"kh":"ký hiệu nguyên tố","so":số nguyên là số oxi hóa (âm, 0 hoặc dương),"n":số nguyên tử của nguyên tố đó mang số oxi hóa này trong MỘT phân tử hoặc ion}]}]},
"luu_y":["điều chưa chắc chắn khi đọc phương trình này, ví dụ hệ số hoặc chất bị mờ"]}
 ],
"de_bai":[{"nhan":"Câu 1","yeu_cau":"chép lại đầy đủ phần yêu cầu/câu hỏi của câu đó trong ảnh, không chép lại các phương trình"}],
"luu_y_chung":["chỉ ghi lỗi đọc ảnh như chữ mờ, bị cắt; TUYỆT ĐỐI không ghi đáp án, lời giải hay số lượng phương trình; để mảng rỗng nếu không có"]}
"de_bai" là mảng rỗng nếu ảnh chỉ có phương trình mà không có câu hỏi hay yêu cầu nào; nếu ảnh có đề bài thì mỗi câu một phần tử.
Mỗi phần tử của "phan_ung" có đầy đủ các trường như trên và được phân tích độc lập với các phần tử khác.
Về cong_thuc: viết công thức phân tử gọn, chỉ số là số thường (H2SO4, [Ag(NH3)2]OH, CH2OH(CHOH)4COONH4), ion ghi điện tích sau dấu mũ (Fe^3+, SO4^2-, NH4^+, OH^-, Ag^+); không ghi kèm tên, trạng thái hay chữ giải thích trong cong_thuc.
Về chat_oxi_hoa và chat_khu: ghi đúng chuỗi cong_thuc của chất đó như trong chat_tham_gia.
Về tác nhân chỉ ghi trên mũi tên: nếu chất khử hoặc chất oxi hóa chỉ được ghi trên mũi tên (LiAlH4, NaBH4...) và phương trình trong ảnh không tự cân bằng được vì thiếu tác nhân đó, thì giữ tên tác nhân trong dieu_kien và thêm vào chat_tham_gia chất tương đương [H] (cong_thuc "[H]", ten "hiđro mới sinh [H] (từ LiAlH4)", smiles "[H]") với he_so đủ để cân bằng, ví dụ glucose bị khử thành sobitol thì thêm 2 [H]. Tương tự dùng [O] cho chất oxi hóa chỉ ghi trên mũi tên (KMnO4, K2Cr2O7...). Nếu H2, O2 đã ghi rõ trong phương trình thì giữ nguyên.
Về hệ số có chữ n (6nCO2, nC6H12O6): he_so ghi phần số nguyên (6, hoặc 1 nếu chỉ có n); phuong_trinh vẫn chép nguyên văn.
Về oxi_hoa_khu (áp dụng cho từng phương trình): liệt kê MỌI nguyên tố của MỌI chất (kể cả nguyên tố không đổi số oxi hóa) để tổng số nguyên tử và tổng số oxi hóa khớp công thức và điện tích của chất đó. Nếu trong một chất cùng một nguyên tố có nhiều số oxi hóa khác nhau (ví dụ C trong chất hữu cơ) thì ghi mỗi số oxi hóa một mục riêng với n tương ứng. Chất đơn chất có số oxi hóa 0. Ion ghi theo điện tích của ion.
Nếu không có phương trình phản ứng nào hoặc không đọc được, trả về "phan_ung" là mảng rỗng và giải thích trong luu_y_chung."""


def analyze_reaction(img_bytes, text):
    head = RULES_RX + "\n\n"
    if img_bytes:
        prompt = head + "Đây là ảnh có một hoặc nhiều phương trình phản ứng hóa học. Hãy xử lý đầy đủ tất cả.\n" + RFMT
        # ảnh nhiều phương trình có chữ nhỏ hơn nên giữ độ phân giải cao hơn
        res = ask_ai([types.Part.from_bytes(data=to_jpeg(img_bytes, 2400), mime_type="image/jpeg"), prompt])
    else:
        res = ask_ai([head + f"Phương trình: {text}\n" + RFMT])
    res["_v"] = RX_BUILD
    try:   # ảnh có đề bài: giải luôn các câu hỏi dựa trên dữ kiện đã phân tích; lỗi thì vẫn giữ phần phân tích phương trình
        sol = solve_questions(res)
        if sol:
            res["loi_giai"] = sol
    except Exception as e:
        res["loi_giai_loi"] = f"{type(e).__name__}: {e}"[:300]
    return res


RX_BUILD = "2026-11-12 · lời giải v3"   # hiện trên màn hình để biết app đang chạy bản nào


RULES_SOLVE = """Bạn là giáo viên Hóa học Việt Nam. Hãy giải từng câu hỏi dưới đây theo chương trình SGK Việt Nam (Hóa 8-12), chỉ dựa vào các câu hỏi và các phương trình đã được phân tích (số oxi hóa, chất oxi hóa, chất khử đã được máy kiểm chứng). Giải thích và kết luận của từng phản ứng phải khớp với dữ kiện đã phân tích, không được mâu thuẫn với chúng.
Nguyên tắc cần nhớ: glucose thể hiện tính khử khi nhóm -CHO bị oxi hóa (tráng bạc, phản ứng với Cu(OH)2 khi đun nóng, làm mất màu nước brom); glucose bị khử bằng H2/Ni, LiAlH4, NaBH4 là thể hiện tính oxi hóa, không phải tính khử; thủy phân, lên men, quang hợp được phân loại theo tên gọi của phản ứng và không tính là glucose thể hiện tính khử.
Với câu yêu cầu sắp xếp hoặc liệt kê theo thứ tự, "dap_an" là dãy số thứ tự phản ứng viết liền theo đúng thứ tự đề yêu cầu (tăng dần nếu đề nói tăng dần). Với câu chọn các phản ứng thỏa điều kiện, "dap_an" là dãy số thứ tự các phản ứng thỏa, viết liền, tăng dần."""

SOLVE_FMT = """Chỉ trả về MỘT đối tượng JSON, không markdown, không lời dẫn:
{"cau":[{"nhan":"Câu 1","tieu_de":"tiêu đề ngắn của câu, ví dụ: Sắp xếp các phản ứng theo tên gọi",
"nguyen_tac":"1-2 câu nguyên tắc hoặc kiến thức dùng để giải, có thể rỗng",
"cot_ket_luan":"tên cột cuối của bảng, ví dụ: Tên phản ứng hoặc Kết luận",
"phan_tich":[{"phan_ung":"số thứ tự phản ứng trong đề, ví dụ (1)","giai_thich":"1 câu ngắn","ket_luan":"nhãn rất ngắn, tối đa 3 từ: với câu chọn phản ứng thì ghi 'Tính khử' hoặc 'Không' (hoặc nhãn tương ứng với đề); với câu phân loại thì ghi tên phản ứng"}],
"ket_luan_cau":"1 câu kết luận",
"dap_an":"đáp án cuối cùng đúng định dạng đề yêu cầu, ví dụ 1324 hoặc 125"}]}
Mỗi câu hỏi trong đề là một phần tử của "cau", mỗi phản ứng của câu đó là một dòng trong "phan_tich"."""


def rx_facts(items):
    """Tóm tắt từng phương trình (kèm kết quả oxi hóa - khử đã kiểm chứng) để đưa cho bước giải đề."""
    lines = []
    for it in items:
        info = []
        a = redox_analysis(it)
        if a and a.get("ok"):
            if a["redox"]:
                kf, of = list(dict.fromkeys(f for f, *_ in a["khu"])), list(dict.fromkeys(f for f, *_ in a["oxh"]))
                both = [f for f in kf if f in of]
                kf, of = [f for f in kf if f not in both], [f for f in of if f not in both]
                txt = f"oxi hóa - khử (chất khử: {', '.join(kf) or 'không có'}; chất oxi hóa: {', '.join(of) or 'không có'}"
                if both:   # chất vừa nhường vừa nhận e trong cùng phản ứng không khử một chất oxi hóa khác
                    txt += f"; {', '.join(both)} tự oxi hóa - khử nội phân tử, không có chất nào khác nhận electron từ nó nên KHÔNG tính là thể hiện tính khử đối với chất khác"
                info.append(txt + ")")
            else:
                info.append("không phải phản ứng oxi hóa - khử")
        lines.append(f'- [{it.get("nhan") or "?"}] {it.get("phuong_trinh") or ""} | điều kiện: {it.get("dieu_kien") or "không"}'
                     f' | loại: {", ".join(str(x) for x in (it.get("loai_phan_ung") or []))}' + (" | " + "; ".join(info) if info else ""))
    return "\n".join(lines)


def solve_questions(res):
    """Giải các câu hỏi có trong ảnh. Trả về None nếu ảnh không có đề bài."""
    items = reactions_of(res)
    qs = [q for q in ((res or {}).get("de_bai") or []) if isinstance(q, dict) and q.get("yeu_cau")]
    if not items or not qs:
        return None
    prompt = (RULES_SOLVE + "\n\nCÁC CÂU HỎI TRONG ẢNH:\n" + "\n".join(f'- {q.get("nhan") or ""}: {q["yeu_cau"]}' for q in qs)
              + "\n\nCÁC PHƯƠNG TRÌNH ĐÃ PHÂN TÍCH:\n" + rx_facts(items) + "\n\n" + SOLVE_FMT)
    out = ask_ai([prompt], temperature=0.1)
    return out if isinstance(out, dict) and out.get("cau") else None


def reactions_of(res):
    """Danh sách phản ứng trong kết quả AI. Hỗ trợ cả dạng cũ (một phản ứng nằm trực tiếp trong kết quả)."""
    if not isinstance(res, dict):
        return []
    lst = res.get("phan_ung")
    if isinstance(lst, list):
        return [x for x in lst if isinstance(x, dict)]
    return [res] if (res.get("chat_tham_gia") or res.get("san_pham") or res.get("phuong_trinh")) else []


def atom_balance(species):
    """Đếm nguyên tử và điện tích mỗi vế bằng RDKit. Trả về None nếu có SMILES lỗi."""
    tot, charge = {}, 0
    for coef, smi in species:
        mol = Chem.MolFromSmiles(smi or "")
        if mol is None:
            return None
        for a in Chem.AddHs(mol).GetAtoms():
            tot[a.GetSymbol()] = tot.get(a.GetSymbol(), 0) + coef
            charge += coef * a.GetFormalCharge()
    return tot, charge


def to_int(v):
    try:
        return max(1, int(v))
    except Exception:
        return 1


def _norm_formula(f):
    """Đưa công thức về dạng so khớp: bỏ khoảng trắng, mũi tên khí/kết tủa, đổi chỉ số dưới/trên về ký tự thường."""
    return re.sub(r"[\s↑↓]", "", str(f or "")).translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉⁺⁻", "0123456789+-"))


def _species_atoms_charge(sp):
    """Đếm nguyên tử và điện tích của một chất từ SMILES bằng RDKit. None nếu SMILES không đọc được."""
    mol = Chem.MolFromSmiles(sp.get("smiles") or "")
    if mol is None:
        return None
    cnt = {}
    for a in Chem.AddHs(mol).GetAtoms():
        cnt[a.GetSymbol()] = cnt.get(a.GetSymbol(), 0) + 1
    return cnt, sum(a.GetFormalCharge() for a in mol.GetAtoms())


def _fmt_ox(v):
    return f"+{v}" if v > 0 else str(v)


_SUPERS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


def _rx_part_counts(p):
    """Đếm nguyên tử của một công thức không có điện tích, ví dụ Ca(OH)2, [Ag(NH3)2]OH. None nếu không đọc được."""
    toks = re.findall(r"[A-Z][a-z]?|\d+|[()\[\]]", p)
    if not toks or "".join(toks) != p:
        return None
    ptable = Chem.GetPeriodicTable()
    stack, i = [{}], 0
    while i < len(toks):
        t = toks[i]
        if t in "([":
            stack.append({})
        elif t in ")]":
            if len(stack) < 2:
                return None
            grp, mult = stack.pop(), 1
            if i + 1 < len(toks) and toks[i + 1].isdigit():
                mult = int(toks[i + 1]); i += 1
            for k, v in grp.items():
                stack[-1][k] = stack[-1].get(k, 0) + v * mult
        elif t.isdigit():
            return None
        else:
            try:
                ptable.GetAtomicNumber(t)
            except Exception:
                return None
            n = 1
            if i + 1 < len(toks) and toks[i + 1].isdigit():
                n = int(toks[i + 1]); i += 1
            stack[-1][t] = stack[-1].get(t, 0) + n
        i += 1
    return stack[0] if len(stack) == 1 else None


def rx_parse_formula(f):
    """Công thức dạng chữ (Ca(OH)2, [Ag(NH3)2]OH, CuSO4.5H2O, Fe^3+, NH4+) -> (số nguyên tử từng nguyên tố, điện tích).
    Trả về None nếu không đọc chắc được (ví dụ có chỉ số n)."""
    s = re.sub(r"([⁰¹²³⁴⁵⁶⁷⁸⁹]*)([⁺⁻])", lambda m: "^" + m.group(1).translate(_SUPERS) + m.group(2).translate(str.maketrans("⁺⁻", "+-")), str(f or ""))
    s = _norm_formula(s)
    s = re.sub(r"\((?:s|l|g|aq|r|k|dd)\)$", "", s)
    charge = 0
    m = re.search(r"\^\{?(\d*)([+-])\}?$", s)
    if m:
        charge = int(m.group(1) or 1) * (1 if m.group(2) == "+" else -1)
        s = s[:m.start()]
    else:
        m = re.search(r"(\d*)([+-])$", s)
        if m and m.start() > 0:
            pre, d, sign = s[:m.start()], m.group(1), (1 if m.group(2) == "+" else -1)
            if d and (re.fullmatch(r"[A-Z][a-z]?", pre) or pre[-1] in ")]"):
                charge, s = int(d) * sign, pre          # Fe2+, [Cu(NH3)4]2+
            else:
                charge, s = sign, s[:m.start(2)]        # NH4+, OH-, Cl-
    s = re.sub(r"[-=≡]", "", s)
    if not s:
        return None
    total = {}
    for k, part in enumerate(re.split(r"[.·•]", s)):
        mult = 1
        mm = re.match(r"(\d+)(.*)$", part)
        if mm and k > 0:
            mult, part = int(mm.group(1)), mm.group(2)
        c = _rx_part_counts(part)
        if c is None:
            return None
        for el, n in c.items():
            total[el] = total.get(el, 0) + n * mult
    return total, charge


def _nullspace(A, ncols):
    """Không gian nghiệm của A·x = 0 trên số hữu tỉ."""
    from fractions import Fraction
    M = [[Fraction(x) for x in row] for row in A]
    piv, r = [], 0
    for c in range(ncols):
        p = next((i for i in range(r, len(M)) if M[i][c] != 0), None)
        if p is None:
            continue
        M[r], M[p] = M[p], M[r]
        M[r] = [x / M[r][c] for x in M[r]]
        for i in range(len(M)):
            if i != r and M[i][c] != 0:
                f = M[i][c]
                M[i] = [a - f * b for a, b in zip(M[i], M[r])]
        piv.append(c); r += 1
        if r == len(M):
            break
    out = []
    for fc in (c for c in range(ncols) if c not in piv):
        v = [Fraction(0)] * ncols
        v[fc] = Fraction(1)
        for row, pc in enumerate(piv):
            v[pc] = -M[row][fc]
        out.append(v)
    return out


def rx_balance_formulas(left, right):
    """Kiểm tra cân bằng từ công thức phân tử (không phụ thuộc SMILES). Trả về None nếu có công thức không đọc được,
    ngược lại {"ok": đã cân bằng chưa, "coefs": hệ số nguyên nhỏ nhất (vế trái rồi vế phải) hoặc None nếu không giải được}."""
    from math import gcd
    sp = []
    for sign, lst in ((1, left), (-1, right)):
        for x in lst:
            p = rx_parse_formula(x.get("cong_thuc"))
            if p is None:
                return None
            sp.append((sign, to_int(x.get("he_so")), p))
    if not sp:
        return None
    elems = sorted({e for _, _, (c, _) in sp for e in c})
    net = {e: sum(s * k * c.get(e, 0) for s, k, (c, _) in sp) for e in elems}
    ok = all(v == 0 for v in net.values()) and sum(s * k * ch for s, k, (_, ch) in sp) == 0
    coefs = None
    A = [[s * c.get(e, 0) for s, _, (c, _) in sp] for e in elems] + [[s * ch for s, _, (_, ch) in sp]]
    ns = _nullspace(A, len(sp))
    if len(ns) == 1:
        v = ns[0]
        if all(x > 0 for x in v) or all(x < 0 for x in v):
            den = 1
            for x in v:
                den = den * x.denominator // gcd(den, x.denominator)
            ints = [abs(int(x * den)) for x in v]
            g = 0
            for x in ints:
                g = gcd(g, x)
            coefs = [x // g for x in ints]
    return {"ok": ok, "coefs": coefs}


def rx_equation(left, right, coefs):
    """Ghép phương trình từ công thức và hệ số (vế trái rồi vế phải)."""
    side = lambda lst, cs: " + ".join((f"{k} " if k > 1 else "") + str(x.get("cong_thuc") or "?") for x, k in zip(lst, cs))
    return side(left, coefs[:len(left)]) + " -> " + side(right, coefs[len(left):])


def redox_analysis(r):
    """Phân tích oxi hóa - khử từ số oxi hóa do AI đưa ra. AI chỉ cung cấp số oxi hóa; máy kiểm tra số nguyên tử và điện tích từng chất,
    rồi tự suy ra nguyên tố thay đổi, chất khử, chất oxi hóa và các quá trình oxi hóa, khử. Trả về None nếu thiếu số oxi hóa."""
    ox = r.get("oxi_hoa_khu") or {}
    left, right = r.get("chat_tham_gia") or [], r.get("san_pham") or []
    table = {}
    for item in ox.get("so_oxi_hoa") or []:
        ents = []
        for e in item.get("nguyen_to") or []:
            try:
                ents.append((str(e["kh"]).strip(), int(e["so"]), int(e["n"])))
            except Exception:
                return {"ok": False, "problems": [str(item.get("cong_thuc", "?"))]}
        table[_norm_formula(item.get("cong_thuc"))] = ents
    if not table or not left or not right:
        return None
    sides, bad, verified = [], [], True
    for lst in (left, right):
        side = []
        for sp in lst:
            ents = table.get(_norm_formula(sp.get("cong_thuc")))
            if not ents:
                return None
            chk = rx_parse_formula(sp.get("cong_thuc"))   # ưu tiên công thức; SMILES do AI sinh ra hay sai
            if chk is None:
                chk = _species_atoms_charge(sp)
            if chk is None:
                verified = False
            else:
                cnt, charge = chk
                have = {}
                for el, so, n in ents:
                    have[el] = have.get(el, 0) + n
                if have != cnt or sum(so * n for el, so, n in ents) != charge:
                    bad.append(sp.get("cong_thuc") or "?")
            side.append((to_int(sp.get("he_so")), sp.get("cong_thuc") or "", ents))
        sides.append(side)
    if bad:
        return {"ok": False, "problems": bad}
    fb = rx_balance_formulas(left, right)
    if fb and not fb["ok"] and fb["coefs"]:   # hệ số trong ảnh sai/thiếu thì dùng hệ số máy tự cân bằng
        nl = len(sides[0])
        sides = [[(fb["coefs"][i], f, e) for i, (_, f, e) in enumerate(sides[0])],
                 [(fb["coefs"][nl + i], f, e) for i, (_, f, e) in enumerate(sides[1])]]
    # Đếm số nguyên tử của từng nguyên tố theo từng số oxi hóa (nhân hệ số), rồi triệt tiêu phần giống nhau giữa hai vế;
    # phần còn lại ở vế trái chuyển thành phần còn lại ở vế phải chính là sự thay đổi số oxi hóa thật sự.
    before, after = {}, {}
    for side, dest in ((sides[0], before), (sides[1], after)):
        for k, f, ents in side:
            for el, so, n in ents:
                dest.setdefault(el, Counter())[so] += k * n
    rem_b, rem_a = {}, {}
    for el in set(before) & set(after):
        rem_b[el], rem_a[el] = before[el] - after[el], after[el] - before[el]
    changed = []
    for el in sorted(rem_b):
        if rem_b[el] and rem_a[el]:
            up, down = max(rem_a[el]) > min(rem_b[el]), min(rem_a[el]) < max(rem_b[el])
            changed.append({"el": el, "before": sorted(rem_b[el]), "after": sorted(rem_a[el]),
                            "kind": "tự oxi hóa – khử" if up and down else "tăng (bị oxi hóa)" if up else "giảm (bị khử)" if down else "thay đổi"})
    khu, oxh, half = [], [], []
    for _, f, ents in sides[0]:
        for el, so, n in ents:
            if el not in rem_b or so not in rem_b[el]:
                continue   # số oxi hóa này không đổi qua phản ứng
            hi = [a for a in rem_a[el] if a > so]
            lo = [a for a in rem_a[el] if a < so]
            if hi:
                t = min(hi); khu.append((f, el, so, t)); half.append(("Quá trình oxi hóa", f"{el}({_fmt_ox(so)}) → {el}({_fmt_ox(t)}) + {t - so}e"))
            if lo:
                t = max(lo); oxh.append((f, el, so, t)); half.append(("Quá trình khử", f"{el}({_fmt_ox(so)}) + {so - t}e → {el}({_fmt_ox(t)})"))
    seen = set()
    half = [h for h in half if not (h in seen or seen.add(h))]
    return {"ok": True, "verified": verified, "redox": bool(changed), "changed": changed, "khu": khu, "oxh": oxh, "half": half}


def _redox_box(oxi, red, half=(), note=""):
    """Khung chất oxi hóa / chất khử. oxi, red: danh sách (công thức, chi tiết) đã escape; half: các nửa quá trình."""
    item = lambda f, d: f'<b>{f}</b>' + (f'<span>{d}</span>' if d else "")
    role = lambda cls, ttl, lst: (f'<div class="rxrole {cls}"><small>{ttl}</small>' + ("".join(item(f, d) for f, d in lst) or "<b>—</b>") + "</div>")
    out = ('<div class="rxredox"><div class="rxredhead">⚡ Phản ứng oxi hóa – khử</div><div class="rxroles">'
           + role("ox", "CHẤT OXI HÓA<br>nhận e · bị khử", oxi) + role("rd", "CHẤT KHỬ<br>nhường e · bị oxi hóa", red) + "</div>")
    if half:
        out += '<div class="rxhalf">' + "".join(f'<div><u>{html.escape(t)}</u>: {html.escape(_sub(s))}</div>' for t, s in half) + "</div>"
    if note:
        out += f'<div class="rxhalf" style="opacity:.8"><i>{html.escape(note)}</i></div>'
    st.markdown(out + "</div>", unsafe_allow_html=True)


def render_redox(r):
    a = redox_analysis(r)
    ox = r.get("oxi_hoa_khu") or {}
    ai_ox, ai_red = _as_list(ox.get("chat_oxi_hoa")), _as_list(ox.get("chat_khu"))
    if a is None or not a["ok"]:
        if ox.get("la_oxi_hoa_khu") and (ai_ox or ai_red):   # số oxi hóa không kiểm chứng được: dùng kết luận của AI, ghi rõ
            _redox_box([(html.escape(pretty(f)), "") for f in ai_ox], [(html.escape(pretty(f)), "") for f in ai_red])
        elif a is not None:
            st.warning("Chưa xác định chắc số oxi hóa của: " + ", ".join(a["problems"]) + ". Hãy tự kiểm tra lại.")
        return
    if not a["redox"]:
        st.info("**Không phải** phản ứng oxi hóa khử.")
        return
    def fmt(lst):   # gom theo (chất, nguyên tố): C: +1, 0 → -1
        grp = {}
        for f, el, so, t in lst:
            g = grp.setdefault((f, el), ([], []))
            if so not in g[0]:
                g[0].append(so)
            if t not in g[1]:
                g[1].append(t)
        j = lambda v: ", ".join(_fmt_ox(x) for x in sorted(v))
        return [(html.escape(pretty(f)), f"{html.escape(el)}: {j(a)} → {j(b)}") for (f, el), (a, b) in grp.items()]
    both = [f for f in dict.fromkeys(f for f, *_ in a["khu"]) if any(f == g for g, *_ in a["oxh"])]
    note = (", ".join(pretty(f) for f in both) + " vừa là chất khử vừa là chất oxi hóa (tự oxi hóa – khử).") if both else ""
    _redox_box(fmt(a["oxh"]), fmt(a["khu"]), a["half"], note)


def _balance_box(ok, eq, title=None):
    ttl = title or ("✓ Phương trình đã cân bằng" if ok else "Phương trình cân bằng đúng")
    st.markdown(f'<div class="rxbal {"ok" if ok else "no"}"><small>{html.escape(ttl)}</small><div class="eq">{_eq_html(eq)}</div></div>',
                unsafe_allow_html=True)


def render_balance(r, left, right):
    """Luôn hiện phương trình đã cân bằng. Kiểm tra bằng công thức phân tử; chỉ dùng SMILES khi công thức không đọc được."""
    fb = rx_balance_formulas(left, right)
    if fb is not None:
        if fb["ok"]:
            _balance_box(True, rx_equation(left, right, [to_int(x.get("he_so")) for x in left + right]))
        elif fb["coefs"]:
            st.warning("Phương trình trong ảnh **chưa cân bằng** (hệ số chưa đúng).")
            _balance_box(False, rx_equation(left, right, fb["coefs"]))
        else:
            st.warning("Phương trình **chưa cân bằng**.")
            if r.get("phuong_trinh_can_bang"):
                _balance_box(False, r["phuong_trinh_can_bang"], "Phương trình cân bằng (AI đề xuất)")
        return
    if re.search(r"[)\]]n\b|\bn[A-Z(]", " ".join(str(x.get("cong_thuc") or "") for x in left + right)):
        return   # có chỉ số n (polime, tinh bột...) nên không kiểm tra cân bằng được
    bl = atom_balance([(to_int(x.get("he_so")), x.get("smiles")) for x in left])
    br = atom_balance([(to_int(x.get("he_so")), x.get("smiles")) for x in right])
    if bl is not None and br is not None:
        if bl == br:
            _balance_box(True, r.get("phuong_trinh") or "")
        else:
            st.warning("Phương trình **chưa cân bằng**.")
            if r.get("phuong_trinh_can_bang"):
                _balance_box(False, r["phuong_trinh_can_bang"], "Phương trình cân bằng (AI đề xuất)")
    elif r.get("phuong_trinh_can_bang"):
        _balance_box(False, r["phuong_trinh_can_bang"], "Phương trình cân bằng (AI đề xuất, chưa kiểm tra)")


def render_reaction(r: dict, header: bool = True):
    left, right = r.get("chat_tham_gia") or [], r.get("san_pham") or []
    if header:   # header=False: phương trình và loại phản ứng đã được vẽ ở thẻ bên ngoài
        if r.get("phuong_trinh"):
            st.markdown("**Phương trình đọc được**")
            st.code(r["phuong_trinh"], language=None)
        types_ = r.get("loai_phan_ung") or []
        if types_:
            st.success("**Loại phản ứng:** " + " · ".join(types_))
    if r.get("giai_thich"):
        st.markdown("**Vì sao:** " + r["giai_thich"])
    if r.get("dieu_kien"):
        st.markdown("**Điều kiện:** " + r["dieu_kien"])

    rows, mols, legends = [], [], []
    for role, lst in (("Tham gia", left), ("Sản phẩm", right)):
        for sp in lst:
            m = Chem.MolFromSmiles(sp.get("smiles") or "")
            mass = f"{Descriptors.MolWt(m):.2f}" if m is not None else "—"
            rows.append({"Vai trò": role, "Hệ số": to_int(sp.get("he_so")), "Tên": sp.get("ten", ""),
                         "Công thức": sp.get("cong_thuc", ""), "M (g/mol)": mass, "SMILES": sp.get("smiles", "")})
            if m is not None and m.GetNumHeavyAtoms() > 1:
                mols.append(m)
                legends.append(sp.get("cong_thuc") or "")
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    if mols:
        try:
            st.image(Draw.MolsToGridImage(mols, molsPerRow=3, subImgSize=(260, 190), legends=legends))
        except Exception:
            pass

    if left and right:
        render_balance(r, left, right)
        render_redox(r)
    if r.get("luu_y"):
        st.info("Lưu ý: " + " • ".join([r["luu_y"]] if isinstance(r["luu_y"], str) else r["luu_y"]))


def _as_list(v):
    return [v] if isinstance(v, str) and v else [x for x in (v or []) if x]


RX_CSS = """<style>
.rxsum{display:flex;align-items:center;gap:1rem;border-radius:1.4rem;padding:1rem 1.2rem;margin:0.4rem 0 1.1rem;color:#fff;
background:radial-gradient(18rem 9rem at 95% 0%,rgba(25,195,255,.4),rgba(25,195,255,0) 70%),linear-gradient(115deg,#152a9a 0%,#3a37cf 55%,#5a3bea 100%);box-shadow:0 0.857rem 2rem rgba(47,53,200,.28)}
.rxsum .big{flex:0 0 3.6rem;height:3.6rem;border-radius:50%;display:grid;place-items:center;font-size:1.9rem;font-weight:800;background:rgba(255,255,255,.18);border:2px solid rgba(255,255,255,.5)}
.rxsum b{display:block;font-size:1.2rem;line-height:1.3}
.rxsum small{opacity:.85;font-size:.9rem}
.rxlist{margin:-0.4rem 0 1.1rem;display:flex;flex-direction:column;gap:.4rem}
.rxlist div{display:flex;gap:.6rem;align-items:center;background:#f3f5ff;border:1px solid #e3e7fb;border-radius:.9rem;padding:.45rem .7rem;font-size:.95rem;line-height:1.5;color:#1b2150;word-break:break-word}
.rxlist div i{flex:0 0 1.7rem;height:1.7rem;border-radius:50%;display:grid;place-items:center;font-style:normal;font-weight:800;font-size:.85rem;color:#fff;background:linear-gradient(135deg,#3b6cf6,#6d4df0)}
[class*="st-key-rxcard"]{background:#fff;border:1px solid #dfe5ff;border-left:0.55rem solid #6d4df0;border-radius:1.4rem;padding:1.1rem 1.2rem 0.7rem;margin-bottom:1.3rem;box-shadow:0 1rem 2.2rem rgba(79,92,240,.15)}
.rxhead{display:flex;align-items:center;gap:.7rem;margin-bottom:.7rem}
.rxnum{flex:0 0 2.6rem;height:2.6rem;border-radius:50%;display:grid;place-items:center;font-size:1.25rem;font-weight:800;color:#fff;background:linear-gradient(135deg,#3b6cf6,#7a52f4);box-shadow:0 0.4rem 1rem rgba(79,92,240,.4)}
.rxttl{font-weight:800;font-size:1.05rem;color:#1b2150}
.rxttl em{font-style:normal;font-weight:600;font-size:.85rem;color:#6d4df0;background:#ece8ff;border-radius:2rem;padding:.12rem .6rem;margin-left:.4rem}
.rxeq{font-size:1.3rem;font-weight:700;line-height:1.9;color:#10163f;background:linear-gradient(135deg,#eef1ff,#f6f0ff);border:1px solid #dfe5ff;border-radius:1.1rem;padding:.8rem 1rem;overflow-x:auto;margin-bottom:.8rem}
.rxeq .ar{color:#6d4df0;font-weight:900;margin:0 .35rem}
.rxpills{display:flex;flex-wrap:wrap;gap:.45rem;margin-bottom:.8rem}
.rxpills span{border-radius:2rem;padding:.3rem .85rem;font-weight:700;font-size:.92rem}
.rxbal{border-radius:1.1rem;padding:.7rem 1rem;margin:.7rem 0;overflow-x:auto}
.rxbal small{display:block;font-weight:800;font-size:.82rem;margin-bottom:.15rem}
.rxbal .eq{font-size:1.2rem;font-weight:700;line-height:1.9;color:#10163f}
.rxbal.ok{background:#e8f8ef;border:1px solid #bfe9d0}.rxbal.ok small{color:#047857}
.rxbal.no{background:#fff7e0;border:1px solid #fde2a1}.rxbal.no small{color:#b45309}
.rxbal .ar{color:#047857;font-weight:900;margin:0 .35rem}
.rxredox{border-radius:1.1rem;border:1px solid #fcd9b6;background:linear-gradient(135deg,#fff8ee,#fff2f7);padding:.8rem 1rem;margin:.7rem 0}
.rxredhead{font-weight:800;color:#b45309;margin-bottom:.6rem}
.rxroles{display:grid;grid-template-columns:1fr;gap:.6rem}
@media(min-width:560px){.rxroles{grid-template-columns:1fr 1fr}}
.rxrole{border-radius:.9rem;padding:.6rem .85rem}
.rxrole small{display:block;font-weight:800;font-size:.76rem;line-height:1.35;margin-bottom:.2rem}
.rxrole b{display:block;font-size:1.15rem;color:#10163f}
.rxrole span{display:block;font-size:.85rem;color:#475569;margin-bottom:.25rem}
.rxrole.ox{background:#ffe9e0;border:1px solid #ffc9b3}.rxrole.ox small{color:#b42318}
.rxrole.rd{background:#e3eeff;border:1px solid #bcd3ff}.rxrole.rd small{color:#1d4ed8}
.rxhalf{margin-top:.6rem;font-size:.95rem;line-height:1.75;color:#10163f}.rxhalf u{text-decoration:none;font-weight:800;color:#b45309}
.rxsec{font-weight:800;font-size:1.25rem;color:#1b2150;margin:1.2rem 0 .7rem;padding-left:.7rem;border-left:.3rem solid #6d4df0}
.rxq{background:#fff;border:1px solid #dfe5ff;border-radius:1.4rem;padding:1.1rem 1.2rem;margin-bottom:1.2rem;box-shadow:0 1rem 2.2rem rgba(79,92,240,.13)}
.rxq h4{margin:0 0 .5rem;font-size:1.15rem;color:#1b2150;line-height:1.4}
.rxq h4 em{font-style:normal;color:#6d4df0}
.rxq p{margin:.3rem 0 .7rem;color:#334155;line-height:1.6}
.rxtbl{width:100%;border-collapse:collapse;margin:.3rem 0 .8rem;font-size:.97rem}
.rxtbl th{text-align:left;color:#6b7299;font-weight:700;padding:.5rem .4rem;border-bottom:2px solid #e3e7fb}
.rxtbl td{padding:.55rem .4rem;border-bottom:1px solid #eef0fb;vertical-align:top;color:#10163f;line-height:1.5}
.rxtbl td:first-child{font-weight:800;white-space:nowrap;color:#4f5cf0}
.rxtbl td:last-child{text-align:right;white-space:nowrap}
.rxtag{display:inline-block;border-radius:2rem;padding:.2rem .7rem;font-weight:800;font-size:.88rem}
.rxtag.g{color:#047857;background:#d9f6e6}.rxtag.r{color:#b42318;background:#ffe4e0}.rxtag.b{color:#2563eb;background:#e3eeff}
.rxans{display:inline-block;margin-top:.3rem;border-radius:2rem;padding:.45rem 1.1rem;font-weight:800;font-size:1.05rem;color:#fff;background:linear-gradient(135deg,#059669,#10b981);box-shadow:0 .4rem 1rem rgba(5,150,105,.3)}
.rxfinal{border-radius:1.4rem;padding:1rem 1.3rem;margin:.2rem 0 1.2rem;color:#fff;background:linear-gradient(115deg,#152a9a 0%,#3a37cf 55%,#5a3bea 100%);box-shadow:0 .857rem 2rem rgba(47,53,200,.28)}
.rxfinal b.t{display:block;font-size:1.1rem;margin-bottom:.4rem}
.rxfinal div{font-size:1.15rem;line-height:1.9}.rxfinal div b{font-size:1.3rem;color:#a7f3d0}
.rxpills span.p0{color:#fff;background:linear-gradient(135deg,#059669,#10b981);box-shadow:0 0.3rem .8rem rgba(5,150,105,.3)}
.rxpills span.p1{color:#2563eb;background:#e3eeff}.rxpills span.p2{color:#d97706;background:#fff1dc}.rxpills span.p3{color:#d6389b;background:#ffe4f5}.rxpills span.p4{color:#6d4df0;background:#ece8ff}
</style>"""


def _eq_html(s):
    """Phương trình dạng chữ -> HTML: chỉ số dưới, mũi tên đẹp."""
    t = html.escape(_sub(str(s or "")))
    for a in ("&lt;-&gt;", "&lt;=&gt;"):
        t = t.replace(a, '<span class="ar">⇌</span>')
    for a in ("--&gt;", "-&gt;", "=&gt;"):
        t = t.replace(a, '<span class="ar">→</span>')
    return t


def _rx_card_head(i, n, it):
    parts = ['<div class="rxhead">' + (f'<div class="rxnum">{i}</div>' if n > 1 else "")
             + f'<div class="rxttl">{"Phương trình " + str(i) + "/" + str(n) if n > 1 else "Phương trình đọc được"}'
             + (f'<em>{html.escape(str(it["nhan"]))}</em>' if it.get("nhan") else "") + '</div></div>']
    if it.get("phuong_trinh"):
        parts.append(f'<div class="rxeq">{_eq_html(it["phuong_trinh"])}</div>')
    types_ = [str(x) for x in (it.get("loai_phan_ung") or []) if x]
    if types_:
        parts.append('<div class="rxpills">' + "".join(
            f'<span class="p{min(k, 4)}">{"Loại phản ứng: " if k == 0 else ""}{html.escape(x)}</span>' for k, x in enumerate(types_)) + "</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def _tag_cls(t):
    s = str(t or "").strip().lower()
    if s.startswith(("không", "sai", "ko")):
        return "r"
    if s.startswith(("tính khử", "có", "đúng", "thỏa", "thoả")):
        return "g"
    return "b"


def render_solution(sol):
    """Lời giải các câu hỏi trong ảnh: bảng từng phản ứng, đáp án từng câu, kết quả cuối cùng."""
    cau = [c for c in ((sol or {}).get("cau") or []) if isinstance(c, dict)]
    if not cau:
        return
    st.markdown('<div class="rxsec">Lời giải</div>', unsafe_allow_html=True)
    finals = []
    for c in cau:
        nhan = html.escape(str(c.get("nhan") or ""))
        parts = [f'<div class="rxq"><h4><em>{nhan}</em>' + (". " + _eq_html(c["tieu_de"]) if c.get("tieu_de") else "") + "</h4>"]
        if c.get("nguyen_tac"):
            parts.append(f'<p><b>Nguyên tắc:</b> {_eq_html(c["nguyen_tac"])}</p>')
        rows = [x for x in (c.get("phan_tich") or []) if isinstance(x, dict)]
        if rows:
            parts.append('<table class="rxtbl"><thead><tr><th>Phản ứng</th><th>Giải thích</th><th>'
                         + html.escape(str(c.get("cot_ket_luan") or "Kết luận")) + "</th></tr></thead><tbody>"
                         + "".join(f'<tr><td>{html.escape(str(x.get("phan_ung") or ""))}</td><td>{_eq_html(x.get("giai_thich"))}</td>'
                                   f'<td><span class="rxtag {_tag_cls(x.get("ket_luan"))}">{html.escape(str(x.get("ket_luan") or ""))}</span></td></tr>'
                                   for x in rows) + "</tbody></table>")
        if c.get("ket_luan_cau"):
            parts.append(f'<p>{_eq_html(c["ket_luan_cau"])}</p>')
        ans = str(c.get("dap_an") or "").strip()
        if ans:
            parts.append(f'<span class="rxans">Đáp án {nhan}: {html.escape(ans)}</span>')
            finals.append((nhan, html.escape(ans)))
        parts.append("</div>")
        st.markdown("".join(parts), unsafe_allow_html=True)
    if finals:
        st.markdown('<div class="rxfinal"><b class="t">Kết quả cuối cùng</b>' + "".join(f"<div>{n}: <b>{a}</b></div>" for n, a in finals) + "</div>",
                    unsafe_allow_html=True)


def render_reactions(res):
    """Hiện tất cả phương trình AI đọc được: bảng tổng quan rồi mỗi phương trình một thẻ riêng, hiện sẵn toàn bộ."""
    items = reactions_of(res)
    general = _as_list((res or {}).get("luu_y_chung")) if isinstance(res, dict) else []
    st.markdown(RX_CSS, unsafe_allow_html=True)
    n = len(items)
    sol = (res or {}).get("loi_giai") if isinstance(res, dict) else None
    meta = res if isinstance(res, dict) else {}
    if meta.get("_v") != RX_BUILD:
        st.warning("Kết quả này được tạo bởi bản cũ (không có phần Lời giải). Hãy bấm lại nút **Nhận dạng và phân loại phản ứng**.")
    else:
        if meta.get("loi_giai_loi"):
            st.warning("Không giải được đề bài trong ảnh: " + meta["loi_giai_loi"])
        elif n > 1 and not sol:
            st.caption("AI không nhận ra đề bài/câu hỏi trong ảnh nên chỉ phân tích từng phương trình (không có phần Lời giải).")
    if sol and items:   # đã có lời giải thì chỉ hiện lời giải, không hiện phần phân tích chi tiết từng phương trình
        render_solution(sol)
        return
    if not items:
        st.warning("Không tìm thấy phương trình phản ứng nào trong dữ liệu đầu vào.")
    if n > 1:
        st.markdown(f'<div class="rxsum"><div class="big">{n}</div><div><b>Tìm thấy {n} phương trình trong ảnh</b>'
                    f'<small>Mỗi phương trình được phân tích đầy đủ ở bên dưới</small></div></div>', unsafe_allow_html=True)
        st.markdown('<div class="rxlist">' + "".join(
            f'<div><i>{i}</i><span>{_eq_html(it.get("phuong_trinh") or it.get("nhan") or "")}</span></div>' for i, it in enumerate(items, 1)) + "</div>",
            unsafe_allow_html=True)
    for i, it in enumerate(items, 1):
        with st.container(key=f"rxcard_{i}"):
            _rx_card_head(i, n, it)
            render_reaction(it, header=False)
    if general:
        st.info("Lưu ý: " + " • ".join(general))


def reaction_ui():
    top = st.container()  # lỗi và lý do sai hiện ở đầu tab
    src = st.radio("Nguồn phương trình", ["🖼️ Tải ảnh", "📷 Chụp ảnh", "⌨️ Gõ phương trình"], horizontal=True, key="rx_src")
    img, txt = None, None
    if src.startswith("🖼️"):
        f = st.file_uploader("Chọn ảnh phương trình", type=["jpg", "jpeg", "png", "webp"], key="rx_up")
        img = f.getvalue() if f else None
    elif src.startswith("📷"):
        f = st.camera_input("Chụp phương trình", key="rx_cam")
        img = f.getvalue() if f else None
    else:
        txt = voice_text_input("rx_txt", "Phương trình", "Ví dụ: CH2=CH2 + Br2 -> CH2Br-CH2Br").strip()
    if st.button("Nhận dạng và phân loại phản ứng", type="primary", disabled=not (img or txt), key="rx_go"):
        if over_quota():
            show_top_error(top, "Bạn đã dùng hết số lượt của phiên này. Hãy tải lại trang để tiếp tục.")
        else:
            with st.spinner("Đang phân tích…"):
                try:
                    st.session_state.rx = analyze_reaction(img, txt)
                    _items = reactions_of(st.session_state.rx)
                    _lbl = (_items[0].get('phuong_trinh') if _items else None) or txt or 'Phương trình'
                    if len(_items) > 1:
                        _lbl = f"{_lbl[:45]} (+{len(_items) - 1} phương trình)"
                    add_history(_lbl[:60], 'Phản ứng')
                    st.session_state.n += 1
                except Exception as e:
                    st.session_state.rx = None
                    show_top_error(top, "Có lỗi khi phân tích, hãy thử lại hoặc chụp rõ hơn.", e)
    if st.session_state.get("rx"):
        st.divider()
        render_reactions(st.session_state.rx)



# ---------------- Đồng phân ----------------
RULES_ISO = """Bạn là giáo viên Hóa hữu cơ Việt Nam. Xác định đồng phân theo SGK: đồng phân cấu tạo (mạch cacbon, vị trí nhóm chức hoặc liên kết bội, nhóm chức) và đồng phân lập thể (hình học cis-trans, quang học). Tên gọi dùng danh pháp tiếng Việt theo SGK (butan-1-ol, đimetyl ete, 2-metylpropan-2-ol...)."""

PRETTY = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def formula_of(m):
    return rdMolDescriptors.CalcMolFormula(m)


def pretty(f):
    return "".join(c.translate(PRETTY) if c.isdigit() else c for c in f)


def noiso(m):
    return Chem.MolToSmiles(m, isomericSmiles=False)


def stereo_count(m):
    try:
        opts = StereoEnumerationOptions(onlyUnassigned=True, unique=True, tryEmbedding=False, maxIsomers=32)
        return max(1, len(list(EnumerateStereoisomers(m, options=opts))))
    except Exception:
        return 1


def mirror(smi):
    return smi.replace("@@", "\x00").replace("@", "@@").replace("\x00", "@")


def relation(m1, m2):
    f1, f2 = formula_of(m1), formula_of(m2)
    if f1 != f2:
        return "khac_cong_thuc"
    if noiso(m1) != noiso(m2):
        return "cau_tao"
    i1, i2 = Chem.MolToSmiles(m1), Chem.MolToSmiles(m2)
    if i1 == i2:
        return "cung_chat"
    mir = Chem.MolFromSmiles(mirror(i1))
    if mir is not None and Chem.MolToSmiles(mir) == i2:
        return "doi_quang"
    if not Chem.FindMolChiralCenters(m1) and not Chem.FindMolChiralCenters(m2):
        return "hinh_hoc"
    return "lap_the"


# ---- Sinh đồng phân cấu tạo bằng thuật toán (không dùng AI) ----
VALENCE = {"C": 4, "N": 3, "O": 2, "S": 2, "F": 1, "Cl": 1, "Br": 1, "I": 1}
_BT = {1: Chem.BondType.SINGLE, 2: Chem.BondType.DOUBLE, 3: Chem.BondType.TRIPLE}
ISO_TIME = float(st.secrets.get("ISO_TIME", 15))


class TooBig(Exception):
    pass


def _canon(atoms, edges, strict=False):
    rw = Chem.RWMol()
    for e in atoms:
        rw.AddAtom(Chem.Atom(e))
    for i, j, o in edges:
        rw.AddBond(i, j, _BT[o])
    m = rw.GetMol()
    Chem.SanitizeMol(m)
    if strict:
        for b in m.GetBonds():
            if b.GetBondType() == Chem.BondType.TRIPLE and b.IsInRing():
                raise ValueError("liên kết ba trong vòng")
    return Chem.MolToSmiles(m, isomericSmiles=False)


def enumerate_isomers(counts, nH, time_limit=15, max_graphs=200000, strict=False):
    """Liệt kê TẤT CẢ đồng phân cấu tạo của công thức (mọi đồ thị liên thông đúng hóa trị, không trùng nhau).
    strict=True: chỉ mạch hở hoặc 1 vòng, không có O–O, không liên kết ba trong vòng."""
    els = sorted(counts)
    N = sum(counts.values())
    sigma = sum(VALENCE[e] * counts[e] for e in els)
    if sigma - nH < 0 or (sigma - nH) % 2:
        return []
    B = (sigma - nH) // 2
    if B < N - 1:
        return []
    t0, memo, total = time.time(), {}, [0]

    def build(sub):
        if sub in memo:
            return memo[sub]
        n = sum(sub)
        res = {}
        if n == 1:
            e = els[[i for i, c in enumerate(sub) if c][0]]
            res[_canon([e], [])] = ([e], [])
            memo[sub] = res
            return res
        upper = B - (N - n)
        for i, c in enumerate(sub):
            if not c:
                continue
            prev = list(sub)
            prev[i] -= 1
            e, vn = els[i], VALENCE[els[i]]
            for atoms, edges in list(build(tuple(prev)).values()):
                T = sum(o for _, _, o in edges)
                if T + 1 > upper:
                    continue
                used = [0] * len(atoms)
                for a, b, o in edges:
                    used[a] += o
                    used[b] += o
                free = [VALENCE[atoms[k]] - used[k] for k in range(len(atoms))]
                k = len(atoms)

                def rec(j, rem_new, added, att):
                    if time.time() - t0 > time_limit:
                        raise TooBig("time")
                    if j == k:
                        if att and T + added <= upper and (n < N or T + added == B):
                            na, ne = atoms + [e], edges + [(a, k, o) for a, o in att]
                            if strict:
                                if len(ne) - len(na) + 1 > 1:
                                    return
                                if e == "O" and any(atoms[a] == "O" for a, _ in att):
                                    return
                            try:
                                key = _canon(na, ne, strict)
                            except Exception:
                                return
                            if key not in res:
                                res[key] = (na, ne)
                                total[0] += 1
                                if total[0] > max_graphs:
                                    raise TooBig("size")
                        return
                    rec(j + 1, rem_new, added, att)
                    for o in (1, 2, 3):
                        if o <= rem_new and o <= free[j] and T + added + o <= upper:
                            rec(j + 1, rem_new - o, added + o, att + [(j, o)])

                rec(0, vn, 0, [])
        memo[sub] = res
        return res

    return sorted(build(tuple(counts[e] for e in els)).keys())


def parse_formula(s):
    s = (s or "").translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")).replace(" ", "")
    toks = re.findall(r"([A-Z][a-z]?)(\d*)", s)
    if not toks or "".join(a + b for a, b in toks) != s:
        raise ValueError("không phải công thức phân tử")
    c = {}
    for a, b in toks:
        c[a] = c.get(a, 0) + (int(b) if b else 1)
    nH = c.pop("H", 0)
    bad = [e for e in c if e not in VALENCE]
    if bad or not c:
        raise ValueError("nguyên tố chưa hỗ trợ: " + ", ".join(bad or ["?"]))
    return c, nH


def is_simple_formula(s):
    s = (s or "").translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")).replace(" ", "")
    toks = re.findall(r"([A-Z][a-z]?)(\d*)", s)
    if not toks or "".join(a + b for a, b in toks) != s:
        return False
    syms = [a for a, _ in toks]
    return len(syms) == len(set(syms)) and (any(b for _, b in toks) or "H" in syms)


def hill_key(counts, nH):
    parts = []
    if "C" in counts:
        parts.append(("C", counts["C"]))
    if nH:
        parts.append(("H", nH))
    parts += [(e, counts[e]) for e in sorted(counts) if e != "C"]
    return "".join(f"{e}{n if n > 1 else ''}" for e, n in parts)


def mol_counts(m):
    c = atom_counts(m)
    nH = c.pop("H", 0)
    return c, nH


# Phân loại theo chương trình phổ thông (dùng riêng cho tab đồng phân)
ISO_GROUPS = [
    ("ancol bậc I", "[CX4;H2,H3][OX2H]"), ("ancol bậc II", "[CX4;H1]([#6])([#6])[OX2H]"),
    ("ancol bậc III", "[CX4;H0]([#6])([#6])([#6])[OX2H]"), ("phenol", "c[OX2H]"),
    ("ete", "[#6;!$([#6]=O)][OX2][#6;!$([#6]=O)]"), ("anđehit", "[CX3;H1,H2;!$(C[OX2,NX3])]=O"),
    ("xeton", "[#6][CX3](=O)[#6]"), ("axit cacboxylic", "[CX3](=O)[OX2H1]"), ("este", "[CX3](=O)[OX2][#6]"),
    ("amin bậc I", "[NX3;H2;!$(NC=[O,N,S])][#6]"), ("amin bậc II", "[NX3;H1;!$(NC=[O,N,S])]([#6])[#6]"),
    ("amin bậc III", "[NX3;H0;!$(NC=[O,N,S])]([#6])([#6])[#6]"), ("amit", "[NX3][CX3]=O"),
    ("nitro", "[N+](=O)[O-]"), ("nitrin", "[CX2]#[NX1]"), ("anken (C=C)", "[CX3]=[CX3]"), ("ankin (C≡C)", "[CX2]#[CX2]"),
    ("hợp chất thơm", "a"), ("dẫn xuất halogen", "[#6][F,Cl,Br,I]"),
]
_ISO_GP = [(n, Chem.MolFromSmarts(p)) for n, p in ISO_GROUPS]
UNSTABLE = [
    ("enol (OH trên C=C)", "[OX2H][CX3]=[CX3]"), ("ynol (OH trên C≡C)", "[OX2H][CX2]#[CX2]"),
    ("hai nhóm OH trên cùng một C", "[CX4]([OX2H])[OX2H]"), ("hemiaxetal", "[CX4]([OX2H])[OX2][#6]"),
    ("OH và halogen trên cùng một C", "[CX4]([OX2H])[F,Cl,Br,I]"), ("OH và N trên cùng một C", "[CX4]([OX2H])[NX3]"),
]
_UNST = [(n, Chem.MolFromSmarts(p)) for n, p in UNSTABLE]


_PAIR = Chem.MolFromSmarts("[CX3](=O)[OX2,NX3]")
_NITRO = Chem.MolFromSmarts("[N+](=O)[O-]")


def func_units(m):
    """Số nhóm chức chứa dị tố: axit/este/amit và nitro mỗi nhóm chỉ tính 1 dù có nhiều nguyên tử."""
    n_het = sum(1 for a in m.GetAtoms() if a.GetSymbol() in ("O", "N", "S", "F", "Cl", "Br", "I"))
    return n_het - len(m.GetSubstructMatches(_PAIR)) - 2 * len(m.GetSubstructMatches(_NITRO))


def is_mono_open(m):
    """Đơn chức (tối đa 1 nhóm chức chứa dị tố) và không có vòng no/không thơm (vòng benzen vẫn được giữ)."""
    return func_units(m) <= 1 and not any(a.IsInRing() and not a.GetIsAromatic() for a in m.GetAtoms())


def iso_labels(m):
    lab = [n for n, p in _ISO_GP if m.HasSubstructMatch(p)]
    has_ring = any(not a.GetIsAromatic() and a.IsInRing() for a in m.GetAtoms())
    if not lab:
        if all(a.GetSymbol() == "C" for a in m.GetAtoms()):
            return ["xicloankan"] if has_ring else ["ankan"]
        lab = ["khác"]
    if has_ring:
        lab.append("có vòng không thơm")
    return lab


@st.cache_data(show_spinner=False, max_entries=64)
def iso_enumerate(fkey, strict):
    counts, nH = parse_formula(fkey)
    try:
        return {"ok": True, "smiles": enumerate_isomers(counts, nH, time_limit=ISO_TIME, strict=strict)}
    except TooBig as e:
        return {"ok": False, "why": str(e)}


def stereo_split(m):
    """(tổng, hình học, quang học): số dạng lập thể; hình học = cis/trans bỏ qua quang học; quang học = bỏ qua cis/trans."""
    try:
        opts = StereoEnumerationOptions(onlyUnassigned=True, unique=True, tryEmbedding=False, maxIsomers=64)
        isos = list(EnumerateStereoisomers(m, options=opts))
    except Exception:
        return 1, 1, 1
    geo, opt = set(), set()
    for x in isos:
        a = Chem.Mol(x)  # hình học: giữ cis/trans của nối đôi và cấu hình tương đối trên vòng; bỏ tâm bất đối ngoài vòng và gộp cặp đối quang
        for at in a.GetAtoms():
            if not at.IsInRing():
                at.SetChiralTag(Chem.ChiralType.CHI_UNSPECIFIED)
        s1 = Chem.MolToSmiles(a)
        mir = Chem.MolFromSmiles(mirror(s1))
        geo.add(min(s1, Chem.MolToSmiles(mir)) if mir is not None else s1)
        b = Chem.Mol(x)  # quang học: giữ mọi tâm bất đối, bỏ cis/trans của nối đôi
        for bd in b.GetBonds():
            if bd.GetBondType() == Chem.BondType.DOUBLE:
                bd.SetStereo(Chem.BondStereo.STEREONONE)
                bd.SetBondDir(Chem.BondDir.NONE)
        opt.add(Chem.MolToSmiles(b))
    return max(1, len(isos)), max(1, len(geo)), max(1, len(opt))


# Từ vựng nhóm mà AI được phép dùng; mỗi từ mở rộng thành các nhãn do bộ máy phân loại
GROUP_VOCAB = {
    "ankan": ["ankan"], "xicloankan": ["xicloankan"], "anken": ["anken (C=C)"], "ankin": ["ankin (C≡C)"],
    "thơm": ["hợp chất thơm"], "ancol": ["ancol bậc I", "ancol bậc II", "ancol bậc III"],
    "ancol bậc I": ["ancol bậc I"], "ancol bậc II": ["ancol bậc II"], "ancol bậc III": ["ancol bậc III"],
    "phenol": ["phenol"], "ete": ["ete"], "anđehit": ["anđehit"], "xeton": ["xeton"],
    "axit cacboxylic": ["axit cacboxylic"], "este": ["este"],
    "amin": ["amin bậc I", "amin bậc II", "amin bậc III"], "amin bậc I": ["amin bậc I"],
    "amin bậc II": ["amin bậc II"], "amin bậc III": ["amin bậc III"], "amit": ["amit"], "nitro": ["nitro"],
    "nitrin": ["nitrin"], "dẫn xuất halogen": ["dẫn xuất halogen"],
}
PRESETS = {
    "mono": {"ben": True, "chuc": "don", "mach": "ho_hoac_thom", "nhom": [], "nhom_ten": [], "kieu": "bat_ky", "lap_the": "khong", "defaults": []},
    "pho": {"ben": True, "chuc": "bat_ky", "mach": "bat_ky", "nhom": [], "nhom_ten": [], "kieu": "bat_ky", "lap_the": "khong", "defaults": []},
    "math": {"ben": False, "chuc": "bat_ky", "mach": "bat_ky", "nhom": [], "nhom_ten": [], "kieu": "bat_ky", "lap_the": "khong", "defaults": []},
}


# Điều kiện "tác dụng được với ..." (theo SGK phổ thông). Máy tự kiểm tra từ cấu tạo, AI không quyết định.
REAGENT_SMARTS = {
    "Na": ["[OX2H]"],                                                    # H linh động của nhóm -OH: ancol, phenol, axit cacboxylic
    "NaOH": ["[CX3](=O)[OX2H1]", "c[OX2H]", "[CX3](=O)[OX2][#6]", "[#6][F,Cl,Br,I]"],   # axit, phenol, este (thủy phân), dẫn xuất halogen
    "NaHCO3": ["[CX3](=O)[OX2H1]"],                                      # chỉ axit cacboxylic giải phóng CO2
    "AgNO3/NH3": ["[CX3H1]=O", "[CX2H]#[CX2]"],                          # nhóm -CHO (anđehit, HCOO-) và ankin-1
    "dung dịch brom": ["[CX3]=[CX3]", "[CX2]#[CX2]", "[CX3H1]=O"],       # liên kết bội và nhóm -CHO
}
_RX = {k: [Chem.MolFromSmarts(x) for x in v] for k, v in REAGENT_SMARTS.items()}
RX_ALIAS = {"na": "Na", "kim loại na": "Na", "naoh": "NaOH", "dung dịch naoh": "NaOH", "nahco3": "NaHCO3", "agno3/nh3": "AgNO3/NH3",
            "tráng bạc": "AgNO3/NH3", "tráng gương": "AgNO3/NH3", "dung dịch brom": "dung dịch brom", "nước brom": "dung dịch brom", "br2": "dung dịch brom"}


def reacts(m, key):
    return any(m.HasSubstructMatch(pt) for pt in _RX[key])


def _rx_names(lst):
    out = []
    for g in lst or []:
        k = RX_ALIAS.get(str(g).strip().lower())
        if k and k not in out:
            out.append(k)
    return out


def norm_params(raw):
    """Kiểm tra tham số AI trích ra: chỉ nhận giá trị trong danh mục. Giá trị AI để trống thì dùng mặc định và ghi rõ."""
    raw = raw or {}
    warn, defaults = [], []
    names = []
    for g in raw.get("nhom") or []:
        key = str(g).strip().lower().replace("đ", "đ")
        hit = next((k for k in GROUP_VOCAB if k.lower() == key), None)
        if hit:
            names.append(hit)
        else:
            warn.append(f"Bỏ qua nhóm không có trong danh mục: {g}")
    p = {"ben": True, "nhom_ten": names, "nhom": [GROUP_VOCAB[n] for n in names]}
    kieu = raw.get("kieu_nhom")
    p["kieu"] = kieu if kieu in ("bat_ky", "tat_ca") else "bat_ky"
    for k, ok, dflt in (("chuc", ("don", "da", "bat_ky"), "don"), ("mach", ("ho", "vong", "bat_ky"), "ho_hoac_thom"),
                        ("lap_the", ("khong", "hinh_hoc", "quang_hoc", "tat_ca"), "khong")):
        v = raw.get(k)
        if v in ok:
            p[k] = v
        else:
            p[k] = dflt
            defaults.append(k)
    if "xicloankan" in names and "mach" in defaults:
        p["mach"] = "bat_ky"
    p["phan_ung"] = _rx_names(raw.get("phan_ung"))
    p["khong_phan_ung"] = [k for k in _rx_names(raw.get("khong_phan_ung")) if k not in p["phan_ung"]]
    p["kieu_pu"] = "bat_ky" if raw.get("kieu_phan_ung") == "bat_ky" else "tat_ca"
    if (p["phan_ung"] or p["khong_phan_ung"]) and "chuc" in defaults and "mach" in defaults:
        p["chuc"] = p["mach"] = "bat_ky"   # hỏi theo tính chất hóa học thì xét mọi cấu tạo, không giới hạn đơn chức mạch hở
    p["defaults"] = defaults
    return p, warn


def pass_filters(m, labels, p):
    u = func_units(m)
    if (p["chuc"] == "don" and u > 1) or (p["chuc"] == "da" and u < 2):
        return False
    rings = m.GetRingInfo().NumRings()
    nonarom = any(a.IsInRing() and not a.GetIsAromatic() for a in m.GetAtoms())
    if (p["mach"] == "ho" and rings) or (p["mach"] == "vong" and not rings) or (p["mach"] == "ho_hoac_thom" and nonarom):
        return False
    if p["nhom"]:
        hit = [bool(set(labels) & set(g)) for g in p["nhom"]]
        if not (all(hit) if p["kieu"] == "tat_ca" else any(hit)):
            return False
    if p.get("phan_ung"):
        hit = [reacts(m, k) for k in p["phan_ung"]]
        if not (all(hit) if p.get("kieu_pu") != "bat_ky" else any(hit)):
            return False
    if any(reacts(m, k) for k in p.get("khong_phan_ung") or []):
        return False
    return True


PARSE_PROMPT = """Bạn là bộ PHÂN TÍCH CÂU HỎI Hóa học. Nhiệm vụ DUY NHẤT: trích tham số từ câu hỏi về đồng phân. TUYỆT ĐỐI không đếm, không liệt kê chất, không trả lời câu hỏi.
Từ vựng nhóm (chỉ dùng đúng các chuỗi này): ankan, xicloankan, anken, ankin, thơm, ancol, ancol bậc I, ancol bậc II, ancol bậc III, phenol, ete, anđehit, xeton, axit cacboxylic, este, amin, amin bậc I, amin bậc II, amin bậc III, amit, nitro, nitrin, dẫn xuất halogen.
Chỉ trả về MỘT đối tượng JSON, không markdown:
{"cong_thuc":"công thức phân tử viết liền, ví dụ C4H8O2, hoặc null",
"chat_goc":"tên hoặc SMILES của chất nếu câu hỏi nhắc một chất cụ thể thay vì công thức, hoặc null",
"nhom":["nhóm mà đồng phân cần tìm phải thuộc, lấy từ từ vựng; để [] nếu câu hỏi không nêu nhóm"],
"kieu_nhom":"bat_ky nếu chỉ cần thuộc ít nhất một nhóm, tat_ca nếu phải có đồng thời mọi nhóm, null nếu không nêu",
"phan_ung":["các chất mà đồng phân PHẢI tác dụng được, chỉ dùng: Na, NaOH, NaHCO3, AgNO3/NH3, dung dịch brom; [] nếu không nêu"],
"khong_phan_ung":["các chất mà đồng phân KHÔNG được tác dụng (câu hỏi nói 'không tác dụng với ...'), cùng danh mục trên; [] nếu không nêu"],
"kieu_phan_ung":"tat_ca nếu phải tác dụng đồng thời (và), bat_ky nếu chỉ cần một trong các chất (hoặc), null nếu không nêu",
"chuc":"don nếu câu hỏi nói đơn chức, da nếu nói đa chức hoặc tạp chức, bat_ky nếu nói rõ tính mọi loại, null nếu không nhắc",
"mach":"ho nếu mạch hở, vong nếu mạch vòng, bat_ky nếu nói rõ tính cả hai, null nếu không nhắc",
"lap_the":"khong nếu nói không tính đồng phân lập thể, hinh_hoc nếu tính thêm đồng phân hình học (cis-trans), quang_hoc nếu tính thêm đồng phân quang học, tat_ca nếu tính mọi đồng phân lập thể, null nếu không nhắc",
"can_hoi_lai":"một câu hỏi làm rõ nếu thiếu công thức hoặc chất, hoặc câu hỏi mơ hồ; nếu không thì để rỗng",
"tom_tat":"câu hỏi được hiểu lại ngắn gọn bằng tiếng Việt"}
Tính chất hóa học (tác dụng được với Na, NaOH...) đặt vào phan_ung, TUYỆT ĐỐI không suy ra nhóm chức từ tính chất. Nếu câu hỏi nêu tính chất ngoài danh mục (ví dụ tác dụng với Cu(OH)2, với H2) thì ghi vào can_hoi_lai là chưa hỗ trợ điều kiện đó. Không đoán những gì câu hỏi không nói: để null hoặc []. Ví dụ: 'Có bao nhiêu đồng phân este của C4H8O2?' thì nhom=["este"], cong_thuc="C4H8O2", các mục còn lại null."""


def parse_question(q):
    raw = ask_ai([PARSE_PROMPT + "\n\nCâu hỏi: " + q], temperature=0, lang_note=False)
    p, warn = norm_params(raw)
    return p, warn, raw


def resolve_formula(img, txt):
    """Trả về (counts, nH, SMILES chất gốc hoặc None, lỗi hoặc None)."""
    if img:
        smi, _ = transcribe_student(img)
        m, err = parse_student(smi)
        if m is None:
            return None, None, None, "Hình vẽ sai nên không xác định được công thức: " + (err or "không đọc được hình")
    elif is_simple_formula(txt):
        try:
            c, h = parse_formula(txt)
            return c, h, None, None
        except ValueError as e:
            return None, None, None, f"Công thức không hợp lệ ({e})."
    else:
        m, err = parse_student(txt) if smiles_like(txt) else (None, None)
        if m is None:
            smi = to_smiles(None, txt)  # tên chất hoặc công thức thu gọn: nhờ AI đổi sang SMILES
            m, err = parse_student(smi)
            if m is None:
                return None, None, None, "Không hiểu chất đã nhập. Hãy gõ công thức phân tử (ví dụ C4H10O), SMILES hoặc tên chất."
    c, h = mol_counts(m)
    if any(e not in VALENCE for e in c):
        return None, None, None, "Chất có nguyên tố chưa được hỗ trợ."
    return c, h, Chem.MolToSmiles(m, isomericSmiles=False), None


def ai_names(smiles_list):
    """Nhờ AI đặt tên. Cấu trúc do thuật toán sinh nên chỉ phần tên có thể sai."""
    lines = "\n".join(f"{i + 1}. {s_}" for i, s_ in enumerate(smiles_list))
    r = ask_ai([RULES_ISO + "\n\nĐặt tên theo danh pháp SGK cho từng chất sau (theo đúng thứ tự). "
                'Chỉ trả JSON {"ten":["tên 1","tên 2",...]} có đúng ' + str(len(smiles_list)) + " phần tử.\n" + lines], temperature=0)
    names = r.get("ten") or []
    return {s_: (names[i] if i < len(names) else "") for i, s_ in enumerate(smiles_list)}


_SMI_RE = re.compile(r"[A-Za-z0-9@+\-\[\]()=#$/\\%.:]+")


def smiles_like(t):
    """Chuỗi giống SMILES thật: không có khoảng trắng hoặc chữ có dấu. Tránh câu tiếng Việt như 'Có bao nhiêu...' bị RDKit đọc nhầm."""
    t = (t or "").strip()
    return bool(t) and _SMI_RE.fullmatch(t) is not None and Chem.MolFromSmiles(t) is not None


def to_smiles(img, text):
    if smiles_like(text):
        return text
    prompt = RULES + '\n\nChuyển chất sau thành SMILES chuẩn. Chỉ trả JSON {"smiles":"","ten":""}, để rỗng nếu không đọc được.'
    if img:
        r = ask_ai([types.Part.from_bytes(data=to_jpeg(img), mime_type="image/jpeg"), prompt])
    elif text:
        r = ask_ai([prompt + "\nChất: " + text])
    else:
        return ""
    return (r.get("smiles") or "").strip()


REL = {
    "cung_chat": ("warning", "Hai công thức biểu diễn **cùng một chất**, không phải đồng phân."),
    "khac_cong_thuc": ("error", "**Không phải đồng phân** vì khác công thức phân tử."),
    "cau_tao": ("success", "Hai chất là **đồng phân cấu tạo** của nhau."),
    "hinh_hoc": ("success", "Hai chất là **đồng phân hình học (cis–trans)** của nhau."),
    "doi_quang": ("success", "Hai chất là **đồng phân quang học (đối quang)** của nhau."),
    "lap_the": ("success", "Hai chất là **đồng phân lập thể** (không phải đối quang) của nhau."),
}


def compare_ui_result(s1, s2):
    m1, m2 = Chem.MolFromSmiles(s1), Chem.MolFromSmiles(s2)
    if m1 is None or m2 is None:
        st.error("Không đọc được một trong hai chất. Hãy kiểm tra lại ảnh hoặc nhập SMILES.")
        return
    c1, c2 = st.columns(2)
    for col, m, s_, tag in ((c1, m1, s1, "A"), (c2, m2, s2, "B")):
        with col:
            st.markdown(f"**Chất {tag}**")
            st.image(Draw.MolToImage(m, size=(320, 240)))
            st.markdown(f"{pretty(formula_of(m))} · M = {Descriptors.MolWt(m):.2f} g/mol")
            st.code(s_, language=None)
    rel = relation(m1, m2)
    kind, msg = REL[rel]
    getattr(st, kind)(msg)
    if rel == "khac_cong_thuc":
        st.markdown(f"{pretty(formula_of(m1))} ≠ {pretty(formula_of(m2))}")
        return
    if rel == "cung_chat":
        return
    try:
        r = ask_ai([RULES_ISO + f'\n\nChất A: {s1}\nChất B: {s2}\nRDKit đã xác nhận quan hệ: {msg}\n'
                    'Hãy đặt tên hai chất và giải thích ngắn gọn theo SGK. Chỉ trả JSON '
                    '{"ten_A":"","ten_B":"","loai_dong_phan":"ví dụ: đồng phân nhóm chức","giai_thich":"2-3 câu: điểm khác nhau về cấu tạo hoặc không gian"}'])
        st.markdown(f"**Tên:** A = {r.get('ten_A', '')}; B = {r.get('ten_B', '')}")
        if r.get("loai_dong_phan"):
            st.markdown("**Loại đồng phân:** " + r["loai_dong_phan"])
        if r.get("giai_thich"):
            st.markdown(r["giai_thich"])
    except Exception as e:
        st.caption(f"Không lấy được phần giải thích: {type(e).__name__}")


def build_iso_result(fkey, orig, p):
    """Bộ máy hóa học: sinh toàn bộ đồng phân, kiểm tra và đếm theo tham số p. AI không tham gia."""
    out = iso_enumerate(fkey, p["ben"])
    if not out["ok"]:
        return {"ok": False, "why": out["why"], "fkey": fkey}
    kept, excluded, hidden = [], {}, 0
    for smi in out["smiles"]:
        m = Chem.MolFromSmiles(smi)
        if p["ben"]:
            bad = next((n for n, pt in _UNST if m.HasSubstructMatch(pt)), None)
            if bad:
                excluded[bad] = excluded.get(bad, 0) + 1
                continue
        labels = iso_labels(m)
        if not pass_filters(m, labels, p):
            hidden += 1
            continue
        tot, geo, opt = stereo_split(m)
        kept.append({"smiles": smi, "labels": labels, "stereo": tot, "geo": geo, "opt": opt})
    return {"ok": True, "fkey": fkey, "params": p, "kept": kept, "excluded": excluded, "hidden": hidden,
            "total_math": len(out["smiles"]), "orig": orig}


LB_CHUC = {"don": "đơn chức", "da": "đa chức hoặc tạp chức", "bat_ky": "mọi loại chức"}
LB_MACH = {"ho": "mạch hở", "vong": "mạch vòng", "ho_hoac_thom": "mạch hở hoặc vòng benzen", "bat_ky": "mọi loại mạch"}
LB_LT = {"khong": "không tính đồng phân lập thể", "hinh_hoc": "kể cả đồng phân hình học (cis–trans)",
         "quang_hoc": "kể cả đồng phân quang học", "tat_ca": "kể cả mọi đồng phân lập thể"}


def answer_of(r):
    k, lt = r["kept"], r["params"]["lap_the"]
    return {"hinh_hoc": sum(x["geo"] for x in k), "quang_hoc": sum(x["opt"] for x in k),
            "tat_ca": sum(x["stereo"] for x in k)}.get(lt, len(k))


def render_iso(r, names):
    kept, p = r["kept"], r["params"]
    nh = " hoặc ".join(p["nhom_ten"])
    cond = []
    if p.get("phan_ung"):
        cond.append("tác dụng được với " + (" và " if p.get("kieu_pu") != "bat_ky" else " hoặc ").join(p["phan_ung"]))
    if p.get("khong_phan_ung"):
        cond.append("không tác dụng với " + ", ".join(p["khong_phan_ung"]))
    nh = " · ".join(x for x in [nh] + cond if x)
    st.success(f"**{answer_of(r)} đồng phân** của {pretty(r['fkey'])}" + (f" ({nh})" if nh else ""))
    hid = r["hidden"] + (sum(r["excluded"].values()) if p["ben"] else 0)
    st.caption(f"Cấu tạo {len(kept)} · kể cả hình học {sum(k['geo'] for k in kept)} · quang học {sum(k['opt'] for k in kept)} · "
               f"lập thể {sum(k['stereo'] for k in kept)} · đã ẩn hoặc loại {hid}")
    comp = {}
    for k in kept:
        for lb in k["labels"]:
            d = comp.setdefault(lb, [0, 0])
            d[0] += 1
            d[1] += k["stereo"]
    with st.expander("Thống kê theo nhóm"):
        st.dataframe([{"Nhóm": n, "Cấu tạo": v[0], "Kể cả lập thể": v[1]} for n, v in sorted(comp.items())], hide_index=True, width="stretch")
        if r["params"]["ben"] and r["excluded"]:
            st.caption("Đã loại cấu trúc kém bền: " + ", ".join(f"{n} ({v})" for n, v in r["excluded"].items()))
    pick = st.multiselect("Lọc theo nhóm", sorted(comp), key="iso_filter")
    shown = [k for k in kept if not pick or any(lb in pick for lb in k["labels"])]
    if pick:
        st.caption(f"{len(shown)} đồng phân cấu tạo thuộc nhóm đã chọn.")
    orig = r.get("orig")
    hit = next((i for i, k in enumerate(kept, 1) if k["smiles"] == orig), None) if orig else None
    if hit:
        st.info(f"Chất bạn nhập là đồng phân số {hit}.")
    rows = [{"STT": i, "Nhóm": " + ".join(k["labels"]),
             "Lập thể": "không" if k["stereo"] == 1 else f"{k['stereo']} dạng",
             **({"Tên (AI)": names.get(k["smiles"], "")} if names else {}), "SMILES": k["smiles"]} for i, k in enumerate(shown, 1)]
    st.dataframe(rows[:200], hide_index=True, width="stretch")
    if len(rows) > 200:
        st.caption(f"Hiện 200 dòng đầu trong {len(rows)}. Hãy lọc theo nhóm.")
    if rows:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
        st.download_button("⬇️ Tải CSV", buf.getvalue().encode("utf-8-sig"), file_name=f"dong_phan_{r['fkey']}.csv", mime="text/csv", key="iso_dl")
    ms = [Chem.MolFromSmiles(k["smiles"]) for k in shown[:48]]
    if ms:
        try:
            st.image(Draw.MolsToGridImage(ms, molsPerRow=4, subImgSize=(230, 180), legends=[str(i) for i in range(1, len(ms) + 1)]))
        except Exception:
            pass


def render_understood(u, r):
    """Một dòng cho biết máy hiểu câu hỏi thế nào (chỉ khi AI đọc câu hỏi)."""
    if not u:
        return
    p = r["params"]
    dflt = set(p.get("defaults", []))
    nhom = (" và " if p["kieu"] == "tat_ca" else " hoặc ").join(p["nhom_ten"]) or "mọi nhóm"
    bits = [f"nhóm: {nhom}", LB_CHUC[p["chuc"]] + ("*" if "chuc" in dflt else ""), LB_MACH[p["mach"]] + ("*" if "mach" in dflt else ""),
            LB_LT[p["lap_the"]] + ("*" if "lap_the" in dflt else "")]
    st.caption("Máy hiểu: " + " · ".join(bits) + ("  (*: mặc định vì câu hỏi không nêu)" if dflt else ""))
    if u.get("chat_goc") and r.get("orig"):
        st.caption(f"Chất được nhắc tới: {u['chat_goc']}")
        try:
            st.image(Draw.MolToImage(Chem.MolFromSmiles(r["orig"]), size=(220, 150)))
        except Exception:
            pass
    for w in u.get("warn") or []:
        st.caption(w)


def isomer_ui():
    top = st.container()  # lỗi và lý do sai hiện ở đầu tab
    t1, t2 = st.tabs(["Liệt kê đồng phân", "So sánh hai chất"])
    with t1:
        q = voice_text_input("iso_q", "Câu hỏi hoặc công thức",
                             "Ví dụ: số đồng phân este của C4H8O2   ·   C4H10O").strip()
        with st.expander("Tùy chọn"):
            scope = st.radio("Phạm vi khi chỉ nhập công thức", ["Đơn chức, mạch hở (đề SGK)", "Phổ thông (cả đa chức và 1 vòng)",
                                                               "Toán học (mọi cấu trúc)"], key="iso_scope")
            want_names = st.checkbox("Gọi tên bằng AI (có thể sai)", key="iso_names")
            f = st.file_uploader("Hoặc dùng ảnh công thức", type=["jpg", "jpeg", "png", "webp"], key="iso_up")
        img = f.getvalue() if f else None
        if st.button("Đếm đồng phân", type="primary", disabled=not (q or img), key="iso_go"):
            direct = bool(img) or is_simple_formula(q) or smiles_like(q)
            ai_used = bool(img or want_names or not direct)
            if ai_used and over_quota():
                show_top_error(top, "Bạn đã dùng hết số lượt của phiên này. Hãy tải lại trang để tiếp tục.")
            else:
                with st.spinner("Đang tính…"):
                    try:
                        st.session_state.iso = None
                        counts = nH = orig = err = und = None
                        if direct:
                            counts, nH, orig, err = resolve_formula(img, q)
                            p = dict(PRESETS["mono" if scope.startswith("Đơn") else ("pho" if scope.startswith("Phổ") else "math")])
                        else:
                            p, warn, raw = parse_question(q)
                            ftxt, gc = raw.get("cong_thuc"), raw.get("chat_goc")
                            und = {"warn": warn, "chat_goc": gc}
                            if ftxt and is_simple_formula(str(ftxt)):
                                counts, nH = parse_formula(str(ftxt))
                            elif gc:
                                counts, nH, orig, err = resolve_formula(None, str(gc))
                            else:
                                err = raw.get("can_hoi_lai") or "Câu hỏi chưa có công thức hoặc tên chất."
                        if err:
                            show_top_error(top, err)
                        else:
                            n_heavy = sum(counts.values())
                            fkey = hill_key(counts, nH)
                            if n_heavy > 12:
                                show_top_error(top, f"{pretty(fkey)} có {n_heavy} nguyên tử khác H, quá lớn để liệt kê chính xác (tối đa 12).")
                            else:
                                res = build_iso_result(fkey, orig, p)
                                if not res["ok"]:
                                    show_top_error(top, f"{pretty(fkey)} có quá nhiều đồng phân để sinh trong {ISO_TIME:.0f} giây. Hãy nêu rõ nhóm chức.")
                                else:
                                    nm = {}
                                    if want_names and 0 < len(res["kept"]) <= 60:
                                        nm = ai_names([k["smiles"] for k in res["kept"]])
                                    st.session_state.iso, st.session_state.iso_nm, st.session_state.iso_und = res, nm, und
                                    add_history(pretty(res['fkey']), 'Đồng phân')
                                    if ai_used:
                                        st.session_state.n += 1
                    except Exception as e:
                        st.session_state.iso = None
                        show_top_error(top, "Có lỗi, hãy thử lại.", e)
        res = st.session_state.get("iso")
        if res:
            st.divider()
            render_understood(st.session_state.get("iso_und"), res)
            if res["kept"]:
                render_iso(res, st.session_state.get("iso_nm") or {})
            else:
                st.warning(f"Không có đồng phân nào của {pretty(res['fkey'])} thỏa điều kiện (đã ẩn {res['hidden']}).")
    with t2:
        st.caption("Mỗi chất nhập bằng ảnh, SMILES hoặc tên.")
        ca, cb = st.columns(2)
        inp = []
        for col, tag in ((ca, "A"), (cb, "B")):
            with col:
                st.markdown(f"**Chất {tag}**")
                f = st.file_uploader(f"Ảnh chất {tag}", type=["jpg", "jpeg", "png", "webp"], key=f"cmp_up{tag}")
                t = st.text_input(f"Hoặc SMILES/tên chất {tag}", key=f"cmp_t{tag}").strip()
                inp.append((f.getvalue() if f else None, t))
        ok = all(i or t for i, t in inp)
        if st.button("So sánh", type="primary", disabled=not ok, key="cmp_go"):
            if over_quota():
                show_top_error(top, "Bạn đã dùng hết số lượt của phiên này. Hãy tải lại trang để tiếp tục.")
            else:
                with st.spinner("Đang phân tích…"):
                    try:
                        smi = [to_smiles(i, t) for i, t in inp]
                        st.session_state.n += 1
                        st.session_state.cmp = smi
                    except Exception as e:
                        st.session_state.cmp = None
                        show_top_error(top, "Có lỗi khi đọc chất, hãy thử lại.", e)
        if st.session_state.get("cmp"):
            st.divider()
            compare_ui_result(*st.session_state.cmp)



# ---------------- Dụng cụ thí nghiệm ----------------
RULES_EQ = """Bạn là giáo viên Hóa học Việt Nam hướng dẫn thực hành thí nghiệm ở trường phổ thông. Hãy nhận biết dụng cụ thí nghiệm theo tên gọi trong SGK Việt Nam, ví dụ: ống nghiệm, cốc thủy tinh, bình tam giác, bình cầu (đáy tròn, đáy bằng, có nhánh), phễu lọc, phễu chiết, đèn cồn, kẹp ống nghiệm, giá sắt, kiềng đun, lưới amiăng, ống đong, pipet, buret, bình định mức, cối và chày sứ, chén sứ, đũa thủy tinh, thìa lấy hóa chất, nhiệt kế, ống sinh hàn, bình Kíp, ống dẫn khí, nút cao su, giấy lọc, cân, bình tia, giá để ống nghiệm. Chỉ nêu những gì thấy rõ trong ảnh; nếu không chắc thì giảm độ tin cậy và nói rõ."""

EFMT = """Chỉ trả về MỘT đối tượng JSON, không markdown, không lời dẫn:
{"loai_anh":"dụng cụ riêng lẻ | bộ lắp thí nghiệm | không phải dụng cụ thí nghiệm",
"dung_cu":[{"ten":"tên theo SGK","ten_khac":"tên gọi khác hoặc tên tiếng Anh, có thể rỗng","vi_tri":"vị trí trong ảnh, ví dụ: bên trái, ở giữa","chat_lieu":"thủy tinh | sứ | kim loại | nhựa | cao su | ...","cong_dung":"1-2 câu","cach_dung":["bước hoặc lưu ý sử dụng"],"luu_y_an_toan":["điều cần chú ý để an toàn"],"do_tin_cay":số 0-1}],
"thi_nghiem":null hoặc {"ten":"thí nghiệm có thể đang lắp, ví dụ: điều chế khí oxi từ KMnO4","mo_ta":"1-2 câu","nhan_xet_lap_rap":["điểm đúng hoặc điểm có thể sai/nguy hiểm trong cách lắp, chỉ nêu khi nhìn thấy rõ"]},
"luu_y":["điều chưa chắc chắn, ví dụ ảnh mờ, bị che khuất"]}
Nếu ảnh có nhiều dụng cụ thì liệt kê từng dụng cụ nhận ra được. Chỉ đặt thi_nghiem khi ảnh là một bộ lắp ráp rõ ràng. Nếu không phải dụng cụ thí nghiệm, để dung_cu rỗng và giải thích trong luu_y."""


def analyze_equipment(img, text):
    head = RULES_EQ + "\n\n"
    if img:
        return ask_ai([types.Part.from_bytes(data=to_jpeg(img), mime_type="image/jpeg"),
                       head + "Đây là ảnh dụng cụ thí nghiệm hóa học. Hãy nhận biết.\n" + EFMT])
    return ask_ai([head + "Hãy giải thích dụng cụ có tên: " + text + ".\n" + EFMT])


def render_equipment(r):
    kind = r.get("loai_anh")
    tools = r.get("dung_cu") or []
    if kind:
        st.markdown(f"**Loại ảnh:** {kind}")
    if not tools:
        st.warning("Chưa nhận ra dụng cụ thí nghiệm nào trong ảnh.")
    for t in tools:
        with st.container(border=True):
            st.markdown(f"### {t.get('ten', 'Dụng cụ')}")
            if t.get("ten_khac"):
                st.caption(f"Tên khác: {t['ten_khac']}")
            meta = [x for x in (t.get("vi_tri"), t.get("chat_lieu")) if x]
            if meta:
                st.markdown("**Vị trí / chất liệu:** " + " · ".join(meta))
            conf = t.get("do_tin_cay")
            if isinstance(conf, (int, float)):
                p = max(0.0, min(1.0, float(conf)))
                st.progress(p, text=f"Độ tin cậy: {round(p * 100)}%")
                if p < 0.6:
                    st.warning("Độ tin cậy thấp, hãy hỏi giáo viên hoặc chụp lại rõ hơn.")
            if t.get("cong_dung"):
                st.markdown("**Công dụng:** " + t["cong_dung"])
            bullets("Cách dùng", t.get("cach_dung"))
            if t.get("luu_y_an_toan"):
                st.warning("**An toàn:** " + " • ".join([t["luu_y_an_toan"]] if isinstance(t["luu_y_an_toan"], str) else t["luu_y_an_toan"]))
    tn = r.get("thi_nghiem")
    if isinstance(tn, dict) and (tn.get("ten") or tn.get("mo_ta")):
        st.divider()
        st.markdown("### Bộ thí nghiệm trong ảnh")
        if tn.get("ten"):
            st.markdown("**Có thể là:** " + tn["ten"])
        if tn.get("mo_ta"):
            st.markdown(tn["mo_ta"])
        bullets("Nhận xét về cách lắp", tn.get("nhan_xet_lap_rap"))
    if r.get("luu_y"):
        st.info("Lưu ý: " + " • ".join([r["luu_y"]] if isinstance(r["luu_y"], str) else r["luu_y"]))
    st.caption("Kết quả do AI nhận biết qua ảnh nên có thể nhầm, nhất là khi ảnh mờ hoặc dụng cụ bị che. "
               "Khi làm thí nghiệm thật, hãy làm theo hướng dẫn của giáo viên và quy định an toàn của phòng thực hành.")


def equipment_ui():
    top = st.container()  # lỗi và lý do sai hiện ở đầu tab
    _m = st.radio("Chức năng", ["Nhận biết dụng cụ", "Mô phỏng thí nghiệm"], horizontal=True, key="eq_mode")
    if _m.startswith("Mô phỏng"):
        _sim_ui(top)
        return
    src = st.radio("Nguồn", ["🖼️ Tải ảnh", "📷 Chụp ảnh", "⌨️ Gõ tên dụng cụ"], horizontal=True, key="eq_src")
    img, txt = None, None
    if src.startswith("📷"):
        f = st.camera_input("Chụp dụng cụ hoặc bộ thí nghiệm", key="eq_cam")
        img = f.getvalue() if f else None
    elif src.startswith("🖼️"):
        f = st.file_uploader("Ảnh dụng cụ hoặc bộ thí nghiệm", type=["jpg", "jpeg", "png", "webp"], key="eq_up")
        img = f.getvalue() if f else None
    else:
        txt = st.text_input("Tên dụng cụ", placeholder="Ví dụ: ống sinh hàn", key="eq_txt").strip()
    if st.button("Nhận biết dụng cụ", type="primary", disabled=not (img or txt), key="eq_go"):
        if over_quota():
            show_top_error(top, "Bạn đã dùng hết số lượt của phiên này. Hãy tải lại trang để tiếp tục.")
        else:
            with st.spinner("Đang phân tích…"):
                try:
                    st.session_state.eq = analyze_equipment(img, txt)
                    add_history(txt or ', '.join(str(t.get('ten', '')) for t in ((st.session_state.eq or {}).get('dung_cu') or [])[:2]) or 'Dụng cụ', 'Dụng cụ')
                    st.session_state.n += 1
                except Exception as e:
                    st.session_state.eq = None
                    show_top_error(top, "Có lỗi khi phân tích, hãy thử lại hoặc chụp rõ hơn.", e)
    if st.session_state.get("eq"):
        st.divider()
        render_equipment(st.session_state.eq)



# ---------------- Chẩn đoán lỗi & chấm bài ----------------
GROUPS = [
    ("ancol", "[CX4][OX2H]"), ("phenol", "c[OX2H]"), ("ete", "[CX4][OX2][CX4]"),
    ("anđehit", "[CX3;H1,H2;!$(C[OX2,NX3])]=O"), ("xeton", "[#6][CX3](=O)[#6]"),
    ("axit cacboxylic", "[CX3](=O)[OX2H1]"), ("este", "[CX3](=O)[OX2][#6]"),
    ("amin", "[NX3;!$(NC=[O,N,S])][#6]"), ("nitro", "[N+](=O)[O-]"),
    ("anken (C=C)", "[CX3]=[CX3]"), ("ankin (C≡C)", "[CX2]#[CX2]"),
    ("vòng benzen", "c1ccccc1"), ("dẫn xuất halogen", "[#6][F,Cl,Br,I]"),
]
_GP = [(n, Chem.MolFromSmarts(p)) for n, p in GROUPS]


def groups_of(m):
    return [n for n, p in _GP if m.HasSubstructMatch(p)]


def atom_counts(m):
    c = {}
    for a in Chem.AddHs(m).GetAtoms():
        c[a.GetSymbol()] = c.get(a.GetSymbol(), 0) + 1
    return c


def diff_text(ms, mt):
    a, b = atom_counts(ms), atom_counts(mt)
    order = ["C", "H"] + sorted(k for k in set(a) | set(b) if k not in ("C", "H"))
    out = []
    for k in order:
        d = a.get(k, 0) - b.get(k, 0)
        if d > 0:
            out.append(f"thừa {d} nguyên tử {k}")
        elif d < 0:
            out.append(f"thiếu {-d} nguyên tử {k}")
    return ", ".join(out)


def parse_student(smi):
    """Trả về (mol, thông báo lỗi bằng tiếng Việt)."""
    smi = (smi or "").strip()
    if not smi:
        return None, "Chưa đọc được công thức em vẽ."
    m = Chem.MolFromSmiles(smi, sanitize=False)
    if m is None:
        return None, "Công thức bị sai cú pháp (thiếu hoặc thừa ngoặc, vòng chưa đóng hoặc ký hiệu lạ)."
    try:
        Chem.SanitizeMol(m)
    except Chem.AtomValenceException as e:
        mm = re.search(r"atom # (\d+) (\w+), (\d+)", str(e))
        if mm:
            return None, f"Nguyên tử {mm.group(2)} thứ {int(mm.group(1)) + 1} có hóa trị {mm.group(3)}, vượt quá hóa trị cho phép."
        return None, "Có nguyên tử vượt quá hóa trị cho phép."
    except Chem.KekulizeException:
        return None, "Vòng thơm vẽ sai: không sắp xếp được các nối đôi xen kẽ trong vòng."
    except Exception:
        return None, "Công thức có lỗi hóa trị."
    return m, None


def draw_student(smi, size=(320, 220)):
    """Vẽ lại đúng hình học sinh đã vẽ, kể cả khi sai hóa trị; khoanh đỏ nguyên tử sai nếu có."""
    m = Chem.MolFromSmiles((smi or "").strip(), sanitize=False)
    if m is None:
        return None
    bad = []
    try:
        Chem.SanitizeMol(m)
    except Chem.AtomValenceException as e:
        mm = re.search(r"atom # (\d+)", str(e))
        if mm:
            bad = [int(mm.group(1))]
    except Exception:
        pass
    try:
        m.UpdatePropertyCache(strict=False)
        Chem.FastFindRings(m)
        return Draw.MolToImage(m, size=size, highlightAtoms=bad, highlightColor=(1.0, 0.55, 0.55))
    except Exception:
        return None


def grade_structure(smi, target_smi):
    mt = Chem.MolFromSmiles(target_smi)
    ms, err = parse_student(smi)
    tips = ["Nhớ hóa trị: C có 4 liên kết, N có 3, O có 2, H và halogen có 1."]
    if ms is None:
        return {"kq": "loi", "nx": [err], "goi_y": tips}
    fs, ft = formula_of(ms), formula_of(mt)
    if noiso(ms) == noiso(mt):
        return {"kq": "dung", "nx": ["Chính xác. Công thức cấu tạo em vẽ đúng."], "goi_y": []}
    gs, gt = set(groups_of(ms)), set(groups_of(mt))
    if fs == ft:
        nx = [f"Công thức phân tử đúng ({pretty(fs)}) nhưng cấu tạo chưa đúng yêu cầu: em đã vẽ một đồng phân khác."]
        if gs != gt:
            nx.append("Nhóm chức khác với chất cần tìm. Hình em vẽ có: " + (", ".join(sorted(gs)) or "không có nhóm chức đặc trưng")
                      + ". Đề cần: " + (", ".join(sorted(gt)) or "không có nhóm chức đặc trưng") + ".")
            nx.append("Loại đồng phân em đã vẽ: đồng phân nhóm chức.")
        else:
            nx.append("Nhóm chức đúng nhưng mạch cacbon hoặc vị trí nhóm thế/liên kết bội chưa đúng.")
        return {"kq": "dong_phan", "nx": nx, "goi_y": ["Đếm lại số cacbon ở mạch chính và vị trí gắn nhóm thế."]}
    nx = [f"Công thức phân tử của hình em vẽ là {pretty(fs)}. So với chất cần tìm, em {diff_text(ms, mt)}."]
    if gs != gt:
        nx.append("Nhóm chức chưa khớp: hình em vẽ có " + (", ".join(sorted(gs)) or "không có nhóm chức đặc trưng")
                  + "; đề cần " + (", ".join(sorted(gt)) or "không có nhóm chức đặc trưng") + ".")
    return {"kq": "sai_cong_thuc", "nx": nx, "goi_y": ["Đếm lại số nguyên tử C và số H gắn vào mỗi C."]}


def norm_name(x):
    x = unicodedata.normalize("NFD", (x or "").lower().replace("đ", "d"))
    x = "".join(c for c in x if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", x)


BANK = [
    ("metan", "C", []), ("etan", "CC", []), ("propan", "CCC", []), ("butan", "CCCC", ["n-butan"]),
    ("2-metylpropan", "CC(C)C", ["isobutan"]), ("pentan", "CCCCC", ["n-pentan"]),
    ("2-metylbutan", "CCC(C)C", ["isopentan"]), ("2,2-đimetylpropan", "CC(C)(C)C", ["neopentan"]),
    ("eten", "C=C", ["etilen"]), ("propen", "C=CC", ["propilen"]), ("but-1-en", "C=CCC", ["1-buten"]),
    ("but-2-en", "CC=CC", ["2-buten"]), ("etin", "C#C", ["axetilen"]), ("propin", "C#CC", []),
    ("benzen", "c1ccccc1", []), ("toluen", "Cc1ccccc1", ["metylbenzen"]), ("stiren", "C=Cc1ccccc1", ["vinylbenzen"]),
    ("phenol", "Oc1ccccc1", ["hiđroxibenzen"]), ("anilin", "Nc1ccccc1", ["phenylamin"]),
    ("metanol", "CO", ["ancol metylic"]), ("etanol", "CCO", ["ancol etylic"]),
    ("propan-1-ol", "CCCO", ["ancol propylic"]), ("propan-2-ol", "CC(C)O", ["ancol isopropylic"]),
    ("butan-1-ol", "CCCCO", []), ("etylen glicol", "OCCO", ["etan-1,2-điol"]),
    ("glixerol", "OCC(O)CO", ["glixerin", "propan-1,2,3-triol"]),
    ("metanal", "C=O", ["fomanđehit", "anđehit fomic"]), ("etanal", "CC=O", ["anđehit axetic", "axetanđehit"]),
    ("propanon", "CC(C)=O", ["axeton"]), ("axit metanoic", "OC=O", ["axit fomic"]),
    ("axit etanoic", "CC(=O)O", ["axit axetic"]), ("axit propanoic", "CCC(=O)O", ["axit propionic"]),
    ("axit benzoic", "OC(=O)c1ccccc1", []), ("metyl axetat", "COC(C)=O", ["metyl etanoat"]),
    ("etyl axetat", "CCOC(C)=O", ["etyl etanoat"]), ("metylamin", "CN", ["metanamin"]), ("etylamin", "CCN", ["etanamin"]),
    ("glyxin", "NCC(=O)O", ["axit aminoaxetic"]), ("alanin", "CC(N)C(=O)O", ["axit 2-aminopropanoic"]),
    ("đimetyl ete", "COC", []), ("đietyl ete", "CCOCC", []), ("etyl clorua", "CCCl", ["cloetan"]),
    ("clorofom", "ClC(Cl)Cl", ["triclometan"]),
]

GRAPH_PROMPT = RULES + """

Đây là ảnh BÀI LÀM của học sinh và sẽ được chấm điểm. Hãy CHÉP LẠI TRUNG THỰC cấu trúc học sinh đã vẽ dưới dạng ĐỒ THỊ nguyên tử - liên kết. TUYỆT ĐỐI không sửa bài, không đoán học sinh định vẽ chất nào và không tự cân lại hóa trị. Nếu hình vẽ sai (ví dụ nguyên tử C nối với 5 nét) thì vẫn chép đúng 5 nét đó.

Quy tắc:
- Mỗi nguyên tử trong hình là một đối tượng {"id":số thứ tự bắt đầu từ 1,"el":"C" hoặc "O", "N", "Cl", "Br"...,"h":số H}.
- Công thức khung (đường gấp khúc): mỗi đầu mút và mỗi chỗ gấp khúc là một nguyên tử C với "h":null (H ngầm định, không vẽ).
- Công thức thu gọn hoặc khai triển: "h" là SỐ H được ghi kèm hoặc vẽ nối trực tiếp vào nguyên tử đó. Ví dụ CH3 thì h=3; nếu có 4 nét nối từ C tới 4 chữ H thì h=4. Đếm đúng từng nét, không làm tròn theo hóa trị. Nguyên tử không ghi và không vẽ H nào thì "h":null.
- KHÔNG tạo đối tượng riêng cho các H đã tính vào "h".
- Mỗi liên kết giữa hai nguyên tử (không kể H) là [id1,id2,bậc], bậc 1, 2 hoặc 3 tính theo số nét song song.
- Vòng benzen vẽ có vòng tròn bên trong: ghi 6 nguyên tử C và các liên kết xen kẽ bậc 1 và 2.
Chỉ trả về JSON: {"atoms":[...],"bonds":[[1,2,1],...],"ghi_chu":"điều chưa rõ hoặc mơ hồ trong hình, có thể rỗng"}"""


def graph_to_smiles(g):
    """Dựng phân tử từ đồ thị AI chép lại, giữ nguyên số H đã vẽ để lỗi hóa trị không bị che mất."""
    atoms, bonds = g.get("atoms") or [], g.get("bonds") or []
    if not atoms:
        return ""
    rw, idx = Chem.RWMol(), {}
    for a in atoms:
        el = str(a.get("el", "C")).strip()
        at = Chem.Atom(el[:1].upper() + el[1:].lower())
        h = a.get("h")
        if isinstance(h, (int, float)) and not isinstance(h, bool):
            at.SetNumExplicitHs(int(h))
            at.SetNoImplicit(True)
        idx[a["id"]] = rw.AddAtom(at)
    kinds = {1: Chem.BondType.SINGLE, 2: Chem.BondType.DOUBLE, 3: Chem.BondType.TRIPLE}
    for b in bonds:
        i, j, o = b[0], b[1], int(b[2])
        if i != j and rw.GetBondBetweenAtoms(idx[i], idx[j]) is None:
            rw.AddBond(idx[i], idx[j], kinds[o])
    m = rw.GetMol()
    m.UpdatePropertyCache(strict=False)
    Chem.FastFindRings(m)
    return Chem.MolToSmiles(m)


def transcribe_student(img):
    r = ask_ai([types.Part.from_bytes(data=to_jpeg(img), mime_type="image/jpeg"), GRAPH_PROMPT], temperature=0, lang_note=False)
    try:
        smi = graph_to_smiles(r)
    except Exception:
        raise ValueError("Không dựng được cấu trúc từ ảnh, hãy chụp rõ hơn.")
    return smi, r.get("ghi_chu", "")


def analyze_image_strict(img):
    """Đọc ảnh trung thực (đồ thị nguyên tử) rồi mới gọi tên và tính chất nếu công thức hợp lệ."""
    smi, note = transcribe_student(img)
    res = {"smiles": smi}
    if smi and parse_student(smi)[0] is not None:
        res = analyze_smiles(smi)
        res["smiles"] = smi
        res.pop("do_tin_cay", None)
    if note:
        old = res.get("luu_y") or []
        res["luu_y"] = ([old] if isinstance(old, str) else list(old)) + [note]
    return res


RANDOM_Q = "🎲 Ngẫu nhiên"
BANK_BY_NAME = {b[0]: b for b in BANK}
MAX_TRIES = 3          # số lần nộp tối đa cho một câu, hết lượt thì hiện đáp án
PRACTICE_KINDS = {"draw": "✍️ Vẽ công thức cấu tạo", "name": "🏷️ Gọi tên chất"}


def topic_of(m):
    """Nhóm chất của một phân tử, dùng cho thống kê chỗ hay sai."""
    g = groups_of(m)
    if g:
        return g[0]
    if any(a.GetIsAromatic() for a in m.GetAtoms()):
        return "hiđrocacbon thơm"
    bt = {b.GetBondType() for b in m.GetBonds()}
    return "ankin" if Chem.BondType.TRIPLE in bt else "anken" if Chem.BondType.DOUBLE in bt else "ankan"


def hint_steps(m):
    """Ba gợi ý tăng dần, đều do RDKit tính từ đáp án, không nói thẳng cấu tạo."""
    g = groups_of(m)
    n_c = sum(1 for a in m.GetAtoms() if a.GetSymbol() == "C")
    rings = m.GetRingInfo().NumRings()
    dbl = sum(1 for b in m.GetBonds() if b.GetBondType() == Chem.BondType.DOUBLE and not b.GetIsAromatic())
    trp = sum(1 for b in m.GetBonds() if b.GetBondType() == Chem.BondType.TRIPLE)
    parts = []
    if rings:
        parts.append(f"{rings} vòng")
    if dbl:
        parts.append(f"{dbl} liên kết đôi (không kể vòng benzen)")
    if trp:
        parts.append(f"{trp} liên kết ba")
    branched = any(a.GetSymbol() == "C" and a.GetDegree() >= 3 and not a.IsInRing() for a in m.GetAtoms())
    if not rings:
        parts.append("mạch có nhánh" if branched else "mạch thẳng")
    return [tx("Chất thuộc loại: ", "This compound is a: ") + (", ".join(g) if g else topic_of(m)) + ".",
            tx(f"Công thức phân tử là {pretty(formula_of(m))} (có {n_c} nguyên tử C).", f"The molecular formula is {pretty(formula_of(m))} ({n_c} carbon atoms)."),
            tx("Cấu tạo có: ", "The structure has: ") + ", ".join(parts) + "."]


def new_qstate(spec, aid=None, prior=None):
    p = prior or {}
    return {"spec": spec, "aid": aid, "uid": random.randrange(10 ** 6), "tries": p.get("tries", 0), "hints": p.get("hints", 0),
            "ok": p.get("ok", False), "res": None}


def new_free(kind):
    st.session_state.pq = new_qstate({"k": kind, "n": random.choice(BANK)[0]})
    st.session_state["pr_pick"] = RANDOM_Q


def _bump_hint(q):
    q["hints"] = min(3, q["hints"] + 1)


def _retry(q):
    q["res"] = None


def _go_next_asg(aid, idx, total):
    st.session_state[f"asg_sel_{aid}"] = min(idx + 1, total - 1)


def record_submission(q, ten, given, res, mt):
    """Ghi bài nộp lên bảng chung nếu học sinh đã đăng nhập (khách thì chỉ lưu trong phiên)."""
    if not cr.is_student(cur_auth()):
        return
    try:
        cr.add_submission(cur_auth(), q["aid"], q["spec"], topic_of(mt), given, res["kq"], q["tries"], q["hints"],
                          _now().strftime("%Y-%m-%d %H:%M:%S"))
        st.session_state.pop("_sub_err", None)
        st.session_state.pop("_prof", None)
    except OSError:
        st.session_state["_sub_err"] = hs.last_error


def render_question(q, allow_hints=True, next_cb=None, next_args=()):
    """Một câu hỏi: gợi ý từng bước, nộp bài, chấm bằng RDKit, thử lại, hiện đáp án khi xong."""
    spec = q["spec"]
    ten, smi, alias = BANK_BY_NAME[spec["n"]]
    mt = Chem.MolFromSmiles(smi)
    is_draw = spec["k"] == "draw"
    uid = q["uid"]
    top = st.container()
    finished = q["ok"] or q["tries"] >= MAX_TRIES
    res = q["res"]

    if res:
        head = {"dung": "Đúng rồi!", "dong_phan": "CHƯA ĐÚNG: đã vẽ một đồng phân khác", "sai_cong_thuc": "CHƯA ĐÚNG: sai công thức phân tử",
                "loi": "CHƯA ĐÚNG: công thức có lỗi", "sai": "CHƯA ĐÚNG"}[res["kq"]]
        with top:
            if res["kq"] == "dung":
                st.success("**" + tx(head, "Correct!") + "**")
                for t in res["nx"]:
                    st.markdown("- " + t)
            else:
                st.markdown(errbanner(head, *res["nx"]), unsafe_allow_html=True)
            for t in res["goi_y"]:
                st.markdown("- 💡 " + t)
            if res.get("note"):
                st.caption("Ghi chú khi đọc ảnh: " + res["note"])
            if is_draw and res.get("given"):
                im = draw_student(res["given"])
                if im is not None:
                    st.markdown("**Hình em vẽ (máy đọc lại đúng như hình, giữ nguyên lỗi" + (", nguyên tử sai khoanh đỏ" if res["kq"] == "loi" else "") + "):**")
                    st.image(im)

    with st.container(border=True):
        if is_draw:
            st.markdown(f"#### {tx('Viết công thức cấu tạo của', 'Draw the structural formula of')}: **{ten}**")
        else:
            st.markdown("#### " + tx("Gọi tên chất sau", "Name this compound"))
            st.image(Draw.MolToImage(mt, size=(360, 240)))
        if allow_hints and not finished:
            steps = hint_steps(mt)
            for i, t in enumerate(steps[:q["hints"]], 1):
                st.markdown(f"💡 **{tx('Gợi ý', 'Hint')} {i}:** {t}")
            if q["hints"] < len(steps):
                st.button(tx(f"💡 Gợi ý tiếp ({q['hints']}/{len(steps)})", f"💡 Next hint ({q['hints']}/{len(steps)})"),
                          key=f"pr_hint_{uid}_{q['hints']}", on_click=_bump_hint, args=(q,))
        go, img, ans = False, None, ""
        if not finished and q["res"] is None:
            sfx = f"{uid}_{q['tries']}"
            if is_draw:
                how = st.radio("Nộp bài bằng", ["🖼️ Ảnh bài làm", "📷 Chụp ảnh", "⌨️ Nhập SMILES"], horizontal=True, key=f"pr_how_{uid}")
                if how.startswith("🖼️"):
                    f = st.file_uploader("Ảnh bài làm", type=["jpg", "jpeg", "png", "webp"], key=f"pr_up_{sfx}")
                    img = f.getvalue() if f else None
                elif how.startswith("📷"):
                    f = st.camera_input("Chụp bài làm", key=f"pr_cam_{sfx}")
                    img = f.getvalue() if f else None
                else:
                    ans = st.text_input("SMILES bài làm", key=f"pr_smi_{sfx}").strip()
            else:
                ans = st.text_input("Tên chất (theo SGK)", key=f"pr_ans_{sfx}").strip()
            go = st.button("Nộp bài", type="primary", disabled=not (img or ans), key=f"pr_go_{sfx}")
            st.caption(tx(f"Lần nộp thứ {q['tries'] + 1}/{MAX_TRIES}. Hết {MAX_TRIES} lần máy mới hiện đáp án.",
                          f"Attempt {q['tries'] + 1}/{MAX_TRIES}. The answer is shown after {MAX_TRIES} attempts."))

    if go:
        if img and over_quota():
            show_top_error(top, "Bạn đã dùng hết số lượt của phiên này. Hãy tải lại trang để tiếp tục.")
        else:
            graded = False
            try:
                note, given = "", ans
                if is_draw:
                    if img:
                        with st.spinner("Đang đọc bài làm…"):
                            given, note = transcribe_student(img)
                        st.session_state.n += 1
                    r = grade_structure(given, smi)
                else:
                    ok = norm_name(ans) in {norm_name(x) for x in [ten] + alias}
                    r = {"kq": "dung" if ok else "sai",
                         "nx": ["Chính xác." if ok else "Chưa đúng. Hãy xác định mạch chính, nhóm chức và vị trí nhóm thế rồi gọi tên lại."],
                         "goi_y": []}
                r.update({"given": given, "note": note})
                q["tries"] += 1
                q["res"] = r
                q["ok"] = q["ok"] or r["kq"] == "dung"
                add_history(ten, "Luyện tập")
                record_submission(q, ten, given, r, mt)
                st.session_state.setdefault("ph", []).append({
                    "Thời gian": _now().strftime("%H:%M:%S"), "Học sinh": student_name(), "Dạng bài": "vẽ CTCT" if is_draw else "gọi tên",
                    "Đề": ten, "Bài làm": given, "Kết quả": r["kq"]})
                graded = True
            except Exception as e:
                show_top_error(top, "Có lỗi khi chấm bài, hãy thử lại.", e)
            if graded:
                st.rerun()

    if q["res"] is not None or finished:
        if q["ok"] or q["tries"] >= MAX_TRIES:
            if q["tries"] and not q["ok"]:
                st.warning(tx(f"Đã hết {MAX_TRIES} lần thử, đây là đáp án để em đối chiếu.", f"All {MAX_TRIES} attempts used; here is the answer to compare."))
            with st.expander(tx("Xem đáp án", "Show the answer"), expanded=not q["ok"]):
                st.image(Draw.MolToImage(mt, size=(300, 200)))
                st.markdown(f"**{ten}** · {pretty(formula_of(mt))} · `{smi}`")
                gl = groups_of(mt)
                if gl:
                    st.markdown("Nhóm chức/đặc điểm: " + ", ".join(gl))
            if next_cb:
                st.button(tx("➡️ Câu tiếp theo", "➡️ Next question"), on_click=next_cb, args=next_args, key=f"pr_next_{uid}")
        else:
            st.caption(tx(f"Còn {MAX_TRIES - q['tries']} lần thử. Dùng gợi ý rồi thử lại nhé.", f"{MAX_TRIES - q['tries']} attempts left. Use a hint and try again."))
            st.button(tx("↻ Thử lại", "↻ Try again"), on_click=_retry, args=(q,), key=f"pr_retry_{uid}_{q['tries']}")
    if st.session_state.get("_sub_err"):
        st.caption("⚠️ " + tx("Chưa ghi được bài nộp lên bảng chung: ", "Could not save the submission: ") + st.session_state["_sub_err"])


def practice_free_ui():
    st.session_state.setdefault("pq", None)
    kind_lab = st.radio("Dạng bài", list(PRACTICE_KINDS.values()), horizontal=True, key="pr_kind")
    kind = "draw" if kind_lab.startswith("✍️") else "name"
    q = st.session_state.pq
    if q is None or q["aid"] is not None or q["spec"]["k"] != kind:
        new_free(kind)
    names = [b[0] for b in BANK]
    pick = st.selectbox("Chọn đề cụ thể (hoặc để ngẫu nhiên)", [RANDOM_Q] + names, key="pr_pick")
    if pick != RANDOM_Q and pick != st.session_state.pq["spec"]["n"]:
        st.session_state.pq = new_qstate({"k": kind, "n": pick})
    render_question(st.session_state.pq, allow_hints=True, next_cb=new_free, next_args=(kind,))
    hist = st.session_state.get("ph", [])
    if hist:
        st.divider()
        n_ok = sum(1 for h in hist if h["Kết quả"] == "dung")
        a, b, c = st.columns(3)
        a.metric("Đã làm", len(hist))
        b.metric("Đúng", n_ok)
        c.metric("Tỉ lệ đúng", f"{round(100 * n_ok / len(hist))}%")
        st.dataframe(hist, hide_index=True, width="stretch")
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(hist[0].keys()))
        w.writeheader()
        w.writerows(hist)
        st.download_button("⬇️ Tải phiếu kết quả (CSV, nộp cho giáo viên)", buf.getvalue().encode("utf-8-sig"),
                           file_name="phieu_ket_qua.csv", mime="text/csv", key="pr_dl")


def _q_label(i, qd, st_):
    mark = "✅" if st_ and st_["ok"] else "❌" if st_ and st_["tries"] >= MAX_TRIES else "▶️" if st_ else "⬜"
    return f'{mark} {i + 1}. {tx("Vẽ", "Draw") if qd["k"] == "draw" else tx("Gọi tên", "Name")}: {qd["n"] if qd["k"] == "draw" else "(hình)"}'


def _fmt_size(n):
    return f"{n / 1000:.0f} KB" if n < 1_000_000 else f"{n / 1_000_000:.1f} MB"


def _docx_text(data):
    """Lấy chữ từ .docx (không cần thư viện ngoài) để xem nhanh yêu cầu."""
    import zipfile
    from io import BytesIO
    try:
        xml = zipfile.ZipFile(BytesIO(data)).read("word/document.xml").decode("utf-8", "ignore")
    except Exception:
        return ""
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml)).strip()


_FMT_RULES = """.opts{display:grid;gap:.1em 1.4em;margin:.25em 0 .6em 1.4em}
.opts>div{min-width:0;overflow-wrap:anywhere}.opts.c4{grid-template-columns:repeat(4,1fr)}
.opts.c2{grid-template-columns:repeat(2,1fr)}.opts.c1{grid-template-columns:1fr}
.opts img{max-width:100%;height:auto}
.fig{text-align:center;margin:.6em 0}.fig img{max-width:min(100%,440px);height:auto}
.sec{text-align:center;font-weight:700;margin:1em 0 .5em}
.exam,.exam p,.exam div,.exam td,.exam th{font-family:'Times New Roman',Times,serif!important;font-size:1.05rem!important;line-height:1.55!important}
.exam p{margin:.3em 0!important}
.exam{overflow-wrap:anywhere}
@media(max-width:560px){.opts.c4{grid-template-columns:repeat(2,1fr)}.opts.c2{grid-template-columns:1fr}}"""


_DOC_CSS = """<style>
body{margin:0;background:#fff;color:#111;font-family:'Times New Roman',Times,serif;font-size:16px;line-height:1.55}
.doc{max-width:820px;margin:0 auto;padding:24px 32px}
p{margin:.35em 0}table{border-collapse:collapse;margin:.6em 0;max-width:100%}
td,th{border:1px solid #444;padding:4px 8px;vertical-align:top}img{max-width:100%;height:auto;vertical-align:middle}
sub,sup{line-height:0}h1,h2,h3{margin:.6em 0 .3em}
"""
_DOC_CSS = _DOC_CSS + _FMT_RULES + "</style>"


_EMF_MARK = "emf-placeholder"


def _docx_body(data):
    """Word -> HTML thân bài (giữ đậm/nghiêng, chỉ số trên/dưới, bảng, hình PNG/JPG). Hình EMF/WMF trình duyệt không vẽ được nên thay bằng chú thích."""
    try:
        import mammoth
        from io import BytesIO
        import base64 as _b64
    except ImportError:
        return ""

    def img(image):
        ct = image.content_type or ""
        if ct in ("image/x-emf", "image/x-wmf", "image/emf", "image/wmf"):
            return {"src": _EMF_MARK}
        with image.open() as f:
            return {"src": f"data:{ct};base64," + _b64.b64encode(f.read()).decode("ascii")}

    try:
        body = mammoth.convert_to_html(BytesIO(data), convert_image=mammoth.images.img_element(img)).value
    except Exception:
        return ""
    body = re.sub(r"(?is)<script.*?</script>", "", body)
    body = re.sub(r"(?i)<a\b[^>]*>", "<a>", body)          # bỏ liên kết trong tệp (tránh javascript:)
    body = re.sub(r'(?i)<img[^>]*src="%s"[^>]*>' % _EMF_MARK, "<em>[Hình: tải file Word để xem]</em>", body)
    return body


def _docx_html(data):
    body = _docx_body(data)
    if not body:
        return ""
    blocks = _html_blocks(body)
    if blocks:
        try:
            body = "\n".join(tidy_exam(blocks))
        except Exception:
            pass
    return _DOC_CSS + '<div class="doc">' + body + "</div>"


def _html_blocks(body):
    """Cắt HTML thân bài thành các khối cấp cao nhất (đoạn, bảng, danh sách) để chèn ô trả lời giữa đề."""
    out, depth, start = [], 0, 0
    block = {"p", "table", "ol", "ul", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}
    for m in re.finditer(r"<(/?)([a-zA-Z0-9]+)[^>]*?(/?)>", body):
        tag = m.group(2).lower()
        if tag not in block or m.group(3):
            continue
        if not m.group(1):
            if depth == 0:
                start = m.start()
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                out.append(body[start:m.end()])
    return out


def _plain(h):
    return html.unescape(re.sub(r"<[^>]+>", "", h)).strip()


_LEFT = "__LEFTOVER__"


def _split_br(blocks):
    """Đoạn có xuống dòng mềm (<br>) chứa nhiều câu/ý: tách ra để gắn ô trả lời đúng chỗ."""
    out = []
    for b in blocks:
        if b.startswith("<p") and re.search(r"<br\s*/?>", b):
            inner = re.sub(r"^<p[^>]*>|</p>$", "", b)
            segs = [x for x in re.split(r"<br\s*/?>", inner) if _plain(x)]
            if any(re.match(r"(?:Câu\s+\d+|[a-hA-H]\s*[\).]|PHẦN\s+)", _plain(x), re.I) for x in segs):
                out += [f"<p>{x}</p>" for x in segs]
                continue
        out.append(b)
    return out



_FMT_TAGS = ("strong", "em", "u", "sub", "sup", "b", "i")
_OPT_MARK = re.compile(r"(?:<(?:strong|em|u|b|i)>\s*)*([A-Za-z])\s*[.)]\s*(?:</(?:strong|em|u|b|i)>\s*)*(?=\S)")


def _balance(h):
    """Sau khi cắt đoạn, cân lại các thẻ định dạng (đậm, nghiêng, chỉ số) để HTML không bị lệch."""
    for t in _FMT_TAGS:
        o = len(re.findall(rf"<{t}>", h))
        c = len(re.findall(rf"</{t}>", h))
        if c > o:
            h = f"<{t}>" * (c - o) + h
        elif o > c:
            h += f"</{t}>" * (o - c)
    return h


def _split_marks(inner, letters, need):
    """Cắt đoạn 'A. … B. … C. … D. …' (hoặc a) … b) …) dính một dòng thành từng ý theo đúng thứ tự chữ cái. None nếu không phải."""
    inner = inner.strip()
    found = []
    for m in _OPT_MARK.finditer(inner):
        ch = m.group(1)
        if ch not in letters:
            continue
        if not found:
            if m.start() != 0:
                return None
        else:
            nxt = letters.index(found[-1][0]) + 1
            if nxt >= len(letters) or ch != letters[nxt] or not (inner[m.start() - 1].isspace() or inner[m.start() - 1] in ">.;,)"):
                continue
        found.append((ch, m.start()))
    if len(found) < need:
        return None
    pos = [p for _, p in found] + [len(inner)]
    return [_balance(inner[pos[i]:pos[i + 1]].strip()) for i in range(len(found))], found[0][0]


def _img_size(raw):
    """Kích thước ảnh (rộng, cao); đọc bằng PIL, không có PIL thì tự đọc phần đầu tệp PNG/JPEG/GIF."""
    try:
        from io import BytesIO
        from PIL import Image
        return Image.open(BytesIO(raw)).size
    except Exception:
        pass
    import struct
    try:
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", raw[16:24])
        if raw[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", raw[6:10])
        if raw[:2] == b"\xff\xd8":
            i = 2
            while i < len(raw) - 9:
                if raw[i] != 0xFF:
                    i += 1
                    continue
                mk = raw[i + 1]
                if 0xC0 <= mk <= 0xCF and mk not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack(">HH", raw[i + 5:i + 9])
                    return w, h
                i += 2 + struct.unpack(">H", raw[i + 2:i + 4])[0]
    except Exception:
        pass
    return None


def _big_img(tag):
    """Hình minh họa (sơ đồ, dụng cụ…) thì tách ra giữa dòng; hình nhỏ (công thức chèn trong câu) thì để nguyên.
    Không đọc được kích thước thì coi là hình minh họa (công thức hiếm khi không đọc được)."""
    m = re.search(r'src="data:[^;]+;base64,([^"]+)"', tag)
    if not m:
        return False
    try:
        import base64 as _b64
        sz = _img_size(_b64.b64decode(m.group(1)))
    except Exception:
        sz = None
    if not sz:
        return True
    w, h = sz
    return (w >= 200 and h >= 80) or (w >= 90 and h >= 90)


def _split_fig(b):
    if not b.startswith("<p") or "<img" not in b:
        return [b]
    inner = re.sub(r"^<p[^>]*>|</p>$", "", b)
    imgs = re.findall(r"<img\b[^>]*>", inner)
    if not imgs or not all(_big_img(i) for i in imgs):
        return [b]
    text = re.sub(r"<img\b[^>]*>", "", inner)
    out = [f"<p>{text}</p>"] if _plain(text) else []
    return out + [f'<p class="fig">{i}</p>' for i in imgs]


def tidy_exam(blocks, student=False):
    """Trình bày đề gọn đẹp: mỗi câu một khối, 'Câu N.' đậm, tiêu đề PHẦN căn giữa, hình đưa xuống giữa dưới đề,
    đáp án A–D dính một dòng hoặc rời từng đoạn được gom thành lưới 4/2/1 cột thẳng hàng, ý a) b) c) d) tách từng dòng."""
    items = []                                         # ("opt", html) | ("b", html)
    for b in _split_br(blocks):
        figs = []
        if b.startswith("<p") and "<img" in b:
            inner0 = re.sub(r"^<p[^>]*>|</p>$", "", b)
            imgs = re.findall(r"<img\b[^>]*>", inner0)
            if imgs and all(_big_img(i) for i in imgs):          # hình minh họa nằm lẫn trong đoạn: tách ra giữa dòng
                figs = [f'<p class="fig">{i}</p>' for i in imgs]
                b = "<p>" + re.sub(r"<img\b[^>]*>", "", inner0) + "</p>"
        if b.startswith("<p"):
            inner = re.sub(r"^<p[^>]*>|</p>$", "", b)
            r = _split_marks(inner, "ABCD", 1)
            if r:
                if figs:                                          # hình thuộc cả câu: đặt trước cụm đáp án
                    j = len(items)
                    while j > 0 and items[j - 1][0] == "opt":
                        j -= 1
                    items[j:j] = [("b", f) for f in figs]
                items += [("opt", x) for x in r[0]]
                continue
            r = _split_marks(inner, "abcdefgh", 2)
            if r:
                items += [("b", f"<p>{x}</p>") for x in r[0]] + [("b", f) for f in figs]
                continue
        if figs:
            items += ([("b", b)] if _plain(b) else []) + [("b", f) for f in figs]
        else:
            items.append(("b", b))
    if student:
        flat = [x if k == "b" else f"<p>{x}</p>" for k, x in items]
        flat = _student_blocks(flat)
        items = [("opt", re.sub(r"^<p[^>]*>|</p>$", "", x)) if x.startswith("<p") and re.match(r"[A-D]\s*[.)]", _plain(x)) else ("b", x) for x in flat]
    out, run = [], []

    def flush():
        nonlocal run
        if not run:
            return
        n = max(len(_plain(x)) for x in run)
        cols = "c1" if n > 46 or len(run) > 4 else "c2" if n > 20 or any("<img" in x for x in run) else "c4"
        if len(run) < 3 and cols == "c4":
            cols = "c2"
        out.append(f'<div class="opts {cols}">' + "".join(f"<div>{x}</div>" for x in run) + "</div>")
        run = []

    for k, x in items:
        if k == "opt":
            if run and re.match(r"A\s*[.)]", _plain(x)):
                flush()
            run.append(x)
            continue
        flush()
        t = _plain(x)
        if x.startswith("<p") and (re.match(r"(?i)PHẦN\s+(I{1,3}|[123])\b", t) or re.match(r"^[-–—\s]*HẾT\b", t, re.I)):
            x = re.sub(r"^<p\b[^>]*>", '<p class="sec">', x, 1)
        elif x.startswith("<p>") and re.match(r"Câu\s+\d+\s*[.:]", t):
            x = re.sub(r"^<p>(Câu\s+\d+\s*[.:]?)", r"<p><strong>\1</strong>", x, 1)
        out.append(x)
    flush()
    return out


def exam_plan(blocks, sh):
    """Gắn ô trả lời vào đúng chỗ trong đề. Trả về [[html, [ô...]], ...]; câu của phiếu không gắn được xếp ở cuối (html = _LEFT). None nếu không gắn được câu nào."""
    names = {"I": "mc", "II": "tf", "III": "sa", "1": "mc", "2": "tf", "3": "sa"}
    plan, section, cur, last, placed_items = [], None, None, None, set()
    placed = set()
    counter = {"mc": 0, "tf": 0, "sa": 0}

    def flush():
        nonlocal cur, last, placed_items
        if cur is None or last is None:
            return
        part, i = cur
        if part == "tf":
            for j in range(len(sh["tf"][i])):
                if (i, j) not in placed_items:
                    plan[last][1].append(("tf", i, j))
        else:
            plan[last][1].append((part, i))
        placed.add((part, i))
        cur, last, placed_items = None, None, set()

    for b in _split_br(blocks):
        t = _plain(b)
        mp = re.match(r"(?i)PHẦN\s+(I{1,3}|[123])\b", t)
        if mp:
            flush()
            section = names.get(mp.group(1).upper())
            plan.append([b, []])
            continue
        if re.match(r"^[-–—\s]*HẾT\b", t, re.I):
            flush()
            plan.append([b, []])
            continue
        mq = re.match(r"Câu\s+(\d+)\s*[.:)]?(?=\s|$)", t)
        if mq and section:
            flush()
            i = counter[section]                       # theo thứ tự trong phần (đề có thể đánh số nối tiếp 19, 20, …)
            counter[section] += 1
            if i < len(sh[section]):
                cur = (section, i)
        plan.append([b, []])
        if cur is not None:
            last = len(plan) - 1
            if cur[0] == "tf":
                mi = re.match(r"([a-hA-H])\s*[\).]", t)
                if mi and (ord(mi.group(1).lower()) - 97) < len(sh["tf"][cur[1]]):
                    j = ord(mi.group(1).lower()) - 97
                    if (cur[1], j) not in placed_items:
                        plan[-1][1].append(("tf", cur[1], j))
                        placed_items.add((cur[1], j))
    flush()
    if not placed:
        return None
    miss = []
    for k in ("mc", "tf", "sa"):
        for i in range(len(sh[k])):
            if (k, i) in placed:
                continue
            if k == "tf":
                miss += [("tf", i, j) for j in range(len(sh["tf"][i]))]
            else:
                miss.append((k, i))
    if miss:
        plan.append([_LEFT, miss])
    return plan


def _html_frame(page, height):
    """Nhúng HTML vào khung: dùng st.iframe (Streamlit mới), lùi về components.html nếu bản cũ."""
    if hasattr(st, "iframe"):
        try:
            st.iframe(page, height=height)
            return
        except Exception:
            pass
    components.html(page, height=height, scrolling=True)


def preview_ui(m, data):
    """Xem nội dung tệp ngay trên trang: ảnh, PDF, văn bản, Word. Excel/PowerPoint thì tải về."""
    ext = cr.ext_of(m["name"])
    if ext in ("png", "jpg", "jpeg", "gif"):
        st.image(data, caption=m["name"], use_container_width=True)
    elif ext == "pdf":
        import base64 as _b64
        b = _b64.b64encode(data).decode("ascii")
        _html_frame(
            f"""<iframe id="f" style="width:100%;height:640px;border:1px solid #ccc;border-radius:8px"></iframe>
<script>
const bin=atob("{b}"),u=new Uint8Array(bin.length);
for(let i=0;i<bin.length;i++)u[i]=bin.charCodeAt(i);
document.getElementById("f").src=URL.createObjectURL(new Blob([u],{{type:"application/pdf"}}));
</script>""", 660)
    elif ext in ("txt", "csv"):
        st.text(data.decode("utf-8", "replace")[:20000])
    elif ext == "docx":
        page = _docx_html(data)
        if page:
            _html_frame(page, 720)
        else:
            t = cr.docx_text(data)
            st.text(t[:20000]) if t else st.info(tx("Không xem trước được, hãy tải về.", "No preview available, please download."))
    else:
        st.info(tx("Loại tệp này không xem trước được trên web, hãy bấm Tải về.", "This file type can't be previewed here, please download it."))


def file_rows_ui(files, prefix, can_delete=False, show_student=False):
    """Danh sách tệp: Xem ngay / Tải về (chỉ đọc dữ liệu khi bấm để đỡ chậm) / Xóa nếu được phép."""
    for m in files:
        c1, cv, c2, c3 = st.columns([4.5, 1.2, 1.7, 1.0], vertical_alignment="center")
        who = f" · {html.escape(m['student'].rsplit(' [', 1)[0])}" if show_student and m["student"] else ""
        c1.markdown(f"📎 **{html.escape(m['name'])}** · {_fmt_size(m['size'])}{who} · {m['ts']}", unsafe_allow_html=True)
        ck, pk = f"_dl_{m['id']}", f"_pv_{m['id']}"

        def _load():
            try:
                st.session_state[ck] = cr.read_file(cur_auth(), m["id"])[1]
                return True
            except (OSError, cr.Denied) as e:
                st.error(str(e) if isinstance(e, cr.Denied) else hs.last_error)
                return False

        opened = st.session_state.get(pk, False)
        if cv.button(tx("🙈 Ẩn", "🙈 Hide") if opened else tx("👁️ Xem", "👁️ View"), key=f"{prefix}_pv_{m['id']}"):
            if opened:
                st.session_state[pk] = False
                st.rerun()
            elif ck in st.session_state or _load():
                st.session_state[pk] = True
                st.rerun()
        if ck in st.session_state:
            c2.download_button(tx("⬇️ Lưu về máy", "⬇️ Save"), st.session_state[ck], file_name=m["name"], mime=m["mime"], key=f"{prefix}_sv_{m['id']}")
        elif c2.button(tx("⬇️ Tải về", "⬇️ Download"), key=f"{prefix}_dl_{m['id']}") and _load():
            st.rerun()
        if can_delete and c3.button(tx("Xóa", "Delete"), key=f"{prefix}_rm_{m['id']}"):
            try:
                cr.delete_file(cur_auth(), m["id"])
                st.session_state.pop(ck, None)
                st.session_state.pop(pk, None)
                st.rerun()
            except (OSError, cr.Denied) as e:
                st.error(str(e) if isinstance(e, cr.Denied) else hs.last_error)
        if opened and ck in st.session_state:
            preview_ui(m, st.session_state[ck])


def upload_ui(aid, kind, key, label, multiple):
    """Chọn tệp và bấm nút để lưu. Trả về số tệp đã lưu (0 nếu chưa có)."""
    exts = sorted(cr.ALLOWED_EXT)
    ups = st.file_uploader(label, type=exts, accept_multiple_files=True, key=f"{key}_{st.session_state.get('_up_n', 0)}",
                           help=tx(f"Tối đa {cr.MAX_FILE // 1000} KB mỗi tệp (ảnh png/jpg tới {cr.MAX_IMG_RAW // 1_000_000} MB sẽ tự nén). Định dạng: " + ", ".join(exts),
                                   f"Up to {cr.MAX_FILE // 1000} KB per file (png/jpg photos up to {cr.MAX_IMG_RAW // 1_000_000} MB are auto-compressed). Formats: " + ", ".join(exts)))
    if not ups:
        return 0
    if st.button(tx("📤 Tải lên", "📤 Upload"), key=f"{key}_go", type="primary"):
        n = 0
        for f in ups[:cr.MAX_ATT]:
            try:
                cr.add_file(cur_auth(), aid, kind, f.name, f.type, f.getvalue(), _now().strftime("%Y-%m-%d %H:%M"))
                n += 1
            except cr.Denied as e:
                st.error(f"{f.name}: {e}")
            except OSError:
                st.error(hs.last_error)
        if n:
            st.session_state["_up_n"] = st.session_state.get("_up_n", 0) + 1
            st.session_state["_toast"] = tx(f"Đã tải lên {n} tệp.", f"Uploaded {n} file(s).")
            st.rerun()
    return 0


@st.cache_data(show_spinner=False, max_entries=20)
def _analyze_docx(data):
    return cr.analyze_docx(data)


@st.cache_data(show_spinner=False, max_entries=20)
def _analyze_key_file(name, data):
    try:
        return cr.analyze_key_file(name, data)
    except cr.Denied as e:
        return {"error": str(e)}


def merge_analyses(infos):
    """Gộp kết quả phân tích nhiều file Word (đề + file đáp án nếu có): số câu từng phần và đáp án đọc được."""
    struct, key = {"mc": 0, "tf": 0, "sa": 0}, {"mc": {}, "tf": {}, "sa": {}}
    for it in infos:
        for k in struct:
            struct[k] = max(struct[k], it["struct"][k])
            for n, v in it["key"][k].items():
                key[k].setdefault(n, v)
    return struct, key


def key_summary(cfg):
    got = {"mc": sum(1 for x in cfg["mc"] if x), "tf": sum(1 for x in cfg["tf"] if x), "sa": sum(1 for x in cfg["sa"] if x)}
    tot = {"mc": len(cfg["mc"]), "tf": len(cfg["tf"]), "sa": len(cfg["sa"])}
    return got, tot


def sheet_editor_ui(prefix, detected=None, existing=None):
    """Nhập cấu trúc và đáp án phiếu trả lời: phần I chọn 1 đáp án, phần II đúng/sai, phần III trả lời ngắn. Trả về cấu hình (dict)."""
    ex = existing or {}
    d = detected or {}
    kf = st.file_uploader(tx("📄 Tải file đáp án để điền tự động (Word .docx, PDF hoặc .txt). Có thể là file đề có đáp án hoặc file đáp án riêng.",
                             "📄 Upload an answer-key file to fill this in automatically (.docx, .pdf or .txt)"),
                          type=["docx", "pdf", "txt"], key=f"{prefix}_kfile")
    if kf is not None:
        info = _analyze_key_file(kf.name, kf.getvalue())
        if info.get("error"):
            st.error(info["error"])
        else:
            struct = {k: (len(ex.get(k, [])) or info["struct"][k] or (d.get(k, 0) if not ex else 0)) for k in ("mc", "tf", "sa")}
            new = cr.cfg_from_key(info["key"], struct)
            if any(new["mc"] + new["tf"] + new["sa"]):
                merged = {k: [(new[k][i] if i < len(new[k]) and new[k][i] else (ex.get(k, [])[i] if i < len(ex.get(k, [])) else ""))
                              for i in range(max(len(new[k]), len(ex.get(k, []))))] for k in ("mc", "tf", "sa")}
                merged["show_key"] = ex.get("show_key", True)
                ex = merged
                got, tot = key_summary(merged)
                st.success(tx(f"✅ Đã điền đáp án từ file: phần I {got['mc']}/{tot['mc']}, phần II {got['tf']}/{tot['tf']}, phần III {got['sa']}/{tot['sa']} câu. Kiểm tra lại rồi lưu.",
                              f"✅ Key filled from the file: {got['mc']}/{tot['mc']}, {got['tf']}/{tot['tf']}, {got['sa']}/{tot['sa']}. Check, then save."))
            else:
                st.warning(tx("Không tìm thấy đáp án trong file này (PDF ảnh quét không đọc được). Thử file khác hoặc nhập tay bên dưới.", "No answer key found in this file (scanned PDFs can't be read)."))
        with st.expander(tx("🔎 Xem app đọc phần đáp án của file này thế nào", "🔎 See how the app read this file's key section")):
            st.code(cr.key_debug(kf.name, kf.getvalue()), language=None)
    prefix = f"{prefix}_{abs(hash(json.dumps(ex, sort_keys=True, ensure_ascii=False))) % 10**8}"
    c1, c2, c3 = st.columns(3)
    n_mc = int(c1.number_input(tx("Phần I: số câu (chọn 1 đáp án)", "Part I: questions (single choice)"), 0, 60, len(ex["mc"]) if ex else d.get("mc") or 18, key=f"{prefix}_nmc"))
    n_tf = int(c2.number_input(tx("Phần II: số câu (đúng/sai)", "Part II: questions (true/false)"), 0, 20, len(ex["tf"]) if ex else d.get("tf") or 4, key=f"{prefix}_ntf"))
    n_sa = int(c3.number_input(tx("Phần III: số câu (trả lời ngắn)", "Part III: questions (short answer)"), 0, 40, len(ex["sa"]) if ex else d.get("sa") or 6, key=f"{prefix}_nsa"))
    st.caption(tx("Điền đáp án để hệ thống tự chấm (để trống nếu chưa có thì câu đó không tính điểm). Học sinh không nhìn thấy đáp án.",
                  "Enter the answer key so answers are auto-graded (blank = not graded). Students never see the key."))
    show_key = st.checkbox(tx("Cho học sinh xem đáp án đúng sau khi nộp bài", "Show the correct answers to students after they submit"),
                           value=ex.get("show_key", True), key=f"{prefix}_showkey")
    mc_str = st.text_input(tx(f"Đáp án phần I: {n_mc} chữ A–D viết liền (vd. BACD…)", f"Part I key: {n_mc} letters A–D (e.g. BACD…)"),
                           value="".join(x or "-" for x in ex.get("mc", [])), key=f"{prefix}_mc", max_chars=80)
    mc_clean = re.sub(r"[\s,;]", "", mc_str.upper())
    if mc_clean and len(mc_clean) != n_mc:
        st.warning(tx(f"Đang nhập {len(mc_clean)} chữ nhưng có {n_mc} câu. Dùng dấu - cho câu chưa có đáp án.", f"{len(mc_clean)} letters for {n_mc} questions. Use - for unknown."))
    mc = [(mc_clean[i] if i < len(mc_clean) else "") for i in range(n_mc)]
    tf, sa = [], []
    if n_tf:
        st.markdown("**" + tx("Phần II: nhập Đ/S cho từng ý a, b, c, d (vd. ĐSĐS)", "Part II: T/F per statement (e.g. TFTF)") + "**")
        cols = st.columns(4)
        for i in range(n_tf):
            tf.append(cols[i % 4].text_input(tx(f"Câu {i + 1}", f"Q{i + 1}"), value=ex["tf"][i] if i < len(ex.get("tf", [])) else "",
                                             key=f"{prefix}_tf{i}", max_chars=8, placeholder="ĐSĐS"))
    if n_sa:
        st.markdown("**" + tx("Phần III: đáp án trả lời ngắn (nhiều đáp án chấp nhận cách nhau dấu ;)", "Part III: short answers (separate accepted variants with ;)") + "**")
        cols = st.columns(3)
        for i in range(n_sa):
            sa.append(cols[i % 3].text_input(tx(f"Câu {i + 1}", f"Q{i + 1}"), value=ex["sa"][i] if i < len(ex.get("sa", [])) else "",
                                             key=f"{prefix}_sa{i}", max_chars=60))
    return {"mc": [("" if x in ("-", "?", "_") else x) for x in mc], "tf": tf, "sa": sa, "show_key": show_key}


_EXAM_CSS = """<style>
.exam{font-family:'Times New Roman',Times,serif;font-size:1.05rem;line-height:1.55}
.exam p{margin:.3em 0}.exam table{border-collapse:collapse;margin:.5em 0;max-width:100%}
.exam td,.exam th{border:1px solid #888;padding:4px 8px;vertical-align:top}.exam img{max-width:100%;height:auto}
"""
_EXAM_CSS += _FMT_RULES + "</style>"


def _show_html(h):
    if hasattr(st, "html"):
        st.html(f'<div class="exam">{h}</div>')
    else:
        st.markdown(f'<div class="exam">{h}</div>', unsafe_allow_html=True)


def _student_blocks(blocks):
    """Bản đề cho học sinh: cắt phần đáp án nếu còn sót, bỏ dòng 'Đáp án: …', bỏ dấu in đậm ở đáp án A–D và chữ (Đúng)/(Sai) sau ý."""
    out, seen = [], 0
    for b in blocks:
        t = _plain(b)
        if re.match(r"Câu\s+\d+\s*[.:]", t):
            seen += 1
        if seen >= 1 and cr.KEY_MARK.match(t) and len(t) <= 100 and not re.search(r"[:：]\s*(?:[A-D]\b|[-\d])", t):
            break
        if re.match(r"(?i)\s*(Đáp\s*án|ĐA)\s*[:：]", t):
            continue
        if re.match(r"[A-D]\s*[.)]", t):
            b = re.sub(r"</?(?:strong|em|u)>", "", b)
        if re.match(r"[a-d]\s*[).]", t):
            b = re.sub(r"\s*[(\[→:\-–]\s*(?:Đúng|Sai)\s*[)\]]?\s*\.?(?=\s*</p>)", "", b)
        out.append(b)
    return out


def _exam_blocks(au, atts):
    """Các khối HTML của đề (file .docx đầu tiên giáo viên đính kèm), đọc một lần rồi giữ trong phiên."""
    for m in atts:
        if cr.ext_of(m["name"]) != "docx":
            continue
        ck = f"_exam_blocks2_{m['id']}"
        if ck not in st.session_state:
            try:
                st.session_state[ck] = tidy_exam(_html_blocks(_docx_body(cr.read_file(au, m["id"])[1])), student=True)
            except (OSError, cr.Denied):
                return None
        return st.session_state[ck] or None
    return None


def _review_ui(a, sh, plan, last, key):
    """Xem lại bài đã nộp: đề kèm lựa chọn của học sinh, ✅/❌ từng câu và đáp án đúng (nếu giáo viên cho xem)."""
    ans, det = last["answers"], last["detail"]
    LET = "abcdefgh"

    def slot(w):
        k, i = w[0], w[1]
        if k == "mc":
            g = (ans.get("mc") or [""] * (i + 1))[i] if i < len(ans.get("mc") or []) else ""
            ok = det.get("mc", [])[i] if i < len(det.get("mc", [])) else None
            extra = f" · {tx('đáp án đúng', 'correct')}: **{key['mc'][i]}**" if key and ok is False and i < len(key["mc"]) and key["mc"][i] else ""
            st.markdown(f"{'✅' if ok else '❌' if ok is False else '▫️'} " + tx(f"Câu {i + 1}: bạn chọn **{g or '—'}**", f"Q{i + 1}: you chose **{g or '—'}**") + extra)
        elif k == "tf":
            j = w[2]
            row = ans.get("tf", [])[i] if i < len(ans.get("tf", [])) else []
            g = row[j] if j < len(row) else None
            marks = det.get("tf", [])[i] if i < len(det.get("tf", [])) else None
            ok = marks[j] if marks and j < len(marks) else None
            gs = tx("Đúng", "True") if g else tx("Sai", "False") if g is False else "—"
            extra = ""
            if key and ok is False and i < len(key["tf"]) and j < len(key["tf"][i]):
                extra = f" · {tx('đáp án đúng', 'correct')}: **{tx('Đúng', 'True') if key['tf'][i][j] == 'Đ' else tx('Sai', 'False')}**"
            st.markdown(f"{'✅' if ok else '❌' if ok is False else '▫️'} " + tx(f"Câu {i + 1} ý {LET[j]}): bạn chọn **{gs}**", f"Q{i + 1} {LET[j]}): you chose **{gs}**") + extra)
        else:
            g = (ans.get("sa") or [])[i] if i < len(ans.get("sa") or []) else ""
            ok = det.get("sa", [])[i] if i < len(det.get("sa", [])) else None
            extra = f" · {tx('đáp án đúng', 'correct')}: **{key['sa'][i]}**" if key and ok is False and i < len(key["sa"]) and key["sa"][i] else ""
            st.markdown(f"{'✅' if ok else '❌' if ok is False else '▫️'} " + tx(f"Câu {i + 1}: bạn trả lời **{g or '—'}**", f"Q{i + 1}: you answered **{g or '—'}**") + extra)

    if plan:
        st.markdown(_EXAM_CSS, unsafe_allow_html=True)
        for h, ws in plan:
            if h != _LEFT:
                _show_html(h)
            for w in ws:
                slot(w)
        return
    cols = st.columns(3)
    for i in range(len(sh["mc"])):
        with cols[i % 3]:
            slot(("mc", i))
    for i, items in enumerate(sh["tf"]):
        for j in range(len(items)):
            slot(("tf", i, j))
    for i in range(len(sh["sa"])):
        slot(("sa", i))


def _exam_timer(aid, remaining):
    """Đồng hồ đếm ngược dính ở đầu trang; hết giờ tự bấm nút Nộp bài (làm bằng JavaScript trong khung nhúng)."""
    st.markdown(f'<style>.st-key-examtimer_{aid}{{position:sticky;top:3.2rem;z-index:99;background:rgba(255,255,255,.95);padding:4px 0;border-radius:10px}}</style>',
                unsafe_allow_html=True)
    with st.container(key=f"examtimer_{aid}"):
        components.html(f"""<div id="t" style="font:700 18px sans-serif;padding:8px 14px;border-radius:10px;display:inline-block"></div>
<script>
let left={int(max(0, remaining))},fired=false;const el=document.getElementById('t');
function fmt(s){{s=Math.max(0,s);return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')}}
function auto(){{if(fired)return;fired=true;el.textContent='⏱️ Hết giờ, đang nộp bài…';
  try{{const d=window.parent.document;if(d.activeElement)d.activeElement.blur();
  setTimeout(()=>{{const b=[...d.querySelectorAll('button')].find(x=>x.innerText.includes('Nộp bài'));if(b)b.click();}},400);}}catch(e){{}}}}
function tick(){{el.textContent='⏱️ Còn lại '+fmt(left);el.style.background=left<=60?'#ffd9d9':'#e8edff';el.style.color=left<=60?'#a00':'#223';
  if(left<=0){{auto();return;}}left--;setTimeout(tick,1000);}}
tick();
</script>""", height=54)


def answer_sheet_ui(a, atts=()):
    """Học sinh làm bài: các ô chọn A–D, Đúng/Sai, nhập đáp án nằm ngay trong đề (nếu ghép được), không thì dùng phiếu rời. Chấm tự động."""
    au = cur_auth()
    try:
        sh = cr.get_sheet(au, a["id"], force=True)
        mine = cr.sheet_results(au, a["id"], force=True) if sh else []
    except (OSError, cr.Denied) as e:
        st.error(str(e) if isinstance(e, cr.Denied) else hs.last_error)
        return
    if not sh:
        return
    st.markdown("#### " + tx("📝 Làm bài trực tiếp", "📝 Take the test"))
    if mine:
        last = mine[-1]
        det = last["detail"]
        wrong = {"mc": [i + 1 for i, v in enumerate(det.get("mc", [])) if v is False],
                 "tf": [i + 1 for i, v in enumerate(det.get("tf", [])) if v and not all(v)],
                 "sa": [i + 1 for i, v in enumerate(det.get("sa", [])) if v is False]}
        st.success(tx(f"Lần nộp gần nhất ({last['ts']}): **{last['score']:g}/{last['max']:g} điểm** · đã nộp {len(mine)} lần.",
                      f"Latest attempt ({last['ts']}): **{last['score']:g}/{last['max']:g}** · {len(mine)} attempt(s)."))
        names = {"mc": tx("Phần I", "Part I"), "tf": tx("Phần II", "Part II"), "sa": tx("Phần III", "Part III")}
        bad = [f"{names[k]}: " + ", ".join(map(str, v)) for k, v in wrong.items() if v]
        if bad:
            st.caption(tx("Câu cần xem lại — ", "Review these — ") + " · ".join(bad))
    n = len(mine)
    aid = a["id"]
    mc, tf, sa = {}, {}, {}

    def widget(w):
        k = w[0]
        if k == "mc":
            mc[w[1]] = st.radio(tx(f"✅ Câu {w[1] + 1}: chọn đáp án", f"✅ Q{w[1] + 1}: choose"), list("ABCD"), index=None, horizontal=True, key=f"sm_{aid}_{n}_{w[1]}")
        elif k == "tf":
            v = st.radio(tx(f"✅ Câu {w[1] + 1} ý {'abcdefgh'[w[2]]})", f"✅ Q{w[1] + 1} {'abcdefgh'[w[2]]})"), [tx("Đúng", "True"), tx("Sai", "False")],
                         index=None, horizontal=True, key=f"st_{aid}_{n}_{w[1]}_{w[2]}")
            tf[(w[1], w[2])] = None if v is None else v == tx("Đúng", "True")
        else:
            sa[w[1]] = st.text_input(tx(f"✅ Câu {w[1] + 1}: đáp án", f"✅ Q{w[1] + 1}: answer"), key=f"ss_{aid}_{n}_{w[1]}", max_chars=60)

    blocks = _exam_blocks(au, atts)
    plan = exam_plan(blocks, sh) if blocks else None
    if mine and not st.session_state.get(f"_redo_{aid}"):
        _review_ui(a, sh, plan, mine[-1], cr.sheet_review(au, aid))
        if st.button(tx("🔁 Làm lại bài", "🔁 Retake"), key=f"redo_{aid}"):
            st.session_state[f"_redo_{aid}"] = True
            st.rerun()
        return
    mins, t0, expired = int(a.get("mins") or 0), None, False
    if not mins:
        st.caption(tx("⏱️ Bài này chưa đặt giờ làm bài (giáo viên đặt trong Quản lý lớp > Giờ làm bài).", "⏱️ No time limit has been set for this one."))
    if mins:
        try:
            t0 = cr.get_start(au, aid)
        except OSError:
            st.error(hs.last_error)
            return
        if t0 is None:
            st.info(tx(f"⏱️ Bài này giới hạn **{mins} phút**. Đồng hồ bắt đầu chạy khi em bấm nút bên dưới; hết giờ bài sẽ tự nộp.",
                       f"⏱️ This one is limited to **{mins} minutes**. The clock starts when you press the button; it submits itself at the end."))
            if st.button(tx("▶️ Bắt đầu làm bài", "▶️ Start"), key=f"begin_{aid}", type="primary"):
                try:
                    cr.begin_attempt(au, aid, time.time())
                    st.rerun()
                except OSError:
                    st.error(hs.last_error)
            return
        left = t0 + mins * 60 - time.time()
        if left < -cr.GRACE:
            st.warning(tx("⏰ Đã hết giờ làm bài lần này.", "⏰ Time is up for this attempt."))
            if st.button(tx("🔁 Làm lại bài", "🔁 Start again"), key=f"restart_{aid}"):
                try:
                    cr.clear_start(au, aid)
                    st.rerun()
                except OSError:
                    st.error(hs.last_error)
            return
        expired = left <= 3
        _exam_timer(aid, left)
    with st.form(f"sheet_{aid}_{n}"):
        if plan:
            st.markdown(_EXAM_CSS, unsafe_allow_html=True)
            for h, ws in plan:
                if h == _LEFT:
                    st.markdown("**" + tx("Các câu còn lại trong phiếu (chưa gắn được vào đề)", "Other questions on the sheet (not matched to the exam)") + "**")
                else:
                    _show_html(h)
                for w in ws:
                    widget(w)
        else:
            if blocks:
                st.markdown(_EXAM_CSS, unsafe_allow_html=True)
                for h in blocks:
                    _show_html(h)
                st.caption(tx("Chọn đáp án ở phiếu dưới đây.", "Answer on the sheet below."))
            if sh["mc"]:
                st.markdown("**" + tx("Phần I. Chọn 1 đáp án", "Part I. Pick one answer") + "**")
                cols = st.columns(3)
                for i in range(len(sh["mc"])):
                    with cols[i % 3]:
                        widget(("mc", i))
            if sh["tf"]:
                st.markdown("**" + tx("Phần II. Đúng / Sai từng ý", "Part II. True / False per statement") + "**")
                for i, items in enumerate(sh["tf"]):
                    st.markdown(tx(f"Câu {i + 1}", f"Q{i + 1}"))
                    cols = st.columns(len(items))
                    for j in range(len(items)):
                        with cols[j]:
                            widget(("tf", i, j))
            if sh["sa"]:
                st.markdown("**" + tx("Phần III. Trả lời ngắn", "Part III. Short answer") + "**")
                cols = st.columns(3)
                for i in range(len(sh["sa"])):
                    with cols[i % 3]:
                        widget(("sa", i))
        go = st.form_submit_button(tx("📨 Nộp bài", "📨 Submit"), type="primary")
    if go:
        ans = {"mc": [mc.get(i) or "" for i in range(len(sh["mc"]))],
               "tf": [[tf.get((i, j)) for j in range(len(items))] for i, items in enumerate(sh["tf"])],
               "sa": [sa.get(i, "") for i in range(len(sh["sa"]))]}
        miss = cr.missing_parts(sh, ans)
        if (miss["mc"] or miss["tf"] or miss["sa"]) and not (mins and t0 and time.time() >= t0 + mins * 60 - 3):
            st.error(tx("⚠️ Em chưa làm đủ các ô nên chưa nộp được. Còn thiếu: ", "⚠️ Some answers are still empty, so it can't be submitted yet. Missing: ")
                     + cr.missing_text(miss, "vi" if i18n.lang() != "en" else "en"))
            return
        try:
            g = cr.submit_sheet(au, aid, ans, _now().strftime("%Y-%m-%d %H:%M"))
            st.session_state[f"_redo_{aid}"] = False
            st.session_state["_toast"] = tx(f"Đã nộp: {g['score']:g}/{g['max']:g} điểm.", f"Submitted: {g['score']:g}/{g['max']:g}.")
            st.rerun()
        except (OSError, cr.Denied) as e:
            st.error(str(e) if isinstance(e, cr.Denied) else hs.last_error)


def sheet_results_ui(a):
    """Giáo viên xem điểm phiếu trả lời của lớp và câu nào hay sai."""
    try:
        sh = cr.get_sheet(cur_auth(), a["id"], force=True)
        subs = cr.sheet_results(cur_auth(), a["id"], force=True) if sh else []
    except OSError:
        st.error(hs.last_error)
        return
    if not sh:
        return
    last, count = {}, {}
    for r in subs:
        last[r["student"]] = r
        count[r["student"]] = count.get(r["student"], 0) + 1
    with st.expander(tx(f"📝 Điểm phiếu trả lời ({len(last)} học sinh đã nộp)", f"📝 Answer sheet scores ({len(last)} submitted)"), expanded=bool(last)):
        if not last:
            st.caption(tx("Chưa có học sinh nào nộp phiếu.", "No submissions yet."))
            return
        rows = [{tx("Học sinh", "Student"): k.rsplit(" [", 1)[0], tx("Điểm", "Score"): v["score"], tx("Tối đa", "Max"): v["max"],
                 tx("Phần I đúng", "Part I ok"): v["right"].get("mc", 0), tx("Phần II đúng cả ý", "Part II ok"): v["right"].get("tf", 0),
                 tx("Phần III đúng", "Part III ok"): v["right"].get("sa", 0), tx("Số lần nộp", "Attempts"): count[k], tx("Lúc nộp", "Time"): v["ts"]}
                for k, v in sorted(last.items())]
        st.dataframe(rows, use_container_width=True, hide_index=True)
        done = {hs.slug(k) for k in last}
        try:
            missing = [n for n in cr.students(cur_auth(), a["code"]) if hs.slug(cr.identity(a["code"], n)) not in done]
        except OSError:
            missing = []
        if missing:
            st.caption(tx("Chưa nộp phiếu: ", "Not submitted: ") + ", ".join(missing))
        qrows = []
        for part, lab in (("mc", "I"), ("tf", "II"), ("sa", "III")):
            for i in range(len(sh[part])):
                ok = []
                for v in last.values():
                    x = (v["detail"].get(part) or [None] * (i + 1))[i] if i < len(v["detail"].get(part) or []) else None
                    if x is None:
                        continue
                    ok.append(all(x) if isinstance(x, list) else bool(x))
                if ok:
                    qrows.append({tx("Phần", "Part"): lab, tx("Câu", "Q"): i + 1, tx("% sai", "% wrong"): round(100 * (1 - sum(ok) / len(ok)))})
        if qrows:
            st.markdown("**" + tx("Câu hay sai (sắp theo tỉ lệ sai)", "Most missed questions") + "**")
            st.dataframe(sorted(qrows, key=lambda r: -list(r.values())[2])[:12], use_container_width=True, hide_index=True)


def student_files_ui(a):
    """Tệp giáo viên đính kèm (tải về) và khu nộp tệp bài làm của học sinh."""
    au = cur_auth()
    try:
        atts = cr.list_files(au, a["id"], kind=cr.ATT)
        mine = cr.list_files(au, a["id"], kind=cr.SUBF)
    except OSError:
        st.error(hs.last_error)
        return
    if atts:
        st.markdown("#### " + tx("📎 Tài liệu của giáo viên", "📎 Teacher's files"))
        file_rows_ui(atts, f"sa_{a['id']}")
    answer_sheet_ui(a, atts)
    with st.expander(tx("📤 Nộp tệp bài làm", "📤 Submit a file"), expanded=bool(mine)):
        if mine:
            file_rows_ui(mine, f"sm_{a['id']}", can_delete=True)
        upload_ui(a["id"], cr.SUBF, f"su_{a['id']}", tx("Chọn tệp bài làm (ảnh, PDF, Word…)", "Choose your file (photo, PDF, Word…)"), True)


def _cat_label(c):
    return tx("📝 Kiểm tra", "📝 Test") if c == cr.TEST else tx("📘 Luyện tập", "📘 Practice")


def practice_assign_ui(cat=None):
    cat = cat or cr.PRACTICE
    au = cur_auth()
    if not cr.is_student(au):
        if cr.is_teacher(au):
            st.info(tx("Tài khoản giáo viên không làm bài. Giao bài và xem kết quả ở tab Lịch sử tra cứu.",
                       "Teacher accounts do not take assignments. Assign work and see results in the History tab."))
        else:
            st.info(tx("Cần đăng nhập để làm bài giáo viên giao và lưu kết quả. Tự luyện thì không cần đăng nhập.",
                       "Log in to do assignments and save your results. Self practice needs no login."))
            if st.button(tx("🔐 Đăng nhập / Tham gia lớp", "🔐 Log in / Join a class"), key="pa_login", type="primary"):
                auth_dialog()
        return
    acct = {"cls": au["cls"]}
    me = au["key"]
    try:
        asgs = cr.assignments(au, au["cls"])
    except OSError:
        st.error(tx("Không đọc được bài giao: ", "Cannot read assignments: ") + hs.last_error)
        return
    asgs = [x for x in asgs if x["cat"] == cat]
    if not asgs:
        st.info(tx(f"Lớp {acct['cls']} chưa có bài kiểm tra nào.", f"Class {acct['cls']} has no tests yet.") if cat == cr.TEST
                else tx(f"Lớp {acct['cls']} chưa có bài luyện tập nào.", f"Class {acct['cls']} has no practice sets yet."))
        return
    a = st.selectbox(tx("Chọn bài", "Choose an assignment"), asgs, key=f"asg_pick_{cat}",
                     format_func=lambda x: (f"[{x['kind']}] " if x["kind"] else "") + x["title"] + (f" · ⏱️ {x['mins']} {tx('phút', 'min')}" if x["mins"] else "") + (f" · {tx('hạn', 'due')} {x['due']}" if x["due"] else ""))
    student_files_ui(a)
    if not a["questions"]:
        st.info(tx("Bài này không có câu luyện tập từng chất. Hãy xem đề, làm phiếu trả lời và nộp tệp bài làm ở trên (nếu có).", "No per-compound practice here. Use the files, answer sheet and file upload above."))
        return
    try:
        prog = cr.progress(a, cr.submissions(au, aid=a["id"])).get(me, {})
    except OSError:
        st.error(hs.last_error)
        return
    qs = a["questions"]
    stat = [prog.get(cr.qkey(x)) for x in qs]
    n_done = sum(1 for s_ in stat if s_ and (s_["ok"] or s_["tries"] >= MAX_TRIES))
    n_ok = sum(1 for s_ in stat if s_ and s_["ok"])
    st.progress(n_done / max(1, len(qs)), text=tx(f"Đã xong {n_done}/{len(qs)} câu · đúng {n_ok}", f"Done {n_done}/{len(qs)} · correct {n_ok}"))
    key = f"asg_sel_{a['id']}"
    if key not in st.session_state:
        st.session_state[key] = next((i for i, s_ in enumerate(stat) if not (s_ and (s_["ok"] or s_["tries"] >= MAX_TRIES))), 0)
    idx = st.selectbox(tx("Câu hỏi", "Question"), list(range(len(qs))), key=key, format_func=lambda i: _q_label(i, qs[i], stat[i]))
    spec = qs[idx]
    if spec["n"] not in BANK_BY_NAME:
        st.warning(tx("Câu này không còn trong ngân hàng đề.", "This question is no longer in the question bank."))
        return
    cur = st.session_state.get("pq")
    if not cur or cur["aid"] != a["id"] or cr.qkey(cur["spec"]) != cr.qkey(spec):
        st.session_state.pq = new_qstate(spec, a["id"], stat[idx])
    render_question(st.session_state.pq, allow_hints=a["hints"], next_cb=_go_next_asg, next_args=(a["id"], idx, len(qs)))


def practice_ui():
    mode = st.radio(tx("Chế độ", "Mode"), ["free", "asg"], horizontal=True, key="pr_mode",
                    format_func=lambda m: tx("Tự luyện", "Self practice") if m == "free" else tx("Bài giáo viên giao", "Teacher's assignments"))
    if mode == "free":
        practice_free_ui()
    else:
        practice_assign_ui(cr.PRACTICE)


# ---------------- Đánh giá độ chính xác (giáo viên / nhóm nghiên cứu) ----------------
def parse_truth(text):
    rows = {}
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.replace(";", ",").split(",")]
        if len(parts) >= 2 and parts[0] and parts[1]:
            rows[parts[0]] = (parts[1], parts[2] if len(parts) > 2 else "")
    return rows


def bench_row(pred, truth):
    mp, mt = Chem.MolFromSmiles(pred or ""), Chem.MolFromSmiles(truth)
    if mp is None or mt is None:
        return {"hop_le": False, "khop_cong_thuc": False, "khop_cau_tao": False, "khop_hoan_toan": False}
    return {"hop_le": True, "khop_cong_thuc": formula_of(mp) == formula_of(mt),
            "khop_cau_tao": noiso(mp) == noiso(mt),
            "khop_hoan_toan": Chem.MolToSmiles(mp) == Chem.MolToSmiles(mt)}


def bench_summary(rows):
    n = len(rows)
    pct = lambda k: round(100 * sum(1 for r in rows if r[k]) / n, 1) if n else 0
    return {"n": n, "hop_le": pct("hop_le"), "khop_cong_thuc": pct("khop_cong_thuc"),
            "khop_cau_tao": pct("khop_cau_tao"), "khop_hoan_toan": pct("khop_hoan_toan"),
            "tb_giay": round(sum(r["giay"] for r in rows) / n, 1) if n else 0}


def bench_ui():
    code = st.secrets.get("TEACHER_CODE", "")
    if code and st.text_input("Mã giáo viên", type="password", key="bm_code") != code:
        st.info("Tab này dành cho giáo viên hoặc nhóm nghiên cứu. Nhập mã giáo viên để dùng.")
        return
    st.markdown("Tải lên một bộ ảnh đã biết đáp án để đo **độ chính xác nhận dạng**. Kết quả có thể đưa vào báo cáo đề tài.")
    files = st.file_uploader("Ảnh kiểm thử", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True, key="bm_files")
    up = st.file_uploader("File đáp án CSV (tên_file, SMILES, nhóm)", type=["csv", "txt"], key="bm_csv")
    txt = st.text_area("Hoặc dán đáp án, mỗi dòng: tên_file, SMILES, nhóm", height=130, key="bm_truth",
                       placeholder="03_toluen.jpg, Cc1ccccc1, benzen\n06_etyl_axetat.jpg, CCOC(C)=O, công thức khung")
    method = st.radio("Phương pháp đọc ảnh", ["Đồ thị nguyên tử (trung thực với bài vẽ)", "SMILES trực tiếp"], horizontal=True, key="bm_method")
    src = up.getvalue().decode("utf-8-sig", errors="ignore") if up else txt
    truth = parse_truth(src)
    todo = [f for f in (files or []) if f.name in truth][:BENCH_MAX]
    if files and truth:
        st.caption(f"Có {len(todo)}/{len(files)} ảnh khớp tên trong file đáp án (tối đa {BENCH_MAX} ảnh mỗi lần chạy).")
    if st.button("Chạy đánh giá", type="primary", disabled=not todo, key="bm_go"):
        rows, bar = [], st.progress(0.0, text="Đang chạy…")
        for i, f in enumerate(todo):
            t0 = time.time()
            pred, err = "", ""
            try:
                pred = transcribe_student(f.getvalue())[0] if method.startswith("Đồ thị") else to_smiles(f.getvalue(), "")
            except Exception as e:
                err = type(e).__name__
            tr, grp = truth[f.name]
            r = {"tep": f.name, "nhom": grp, "dap_an": tr, "phuong_phap": "do_thi" if method.startswith("Đồ thị") else "smiles", "ket_qua_may": pred, "loi": err, "giay": round(time.time() - t0, 1)}
            r.update(bench_row(pred, tr))
            rows.append(r)
            bar.progress((i + 1) / len(todo), text=f"Đã xử lý {i + 1}/{len(todo)}")
        st.session_state.bm = rows
    rows = st.session_state.get("bm")
    if rows:
        sm = bench_summary(rows)
        a, b, c, d = st.columns(4)
        a.metric("Số ảnh", sm["n"])
        b.metric("Khớp cấu tạo", f"{sm['khop_cau_tao']}%")
        c.metric("Khớp công thức PT", f"{sm['khop_cong_thuc']}%")
        d.metric("SMILES hợp lệ", f"{sm['hop_le']}%")
        st.caption(f"Khớp hoàn toàn (kể cả lập thể): {sm['khop_hoan_toan']}% · thời gian trung bình: {sm['tb_giay']} giây/ảnh")
        grp = sorted({r["nhom"] for r in rows if r["nhom"]})
        if grp:
            st.markdown("**Theo nhóm nét vẽ**")
            st.dataframe([{"Nhóm": g, **{k: v for k, v in bench_summary([r for r in rows if r["nhom"] == g]).items()
                                         if k in ("n", "khop_cau_tao", "khop_cong_thuc", "hop_le")}} for g in grp],
                         hide_index=True, width="stretch")
        st.dataframe(rows, hide_index=True, width="stretch")
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
        st.download_button("⬇️ Tải bảng kết quả (CSV)", buf.getvalue().encode("utf-8-sig"), file_name="ket_qua_danh_gia.csv",
                           mime="text/csv", key="bm_dl")
    st.caption("Khớp cấu tạo: SMILES máy đọc được và đáp án giống nhau về cấu tạo (RDKit chuẩn hóa trước khi so sánh).")


# ---------------- Sơ đồ tư duy ----------------
MM_COLORS = ["#e11d48", "#f59e0b", "#16a34a", "#0ea5e9", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"]
MM_FONT = "Arial, Helvetica, sans-serif"

MM_PROMPT = """Bạn là giáo viên Hóa học THPT Việt Nam. Hãy lập SƠ ĐỒ TƯ DUY cho chủ đề được yêu cầu, đúng nội dung SGK Việt Nam.
Chỉ trả về MỘT đối tượng JSON, không markdown:
{"chu_de":"tên chủ đề ngắn gọn","chat_smiles":"SMILES nếu chủ đề là MỘT chất cụ thể (ví dụ etanol), nếu là nhóm chất hoặc khái niệm thì null",
"nhanh":[{"ten":"tên nhánh, tối đa 24 ký tự","y":["ý ngắn, tối đa 80 ký tự"]}]}
Quy tắc:
- Chọn các nhánh phù hợp chủ đề, ví dụ: Khái niệm và cấu tạo, Danh pháp, Tính chất vật lí, Tính chất hóa học, Điều chế, Ứng dụng, Nhận biết, Lưu ý. Với chủ đề phản ứng thì dùng: Định nghĩa, Điều kiện, Ví dụ, Quy tắc, Nhận biết.
- Mỗi ý ngắn gọn, dễ nhớ. Viết công thức bằng chữ thường (CH3-CH2-OH). Phương trình viết dạng: A + B → C (điều kiện).
- KHÔNG nêu số lượng đồng phân hay khối lượng mol (bộ máy tính toán sẽ thêm riêng). Không bịa số liệu."""


def _wrap(text, width):
    lines, cur = [], ""
    for w in str(text).split():
        if len(cur) + len(w) + (1 if cur else 0) <= width:
            cur = (cur + " " + w).strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _tint(hexc, a=0.12):
    r, g, b = int(hexc[1:3], 16), int(hexc[3:5], 16), int(hexc[5:7], 16)
    return f"rgba({r},{g},{b},{a})"


def mindmap_layout(title, branches):
    """Tính vị trí mọi khung và đường nối (đơn vị px). Dùng chung cho SVG, PowerPoint, draw.io và FreeMind."""
    LEAF_W, LH = 30, 19
    cw_leaf, cw_br, cw_root = 7.9, 9.8, 14.0
    root_lines = _wrap(title, 16)
    rw = max(len(x) for x in root_lines) * cw_root + 56
    rh = len(root_lines) * 28 + 36
    items = []
    for i, b in enumerate(branches):
        blines = _wrap(b["ten"], 18)
        bw = max(len(x) for x in blines) * cw_br + 36
        bh = len(blines) * 22 + 20
        leaves = []
        for t in b.get("y", []):
            ll = _wrap(t, LEAF_W)
            leaves.append((t, ll, max(len(x) for x in ll) * cw_leaf + 24, len(ll) * LH + 14))
        block = sum(l[3] for l in leaves) + 8 * max(0, len(leaves) - 1)
        items.append({"b": b, "blines": blines, "bw": bw, "bh": bh, "leaves": leaves, "block": block,
                      "h": max(block, bh), "color": b.get("color") or MM_COLORS[i % len(MM_COLORS)]})
    half = (len(items) + 1) // 2
    sides = {"R": items[:half], "L": items[half:]}
    GAP, MARG = 28, 50
    tot = {k: sum(x["h"] for x in v) + GAP * max(0, len(v) - 1) for k, v in sides.items()}
    H = max(max(tot.values()), rh) + 2 * MARG
    reach = 0
    for v in sides.values():
        for x in v:
            reach = max(reach, 70 + x["bw"] + 55 + max([l[2] for l in x["leaves"]] or [0]))
    W = 2 * (rw / 2 + reach + MARG)
    cx, cy = W / 2, H / 2
    nodes = [{"id": "n0", "kind": "root", "x": cx - rw / 2, "y": cy - rh / 2, "w": rw, "h": rh, "text": title,
              "lines": root_lines, "color": "#4f46e5", "side": None, "parent": None}]
    edges, k = [], 1
    for side, v in sides.items():
        sgn = 1 if side == "R" else -1
        y = cy - tot[side] / 2
        for x in v:
            col, yb = x["color"], y + x["h"] / 2
            bx0 = cx + sgn * (rw / 2 + 70)
            bx1 = bx0 + sgn * x["bw"]
            bid = f"n{k}"
            k += 1
            nodes.append({"id": bid, "kind": "branch", "x": min(bx0, bx1), "y": yb - x["bh"] / 2, "w": x["bw"], "h": x["bh"],
                          "text": x["b"]["ten"], "lines": x["blines"], "color": col, "side": side, "parent": "n0"})
            edges.append({"a": "n0", "b": bid, "color": col, "width": 5, "x1": cx + sgn * rw / 2, "y1": cy, "x2": bx0, "y2": yb, "side": side})
            ly = y + (x["h"] - x["block"]) / 2
            lx0 = bx1 + sgn * 55
            for text, ll, lw, lh in x["leaves"]:
                lid = f"n{k}"
                k += 1
                nodes.append({"id": lid, "kind": "leaf", "x": lx0 if side == "R" else lx0 - lw, "y": ly, "w": lw, "h": lh,
                              "text": text, "lines": ll, "color": col, "side": side, "parent": bid})
                edges.append({"a": bid, "b": lid, "color": col, "width": 2.5, "x1": bx1, "y1": yb, "x2": lx0, "y2": ly + lh / 2, "side": side})
                ly += lh + 8
            y += x["h"] + GAP
    return {"W": W, "H": H, "nodes": nodes, "edges": edges}


def svg_from_layout(L):
    esc = html.escape
    W, H = L["W"], L["H"]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" '
           f'font-family="{MM_FONT}"><defs><linearGradient id="rg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4f46e5"/>'
           f'<stop offset="1" stop-color="#14b8a6"/></linearGradient></defs><rect width="100%" height="100%" fill="#ffffff"/>']
    for e in L["edges"]:
        xm = (e["x1"] + e["x2"]) / 2
        out.append(f'<path d="M{e["x1"]:.1f} {e["y1"]:.1f} C{xm:.1f} {e["y1"]:.1f} {xm:.1f} {e["y2"]:.1f} {e["x2"]:.1f} {e["y2"]:.1f}" '
                   f'fill="none" stroke="{e["color"]}" stroke-width="{e["width"]}" stroke-linecap="round"/>')
    texts = []
    for n in L["nodes"]:
        x, y, w, h, col = n["x"], n["y"], n["w"], n["h"], n["color"]
        cxn, cyn = x + w / 2, y + h / 2
        if n["kind"] == "root":
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{h / 2:.1f}" fill="url(#rg)"/>')
            ty = cyn - len(n["lines"]) * 28 / 2 + 21
            for j, ln in enumerate(n["lines"]):
                texts.append(f'<text x="{cxn:.1f}" y="{ty + j * 28:.1f}" text-anchor="middle" font-size="24" font-weight="800" fill="#fff">{esc(ln)}</text>')
        elif n["kind"] == "branch":
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="14" fill="{col}"/>')
            ty = cyn - len(n["lines"]) * 22 / 2 + 16
            for j, ln in enumerate(n["lines"]):
                texts.append(f'<text x="{cxn:.1f}" y="{ty + j * 22:.1f}" text-anchor="middle" font-size="17" font-weight="700" fill="#fff">{esc(ln)}</text>')
        else:
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="10" fill="{_tint(col)}" stroke="{col}" stroke-width="1.5"/>')
            for j, ln in enumerate(n["lines"]):
                texts.append(f'<text x="{x + 12:.1f}" y="{y + 7 + 19 * (j + 1) - 5:.1f}" font-size="15" fill="#1f2937">{esc(ln)}</text>')
    return "".join(out + texts) + "</svg>"


def mindmap_svg(title, branches):
    L = mindmap_layout(title, branches)
    return svg_from_layout(L), L["W"], L["H"]


def _blend(hexc, a=0.12):
    r, g, b = int(hexc[1:3], 16), int(hexc[3:5], 16), int(hexc[5:7], 16)
    return "{:02x}{:02x}{:02x}".format(*(round(c * a + 255 * (1 - a)) for c in (r, g, b)))


def mm_pptx_bytes(L):
    """PowerPoint: mỗi khung là hình có chữ sửa được, đường nối dính vào khung nên kéo khung thì đường nối đi theo."""
    try:
        from pptx import Presentation
        from pptx.dml.color import RGBColor
        from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
        from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
        from pptx.util import Emu, Pt
    except ImportError:
        return None
    E = 9525
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(int(L["W"] * E)), Emu(int(L["H"] * E))
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    rgb = lambda h: RGBColor.from_string(h.lstrip("#").upper())
    shapes = {}
    for n in L["nodes"]:
        shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Emu(int(n["x"] * E)), Emu(int(n["y"] * E)), Emu(int(n["w"] * E)), Emu(int(n["h"] * E)))
        shp.adjustments[0] = min(0.5, (n["h"] / 2 if n["kind"] == "root" else (14 if n["kind"] == "branch" else 10)) / min(n["w"], n["h"]))
        shp.shadow.inherit = False
        shp.fill.solid()
        if n["kind"] == "leaf":
            shp.fill.fore_color.rgb = RGBColor.from_string(_blend(n["color"]).upper())
            shp.line.color.rgb = rgb(n["color"])
            shp.line.width = Pt(1.2)
        else:
            shp.fill.fore_color.rgb = rgb(n["color"])
            shp.line.fill.background()
        tf = shp.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.margin_left = tf.margin_right = Emu(int(10 * E))
        tf.margin_top = tf.margin_bottom = Emu(int(4 * E))
        para = tf.paragraphs[0]
        para.alignment = PP_ALIGN.LEFT if n["kind"] == "leaf" else PP_ALIGN.CENTER
        run = para.add_run()
        run.text = n["text"]
        run.font.name = "Arial"
        run.font.size = Pt({"root": 18, "branch": 13, "leaf": 11}[n["kind"]])
        run.font.bold = n["kind"] != "leaf"
        run.font.color.rgb = RGBColor(0x1F, 0x29, 0x37) if n["kind"] == "leaf" else RGBColor(255, 255, 255)
        shapes[n["id"]] = shp
    tree = slide.shapes._spTree
    for e in L["edges"]:
        c = slide.shapes.add_connector(MSO_CONNECTOR.CURVE, Emu(int(e["x1"] * E)), Emu(int(e["y1"] * E)), Emu(int(e["x2"] * E)), Emu(int(e["y2"] * E)))
        right = e["side"] == "R"
        c.begin_connect(shapes[e["a"]], 3 if right else 1)
        c.end_connect(shapes[e["b"]], 1 if right else 3)
        c.line.color.rgb = rgb(e["color"])
        c.line.width = Pt(e["width"] * 0.75)
        tree.remove(c._element)
        tree.insert(2, c._element)  # đưa đường nối xuống dưới các khung
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def mm_drawio(L):
    """File .drawio (mở bằng app.diagrams.net hoặc draw.io Desktop)."""
    def attr(t):
        return html.escape(html.escape(str(t), quote=False), quote=True)
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    for n in L["nodes"]:
        if n["kind"] == "root":
            st_ = "rounded=1;arcSize=50;whiteSpace=wrap;html=1;fillColor=#4f46e5;strokeColor=none;fontColor=#ffffff;fontStyle=1;fontSize=18;"
        elif n["kind"] == "branch":
            st_ = f"rounded=1;arcSize=30;whiteSpace=wrap;html=1;fillColor={n['color']};strokeColor=none;fontColor=#ffffff;fontStyle=1;fontSize=13;"
        else:
            st_ = (f"rounded=1;arcSize=20;whiteSpace=wrap;html=1;fillColor=#{_blend(n['color'])};strokeColor={n['color']};"
                   "fontColor=#1f2937;fontSize=11;align=left;spacingLeft=6;")
        cells.append(f'<mxCell id="{n["id"]}" value="{attr(n["text"])}" style="{st_}" vertex="1" parent="1">'
                     f'<mxGeometry x="{n["x"]:.0f}" y="{n["y"]:.0f}" width="{n["w"]:.0f}" height="{n["h"]:.0f}" as="geometry"/></mxCell>')
    for i, e in enumerate(L["edges"]):
        ex, nx = ("1", "0") if e["side"] == "R" else ("0", "1")
        cells.append(f'<mxCell id="e{i}" style="curved=1;endArrow=none;html=1;strokeColor={e["color"]};strokeWidth={e["width"]};'
                     f'exitX={ex};exitY=0.5;entryX={nx};entryY=0.5;" edge="1" parent="1" source="{e["a"]}" target="{e["b"]}">'
                     '<mxGeometry relative="1" as="geometry"/></mxCell>')
    return ('<mxfile host="app.diagrams.net"><diagram name="So do tu duy" id="mm1"><mxGraphModel grid="1" gridSize="10" page="0">'
            "<root>" + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>")


def mm_freemind(L):
    """File .mm (FreeMind) mở được bằng XMind, Freeplane, MindManager, Mindomo."""
    q = lambda t: html.escape(str(t), quote=True)
    root = L["nodes"][0]
    out = [f'<map version="1.0.1"><node TEXT="{q(root["text"])}">']
    for b in [n for n in L["nodes"] if n["kind"] == "branch"]:
        pos = "right" if b["side"] == "R" else "left"
        out.append(f'<node TEXT="{q(b["text"])}" POSITION="{pos}" COLOR="{b["color"]}">')
        out += [f'<node TEXT="{q(l["text"])}"/>' for l in L["nodes"] if l["parent"] == b["id"]]
        out.append("</node>")
    out.append("</node></map>")
    return "".join(out)


def rows_to_branches(rows):
    """Bảng chỉnh sửa (Nhánh, Ý) -> danh sách nhánh. Dòng không ghi nhánh thì thuộc nhánh ngay trên."""
    order, data = [], {}
    for r_ in rows:
        n = str(r_.get("Nhánh") or "").strip()
        y = str(r_.get("Ý") or "").strip()
        if not n and not y:
            continue
        n = n or (order[-1] if order else "Nhánh mới")
        if n not in data:
            data[n] = []
            order.append(n)
        if y:
            data[n].append(y[:100])
    return [{"ten": n[:28], "y": data[n], **({"color": "#475569"} if n.startswith("Số liệu (máy tính)") else {})} for n in order[:10]]


def mm_outline(title, branches):
    lines = [f"# {title}"]
    for b in branches:
        lines.append(f"\n## {b['ten']}")
        lines += [f"- {t}" for t in b.get("y", [])]
    return "\n".join(lines)


def mm_clean(raw):
    """Giữ sơ đồ gọn: tối đa 8 nhánh, 5 ý mỗi nhánh, cắt câu quá dài."""
    out = []
    wl, yl = (28, 100) if i18n.lang() == "vi" else (48, 180)   # chữ song ngữ dài hơn
    for b in (raw.get("nhanh") or [])[:8]:
        ten = str(b.get("ten", "")).strip()[:wl]
        ys = [str(t).strip()[:yl] for t in (b.get("y") or []) if str(t).strip()][:5]
        if ten and ys:
            out.append({"ten": ten, "y": ys})
    return out


def mm_engine_facts(smiles):
    """Số liệu do RDKit và bộ máy đồng phân tính, không phải AI."""
    m, _ = parse_student(smiles or "")
    if m is None:
        return None
    f = formula_of(m)
    facts = [f"Công thức phân tử: {pretty(f)}", f"Khối lượng mol: {Descriptors.MolWt(m):.2f} g/mol",
             "Nhóm chức / loại: " + ", ".join(iso_labels(m))]
    counts, nH = mol_counts(m)
    if sum(counts.values()) <= 10 and all(e in VALENCE for e in counts):
        try:
            res = build_iso_result(hill_key(counts, nH), None, dict(PRESETS["mono"]))
            if res["ok"] and res["kept"]:
                k = res["kept"]
                facts.append(f"Số đồng phân cấu tạo đơn chức mạch hở của {pretty(f)}: {len(k)} (kể cả lập thể: {sum(x['stereo'] for x in k)})")
        except Exception:
            pass
    return facts


MM_PAGE = """<div style="font-family:Arial,sans-serif"><button id="dl" style="background:#1f7a4d;color:#fff;border:0;border-radius:10px;padding:11px 18px;font-weight:700;font-size:15px;cursor:pointer">⬇️ Tải ảnh PNG</button>
<span id="msg" style="margin-left:10px;font-size:13px;color:#555"></span>
<div style="overflow:auto;border:1px solid #d6ece5;border-radius:12px;margin-top:8px;background:#fff"><div style="width:max-content;max-width:100%">__SVG__</div></div>
<div id="prev" style="display:none;margin-top:10px;text-align:center"><div style="font-size:13px;color:#555;margin-bottom:6px">Nếu máy không tự tải, nhấn giữ vào ảnh bên dưới rồi chọn "Tải ảnh xuống" hoặc "Lưu ảnh".</div><img id="pimg" style="max-width:100%;border:1px solid #ddd;border-radius:8px"></div></div>
<script>
(function () {
  var W = __W__, H = __H__, msg = document.getElementById("msg");
  function say(t) { msg.textContent = t || ""; }
  document.getElementById("dl").onclick = function () {
    say("Đang tạo ảnh…");
    try {
      var s = document.querySelector("svg"), x = new XMLSerializer().serializeToString(s), i = new Image();
      // điện thoại giới hạn kích thước canvas: cạnh dài tối đa 3000 px và tối đa 8 triệu điểm ảnh
      var k = Math.min(2, 3000 / Math.max(W, H), Math.sqrt(8000000 / (W * H)));
      i.onerror = function () { say("Không tạo được ảnh. Hãy dùng nút SVG bên dưới."); };
      i.onload = function () {
        var c = document.createElement("canvas"); c.width = Math.max(1, Math.round(W * k)); c.height = Math.max(1, Math.round(H * k));
        var g = c.getContext("2d"); g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height); g.drawImage(i, 0, 0, c.width, c.height);
        c.toBlob(function (b) {
          if (!b) { say("Máy không tạo được ảnh PNG (hết bộ nhớ). Hãy dùng nút SVG bên dưới."); return; }
          var url = URL.createObjectURL(b);
          document.getElementById("pimg").src = url; document.getElementById("prev").style.display = "block";
          var file = null; try { file = new File([b], "so_do_tu_duy.png", { type: "image/png" }); } catch (e) { }
          var mobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
          function plain() {
            var a = document.createElement("a"); a.href = url; a.download = "so_do_tu_duy.png"; a.style.display = "none"; document.body.appendChild(a); a.click();
            setTimeout(function () { document.body.removeChild(a); }, 1000); say("Đã tạo ảnh. Nếu chưa thấy tệp, nhấn giữ vào ảnh bên dưới để lưu.");
          }
          if (mobile && file && navigator.canShare && navigator.canShare({ files: [file] })) {
            navigator.share({ files: [file], title: "Sơ đồ tư duy" }).then(function () { say(""); }).catch(function (e) { if (e && e.name === "AbortError") say(""); else plain(); });
          } else plain();
        }, "image/png");
      };
      i.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(x);
    } catch (e) { say("Lỗi: " + e); }
  };
})();
</script>"""


_MM_FONT_FILES = {
    False: ["/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf", "arial.ttf"],
    True: ["/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
           "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf"]}


def _mm_font(size, bold):
    from PIL import ImageFont
    for f in _MM_FONT_FILES[bold]:
        try:
            return ImageFont.truetype(f, int(round(size)))
        except Exception:
            continue
    return None


@st.cache_data(show_spinner=False, max_entries=20)
def mm_png_bytes(_L, key):
    """Vẽ sơ đồ thành ảnh PNG ngay trên máy chủ (Pillow) để dùng nút tải chuẩn của Streamlit, chạy được trên điện thoại.
    Trả về None nếu máy chủ không có phông chữ phù hợp (khi đó dùng nút tạo ảnh bằng trình duyệt)."""
    from PIL import Image, ImageDraw
    L = _L
    if _mm_font(15, False) is None:
        return None
    W, H = L["W"], L["H"]
    k = min(2.0, 3000 / max(W, H))
    S = 2   # vẽ gấp đôi rồi thu nhỏ để nét mượt
    sc = k * S
    img = Image.new("RGB", (max(1, int(W * sc)), max(1, int(H * sc))), "white")
    d = ImageDraw.Draw(img)

    def rgb(h):
        h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    def bez(e):
        x1, y1, x2, y2 = e["x1"], e["y1"], e["x2"], e["y2"]; xm = (x1 + x2) / 2
        pts = []
        for i in range(41):
            t = i / 40; u = 1 - t
            pts.append(((u ** 3 * x1 + 3 * u * u * t * xm + 3 * u * t * t * xm + t ** 3 * x2) * sc, (u ** 3 * y1 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3 * y2) * sc))
        return pts
    for e in L["edges"]:
        pts, w, c = bez(e), max(1, int(e["width"] * sc)), rgb(e["color"])
        d.line(pts, fill=c, width=w, joint="curve")
        for (px, py) in (pts[0], pts[-1]):
            d.ellipse([px - w / 2, py - w / 2, px + w / 2, py + w / 2], fill=c)

    def fit(text, size, bold, maxw):
        f = _mm_font(size * sc, bold)
        while f is not None and f.getlength(text) > maxw * sc and size > 8:
            size -= 0.5; f = _mm_font(size * sc, bold)
        return f
    for n in L["nodes"]:
        x, y, w, h, col = n["x"] * sc, n["y"] * sc, n["w"] * sc, n["h"] * sc, n["color"]
        if n["kind"] == "root":
            grad = Image.new("RGB", (max(1, int(w)), max(1, int(h))))
            gd = ImageDraw.Draw(grad); a, b = rgb("#4f46e5"), rgb("#14b8a6")
            for i in range(int(w + h)):
                t = i / max(1, w + h - 1); c = tuple(int(a[j] + (b[j] - a[j]) * t) for j in range(3)); gd.line([(i, 0), (i - h, h)], fill=c, width=2)
            mask = Image.new("L", grad.size, 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, grad.size[0] - 1, grad.size[1] - 1], radius=h / 2, fill=255)
            img.paste(grad, (int(x), int(y)), mask)
            fs, bold, tc, lh = 24, True, "white", 28
        elif n["kind"] == "branch":
            d.rounded_rectangle([x, y, x + w, y + h], radius=14 * sc, fill=rgb(col)); fs, bold, tc, lh = 17, True, "white", 22
        else:
            d.rounded_rectangle([x, y, x + w, y + h], radius=10 * sc, fill=rgb("#" + _blend(col, .12)), outline=rgb(col), width=max(1, int(1.5 * sc))); fs, bold, tc, lh = 15, False, "#1f2937", 19
        cxn, cyn = x + w / 2, y + h / 2
        for j, ln in enumerate(n["lines"]):
            f = fit(ln, fs, bold, n["w"] - (10 if n["kind"] != "leaf" else 18))
            if f is None:
                continue
            if n["kind"] == "root":
                d.text((cxn, cyn - len(n["lines"]) * lh * sc / 2 + (j + .5) * lh * sc), ln, font=f, fill=tc, anchor="mm")
            elif n["kind"] == "branch":
                d.text((cxn, cyn - len(n["lines"]) * lh * sc / 2 + (j + .5) * lh * sc), ln, font=f, fill=tc, anchor="mm")
            else:
                d.text((x + 12 * sc, y + (7 + lh * (j + .5)) * sc), ln, font=f, fill=tc, anchor="lm")
    img = img.resize((max(1, int(W * k)), max(1, int(H * k))), Image.LANCZOS)
    buf = io.BytesIO(); img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def mm_component(svg, W, H, button=True):
    scale = min(1.0, 1000.0 / W)
    page = MM_PAGE.replace("__SVG__", svg.replace("<svg ", '<svg style="max-width:100%;height:auto;display:block" ', 1)).replace("__W__", str(int(W))).replace("__H__", str(int(H)))
    if not button:   # đã có nút tải chuẩn ở ngoài khung, ẩn nút bằng JavaScript trong khung
        page = page.replace('<button id="dl" style="', '<button id="dl" style="display:none;', 1)
    height = int(H * scale) + 90
    if hasattr(st, "iframe"):  # st.components.v1.html sẽ bị gỡ; nội dung trong page đã được escape, không chứa HTML từ AI
        st.iframe(page, height=height + 40)
    else:
        components.html(page, height=height + 40, scrolling=True)


MM_EXAMPLES = ["Ancol", "Anđehit và xeton", "Axit cacboxylic", "Este và lipit", "Amin và amino axit", "Benzen và đồng đẳng",
               "Phenol", "Etanol", "Phản ứng cộng"]


def _set_topic(t):
    st.session_state["mm_topic"] = t


MM_PHOTO_PROMPT = """Đây là ảnh SƠ ĐỒ TƯ DUY HÓA HỌC được vẽ tay trên giấy. Hãy đọc và số hóa lại ĐÚNG cấu trúc và nội dung đã vẽ.
Chỉ trả về MỘT đối tượng JSON, không markdown:
{"chu_de":"chủ đề ở giữa sơ đồ","nhanh":[{"ten":"tên nhánh chính nối trực tiếp với chủ đề, tối đa 28 ký tự","mau":"mã màu #rrggbb của nhánh nếu trên giấy có tô màu, nếu không thì null","y":["các ý thuộc nhánh này, theo thứ tự đọc"]}],"ghi_chu":"chữ khó đọc hoặc chỗ không chắc chắn, nếu không có thì null"}
Quy tắc:
- Giữ đúng chữ và cách diễn đạt trên giấy. KHÔNG thêm ý mới, KHÔNG sửa nội dung hóa học. Chỉ sửa lỗi chính tả hiển thị rõ ràng.
- Nhánh phụ cấp 2, cấp 3 gộp vào danh sách y của nhánh chính. Dùng dạng "Tên nhánh phụ: nội dung" hoặc "A → B" để giữ quan hệ.
- Viết công thức bằng chữ thường (CH3-CH2-OH). Phương trình viết dạng: A + B → C (điều kiện).
- Chữ không đọc được thì ghi [?] tại chỗ đó và nêu trong ghi_chu.
- Nếu ảnh không phải sơ đồ tư duy: trả {"chu_de":"","nhanh":[],"ghi_chu":"lý do"}."""

_HEX6 = re.compile(r"^#[0-9a-fA-F]{6}$")


def mm_clean_photo(raw):
    """Giữ gần nguyên bản vẽ tay: tối đa 10 nhánh, 8 ý mỗi nhánh, giữ màu nhánh nếu hợp lệ."""
    out = []
    for b in (raw.get("nhanh") or [])[:10]:
        ten = str(b.get("ten", "")).strip()[:28]
        ys = [str(t).strip()[:100] for t in (b.get("y") or []) if str(t).strip()][:8]
        if ten:
            item = {"ten": ten, "y": ys or [""]}
            c = str(b.get("mau") or "").strip()
            if _HEX6.match(c):
                item["color"] = c.lower()
            out.append(item)
    return out


def _mm_photo_inputs(top):
    src = st.radio("Nguồn ảnh", ["🖼️ Tải ảnh lên", "📷 Chụp ảnh"], horizontal=True, key="mm_src")
    if src.startswith("📷"):
        f = st.camera_input("Chụp sơ đồ vẽ tay (đủ sáng, chụp thẳng góc, chữ rõ nét)", key="mm_cam")
    else:
        f = st.file_uploader("Chọn ảnh sơ đồ tư duy vẽ tay (đủ sáng, chụp thẳng góc, chữ rõ nét)", type=["jpg", "jpeg", "png", "webp"], key="mm_up")
    img = f.getvalue() if f else None
    if img:
        st.image(img, caption="Sơ đồ bạn đã vẽ", width=380)
    if st.button("Số hóa sơ đồ này", type="primary", disabled=not img, key="mm_photo_go"):
        if over_quota():
            show_top_error(top, "Bạn đã dùng hết số lượt của phiên này. Hãy tải lại trang để tiếp tục.")
            return
        with st.spinner("Đang đọc sơ đồ vẽ tay…"):
            try:
                raw = ask_ai([types.Part.from_bytes(data=to_jpeg(img), mime_type="image/jpeg"), MM_PHOTO_PROMPT], temperature=0.1, lang_note=False)
                branches = mm_clean_photo(raw)
                if not branches:
                    show_top_error(top, "Chưa đọc được sơ đồ trong ảnh. " + str(raw.get("ghi_chu") or "Hãy chụp rõ hơn, đủ sáng và thẳng góc."))
                else:
                    title = str(raw.get("chu_de") or "Sơ đồ tư duy").strip()[:60] or "Sơ đồ tư duy"
                    note = raw.get("ghi_chu")
                    st.session_state.mm = {"title": title, "branches": branches, "smiles": "", "rev": int(time.time() * 1000),
                                           "note": note if note and str(note).lower() != "null" else "", "photo": img}
                    add_history(title, "Sơ đồ")
                    st.session_state.n += 1
            except Exception as e:
                st.session_state.mm = None
                show_top_error(top, "Có lỗi khi đọc ảnh, hãy thử lại hoặc chụp rõ hơn.", e)


def _mm_topic_inputs(top):
    voice_text_input("mm_topic", "Chủ đề hoặc tên chất", "Ví dụ: Ancol, Etanol, Phản ứng thế, Este và lipit")
    cols = st.columns(len(MM_EXAMPLES))
    for c, t in zip(cols, MM_EXAMPLES):
        c.button(t, key=f"mm_ex_{t}", on_click=_set_topic, args=(t,), width="stretch")
    level = st.radio("Mức chi tiết", ["Gọn (4 nhánh, mỗi nhánh 2-3 ý)", "Đầy đủ (6 nhánh, mỗi nhánh 3-4 ý)"], horizontal=True, key="mm_level")
    topic = st.session_state.get("mm_topic", "").strip()
    if st.button("Tạo sơ đồ tư duy", type="primary", disabled=not topic, key="mm_go"):
        if over_quota():
            show_top_error(top, "Bạn đã dùng hết số lượt của phiên này. Hãy tải lại trang để tiếp tục.")
        else:
            with st.spinner("Đang vẽ sơ đồ…"):
                try:
                    want = "4 nhánh, mỗi nhánh 2-3 ý" if level.startswith("Gọn") else "6 nhánh, mỗi nhánh 3-4 ý"
                    raw = ask_ai([MM_PROMPT + f"\nSố nhánh và ý: {want}.\n\nChủ đề: {topic}"], temperature=0.2)
                    branches = mm_clean(raw)
                    if not branches:
                        show_top_error(top, "Chưa tạo được sơ đồ cho chủ đề này, hãy thử diễn đạt rõ hơn.")
                    else:
                        smi, facts = (raw.get("chat_smiles") or "").strip(), None
                        if smi and smi.lower() != "null":
                            facts = mm_engine_facts(smi)
                        if facts:
                            branches.append({"ten": "Số liệu (máy tính)", "y": facts, "color": "#475569"})
                        st.session_state.mm = {"title": str(raw.get("chu_de") or topic)[:60], "branches": branches,
                                               "smiles": smi if facts else "", "rev": int(time.time() * 1000)}
                        add_history(st.session_state.mm['title'], 'Sơ đồ')
                        st.session_state.n += 1
                except Exception as e:
                    st.session_state.mm = None
                    show_top_error(top, "Có lỗi khi tạo sơ đồ, hãy thử lại.", e)


def _mm_result():
    r = st.session_state.get("mm")
    if r:
        st.divider()
        rev = r.setdefault("rev", 0)
        if r.get("note"):
            st.info("Ghi chú khi đọc ảnh: " + str(r["note"]))
        if r.get("photo"):
            with st.expander("Ảnh gốc để đối chiếu"):
                st.image(r["photo"])
        title = st.text_input("Chủ đề ở giữa sơ đồ", value=r["title"], key=f"mm_title_{rev}").strip() or r["title"]
        with st.expander("✏️ Chỉnh sửa nội dung (sửa chữ, thêm hoặc xóa dòng, sơ đồ cập nhật ngay)", expanded=False):
            base = [{"Nhánh": b["ten"], "Ý": t} for b in r["branches"] for t in (b["y"] or [""])]
            edited = st.data_editor(base, num_rows="dynamic", hide_index=True, key=f"mm_edit_{rev}", width="stretch",
                                    column_config={"Nhánh": st.column_config.TextColumn("Nhánh", width="medium"),
                                                   "Ý": st.column_config.TextColumn("Ý", width="large")})
            st.caption("Muốn thêm nhánh mới: thêm dòng mới và gõ tên nhánh mới. Dòng để trống cột Nhánh sẽ thuộc nhánh ngay phía trên.")
        rows = edited.to_dict("records") if hasattr(edited, "to_dict") else list(edited)
        branches = rows_to_branches(rows)
        _cm = {b["ten"]: b.get("color") for b in r["branches"] if b.get("color")}
        for _b in branches:
            if not _b.get("color") and _b["ten"] in _cm:
                _b["color"] = _cm[_b["ten"]]
        if not branches:
            st.warning("Sơ đồ đang trống, hãy nhập ít nhất một nhánh.")
        else:
            L = mindmap_layout(title, branches)
            svg = svg_from_layout(L)
            png = None
            try:
                png = mm_png_bytes(L, svg)
            except Exception:
                png = None
            if png:   # nút tải chuẩn của Streamlit: chạy được cả trên điện thoại
                st.download_button("⬇️ Tải ảnh PNG", png, file_name="so_do_tu_duy.png", mime="image/png", key=f"mm_png_{rev}")
            mm_component(svg, L["W"], L["H"], button=not png)
            st.markdown("**Tải về để chỉnh sửa tiếp trên máy**")
            c1, c2, c3 = st.columns(3)
            pp = mm_pptx_bytes(L)
            if pp:
                c1.download_button("📊 PowerPoint (.pptx)", pp, file_name="so_do_tu_duy.pptx", key="mm_pptx",
                                   mime="application/vnd.openxmlformats-officedocument.presentationml.presentation", width="stretch")
            else:
                c1.caption("Thiếu thư viện python-pptx nên chưa xuất được PowerPoint.")
            c2.download_button("🧩 draw.io (.drawio)", mm_drawio(L).encode("utf-8"), file_name="so_do_tu_duy.drawio", key="mm_dio", width="stretch")
            c3.download_button("🗺️ XMind / FreeMind (.mm)", mm_freemind(L).encode("utf-8"), file_name="so_do_tu_duy.mm", key="mm_fm", width="stretch")
            d1, d2 = st.columns(2)
            d1.download_button("🖼️ SVG (vector, in sắc nét)", svg.encode("utf-8"), file_name="so_do_tu_duy.svg", mime="image/svg+xml", key="mm_svg", width="stretch")
            d2.download_button("📝 Dàn ý (Markdown)", mm_outline(title, branches).encode("utf-8"), file_name="so_do_tu_duy.md", key="mm_md", width="stretch")
            st.caption("PowerPoint: mỗi khung là hình có chữ sửa được và đường nối dính vào khung, kéo khung thì đường nối đi theo. "
                       "draw.io mở bằng app.diagrams.net. File .mm mở bằng XMind, Freeplane, MindManager.")
        if r.get("smiles"):
            with st.expander("Cấu trúc chất (kiểm tra xem đúng chất bạn muốn chưa)"):
                m = Chem.MolFromSmiles(r["smiles"])
                if m is not None:
                    st.image(Draw.MolToImage(m, size=(300, 200)))
                st.code(r["smiles"], language=None)


def mindmap_ui():
    top = st.container()
    st.session_state.setdefault("mm", None)
    mode = st.radio("Cách tạo sơ đồ", ["Từ chủ đề", "Từ ảnh sơ đồ tôi vẽ tay"], horizontal=True, key="mm_mode")
    if mode.startswith("Từ ảnh"):
        _mm_photo_inputs(top)
    else:
        _mm_topic_inputs(top)
    _mm_result()


# ---------------- Giao diện ----------------
# ====================================================================
#  GIAO DIỆN MolSnap (thay thế lớp giao diện cũ, giữ nguyên toàn bộ logic phía trên)
# ====================================================================
def _uri(svg):
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode()


# ---------- Bộ biểu tượng nét (24x24) ----------
ICON_PATHS = {
    "home": "<path d='M3 11l9-8 9 8'/><path d='M5 10v10h5v-6h4v6h5V10'/>",
    "structure": "<circle cx='6' cy='6' r='2'/><circle cx='18' cy='6' r='2'/><circle cx='12' cy='12' r='2'/><circle cx='6' cy='18' r='2'/><circle cx='18' cy='18' r='2'/><path d='M7.5 7.5l3 3M16.5 7.5l-3 3M7.5 16.5l3-3M16.5 16.5l-3-3'/>",
    "flask": "<path d='M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3'/><path d='M7.5 15h9'/>",
    "isomer": "<path d='M16 3h5v5M4 20L21 3M21 16v5h-5M15 15l6 6M4 4l5 5'/>",
    "equipment": "<path d='M7 3h10v3H7zM6 6h12v14a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1z'/><path d='M9 12h6M9 16h6'/>",
    "mind": "<circle cx='18' cy='5' r='3'/><circle cx='6' cy='12' r='3'/><circle cx='18' cy='19' r='3'/><path d='M8.6 13.5l6.8 4M15.4 6.5l-6.8 4'/>",
    "practice": "<rect x='5' y='4' width='14' height='17' rx='2'/><path d='M9 4h6v3H9zM9 14l2 2 4-4'/>",
    "test": "<rect x='5' y='4' width='14' height='17' rx='2'/><path d='M9 4h6v3H9zM9 12h6M9 16h4'/>",
    "stats": "<path d='M5 21V11M12 21V4M19 21v-7'/>",
    "chat": "<path d='M21 12a8 8 0 0 1-11.5 7.2L4 21l1.8-5.3A8 8 0 1 1 21 12z'/>",
    "pen": "<path d='M12 20h9'/><path d='M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z'/>",
    "search": "<circle cx='11' cy='11' r='7'/><path d='M21 21l-4.3-4.3'/>",
    "sun": "<circle cx='12' cy='12' r='4'/><path d='M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4'/>",
    "bell": "<path d='M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9'/><path d='M10.3 21a1.9 1.9 0 0 0 3.4 0'/>",
    "image": "<rect x='3' y='3' width='18' height='18' rx='3'/><circle cx='9' cy='9' r='2'/><path d='M21 15l-5-5L5 21'/>",
    "arrow": "<path d='M5 12h14M13 6l6 6-6 6'/>",
    "camera": "<path d='M4 8h3l2-3h6l2 3h3v11H4z'/><circle cx='12' cy='13' r='3.5'/>",
}


def icon_svg(name, color="currentColor", size=22, sw=1.8):
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{size}' height='{size}' viewBox='0 0 24 24' fill='none' stroke='{color}' "
            f"stroke-width='{sw}' stroke-linecap='round' stroke-linejoin='round'>{ICON_PATHS[name]}</svg>")


def _mask(name):
    return f'url("{_uri(icon_svg(name, "black"))}")'


# ---------- Hình minh họa ----------
LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs>
<linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#8b5cf6"/><stop offset=".55" stop-color="#4f6df5"/><stop offset="1" stop-color="#22d3ee"/></linearGradient></defs>
<path d="M32 5 L56 19 V45 L32 59 L8 45 V19 Z" fill="url(#lg)" stroke="url(#lg)" stroke-width="6" stroke-linejoin="round"/>
<path d="M42 23 C37 16 23 18 23 26 C23 34 41 31 41 40 C41 48 28 48 22 41" fill="none" stroke="#fff" stroke-width="5.5" stroke-linecap="round"/>
<circle cx="45" cy="21" r="3" fill="#fff" opacity=".9"/><circle cx="19" cy="43" r="3" fill="#fff" opacity=".9"/></svg>"""

HERO_ART = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 290"><defs>
<linearGradient id="liq" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#67e8f9"/><stop offset=".55" stop-color="#3b82f6"/><stop offset="1" stop-color="#4f46e5"/></linearGradient>
<linearGradient id="glass" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".55"/><stop offset="1" stop-color="#bfdbfe" stop-opacity=".25"/></linearGradient>
<linearGradient id="leaf" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#86efac"/><stop offset="1" stop-color="#16a34a"/></linearGradient>
<style>.f1{animation:f 5s ease-in-out infinite}.f2{animation:f 6.5s ease-in-out 1s infinite}.f3{animation:f 7.5s ease-in-out .4s infinite}
@keyframes f{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}</style></defs>
<path d="M395 250 Q360 190 400 150 Q430 190 395 250Z" fill="url(#leaf)" opacity=".95"/>
<path d="M410 252 Q420 190 470 170 Q470 220 410 252Z" fill="#22c55e" opacity=".9"/>
<path d="M340 214 Q388 192 442 206 L442 266 Q388 252 340 272Z" fill="#ece9ff"/>
<path d="M442 206 Q500 190 552 212 L552 270 Q500 252 442 266Z" fill="#fff"/>
<path d="M442 206 V266" stroke="#c7c9f5" stroke-width="2"/>
<g stroke="#c4c8ef" stroke-width="2.5" stroke-linecap="round"><path d="M462 232 H520"/><path d="M462 244 H532"/><path d="M356 232 H420"/><path d="M356 244 H410"/></g>
<text x="466" y="226" font-family="Dancing Script,cursive" font-size="20" fill="#7a86c9" font-style="italic">H₂O</text>
<polygon points="378,226 388,220 398,226 398,238 388,244 378,238" fill="none" stroke="#7a86c9" stroke-width="2"/>
<g class="f1"><path d="M290 34 H322 V98 H290Z" fill="url(#glass)" stroke="#fff" stroke-opacity=".8" stroke-width="2"/>
<ellipse cx="306" cy="32" rx="24" ry="8" fill="none" stroke="#a5f3fc" stroke-width="6"/>
<path d="M290 98 H322 L372 196 Q384 230 352 232 H260 Q228 230 240 196Z" fill="url(#glass)" stroke="#fff" stroke-opacity=".85" stroke-width="2"/>
<path d="M254 170 H358 L372 196 Q384 230 352 232 H260 Q228 230 240 196Z" fill="url(#liq)"/>
<path d="M254 170 Q306 160 358 170" fill="none" stroke="#e0f2fe" stroke-width="3" opacity=".8"/>
<circle cx="276" cy="198" r="7" fill="#e0f2fe" opacity=".75"/><circle cx="312" cy="190" r="5" fill="#e0f2fe" opacity=".75"/><circle cx="332" cy="210" r="6" fill="#e0f2fe" opacity=".75"/><circle cx="300" cy="218" r="4" fill="#e0f2fe" opacity=".7"/>
<path d="M262 120 Q250 170 252 196" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".55" transform="translate(30 0)"/></g>
<g class="f2"><g stroke="#cfd8ff" stroke-width="5" stroke-linecap="round"><line x1="70" y1="132" x2="128" y2="88"/><line x1="128" y1="88" x2="190" y2="134"/><line x1="190" y1="134" x2="152" y2="186"/><line x1="128" y1="88" x2="214" y2="66"/><line x1="70" y1="132" x2="98" y2="186"/></g>
<circle cx="70" cy="132" r="15" fill="#4f6df5"/><circle cx="128" cy="88" r="19" fill="#8b5cf6"/><circle cx="190" cy="134" r="15" fill="#22d3ee"/><circle cx="152" cy="186" r="17" fill="#3b82f6"/><circle cx="214" cy="66" r="11" fill="#f59e0b"/><circle cx="98" cy="186" r="9" fill="#f97316"/>
<g fill="#fff" opacity=".6"><circle cx="65" cy="126" r="5"/><circle cx="122" cy="80" r="6"/><circle cx="185" cy="129" r="5"/><circle cx="146" cy="179" r="5"/><circle cx="211" cy="63" r="3.5"/></g></g>
<g class="f3"><ellipse cx="232" cy="38" rx="30" ry="12" fill="none" stroke="#7dd3fc" stroke-width="7" opacity=".85" transform="rotate(-14 232 38)"/>
<ellipse cx="452" cy="96" rx="20" ry="8" fill="none" stroke="#c4b5fd" stroke-width="6" opacity=".8" transform="rotate(12 452 96)"/></g>
<g fill="#fff" opacity=".9"><path d="M40 52 l3 9 9 3 -9 3 -3 9 -3-9 -9-3 9-3z"/><path d="M500 40 l2 6 6 2 -6 2 -2 6 -2-6 -6-2 6-2z"/><path d="M360 262 l2 5 5 2 -5 2 -2 5 -2-5 -5-2 5-2z" opacity=".6"/></g></svg>"""

MASCOT_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 250"><defs>
<linearGradient id="lf" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4ade80"/><stop offset="1" stop-color="#15803d"/></linearGradient>
<linearGradient id="rb" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#dbe4ff"/></linearGradient>
<style>.bob{animation:b 4s ease-in-out infinite;transform-origin:150px 200px}@keyframes b{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}</style></defs>
<path d="M8 232 Q-6 180 40 160 Q52 205 8 232Z" fill="url(#lf)" opacity=".9"/><path d="M40 238 Q40 190 84 176 Q90 220 40 238Z" fill="#22c55e" opacity=".85"/>
<path d="M290 236 Q306 196 262 176 Q250 214 290 236Z" fill="url(#lf)" opacity=".9"/>
<rect x="50" y="206" width="200" height="26" rx="6" fill="#3b5bdb"/><rect x="50" y="206" width="200" height="8" rx="4" fill="#6c8cff"/>
<rect x="64" y="182" width="176" height="26" rx="6" fill="#7c3aed"/><rect x="64" y="182" width="176" height="8" rx="4" fill="#a78bfa"/>
<rect x="80" y="160" width="150" height="24" rx="6" fill="#0891b2"/><rect x="80" y="160" width="150" height="7" rx="3.5" fill="#67e8f9"/>
<g class="bob"><line x1="150" y1="30" x2="150" y2="48" stroke="#a5b4fc" stroke-width="4"/><circle cx="150" cy="26" r="7" fill="#22d3ee"/>
<rect x="104" y="46" width="92" height="70" rx="30" fill="url(#rb)" stroke="#c7d2fe" stroke-width="3"/>
<rect x="114" y="60" width="72" height="42" rx="20" fill="#16204f"/><ellipse cx="136" cy="80" rx="7" ry="9" fill="#38e1ff"/><ellipse cx="166" cy="80" rx="7" ry="9" fill="#38e1ff"/>
<path d="M143 92 Q151 98 159 92" fill="none" stroke="#38e1ff" stroke-width="3" stroke-linecap="round"/>
<rect x="98" y="66" width="10" height="28" rx="5" fill="#7c8cff"/><rect x="192" y="66" width="10" height="28" rx="5" fill="#7c8cff"/>
<rect x="116" y="116" width="68" height="46" rx="20" fill="url(#rb)" stroke="#c7d2fe" stroke-width="3"/>
<circle cx="150" cy="138" r="6" fill="#6d5bf0"/>
<path d="M118 126 Q96 140 104 158" fill="none" stroke="#dbe4ff" stroke-width="12" stroke-linecap="round"/>
<path d="M182 126 Q204 132 208 148" fill="none" stroke="#dbe4ff" stroke-width="12" stroke-linecap="round"/>
<g transform="translate(196 134)"><path d="M10 0 h10 v14 l12 22 q4 10 -6 10 h-22 q-10 0 -6 -10 l12 -22z" fill="#dff7ff" stroke="#fff" stroke-width="2"/><path d="M4 30 h32 l4 8 q3 8 -6 8 h-28 q-9 0 -6 -8z" fill="#4ade80"/></g></g></svg>"""

AI_FACE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect x="8" y="12" width="48" height="40" rx="18" fill="#fff"/><rect x="14" y="20" width="36" height="24" rx="12" fill="#16204f"/><ellipse cx="25" cy="32" rx="4" ry="5" fill="#38e1ff"/><ellipse cx="39" cy="32" rx="4" ry="5" fill="#38e1ff"/><circle cx="32" cy="8" r="4" fill="#22d3ee"/><rect x="31" y="9" width="2" height="5" fill="#a5b4fc"/></svg>"""

PAPER_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 150 130"><defs><filter id="s" x="-10%" y="-10%" width="130%" height="130%"><feDropShadow dx="0" dy="3" stdDeviation="3" flood-color="#1b2150" flood-opacity=".25"/></filter></defs>
<g transform="rotate(4 75 65)"><rect x="18" y="14" width="112" height="100" rx="3" fill="#dcd5c8" filter="url(#s)"/></g>
<g transform="rotate(-3 75 65)"><rect x="14" y="10" width="112" height="100" rx="3" fill="#f6f3ec" filter="url(#s)"/>
<g fill="none" stroke="#5b6075" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
<polygon points="52,58 64,51 76,58 76,72 64,79 52,72"/><polyline points="55,60 55,70" stroke-width="1.6"/><polyline points="66,77 74,72" stroke-width="1.6" transform="translate(0 0)"/><polyline points="58,54 64,51 70,54" stroke-width="1.6"/>
<line x1="76" y1="58" x2="88" y2="51"/><line x1="88" y1="51" x2="88" y2="38"/><line x1="91" y1="51" x2="91" y2="38"/><line x1="88" y1="51" x2="100" y2="58"/></g>
<text x="86" y="33" font-family="Dancing Script,cursive" font-size="13" fill="#5b6075">O</text><text x="100" y="66" font-family="Dancing Script,cursive" font-size="13" fill="#5b6075">OH</text></g></svg>"""


# ---------- Tài nguyên giao diện ----------
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&family=Dancing+Script:wght@600;700&display=swap');
:root{--pri:#4f5cf0;--vio:#7c4dff;--cy:#19c3ff;--ink:#1b2150;--mut:#6b7299;--line:#e3e7fb;--soft:#f3f5ff;--navy:#0a0e30;
--grad:linear-gradient(135deg,#3b6cf6 0%,#6d4df0 100%)}
html{font-size:__ROOT__!important}
html,body,.stApp,.stMarkdown,p,label,input,textarea,button,li,h1,h2,h3,h4{font-family:'Be Vietnam Pro',system-ui,sans-serif}
.stApp{background:radial-gradient(64.286rem 30rem at 78% -8%,#e3e8ff 0%,rgba(227,232,255,0) 70%),#f5f7ff}
[data-testid="stHeader"]{background:transparent}
[data-testid="stAppDeployButton"]{display:none}
[class*="st-key-vrow_"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.5rem!important;align-items:flex-end!important}
[class*="st-key-vrow_"] [data-testid="stColumn"]:first-child{flex:1 1 0!important;min-width:0!important;width:auto!important}
[class*="st-key-vrow_"] [data-testid="stColumn"]:last-child{flex:0 0 3.6rem!important;width:3.6rem!important;min-width:3.6rem!important}
.block-container{max-width:95.714rem;padding:.6rem 1.6rem .8rem}
.block-container [data-testid="stVerticalBlock"]{gap:.7rem}
[data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"]{gap:.35rem}

/* ---------- Sidebar ---------- */
[data-testid="stSidebar"]{background:linear-gradient(185deg,#080c2c 0%,#0e1450 52%,#0a0f3a 100%);border-right:0}
[data-testid="stSidebarContent"]{background:transparent}
[data-testid="stSidebarUserContent"]{padding:0 .9rem .5rem}
[data-testid="stSidebar"] *{color:#e6eaff}
[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] *{color:#c3cbff}
.sb-brand{display:flex;align-items:center;gap:0.857rem;margin:0 0 .6rem}
.sb-brand img{width:3rem;height:3rem;flex:0 0 auto;filter:drop-shadow(0 0.429rem 1rem rgba(110,90,255,.55))}
.sb-brand b{display:block;font-size:1.7rem;font-weight:800;letter-spacing:-.5px;line-height:1.05;color:#fff}
.sb-brand b i{font-style:normal;background:linear-gradient(90deg,#6cb8ff,#a78bfa);-webkit-background-clip:text;background-clip:text;color:transparent}
.sb-brand span{display:block;white-space:nowrap;font-style:italic;font-size:.72rem;color:#aab4ea;margin-top:0.214rem}
.st-key-sidenav [role="radiogroup"]{display:flex;flex-direction:column;gap:0.214rem;width:100%}
.st-key-sidenav [role="radiogroup"]>div{width:100%}
.st-key-sidenav [data-testid="stRadioOption"]>div{flex:1;min-width:0}
.st-key-sidenav [data-testid="stRadioOption"] p{white-space:nowrap}
.st-key-sidenav :is(label[data-baseweb="radio"],[data-testid="stRadioOption"]){display:flex;align-items:center;gap:0.857rem;margin:0;width:100%;padding:0.5rem 1rem;border-radius:0.857rem;cursor:pointer;border:1px solid transparent;transition:background .15s,transform .15s}
.st-key-sidenav :is(label[data-baseweb="radio"],[data-testid="stRadioOption"])>div:first-child{display:none}
.st-key-sidenav [data-testid="stRadioOption"]>div{display:flex;align-items:center;gap:0;width:auto;padding:0}
.st-key-sidenav [data-testid="stRadioOption"]>div>div:first-child{display:none}
.st-key-sidenav :is(label[data-baseweb="radio"],[data-testid="stRadioOption"])::before{content:"";flex:0 0 1.571rem;width:1.571rem;height:1.571rem;background-color:#dbe1ff;-webkit-mask:var(--ic) center/contain no-repeat;mask:var(--ic) center/contain no-repeat}
.st-key-sidenav :is(label[data-baseweb="radio"],[data-testid="stRadioOption"]) p{font-size:1rem;font-weight:500;color:#e6eaff}
.st-key-sidenav :is(label[data-baseweb="radio"],[data-testid="stRadioOption"]):hover{background:rgba(255,255,255,.08);transform:translateX(2px)}
.st-key-sidenav :is(label[data-baseweb="radio"]:has(input:checked),[data-testid="stRadioOption"][data-selected="true"]){background:linear-gradient(90deg,#3f63ee,#5b86ff);border-color:rgba(255,255,255,.28);box-shadow:0 0.571rem 1.571rem rgba(63,99,238,.45)}
.st-key-sidenav :is(label[data-baseweb="radio"]:has(input:checked),[data-testid="stRadioOption"][data-selected="true"])::before{background-color:#fff}
.st-key-sidenav :is(label[data-baseweb="radio"]:has(input:checked),[data-testid="stRadioOption"][data-selected="true"]) p{color:#fff;font-weight:700}
__NAVICONS__
.aicard{display:flex;align-items:center;gap:0.857rem;padding:0.643rem 0.857rem;border-radius:1.143rem;background:linear-gradient(135deg,rgba(63,99,238,.42),rgba(109,77,240,.32));border:1px solid rgba(130,160,255,.5);box-shadow:0 0.714rem 1.857rem rgba(10,14,60,.45);margin-top:0.429rem}
.aicard img{width:2.714rem;height:2.714rem;flex:0 0 auto}
.aicard b{display:block;color:#fff;font-size:1rem}.aicard span{display:block;font-size:.78rem;color:#c9d2ff;line-height:1.35;margin-top:2px}
.aicard .go{margin-left:auto;flex:0 0 auto;width:2.143rem;height:2.143rem;border-radius:50%;background:rgba(255,255,255,.16);display:grid;place-items:center;color:#fff;font-weight:700}
.mascot{position:relative;margin:0 auto;width:72%}.mascot img{width:100%;display:block}
.mascot .hw{position:absolute;right:0.429rem;top:1rem;font-family:'Dancing Script',cursive;font-size:1.35rem;line-height:1.1;transform:rotate(-8deg);color:#e8ecff;text-align:center}

/* ---------- Ô bấm phủ lên thẻ (thẻ HTML + nút ẩn) ---------- */
div[class*="st-key-qk_"],.st-key-aibtn{position:relative;gap:0}
div[class*="st-key-qk_"] [data-testid="stElementContainer"]:has([data-testid="stButton"]),.st-key-aibtn [data-testid="stElementContainer"]:has([data-testid="stButton"]){position:absolute;inset:0;z-index:3;width:100%!important}
div[class*="st-key-qk_"] [data-testid="stButton"],.st-key-aibtn [data-testid="stButton"],div[class*="st-key-qk_"] [data-testid="stButton"] button,.st-key-aibtn [data-testid="stButton"] button{width:100%;height:100%;min-height:0}
div[class*="st-key-qk_"] button,.st-key-aibtn button{opacity:0;cursor:pointer}
div[class*="st-key-qk_"]:hover .tile{transform:translateY(-3px);box-shadow:0 0.857rem 1.857rem rgba(79,92,240,.2)}
.st-key-aibtn:hover .aicard{border-color:#9db4ff;transform:translateY(-1px)}.aicard{transition:all .15s}

/* ---------- Thanh trên ---------- */
.st-key-gsearch [data-testid="InputInstructions"]{display:none}
.st-key-gsearch div[data-baseweb="input"]{background:#fff;border:1px solid var(--line);border-radius:71.357rem;box-shadow:0 0.429rem 1.429rem rgba(79,92,240,.08);height:2.5rem}
.st-key-gsearch input{padding-left:3rem;background:url("__SEARCHIC__") no-repeat 1.1rem center/1.429rem;color:var(--ink)}
.tb-right{display:flex;justify-content:flex-end;align-items:center;gap:1.143rem;color:#5b6293}
.tb-right .av{width:2.571rem;height:2.571rem;border-radius:50%;background:var(--grad);color:#fff;display:grid;place-items:center;font-weight:700;box-shadow:0 0.286rem 0.857rem rgba(79,92,240,.4)}

/* ---------- Hero ---------- */
.hero3{position:relative;display:flex;justify-content:space-between;align-items:center;gap:0.714rem;color:#fff;border-radius:1.714rem;padding:1.143rem 2rem;margin:0 0 0.714rem;overflow:hidden;
background:radial-gradient(30rem 18.571rem at 88% 18%,rgba(25,195,255,.38),rgba(25,195,255,0) 70%),radial-gradient(27.143rem 18.571rem at 40% 110%,rgba(139,92,246,.5),rgba(139,92,246,0) 70%),linear-gradient(115deg,#152a9a 0%,#2f35c8 48%,#5a3bea 100%);
box-shadow:0 1.286rem 3.143rem rgba(47,53,200,.32)}
.hero3 .pill{display:inline-block;font-size:.85rem;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.34);border-radius:71.357rem;padding:0.357rem 1.143rem;font-weight:600;font-size:.95rem;margin-bottom:0.571rem}
.hero3 h1{margin:0;padding:0;font-size:2.05rem;line-height:1.16;font-weight:800;color:#fff;letter-spacing:-.4px}
.hero3 h1 em{font-style:normal;font-size:2.6rem;background:linear-gradient(90deg,#22d3ee,#60a5fa 60%,#a5b4fc);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero3 .sub{margin:0.429rem 0 0.714rem;font-size:1rem;font-weight:600;display:flex;gap:1rem;align-items:center;flex-wrap:wrap}.hero3 .sub i{opacity:.7;font-style:normal}
.hero3 .chips{display:flex;flex-wrap:wrap;gap:0.714rem}
.hero3 .chips span{background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.3);border-radius:71.357rem;padding:0.429rem 0.929rem;font-size:.85rem;font-weight:600;backdrop-filter:blur(0.429rem)}
.hero3 .hr{position:relative;flex:0 0 31%}.hero3 .art{width:100%;display:block}
.hero3 .slogan{position:absolute;right:0.714rem;top:0;font-family:'Dancing Script',cursive;font-weight:700;font-size:1.45rem;line-height:1.15;transform:rotate(-7deg);text-align:right;opacity:.96}
.hero3 .slogan u{display:block;height:2px;margin-top:0.429rem;background:linear-gradient(90deg,rgba(255,255,255,0),#fff);border-radius:2px}

/* ---------- Banner trang con ---------- */
.pbanner{display:flex;align-items:center;gap:1rem;color:#fff;border-radius:1.429rem;padding:1rem 1.429rem;margin:0.429rem 0 1.143rem;
background:radial-gradient(21.429rem 11.429rem at 92% 0%,rgba(25,195,255,.35),rgba(25,195,255,0) 70%),linear-gradient(115deg,#152a9a 0%,#3a37cf 55%,#5a3bea 100%);box-shadow:0 0.857rem 2.143rem rgba(47,53,200,.25);animation:fu .45s ease}
.pbanner .pb-ic{width:3.857rem;height:3.857rem;border-radius:1.143rem;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.3);display:grid;place-items:center;flex:0 0 auto}
.pbanner b{display:block;font-size:1.35rem;font-weight:800;color:#fff}.pbanner span{display:block;color:#dbe3ff;font-size:.95rem;margin-top:2px}
@keyframes fu{from{opacity:0;transform:translateY(0.571rem)}to{opacity:1;transform:none}}
.st-key-panel{background:#fff;border:1px solid var(--line);border-radius:1.714rem;padding:1.571rem 1.857rem;box-shadow:0 0.714rem 2.143rem rgba(79,92,240,.08)}
.st-key-panel [role="radiogroup"]{gap:0.571rem;flex-wrap:wrap}
.st-key-panel :is(label[data-baseweb="radio"],[data-testid="stRadioOption"]){background:#fff;border:0.107rem solid var(--line);border-radius:1rem;padding:0.571rem 1.143rem;margin:0}
.st-key-panel :is(label[data-baseweb="radio"]:has(input:checked),[data-testid="stRadioOption"][data-selected="true"]){border-color:var(--pri);background:var(--soft)}

/* ---------- Thẻ tải ảnh (trang chủ) ---------- */
.st-key-upcard{background:linear-gradient(135deg,#e7f8f6 0%,#eef1ff 60%,#f1ecff 100%);border:1px solid #dfe5ff;border-radius:1.571rem;padding:0.857rem 1.286rem;box-shadow:0 0.857rem 2.286rem rgba(79,92,240,.1)}
.uphead{display:flex;align-items:center;gap:1.143rem;margin-bottom:0.571rem}
.uphead .hex{flex:0 0 3.714rem;height:3.714rem;display:grid;place-items:center;background:linear-gradient(135deg,#22c1a5,#3b82f6);clip-path:polygon(50% 0,93% 25%,93% 75%,50% 100%,7% 75%,7% 25%);filter:drop-shadow(0 0.571rem 1rem rgba(34,193,165,.4))}
.uphead h3{margin:0 0 0.286rem;padding:0;font-size:1.25rem;font-weight:800;color:var(--ink)}
.uphead p{margin:0;color:#59618f;font-size:.98rem;line-height:1.5}
.uphead .hw{margin-left:auto;font-family:'Dancing Script',cursive;font-size:1.25rem;color:#3a4690;transform:rotate(-5deg);text-align:right;line-height:1.1;flex:0 0 auto}
.demo{position:relative;display:flex;align-items:center;gap:0.714rem;justify-content:flex-end}
.demo .paper{width:clamp(5rem,8vw,8.571rem);flex:0 1 auto;min-width:0}
.demo .arrow{color:#6d4df0;flex:0 0 auto}
.demo .res{position:relative;flex:1;min-width:0;background:#fff;border-radius:1rem;padding:0.714rem 1rem;box-shadow:0 0.714rem 1.857rem rgba(79,92,240,.14);border:1px solid #e6e9ff;min-width:0}
.demo .res .badge{position:absolute;top:-13px;right:0.714rem;background:#12b886;color:#fff;font-size:.72rem;font-weight:700;border-radius:71.357rem;padding:0.286rem 0.857rem;box-shadow:0 0.429rem 1rem rgba(18,184,134,.35)}
.demo .res h4{margin:0;padding:0;font-size:1.05rem;color:var(--ink)}.demo .res h4 i{float:right;font-style:normal;color:#12b886}
.demo .res b{display:block;color:var(--ink);font-size:.9rem;margin:2px 0 0.571rem}
.demo .res div{font-size:.78rem;color:#4b5380;margin-top:0.286rem;line-height:1.35}
.demo .res small{display:block;margin-top:0.571rem;font-size:.68rem;color:#98a0c7}
[data-testid="stFileUploaderDropzone"]{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0.571rem;border:2px dashed #8f9dff;background:rgba(255,255,255,.72);border-radius:1.286rem;padding:0.714rem 0.714rem;min-height:11rem}
[data-testid="stFileUploaderDropzone"]::before{content:"";order:0;width:3.286rem;height:3.286rem;border-radius:1rem;background:#e7ebff url("__IMGIC__") center/1.714rem no-repeat}
[data-testid="stFileUploaderDropzone"]>span{order:1}
[data-testid="stFileUploaderDropzone"]>span>button *{font-size:0!important}
[data-testid="stFileUploaderDropzone"]>span>button{font-size:0;background:var(--grad);color:#fff;border:0;border-radius:71.357rem;padding:0.571rem 2.143rem;box-shadow:0 0.714rem 1.571rem rgba(79,92,240,.35)}
[data-testid="stFileUploaderDropzone"]>span>button *{color:#fff}
[data-testid="stFileUploaderDropzone"]>span>button p{display:none}
[data-testid="stFileUploaderDropzone"]>span>button::after{content:"Tải ảnh lên";font-size:1rem;font-weight:700;color:#fff}
[data-testid="stFileUploaderDropzone"]>span>button [data-testid="stIconMaterial"]{display:none}
[data-testid="stFileUploaderDropzoneInstructions"]{order:2;text-align:center}
[data-testid="stFileUploaderDropzoneInstructions"] *{font-size:0}
[data-testid="stFileUploaderDropzoneInstructions"] svg,[data-testid="stFileUploaderDropzoneInstructions"] [data-testid="stIconMaterial"]{display:none}
[data-testid="stFileUploaderDropzoneInstructions"]::before{content:"Kéo thả ảnh hoặc chọn file  |  JPG, PNG, WEBP (tối đa 200MB)";font-size:.78rem;color:#6b7299;line-height:1.4}

/* ---------- Khám phá nhanh ---------- */
.sec-title{display:flex;align-items:center;gap:0.714rem;font-weight:700;font-size:1.02rem;color:var(--ink);margin:0.429rem 0.286rem 0}
.sec-title svg{color:var(--pri)}
.tile{display:flex;align-items:center;justify-content:space-between;gap:0.429rem;border-radius:1.286rem;padding:1rem 0.857rem;height:7.4rem;box-sizing:border-box;border:1px solid rgba(255,255,255,.7);transition:all .18s ease}
.tile .tt{display:flex;flex-direction:column;gap:0.429rem}
.tile .ib{width:2rem;height:2rem;border-radius:50%;background:rgba(255,255,255,.85);display:grid;place-items:center}
.tile b{font-size:.88rem;font-weight:700;line-height:1.25;white-space:pre-line}
.tile .ar{align-self:flex-end;opacity:.85}
.t-pink{background:linear-gradient(135deg,#ffe4f5,#fbd3ee);color:#d6389b}
.t-blue{background:linear-gradient(135deg,#e3eeff,#d4e4ff);color:#2563eb}
.t-green{background:linear-gradient(135deg,#dcf7ea,#c8f1dd);color:#059669}
.t-orange{background:linear-gradient(135deg,#fff1dc,#ffe4bd);color:#d97706}
.t-violet{background:linear-gradient(135deg,#ece8ff,#ddd6ff);color:#6d4df0}

/* ---------- Hành trình + dải tính năng ---------- */
.st-key-journey{background:#fff;border:1px solid var(--line);border-radius:1.286rem;padding:0.571rem 1.286rem;box-shadow:0 0.571rem 1.714rem rgba(79,92,240,.07);margin-top:0}
.jr{display:flex;align-items:center;gap:1.143rem}.jr .tr{font-size:1.9rem;line-height:1}
.jr .tx{flex:1}.jr b{display:block;color:var(--ink);font-size:1.02rem}.jr small{color:var(--mut)}
.jr .bar{flex:1.2;height:0.643rem;border-radius:7.071rem;background:#e8ebff;overflow:hidden;min-width:8.571rem}.jr .bar i{display:block;height:100%;border-radius:7.071rem;background:var(--grad)}
.jr .cnt{font-weight:700;font-size:.88rem;color:var(--ink);white-space:nowrap}
.feat{display:flex;justify-content:space-around;align-items:center;margin:2px 0.286rem 0;color:#4b5380;font-weight:600;font-size:.9rem;flex-wrap:wrap;gap:0.571rem}
.feat span{display:flex;align-items:center;gap:0.571rem}.feat i{width:1px;height:1.286rem;background:#d9defa;display:inline-block}

/* ---------- Cột phải ---------- */
.st-key-quick{background:linear-gradient(135deg,#3b6cf6 0%,#7a52f4 100%);border-radius:1.429rem;padding:0.857rem 1rem 0.714rem;box-shadow:0 1rem 2.143rem rgba(79,92,240,.35)}
.qhead{display:flex;align-items:center;gap:0.857rem;color:#fff;margin-bottom:0.714rem}
.qhead .qi{width:2.714rem;height:2.714rem;border-radius:1rem;background:rgba(255,255,255,.2);display:grid;place-items:center;flex:0 0 auto}
.qhead b{display:block;font-size:1.1rem;color:#fff}.qhead span{font-size:.8rem;color:#e1e6ff}
.st-key-quick [data-testid="stForm"]{border:0;padding:0;background:transparent}
.st-key-quick [data-testid="InputInstructions"]{display:none}
.st-key-quick div[data-baseweb="input"]{background:#fff;border:0;border-radius:71.357rem;height:2.9rem}
.st-key-quick input{color:var(--ink);padding-left:1.1rem}
.st-key-quick [data-testid="stFormSubmitButton"] button{width:2.7rem;height:2.7rem;min-height:0;padding:0;border-radius:50%;background:var(--grad);border:2px solid #fff;color:#fff;font-size:1.15rem;line-height:1}
.st-key-quick [data-testid="stFormSubmitButton"] button p{color:#fff;font-size:1.2rem}
.rcard{background:#fff;border:1px solid var(--line);border-radius:1.286rem;padding:0.714rem 1rem;box-shadow:0 0.571rem 1.714rem rgba(79,92,240,.07);margin-top:0}
.rcard .rh{display:flex;align-items:center;gap:0.714rem;margin-bottom:0.286rem}.rcard .rh svg{color:var(--pri)}
.rcard .rh b{color:var(--ink);font-size:1rem}.rcard .rs{color:var(--mut);font-size:.78rem;margin:0 0 0.429rem 2.429rem}
.st-key-res{background:#fff;border:1px solid var(--line);border-radius:1.286rem;padding:0.714rem 0.857rem 0.286rem;box-shadow:0 0.571rem 1.714rem rgba(79,92,240,.07);margin-top:0}
.st-key-res{gap:0!important}
.st-key-res [data-testid="stElementContainer"],.st-key-res [data-testid="stButton"]{width:100%}
.st-key-res button>div{width:100%;justify-content:flex-start}
.st-key-res button::after{content:"›";margin-left:auto;font-size:1.2rem;color:#9aa3d6}
.st-key-res button{width:100%;justify-content:flex-start;gap:0.714rem;background:transparent;border:0;border-top:1px solid #eef0fb;border-radius:0;padding:.15rem .4rem;min-height:2.1rem;color:var(--ink);box-shadow:none}
.st-key-res button:hover{background:var(--soft);transform:none;box-shadow:none}
.st-key-res button p{font-weight:500;font-size:.9rem;color:var(--ink)}
.st-key-res button [data-testid="stIconMaterial"]{color:var(--pri)}
.hrow{display:flex;align-items:center;gap:0.857rem;padding:0.357rem 2px;border-top:1px solid #eef0fb}
.hrow:first-of-type{border-top:0}
.hrow .hc{width:2.286rem;height:2.286rem;border-radius:50%;display:grid;place-items:center;flex:0 0 auto}
.hrow b{display:block;color:var(--ink);font-size:.88rem}.hrow small{color:var(--mut);font-size:.72rem}
.hrow .hc.c0{background:#d9f7ee;color:#0f9f78}.hrow .hc.c1{background:#ffe0ef;color:#d6389b}.hrow .hc.c2{background:#ffeccd;color:#c2740a}.hrow .hc.c3{background:#e6e0ff;color:#6d4df0}
.rsh{display:flex;align-items:center;gap:0.857rem;color:var(--pri);padding:2px 0.286rem 0.857rem}
.rsh b{display:block;color:var(--ink);font-size:1rem;line-height:1.3}.rsh span{display:block;color:var(--mut);font-size:.78rem;line-height:1.3;margin-top:2px}
.hempty{color:var(--mut);font-size:.85rem;padding:0.571rem 2px}
.st-key-hclear button{border:0;background:transparent;color:var(--pri);font-size:.78rem;padding:0;min-height:0;box-shadow:none}
.quote{display:flex;align-items:center;gap:1rem;border-radius:1.286rem;padding:0.714rem 1rem;margin-top:0;background:linear-gradient(135deg,#f1ecff,#e6f6ff);border:1px solid #e3e6ff}
.quote .lf{font-size:2.2rem;line-height:1}.quote p{margin:0;font-style:italic;color:#3a4690;font-size:.85rem;line-height:1.5}.quote em{display:block;text-align:right;color:var(--pri);font-size:.8rem;font-weight:600;margin-top:0.286rem}

/* ---------- Hộp thoại tài liệu ---------- */
.ptwrap{overflow-x:auto;padding-bottom:0.429rem}
.ptgrid{display:grid;grid-template-columns:repeat(18,minmax(3.857rem,1fr));grid-template-rows:repeat(7,auto) 0.857rem auto auto;gap:0.214rem;min-width:71.429rem}
.ptc{border-radius:0.5rem;padding:0.214rem 0.286rem;text-align:center;line-height:1.15;display:flex;flex-direction:column;align-items:center;min-height:4.429rem;border:1px solid rgba(27,33,80,.08)}
.ptc i{font-style:normal;font-size:.62rem;align-self:flex-start;color:#4b5380}.ptc b{font-size:1.02rem;color:var(--ink)}
.ptc span{font-size:.54rem;color:#3a4172;white-space:nowrap}.ptc em{font-style:normal;font-size:.56rem;color:#4b5380;margin-top:auto}
.ptx{background:#eef0fb;justify-content:center}.ptx b{font-size:.7rem;color:#6b7299}
.ptleg{display:flex;flex-wrap:wrap;gap:0.429rem 1.143rem;margin:0.714rem 0 0.286rem;font-size:.78rem;color:#4b5380}.ptleg span{display:flex;align-items:center;gap:0.429rem}.ptleg i{width:1rem;height:1rem;border-radius:0.286rem;display:inline-block;border:1px solid rgba(27,33,80,.12)}
.kl-kiem{background:#ffd6d6}.kl-kt{background:#ffe3c2}.chuyen{background:#fff0a8}.sau-chuyen{background:#d8f0c8}.a-kim-loai{background:#c7eee3}.phi-kim{background:#c9e6ff}.halogen{background:#d9d4ff}.khi-hiem{background:#f1d2f5}.lantan{background:#ffd0e6}.actini{background:#f4c7d9}
.reftbl{overflow-x:auto}.reftbl table{width:100%;border-collapse:collapse;font-size:.88rem}
.reftbl th{background:#eef1ff;color:var(--ink);text-align:left;padding:0.571rem 0.714rem;position:sticky;top:0}
.reftbl td{padding:0.571rem 0.714rem;border-top:1px solid #eef0fb;color:#2c3466;vertical-align:top}
.rxr{display:flex;gap:0.857rem;align-items:center;padding:0.643rem 2px;border-top:1px solid #eef0fb}.rxr:first-child{border-top:0}
.rxt{flex:0 0 10.714rem;background:#eef1ff;color:#4f5cf0;border-radius:71.357rem;padding:0.214rem 0.714rem;font-size:.74rem;font-weight:700;text-align:center}
.rxe{display:flex;align-items:center;flex-wrap:wrap;gap:0.429rem;color:var(--ink);font-weight:600;font-size:.95rem}
.rxa{display:inline-flex;flex-direction:column;align-items:center;min-width:3.286rem;line-height:1}.rxa small{font-size:.62rem;color:#6b7299;font-weight:500;white-space:nowrap}.rxa i{font-style:normal;font-size:1.2rem;color:#4f5cf0}

/* ---------- Bảng tính tan ---------- */
.soltbl{overflow-x:auto}.soltbl table{border-collapse:separate;border-spacing:2px;font-size:.78rem;width:100%}
.soltbl th{background:#eef1ff;color:var(--ink);padding:.3rem .4rem;font-weight:700;white-space:nowrap}
.soltbl td{text-align:center;font-weight:700;padding:.32rem .2rem;border-radius:.3rem}
.sol-t{background:#d7f5e5;color:#087a4a}.sol-i{background:#fff0c2;color:#a96800}.sol-k{background:#ffd9d9;color:#c2272d}.sol-b{background:#d9e8ff;color:#1d5fd1}.sol-x{background:#eceef6;color:#6b7299}.sol-q{background:#f5f6fb;color:#9aa3c4}
.sol-sel{outline:3px solid #4f5cf0;outline-offset:-1px;box-shadow:0 0 0 4px rgba(79,92,240,.25)}
.solres{display:flex;align-items:center;flex-wrap:wrap;gap:.8rem;margin:.4rem 0 .7rem}.solres b{font-size:1.5rem;color:var(--ink)}
.solbadge{padding:.3rem .85rem;border-radius:999px;font-weight:700;font-size:.85rem}
.sollg{display:flex;flex-wrap:wrap;gap:.4rem .9rem;margin-top:.6rem;font-size:.78rem;color:#4b5380;align-items:center}.sollg span{padding:.1rem .5rem;border-radius:.3rem;font-weight:700}

/* ---------- Thành phần chung ---------- */
[data-testid="stWidgetLabel"] p{font-weight:700;color:var(--ink);border-left:0.286rem solid var(--pri);padding-left:0.643rem}
.st-key-gsearch [data-testid="stWidgetLabel"],.st-key-quick [data-testid="stWidgetLabel"]{display:none}
button[kind="primary"],[data-testid="stBaseButton-primary"],[data-testid="stBaseButton-primary"]{background:var(--grad);border:0;color:#fff;border-radius:0.857rem;font-weight:700;padding:.55rem 1.3rem}
[data-testid="stBaseButton-secondary"]{border-radius:0.857rem;border-color:var(--line)}
button{transition:transform .15s ease,box-shadow .15s ease}
button:hover{transform:translateY(-1px);box-shadow:0 0.429rem 1.143rem rgba(79,92,240,.22)}
.st-key-jbtn button{border-radius:71.357rem;background:var(--grad);color:#fff;border:0;padding:.6rem 1.4rem;font-weight:700;white-space:nowrap}
.st-key-jbtn button p{color:#fff}
div[data-baseweb="input"],div[data-baseweb="textarea"]{border-radius:0.857rem}
.errtop{color:#d00000;font-weight:800;font-size:1.08rem;line-height:1.5;background:rgba(220,0,0,.08);border:2px solid rgba(220,0,0,.45);border-radius:0.857rem;padding:0.857rem 1.143rem;margin:0.429rem 0 0.857rem}
button:disabled,[data-testid="stBaseButton-primary"]:disabled{background:#dfe3f7!important;color:#8a90b8!important;box-shadow:none!important;transform:none!important}
button:disabled p{color:#8a90b8!important}
.usage{display:flex;align-items:center;gap:0.714rem;background:#fff;border:1px solid var(--line);border-radius:1rem;padding:0.429rem 1rem;color:var(--mut);margin-top:0.429rem;font-size:.85rem}
.usage b{color:var(--pri)}
.disc{color:var(--mut);font-size:.75rem;margin:0.286rem 0.286rem 0}
@media(max-width:900px){.hero3{padding:1.429rem 1.429rem}.hero3 .hr{display:none}.hero3 h1{font-size:1.8rem}.hero3 h1 em{font-size:2.3rem}.st-key-panel{padding:1rem}.uphead .hw{display:none}.demo{flex-wrap:wrap}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media(max-width:640px){
html{font-size:14.5px!important}
.block-container{padding:2.8rem .7rem 1rem!important}
.hero3{padding:1rem 1.1rem;border-radius:1.2rem}
.hero3 h1{font-size:1.5rem}.hero3 h1 em{font-size:1.9rem}.hero3 .sub{font-size:.9rem}
.hero3 .chips span{font-size:.78rem;padding:.35rem .7rem}
.st-key-topbar [data-testid="stHorizontalBlock"]{flex-direction:row!important;flex-wrap:nowrap!important;gap:.5rem!important}
.st-key-topbar [data-testid="stColumn"]{min-width:0!important;width:auto!important}
.st-key-topbar [data-testid="stColumn"]:first-child{flex:1 1 auto!important}
.st-key-topbar [data-testid="stColumn"]:last-child{flex:0 0 auto!important}
.st-key-topbar [data-testid="stColumn"]:last-child{display:none!important}
.st-key-topbar [data-testid="stColumn"]:first-child{flex:1 1 100%!important;width:100%!important}
.hero3 .sub{display:none}
[data-testid="stExpandSidebarButton"]{background:var(--grad)!important;border-radius:999px!important;width:auto!important;height:2.4rem!important;padding:0 .9rem!important;box-shadow:0 6px 16px rgba(79,92,240,.4)!important;display:inline-flex!important;align-items:center;gap:.35rem}
[data-testid="stExpandSidebarButton"] *{color:#fff!important;fill:#fff!important}
[data-testid="stExpandSidebarButton"]::after{content:"Menu";color:#fff;font-weight:700;font-size:.9rem}
.hero3 h1{margin-bottom:.7rem}
.st-key-tilesrow [data-testid="stHorizontalBlock"]{flex-direction:row!important;flex-wrap:wrap!important;gap:.6rem!important}
.st-key-tilesrow [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{flex:1 1 calc(50% - .6rem)!important;min-width:calc(50% - .6rem)!important}
.uphead .hw{display:none}.uphead{gap:.8rem}.uphead h3{font-size:1.05rem}.uphead p{font-size:.82rem}
.demo{flex-direction:column;align-items:stretch}.demo .paper,.demo .arrow{display:none}
.jr{flex-wrap:wrap}.jr .bar{flex:1 1 100%;order:3}
.feat{display:grid;grid-template-columns:1fr 1fr;gap:.4rem}.feat i{display:none}
.tile{height:5.2rem}
.st-key-panel{padding:.8rem .9rem}
.st-key-quick [data-testid="stHorizontalBlock"]{flex-direction:row!important;flex-wrap:nowrap!important;gap:.5rem!important}
.st-key-quick [data-testid="stColumn"]{min-width:0!important}
.st-key-quick [data-testid="stColumn"]:first-child{flex:1 1 auto!important}
.st-key-quick [data-testid="stColumn"]:last-child{flex:0 0 auto!important;width:auto!important}
.st-key-jbtn button{width:100%}
}
</style>
"""

# Biểu tượng cho từng mục điều hướng (thứ tự = thứ tự trong thanh bên)
NAV_ICON_ORDER = ["home", "structure", "flask", "isomer", "equipment", "mind", "practice", "test", "search"]
_nav_css = "".join(
    f'.st-key-sidenav label[data-baseweb="radio"]:nth-of-type({i + 1}){{--ic:{_mask(n)}}}.st-key-sidenav [role="radiogroup"]>div:nth-of-type({i + 1}) [data-testid="stRadioOption"]{{--ic:{_mask(n)}}}' for i, n in enumerate(NAV_ICON_ORDER)
)
_ROOT = "clamp(9px, 1.6vh, 16px)" if st.session_state.get("nav", "Trang chủ") == "Trang chủ" else "14px"
CSS = (CSS.replace("__ROOT__", _ROOT).replace("__NAVICONS__", _nav_css)
          .replace("__SEARCHIC__", _uri(icon_svg("search", "#7a82b8", 20)))
          .replace("__IMGIC__", _uri(icon_svg("image", "#4f5cf0", 30))))
st.markdown(CSS, unsafe_allow_html=True)
_UP_BTN = {"en": "Upload image", "bi": "Tải ảnh lên · Upload image"}
_UP_HINT = {"en": "Drag and drop an image or choose a file  |  JPG, PNG, WEBP (max 200MB)",
            "bi": "Kéo thả ảnh hoặc chọn file · Drag and drop or choose a file  |  JPG, PNG, WEBP (200MB)"}
st.markdown("<style>"
            ".st-key-sbacct{margin:.2rem 0 .9rem}"
            ".acct{background:linear-gradient(135deg,rgba(99,102,241,.28),rgba(139,92,246,.22));border:1px solid rgba(167,139,250,.35);border-radius:16px;padding:.8rem .85rem}"
            ".acct-top{display:flex;align-items:center;gap:.7rem}"
            ".acct .avt{flex:0 0 auto;width:2.9rem;height:2.9rem;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:1.05rem;color:#fff;background:linear-gradient(135deg,#4f46e5,#8b5cf6);box-shadow:0 .3rem .9rem rgba(110,90,255,.45)}"
            ".acct .avt.guest{background:rgba(255,255,255,.14);box-shadow:none}"
            ".acct .who{min-width:0}.acct .who b{display:block;color:#fff;font-size:1rem;line-height:1.2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
            ".acct .who span{display:block;color:#c7cdf5;font-size:.78rem;margin-top:.1rem}"
            ".acct .role{display:inline-block;margin-left:.35rem;padding:0 .4rem;border-radius:99px;background:rgba(255,255,255,.16);font-size:.68rem;color:#fff}"
            ".acct-st{display:flex;align-items:center;gap:.4rem;margin-top:.6rem;font-size:.74rem;color:#d6dafc}"
            ".acct-st i{width:.55rem;height:.55rem;border-radius:50%;background:#9ca3af;flex:0 0 auto}.acct-st i.ok{background:#34d399}.acct-st i.warn{background:#fbbf24}.acct-st i.err{background:#f87171}"
            ".acct-kpi{display:grid;grid-template-columns:1fr 1fr;gap:.5rem;margin-top:.65rem}"
            ".acct-kpi div{background:rgba(255,255,255,.09);border-radius:12px;padding:.45rem .3rem;text-align:center}"
            ".acct-kpi b{display:block;color:#fff;font-size:1.25rem;line-height:1.1}.acct-kpi span{display:block;color:#c7cdf5;font-size:.68rem;margin-top:.15rem}"
            ".acct-none{margin-top:.6rem;font-size:.76rem;color:#c7cdf5;text-align:center}"
            ".st-key-sbacct button{width:100%}"
            ".tb-right .av.guest{background:#e4e7ff;color:#4f46e5}"
            "@media(max-width:640px){.acct-kpi b{font-size:1.1rem}}"
            "</style>", unsafe_allow_html=True)
st.markdown("<style>@media(max-width:640px){.block-container{padding-left:.7rem!important;padding-right:.7rem!important}"
            "[data-testid='stDataFrame']{max-width:100%;overflow-x:auto}.stTabs [data-baseweb='tab-list']{overflow-x:auto}"
            "[data-testid='stFileUploaderDropzone']{padding:1rem!important}}</style>", unsafe_allow_html=True)
if i18n.lang() != "vi":   # nút/dòng chú thích của khung tải ảnh được viết bằng CSS nên phải đổi ở đây
    st.markdown('<style>[data-testid="stFileUploaderDropzone"]>span>button::after{content:"%s"}'
                '[data-testid="stFileUploaderDropzoneInstructions"]::before{content:"%s"}</style>'
                % (_UP_BTN[i18n.lang()], _UP_HINT[i18n.lang()]), unsafe_allow_html=True)
st.markdown("<style>[data-testid='stSidebar'] [data-testid='stWidgetLabel'] p{color:#dfe5ff!important;font-weight:600}"
            "[data-testid='stSidebar'] [data-baseweb='select'] *{color:#fff!important}</style>", unsafe_allow_html=True)
if i18n.lang() != "vi":   # chữ song ngữ dài hơn: ô công cụ cao tự động, dòng tiếng Anh nhỏ bên dưới
    st.markdown("<style>.tile{height:auto!important;min-height:7.4rem}.tile b small{display:block;font-weight:500;opacity:.8;font-size:.74rem;margin-top:2px}"
                ".pbanner span{font-size:.88rem}</style>", unsafe_allow_html=True)

pw = st.secrets.get("APP_PASSWORD", "")
if pw and st.text_input("Mật khẩu lớp học", type="password") != pw:
    st.stop()

# Khi cập nhật mã, dữ liệu kết quả cũ trong phiên đang mở có thể thiếu trường mới. Xóa các kết quả cũ để tránh lỗi KeyError.
SCHEMA = 5
if st.session_state.get("_schema") != SCHEMA:
    for _k in ("mm", "iso", "iso_nm", "iso_und", "bm", "eq", "rx", "res", "pq"):
        st.session_state.pop(_k, None)
    st.session_state["_schema"] = SCHEMA
st.session_state.setdefault("n", 0)
st.session_state.setdefault("res", None)
st.session_state.setdefault("hist", [])
st.session_state.setdefault("chat", [])


def errbanner(*lines):
    body = "<br>".join(html.escape(tx(str(x), sep="\n")).replace("\n", "<br>") for x in lines if x)
    return f'<div class="errtop">❌ {body}</div>'


def show_top_error(top, msg, exc=None):
    """Hiện lỗi ở ĐẦU tab, chữ đỏ in đậm."""
    with top:
        st.markdown(errbanner(msg), unsafe_allow_html=True)
        if exc is not None:
            st.caption(f"Chi tiết kỹ thuật: {type(exc).__name__}: {str(exc)[:400]}")


# ---------------- Lịch sử tra cứu của học sinh ----------------
# Mỗi lượt: {"q": nội dung, "k": loại, "d": ngày, "t": giờ, "p": dữ liệu để tra lại (tùy chọn)}.
# Học sinh đã đăng nhập thì lượt tra cứu được lưu vào tệp riêng của học sinh đó (history_store.py),
# lần sau nhập lại tên là thấy lại. Không có tên thì chỉ giữ trong phiên đang mở.
HIST_MAX = 300
try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:
    _TZ = None


def _now():
    return datetime.now(_TZ) if _TZ else datetime.now()


def cur_auth():
    """Danh tính hiện tại của phiên: None (khách), học sinh hoặc giáo viên."""
    return st.session_state.get("auth")


def student_name():
    """Khóa lưu dữ liệu của học sinh đã đăng nhập ('Tên [LỚP]'); khách và giáo viên thì rỗng (chỉ lưu trong phiên)."""
    a = cur_auth()
    return a["key"] if cr.is_student(a) else ""


def add_history(label, kind="Công thức", payload=None):
    """Ghi một lượt tra cứu (bỏ trùng liên tiếp); học sinh đã đăng nhập thì lưu luôn vào kho dữ liệu."""
    h = st.session_state.hist
    label = (label or "").strip()
    if not label or (h and h[0].get("q") == label and h[0].get("k") == kind):
        return
    now = _now()
    e = {"q": label[:200], "k": kind, "d": now.strftime("%Y-%m-%d"), "t": now.strftime("%H:%M")}
    if payload:
        e["p"] = payload
    h.insert(0, e)
    del h[HIST_MAX:]
    who = student_name()
    if who:
        try:
            cr.append_history(cur_auth(), who, dict(e))
        except OSError:
            pass   # ổ đĩa chỉ đọc: vẫn giữ trong phiên


def _hkey(x):
    return (x.get("d"), x.get("t"), x.get("k"), x.get("q"))


def sync_student():
    """Gọi mỗi lần chạy và khi đăng nhập/đăng xuất: nạp lịch sử đã lưu của tài khoản (hoặc gắn các lượt đã tra cứu khi còn là khách)."""
    who = student_name()
    prev = st.session_state.get("_hist_owner")
    if prev == who:
        return
    cur = st.session_state.hist
    try:
        saved = cr.read_history(cur_auth(), who) if who else []
    except OSError:
        saved = []   # Sheets/ổ đĩa tạm lỗi: vẫn dùng app, lượt mới ghi lại khi nối được
    if who and not prev and cur:   # đã tra cứu khi còn là khách: gắn vào tài khoản vừa đăng nhập
        seen = {_hkey(x) for x in saved}
        saved = sorted([x for x in cur if _hkey(x) not in seen] + saved, key=lambda x: (x.get("d", ""), x.get("t", "")), reverse=True)[:HIST_MAX]
        try:
            cr.write_history(cur_auth(), who, saved)
        except OSError:
            pass
    st.session_state.hist = saved
    st.session_state["_hist_owner"] = who
    if who:
        try:
            cr.touch_visit(cur_auth(), who, _now().strftime("%Y-%m-%d %H:%M"))   # ghi nhận lần truy cập để giáo viên xem
        except OSError:
            pass


def _set_token(on, au=None):
    """Nhớ (hoặc quên) đăng nhập của học sinh trong địa chỉ trang để tải lại vẫn còn."""
    try:
        if on and cr.is_student(au):
            st.query_params["tk"] = cr.make_token(_SECRET, au["cls"], au["name"])
        else:
            st.query_params.pop("tk", None)
    except Exception:
        pass


def finish_login(au, msg):
    ss = st.session_state
    ss["auth"] = au
    ss["lg_fail"] = 0
    ss["_toast"] = msg
    ss.pop("_prof", None)
    _set_token(True, au)
    sync_student()


def is_logged_in():
    """Đã đăng nhập (học sinh hoặc giáo viên) mới được dùng các tab ngoài Trang chủ."""
    a = cur_auth()
    return bool(a) and (cr.is_student(a) or cr.is_teacher(a))


def do_logout():
    ss = st.session_state
    ss["auth"] = None
    ss["nav"] = "Trang chủ"
    ss["nav_side"] = "Trang chủ"
    ss.pop("_prof", None)
    ss["_toast"] = tx("Đã đăng xuất.", "Logged out.")
    _set_token(False)
    ss["pq"] = None
    sync_student()


_AUTH_ERR = {
    "bad_code": ("Mã lớp gồm 2-20 ký tự chữ, số, gạch nối.", "The class code is 2-20 letters, digits or dashes."),
    "bad_name": ("Họ tên cần 2-40 ký tự, bắt đầu bằng chữ cái và không có ký tự đặc biệt.", "Your name needs 2-40 characters, starting with a letter, with no special symbols."),
    "bad_pin": ("PIN phải từ 4 đến 12 ký tự.", "The PIN must be 4-12 characters."),
    "mismatch": ("Hai lần nhập PIN chưa giống nhau.", "The two PINs do not match."),
    "no_class": ("Mã lớp không tồn tại. Hãy hỏi giáo viên mã lớp.", "Unknown class code. Ask your teacher for it."),
    "no_account": ("Chưa có tài khoản với tên này trong lớp. Hãy chọn \"Đăng ký lần đầu\".", "No account with this name in the class. Choose \"First time here\"."),
    "exists": ("Tên này đã có tài khoản trong lớp. Hãy chọn \"Đã có tài khoản\" và nhập PIN.", "This name already has an account in the class. Choose \"I have an account\" and enter the PIN."),
    "wrong": ("Sai PIN. Quên PIN thì nhờ giáo viên đặt lại.", "Wrong PIN. If you forgot it, ask your teacher to reset it."),
}


def _auth_error(stt):
    vi, en = _AUTH_ERR.get(stt, (stt, stt))
    return tx(vi, en)


def submit_student_auth(mode, code, name, pin, pin2):
    """Đăng nhập lại hoặc đăng ký lần đầu. Trả về chuỗi lỗi, hoặc '' nếu thành công."""
    ss = st.session_state
    if ss.get("lg_fail", 0) >= 5:
        return tx("Nhập sai quá nhiều lần. Hãy tải lại trang hoặc nhờ giáo viên đặt lại PIN.", "Too many wrong attempts. Reload the page or ask your teacher to reset the PIN.")
    try:
        if mode == "register":
            stt, nm = cr.register(code, name, pin, pin2, _now().strftime("%Y-%m-%d %H:%M"))
            ok = stt == "new"
        else:
            stt, nm = cr.login(code, name, pin)
            ok = stt == "ok"
    except OSError:
        return tx("Không kết nối được nơi lưu dữ liệu: ", "Cannot reach the data store: ") + hs.last_error
    if not ok:
        if stt in ("wrong", "no_account", "exists"):
            ss["lg_fail"] = ss.get("lg_fail", 0) + 1
        return _auth_error(stt)
    finish_login(cr.make_auth(cr.STUDENT, code, nm),
                 tx(f"Chào {nm}! Đã tạo tài khoản, hãy nhớ PIN nhé.", f"Welcome {nm}! Account created, remember your PIN.") if stt == "new"
                 else tx(f"Chào mừng {nm} quay lại!", f"Welcome back, {nm}!"))
    return ""


_TEACHER_INVITE = str(st.secrets.get("TEACHER_INVITE", "") or "")   # tùy chọn: mã mời, có đặt thì mới được tự tạo mã giáo viên

_TCH_ERR = {
    "bad_name": ("Họ tên cần 2-40 ký tự, bắt đầu bằng chữ cái và không có ký tự đặc biệt.", "Your name needs 2-40 characters, starting with a letter, with no special symbols."),
    "bad_tcode": ("Mã giáo viên cần 6-24 ký tự, không có khoảng trắng.", "The teacher code needs 6-24 characters with no spaces."),
    "mismatch": ("Hai lần nhập mã chưa giống nhau.", "The two codes do not match."),
    "taken": ("Mã này đã có người dùng, hãy chọn mã khác.", "This code is already taken, choose another one."),
    "invite": ("Mã mời chưa đúng. Hãy hỏi quản trị viên của trường/nhóm.", "Wrong invitation code. Ask your administrator."),
}


def submit_teacher_auth(code):
    """Đăng nhập giáo viên bằng mã chung (TEACHER_CODE trong Secrets) hoặc mã cá nhân đã tự tạo."""
    ss = st.session_state
    if ss.get("lg_fail", 0) >= 5:
        return tx("Nhập sai quá nhiều lần. Hãy tải lại trang.", "Too many wrong attempts. Reload the page.")
    ok = bool(_TEACHER_CODE) and cr.check_teacher_code(code, _TEACHER_CODE)
    if not ok:
        try:
            ok = cr.login_teacher(code) is not None
        except OSError:
            return tx("Không kết nối được nơi lưu dữ liệu: ", "Cannot reach the data store: ") + hs.last_error
    if not ok:
        ss["lg_fail"] = ss.get("lg_fail", 0) + 1
        return tx("Mã giáo viên chưa đúng. Chưa có mã? Chọn \"Chưa có mã, tạo mã\".", "Wrong teacher code. No code yet? Choose \"No code yet, create one\".")
    finish_login(cr.make_auth(cr.TEACHER), tx("Đã đăng nhập giáo viên.", "Logged in as teacher."))
    return ""


def submit_teacher_register(name, code, code2, invite):
    """Giáo viên chưa có mã tự tạo mã rồi đăng nhập luôn. Trả về chuỗi lỗi, hoặc '' nếu thành công."""
    ss = st.session_state
    if ss.get("lg_fail", 0) >= 5:
        return tx("Thử quá nhiều lần. Hãy tải lại trang.", "Too many attempts. Reload the page.")
    if _TEACHER_INVITE and not hmac.compare_digest(str(invite or "").strip().encode(), _TEACHER_INVITE.encode()):
        ss["lg_fail"] = ss.get("lg_fail", 0) + 1
        return tx(*_TCH_ERR["invite"])
    try:
        stt = cr.register_teacher(name, code, code2, _now().strftime("%Y-%m-%d %H:%M"), _TEACHER_CODE)
    except OSError:
        return tx("Không kết nối được nơi lưu dữ liệu: ", "Cannot reach the data store: ") + hs.last_error
    if stt != "new":
        return tx(*_TCH_ERR[stt])
    finish_login(cr.make_auth(cr.TEACHER), tx(f"Đã tạo mã và đăng nhập giáo viên. Hãy ghi nhớ mã: {code.strip()}", f"Teacher code created and logged in. Remember your code: {code.strip()}"))
    return ""


def on_lang():
    try:
        st.query_params["lang"] = st.session_state.get("lang", "vi")
    except Exception:
        pass


sync_student()


def used_today():
    today = _now().strftime("%Y-%m-%d")
    return sum(1 for h in st.session_state.hist if h.get("d") == today and h.get("k") != "Luyện tập")


def over_quota():
    """Hết lượt gọi AI: quá số lượt của phiên, hoặc (nếu đặt MAX_PER_DAY) quá số lượt trong ngày của học sinh có tên."""
    return st.session_state.n >= MAX_PER_SESSION or (MAX_PER_DAY > 0 and bool(student_name()) and used_today() >= MAX_PER_DAY)


# ---------------- Công thức cấu tạo viết tay ----------------
def _log_result():
    r = st.session_state.res
    smi = ((r[0].get("smiles") if r else "") or "").strip()
    if smi:
        mol, num = chem_numbers(smi)
        if num:
            add_history(num["formula"], "Công thức", {"smi": smi})


def _run_structure(top, img_bytes=None, smi=None):
    if over_quota():
        show_top_error(top, "Bạn đã dùng hết số lượt của phiên này. Hãy tải lại trang để tiếp tục.")
        return
    with st.spinner("Đang phân tích…"):
        try:
            if img_bytes:
                st.session_state.res = (analyze_image_strict(img_bytes), True)
                st.session_state.n += 1
            elif parse_student(smi)[0] is None:
                st.session_state.res = ({"smiles": smi}, False)  # SMILES sai: chấm lỗi ngay, không gọi AI
            else:
                st.session_state.res = (analyze_smiles(smi), False)
                st.session_state.n += 1
            _log_result()
        except Exception as e:
            st.session_state.res = None
            show_top_error(top, "Có lỗi khi phân tích, hãy thử lại hoặc chụp rõ hơn.", e)


def structure_ui():
    top = st.container()  # lỗi và lý do sai hiện ở đầu tab
    # Ảnh hoặc SMILES gửi từ trang chủ / ô Nhập nhanh: phân tích ngay
    pend_img = st.session_state.pop("pending_img", None)
    pend_smi = st.session_state.pop("pending_smi", None)
    if pend_img:
        _run_structure(top, img_bytes=pend_img)
    elif pend_smi:
        _run_structure(top, smi=pend_smi)

    mode = st.radio("Cách nhập", ["🖼️ Tải ảnh lên", "📷 Chụp ảnh", "⌨️ Nhập SMILES"], horizontal=True, key="st_mode")
    img_bytes, smi_in = None, None
    if mode.startswith("📷"):
        f = st.camera_input("Chụp công thức (viết rõ nét, nền sáng, mỗi ảnh một chất)", key="st_cam")
        img_bytes = f.getvalue() if f else None
    elif mode.startswith("🖼️"):
        f = st.file_uploader("Chọn ảnh công thức (viết rõ nét, nền sáng, mỗi ảnh một chất)", type=["jpg", "jpeg", "png", "webp"], key="st_up")
        img_bytes = f.getvalue() if f else None
    else:
        smi_in = st.text_input("Mã SMILES", placeholder="Ví dụ: CC(=O)O", key="st_smi").strip()

    if st.button("Phân tích", type="primary", disabled=not (img_bytes or smi_in), key="st_go"):
        _run_structure(top, img_bytes=img_bytes, smi=smi_in)

    if st.session_state.res:
        r, from_img = st.session_state.res
        smiles_r = (r.get("smiles") or "").strip()
        _, err_r = parse_student(smiles_r) if smiles_r else (None, None)
        if err_r:
            with top:
                st.markdown(errbanner("CÔNG THỨC VẼ SAI: " + err_r), unsafe_allow_html=True)
                im = draw_student(smiles_r)
                if im is not None:
                    st.markdown("**Hình máy đọc lại đúng như hình vẽ (nguyên tử sai khoanh đỏ):**")
                    st.image(im)
                if r.get("luu_y"):
                    st.caption("Ghi chú khi đọc ảnh: " + " • ".join([r["luu_y"]] if isinstance(r["luu_y"], str) else r["luu_y"]))
            st.info("Vì công thức sai hóa trị nên chưa thể gọi tên hay tính khối lượng mol. Hãy sửa lại hình vẽ hoặc sửa SMILES ở ô bên dưới.")
        else:
            st.divider()
            render(r, from_img)
        st.divider()
        fix = st.text_input("Nhận dạng sai? Sửa SMILES rồi phân tích lại", value=r.get("smiles", ""), key="st_fix").strip()
        if st.button("Phân tích lại từ SMILES đã sửa", key="st_fix_go") and fix:
            if over_quota():
                show_top_error(top, "Đã hết số lượt của phiên này.")
            else:
                with st.spinner("Đang phân tích…"):
                    try:
                        st.session_state.res = (analyze_smiles(fix), False)
                        st.session_state.n += 1
                        _log_result()
                        st.rerun()
                    except Exception as e:
                        show_top_error(top, "Có lỗi khi phân tích lại.")


# ---------------- Trợ lý AI ----------------
ASSIST_RULES = ("Bạn là trợ lý học Hóa học thân thiện cho học sinh Việt Nam (THCS và THPT), bám sát SGK Việt Nam. "
                "Trả lời bằng tiếng Việt, ngắn gọn, rõ ràng; có phương trình, điều kiện, ví dụ khi cần. Dùng danh pháp theo SGK. "
                "Nếu không chắc chắn thì nói rõ và khuyên đối chiếu SGK. Nếu câu hỏi không liên quan đến hóa học, nhẹ nhàng đưa cuộc trò chuyện về hóa học.")


SOCRATIC_NOTE = (" CHẾ ĐỘ GỢI Ý TỪNG BƯỚC: khi học sinh nhờ giải bài tập hoặc đề bài, KHÔNG đưa đáp án cuối cùng ngay. Hãy hỏi lại một câu "
                 "dẫn dắt hoặc nêu một bước nhỏ để học sinh tự làm, rồi chờ em trả lời. Chỉ đưa lời giải đầy đủ khi học sinh đã thử và nhờ kiểm tra, "
                 "hoặc nhắc lại yêu cầu xem lời giải. Câu hỏi lý thuyết, khái niệm, danh pháp thì vẫn trả lời bình thường.")


def chat_ai(history):
    contents = [types.Content(role="user" if m["role"] == "user" else "model", parts=[types.Part.from_text(text=m["text"])]) for m in history]
    models = [MODEL]
    fb = st.secrets.get("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
    if fb and fb != MODEL:
        models.append(fb)
    last = None
    for m in models:
        for i in range(2):
            try:
                resp = get_client().models.generate_content(
                    model=m, contents=contents, config=types.GenerateContentConfig(system_instruction=ASSIST_RULES + i18n.chat_note() + (SOCRATIC_NOTE if st.session_state.get('socratic', True) else '')))
                return (resp.text or "").strip() or "Mình chưa có câu trả lời, bạn hỏi lại giúp mình nhé."
            except errors.ServerError as e:
                last = e
                time.sleep(2 * (i + 1))
            except errors.ClientError as e:
                last = e
                if getattr(e, "code", None) == 429:
                    time.sleep(3 * (i + 1))
                else:
                    break
    raise last


def assistant_ui():
    chat = st.session_state.chat
    st.toggle("Chế độ gợi ý từng bước (không đưa đáp án ngay)", value=True, key="socratic")
    box = st.container()  # tin nhắn nằm trên, ô nhập nằm dưới
    voice_input("chat", chat=True)
    q = st.session_state.pop("pending_chat", None) or st.chat_input("Hỏi bất cứ điều gì về hóa học…", key="chat_in")
    if q:
        chat.append({"role": "user", "text": q})
        add_history(q, "Hỏi đáp")
    with box:
        if not chat:
            st.markdown("Xin chào! Mình là trợ lý hóa học. Bạn cứ hỏi về công thức, phản ứng, danh pháp, đồng phân, cách làm bài tập... nhé.")
        for m in chat:
            with st.chat_message("user" if m["role"] == "user" else "assistant"):
                st.markdown(m["text"])
        if q:
            with st.chat_message("assistant"):
                if over_quota():
                    ans = "Bạn đã dùng hết số lượt của phiên này. Hãy tải lại trang để tiếp tục."
                    st.markdown(errbanner(ans), unsafe_allow_html=True)
                else:
                    with st.spinner("Đang suy nghĩ…"):
                        try:
                            ans = chat_ai(chat)
                            st.session_state.n += 1
                        except Exception as e:
                            ans = "Có lỗi khi hỏi trợ lý, bạn thử lại sau nhé."
                            st.caption(f"Chi tiết kỹ thuật: {type(e).__name__}: {str(e)[:300]}")
                    st.markdown(ans)
            chat.append({"role": "assistant", "text": ans})
        if chat and st.button("Xóa cuộc trò chuyện", key="chat_clear"):
            st.session_state.chat = []
            st.rerun()


# ---------------- Mô phỏng thí nghiệm (phim hoạt hình trong trình duyệt) ----------------
# Kịch bản thí nghiệm có sẵn: chạy ngay, không tốn lượt gọi AI. Mỗi kịch bản có phương trình đã kiểm tra cân bằng.
def _sp(he_so, cong_thuc, smiles):
    return {"he_so": he_so, "cong_thuc": cong_thuc, "smiles": smiles}


SIM_BUILTINS = {
    "zn_hcl": {
        "kw": [["kem", "hcl"], ["zn", "hcl"], ["kem", "axit clohidric"], ["zn", "axit clohidric"], ["kem", "axit"]],
        "ten": "Kẽm tác dụng với dung dịch axit clohiđric",
        "dung_cu": [{"id": "A", "loai": "binh_tam_giac", "nhan": "Bình tam giác"}],
        "thu_khi": {"tu": "A", "khi": "H2", "mau": "#e6e9f2"},
        "buoc": [
            {"tieu_de": "Chuẩn bị", "thoi_gian": 6, "mo_ta": "Dùng ống nhỏ giọt cho khoảng 10 mL dung dịch HCl loãng vào bình tam giác. Lắp nút cao su có ống dẫn khí, đầu ống dẫn khí đặt dưới miệng ống thu khí úp ngược trong chậu nước.",
             "hanh_dong": [{"loai": "them_long", "dung_cu": "A", "chat": "dd HCl", "mau": "#eef3ff", "muc": 0.4}]},
            {"tieu_de": "Cho kẽm vào", "thoi_gian": 7, "mo_ta": "Thả vài viên kẽm vào bình. Trên bề mặt viên kẽm xuất hiện nhiều bọt khí, viên kẽm nhỏ dần.",
             "hanh_dong": [{"loai": "them_ran", "dung_cu": "A", "chat": "Zn", "mau": "#9aa4ad", "kieu": "vien"}, {"loai": "sui_bot", "dung_cu": "A", "cuong_do": 0.75},
                           {"loai": "tan", "dung_cu": "A", "con_lai": 0.35, "thoi_gian": 8, "dong_thoi": True}]},
            {"tieu_de": "Thu khí hiđro", "thoi_gian": 7, "mo_ta": "Khí không màu, không mùi thoát ra theo ống dẫn khí và đẩy nước trong ống thu khí xuống. H2 ít tan trong nước nên thu được bằng cách đẩy nước.",
             "hanh_dong": [{"loai": "thu_khi", "luong": 0.8, "thoi_gian": 6}]},
            {"tieu_de": "Thử khí", "thoi_gian": 5, "mo_ta": "Đưa que đóm đang cháy lại gần miệng ống thu khí: khí cháy với ngọn lửa xanh nhạt và nghe tiếng nổ nhỏ “póp”, chứng tỏ khí là hiđro.",
             "hanh_dong": [{"loai": "que_dom", "ket_qua": "no_nho"}]},
        ],
        "hien_tuong": ["Có bọt khí không màu thoát ra trên bề mặt viên kẽm", "Viên kẽm tan dần", "Dung dịch trong suốt, không màu", "Khí thu được cháy có tiếng nổ nhỏ"],
        "phuong_trinh": "Zn + 2HCl -> ZnCl2 + H2↑",
        "chat_tham_gia": [_sp(1, "Zn", "[Zn]"), _sp(2, "HCl", "Cl")], "san_pham": [_sp(1, "ZnCl2", "Cl[Zn]Cl"), _sp(1, "H2", "[H][H]")],
        "giai_thich": "Kẽm đứng trước hiđro trong dãy hoạt động hóa học nên đẩy được hiđro ra khỏi dung dịch axit loãng.",
        "an_toan": ["Đeo kính bảo hộ và găng tay", "Không để lửa gần bình khi đang sinh nhiều khí H2", "Axit HCl ăn mòn, tránh để dính vào da"],
    },
    "cuso4_naoh": {
        "kw": [["cuso4", "naoh"], ["dong sunfat", "naoh"], ["cuso4", "natri hidroxit"], ["dong ii sunfat", "natri hidroxit"], ["dong (ii) sunfat", "naoh"]],
        "ten": "Dung dịch đồng(II) sunfat tác dụng với dung dịch natri hiđroxit",
        "dung_cu": [{"id": "A", "loai": "ong_nghiem", "nhan": "Ống nghiệm"}],
        "thu_khi": None,
        "buoc": [
            {"tieu_de": "Chuẩn bị", "thoi_gian": 5, "mo_ta": "Cho khoảng 2 mL dung dịch CuSO4 vào ống nghiệm. Dung dịch có màu xanh lam.",
             "hanh_dong": [{"loai": "them_long", "dung_cu": "A", "chat": "dd CuSO4", "mau": "#2f7be0", "muc": 0.45}]},
            {"tieu_de": "Nhỏ dung dịch NaOH", "thoi_gian": 7, "mo_ta": "Nhỏ từ từ dung dịch NaOH vào ống nghiệm. Xuất hiện kết tủa màu xanh lam lơ lửng rồi lắng xuống đáy ống.",
             "hanh_dong": [{"loai": "them_long", "dung_cu": "A", "chat": "dd NaOH", "mau": "#f3f7ff", "muc": 0.2},
                           {"loai": "ket_tua", "dung_cu": "A", "chat": "Cu(OH)2", "mau": "#4f93f2", "luong": 0.85, "thoi_gian": 4},
                           {"loai": "doi_mau", "dung_cu": "A", "mau": "#cfe3fb", "thoi_gian": 4, "dong_thoi": True}]},
            {"tieu_de": "Quan sát", "thoi_gian": 4, "mo_ta": "Kết tủa Cu(OH)2 màu xanh lam không tan, lắng ở đáy ống nghiệm; phần dung dịch phía trên nhạt màu đi.", "hanh_dong": []},
        ],
        "hien_tuong": ["Dung dịch CuSO4 màu xanh lam", "Khi nhỏ NaOH xuất hiện kết tủa màu xanh lam", "Kết tủa lắng xuống đáy ống nghiệm"],
        "phuong_trinh": "CuSO4 + 2NaOH -> Cu(OH)2↓ + Na2SO4",
        "chat_tham_gia": [_sp(1, "CuSO4", "[Cu+2].[O-]S(=O)(=O)[O-]"), _sp(2, "NaOH", "[Na+].[OH-]")],
        "san_pham": [_sp(1, "Cu(OH)2", "[Cu+2].[OH-].[OH-]"), _sp(1, "Na2SO4", "[Na+].[Na+].[O-]S(=O)(=O)[O-]")],
        "giai_thich": "Đây là phản ứng trao đổi: ion Cu2+ kết hợp với ion OH- tạo hiđroxit không tan Cu(OH)2.",
        "an_toan": ["Đeo kính bảo hộ và găng tay", "NaOH có tính ăn mòn, tránh dính vào da và mắt"],
    },
    "agno3_nacl": {
        "kw": [["agno3", "nacl"], ["bac nitrat", "natri clorua"], ["agno3", "muoi an"], ["agno3", "natri clorua"], ["bac nitrat", "nacl"]],
        "ten": "Dung dịch bạc nitrat tác dụng với dung dịch natri clorua",
        "dung_cu": [{"id": "A", "loai": "ong_nghiem", "nhan": "Ống nghiệm"}],
        "thu_khi": None,
        "buoc": [
            {"tieu_de": "Chuẩn bị", "thoi_gian": 5, "mo_ta": "Cho khoảng 2 mL dung dịch AgNO3 vào ống nghiệm. Dung dịch trong suốt, không màu.",
             "hanh_dong": [{"loai": "them_long", "dung_cu": "A", "chat": "dd AgNO3", "mau": "#f2f6ff", "muc": 0.45}]},
            {"tieu_de": "Nhỏ dung dịch NaCl", "thoi_gian": 7, "mo_ta": "Nhỏ dung dịch NaCl vào ống nghiệm. Xuất hiện ngay kết tủa màu trắng dạng sữa, vón cục, làm đục dung dịch.",
             "hanh_dong": [{"loai": "them_long", "dung_cu": "A", "chat": "dd NaCl", "mau": "#f3f7ff", "muc": 0.2},
                           {"loai": "ket_tua", "dung_cu": "A", "chat": "AgCl", "mau": "#fbfbf7", "luong": 0.9, "thoi_gian": 3.5},
                           {"loai": "doi_mau", "dung_cu": "A", "mau": "#e9ecf3", "thoi_gian": 3, "dong_thoi": True}]},
            {"tieu_de": "Quan sát", "thoi_gian": 4, "mo_ta": "Kết tủa trắng AgCl không tan trong nước và trong axit, lắng dần xuống đáy ống nghiệm.", "hanh_dong": []},
        ],
        "hien_tuong": ["Xuất hiện kết tủa màu trắng", "Kết tủa vón cục, lắng xuống đáy ống nghiệm"],
        "phuong_trinh": "AgNO3 + NaCl -> AgCl↓ + NaNO3",
        "chat_tham_gia": [_sp(1, "AgNO3", "[Ag+].[O-][N+](=O)[O-]"), _sp(1, "NaCl", "[Na+].[Cl-]")],
        "san_pham": [_sp(1, "AgCl", "[Ag+].[Cl-]"), _sp(1, "NaNO3", "[Na+].[O-][N+](=O)[O-]")],
        "giai_thich": "Ion Ag+ kết hợp với ion Cl- tạo AgCl không tan. Phản ứng này dùng để nhận biết ion clorua.",
        "an_toan": ["Đeo kính bảo hộ và găng tay", "AgNO3 làm đen da khi dính vào, rửa ngay bằng nhiều nước"],
    },
    "kmno4": {
        "kw": [["kmno4", "nhiet"], ["kali pemanganat", "nhiet"], ["kmno4", "oxi"], ["kmno4", "o2"], ["thuoc tim", "nhiet"], ["dieu che oxi"], ["dieu che khi oxi"]],
        "ten": "Nhiệt phân kali pemanganat điều chế khí oxi",
        "dung_cu": [{"id": "A", "loai": "ong_nghiem", "nhan": "Ống nghiệm"}],
        "thu_khi": {"tu": "A", "khi": "O2", "mau": "#dfeaf7"},
        "buoc": [
            {"tieu_de": "Chuẩn bị", "thoi_gian": 6, "mo_ta": "Cho một ít tinh thể KMnO4 màu tím đen vào ống nghiệm, nhét một nhúm bông ở miệng ống rồi đậy bằng nút cao su có ống dẫn khí. Kẹp ống nghiệm trên giá, đặt ống thu khí đầy nước úp trong chậu nước.",
             "hanh_dong": [{"loai": "them_ran", "dung_cu": "A", "chat": "KMnO4", "mau": "#5a1b6f", "kieu": "bot"}]},
            {"tieu_de": "Đun nóng", "thoi_gian": 8, "mo_ta": "Đốt đèn cồn và đun nóng ống nghiệm. Chất rắn đổi màu, khí oxi thoát ra theo ống dẫn khí.",
             "hanh_dong": [{"loai": "dun_nong", "bat": True, "dung_cu": "A"}, {"loai": "doi_mau_ran", "dung_cu": "A", "mau": "#2b2623", "thoi_gian": 5}]},
            {"tieu_de": "Thu khí oxi", "thoi_gian": 7, "mo_ta": "Khí O2 ít tan trong nước nên thu được bằng cách đẩy nước. Khí đẩy nước trong ống thu khí xuống.",
             "hanh_dong": [{"loai": "thu_khi", "luong": 0.8, "thoi_gian": 6}]},
            {"tieu_de": "Thử khí", "thoi_gian": 5, "mo_ta": "Đưa que đóm còn tàn đỏ vào miệng ống thu khí: tàn đỏ bùng cháy thành ngọn lửa, chứng tỏ khí là oxi.",
             "hanh_dong": [{"loai": "que_dom", "ket_qua": "bung_chay"}]},
            {"tieu_de": "Kết thúc", "thoi_gian": 5, "mo_ta": "Tháo ống dẫn khí ra khỏi chậu nước trước, sau đó mới tắt đèn cồn để nước không bị hút ngược vào ống nghiệm nóng.",
             "hanh_dong": [{"loai": "dun_nong", "bat": False, "dung_cu": "A"}]},
        ],
        "hien_tuong": ["Chất rắn màu tím đen chuyển sang màu sẫm hơn khi đun nóng", "Có khí không màu thoát ra, thu được khí trong ống thu khí", "Que đóm còn tàn đỏ bùng cháy trong khí thu được"],
        "phuong_trinh": "2KMnO4 -> K2MnO4 + MnO2 + O2↑",
        "chat_tham_gia": [_sp(2, "KMnO4", "[K+].[O-][Mn](=O)(=O)=O")], "san_pham": [_sp(1, "K2MnO4", "[K+].[K+].[O-][Mn](=O)(=O)[O-]"), _sp(1, "MnO2", "O=[Mn]=O"), _sp(1, "O2", "O=O")],
        "giai_thich": "KMnO4 bị nhiệt phân, giải phóng khí oxi. Nhúm bông ở miệng ống giữ bụi chất rắn không bị cuốn vào ống dẫn khí.",
        "an_toan": ["Đeo kính bảo hộ", "Tháo ống dẫn khí khỏi chậu nước trước khi tắt đèn cồn", "Ống nghiệm nóng không chạm tay, để nguội rồi mới rửa"],
    },
    "fe_cuso4": {
        "kw": [["fe", "cuso4"], ["sat", "cuso4"], ["dinh sat", "dong sunfat"], ["sat", "dong sunfat"], ["fe", "dong sunfat"], ["sat", "dong ii sunfat"]],
        "ten": "Sắt tác dụng với dung dịch đồng(II) sunfat",
        "dung_cu": [{"id": "A", "loai": "coc", "nhan": "Cốc thủy tinh"}],
        "thu_khi": None,
        "buoc": [
            {"tieu_de": "Chuẩn bị", "thoi_gian": 5, "mo_ta": "Cho khoảng 50 mL dung dịch CuSO4 màu xanh lam vào cốc thủy tinh.",
             "hanh_dong": [{"loai": "them_long", "dung_cu": "A", "chat": "dd CuSO4", "mau": "#2f7be0", "muc": 0.55}]},
            {"tieu_de": "Nhúng đinh sắt", "thoi_gian": 8, "mo_ta": "Nhúng một chiếc đinh sắt đã làm sạch vào dung dịch. Sau một lúc, đinh sắt được phủ một lớp kim loại màu đỏ (đồng), màu xanh của dung dịch nhạt dần.",
             "hanh_dong": [{"loai": "them_ran", "dung_cu": "A", "chat": "Fe (đinh sắt)", "mau": "#8b9199", "kieu": "dinh"},
                           {"loai": "doi_mau_ran", "dung_cu": "A", "mau": "#c0642a", "thoi_gian": 6},
                           {"loai": "doi_mau", "dung_cu": "A", "mau": "#bfe6cf", "thoi_gian": 7, "dong_thoi": True}]},
            {"tieu_de": "Quan sát", "thoi_gian": 4, "mo_ta": "Dung dịch chuyển từ xanh lam sang xanh lục nhạt (FeSO4). Trên đinh sắt có lớp đồng màu đỏ bám vào.", "hanh_dong": []},
        ],
        "hien_tuong": ["Có lớp kim loại màu đỏ bám trên đinh sắt", "Dung dịch từ màu xanh lam chuyển sang xanh lục nhạt"],
        "phuong_trinh": "Fe + CuSO4 -> FeSO4 + Cu↓",
        "chat_tham_gia": [_sp(1, "Fe", "[Fe]"), _sp(1, "CuSO4", "[Cu+2].[O-]S(=O)(=O)[O-]")], "san_pham": [_sp(1, "FeSO4", "[Fe+2].[O-]S(=O)(=O)[O-]"), _sp(1, "Cu", "[Cu]")],
        "giai_thich": "Sắt hoạt động hóa học mạnh hơn đồng nên đẩy đồng ra khỏi dung dịch muối của nó.",
        "an_toan": ["Đeo găng tay và kính bảo hộ", "Muối đồng độc, không để dính vào miệng và mắt"],
    },
    "naoh_hcl": {
        "kw": [["naoh", "hcl"], ["phenolphtalein"], ["trung hoa"], ["natri hidroxit", "axit clohidric"]],
        "ten": "Phản ứng trung hòa NaOH bằng HCl với chất chỉ thị phenolphtalein",
        "dung_cu": [{"id": "A", "loai": "coc", "nhan": "Cốc thủy tinh"}],
        "thu_khi": None,
        "buoc": [
            {"tieu_de": "Chuẩn bị", "thoi_gian": 5, "mo_ta": "Cho khoảng 30 mL dung dịch NaOH loãng vào cốc, nhỏ vài giọt phenolphtalein. Dung dịch chuyển sang màu hồng.",
             "hanh_dong": [{"loai": "them_long", "dung_cu": "A", "chat": "dd NaOH", "mau": "#f4f8ff", "muc": 0.45}, {"loai": "doi_mau", "dung_cu": "A", "mau": "#f07db8", "thoi_gian": 2.5}]},
            {"tieu_de": "Nhỏ từ từ dung dịch HCl", "thoi_gian": 8, "mo_ta": "Nhỏ từng giọt dung dịch HCl vào cốc và khuấy đều. Màu hồng nhạt dần rồi mất hẳn khi axit vừa đủ trung hòa hết NaOH.",
             "hanh_dong": [{"loai": "them_long", "dung_cu": "A", "chat": "dd HCl", "mau": "#f4f8ff", "muc": 0.2, "thoi_gian": 4},
                           {"loai": "doi_mau", "dung_cu": "A", "mau": "#f3f7ff", "thoi_gian": 5, "dong_thoi": True}]},
            {"tieu_de": "Quan sát", "thoi_gian": 4, "mo_ta": "Dung dịch trở về không màu: bazơ đã bị trung hòa hết, tạo muối NaCl và nước.", "hanh_dong": []},
        ],
        "hien_tuong": ["Dung dịch NaOH có phenolphtalein màu hồng", "Nhỏ HCl vào, màu hồng nhạt dần rồi mất hẳn"],
        "phuong_trinh": "NaOH + HCl -> NaCl + H2O",
        "chat_tham_gia": [_sp(1, "NaOH", "[Na+].[OH-]"), _sp(1, "HCl", "Cl")], "san_pham": [_sp(1, "NaCl", "[Na+].[Cl-]"), _sp(1, "H2O", "O")],
        "giai_thich": "Phenolphtalein có màu hồng trong môi trường bazơ và không màu trong môi trường axit hoặc trung tính, nên đổi màu báo hiệu điểm trung hòa.",
        "an_toan": ["Đeo kính bảo hộ và găng tay", "NaOH và HCl đều ăn mòn, nhỏ từ từ và tránh bắn"],
    },
}


def _fold_sim(s):
    s = unicodedata.normalize("NFD", (s or "").lower().replace("đ", "d"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


_SIM_FILLER = set("thi nghiem mo phong cho dung dich dd tac voi va phan ung hien tuong xem phim cua nho vao trong thu khi chat muoi axit bazo baz loang dac long ran bang the nao hay hoa tan thuc hien lam".split())


def sim_match_builtin(text):
    """Tìm kịch bản có sẵn khớp với câu người dùng gõ. Khớp khi chứa đủ các từ khóa của một nhóm
    VÀ không còn chất hay từ lạ nào khác (ví dụ "Gly-Ala-Gly + CuSO4 + NaOH" không được lấy kịch bản "CuSO4 + NaOH")."""
    f = _fold_sim(text)
    for key, sc in SIM_BUILTINS.items():
        for grp in sc["kw"]:
            if all(tok in f for tok in grp):
                rest = f
                for g2 in sc["kw"]:
                    for tok in g2:
                        rest = rest.replace(tok, " ")
                words = [w for w in re.split(r"[^a-z0-9]+", rest) if w and w not in _SIM_FILLER and not (len(w) <= 2 and not any(c.isdigit() for c in w))]
                if not words:
                    return key
    return None


SIM_TEMPLATE = r'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Mô phỏng thí nghiệm</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Arial,"DejaVu Sans",sans-serif;background:#f5f7ff;color:#1b2150}
#wrap{max-width:960px;margin:0 auto}
#cv{width:100%;height:auto;display:block;border-radius:14px;background:#0f1640;box-shadow:0 8px 26px rgba(40,50,160,.25)}
#bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:8px}
button,select{font:inherit;border:1px solid #d9defa;background:#fff;color:#1b2150;border-radius:10px;padding:7px 12px;cursor:pointer;font-weight:600}
button.pri{background:linear-gradient(135deg,#3b6cf6,#6d4df0);color:#fff;border:0}
button:hover{filter:brightness(.97)}button.off{background:#eef0fb;color:#8a90b8}
#sl{flex:1 1 200px;accent-color:#4f5cf0}
#tm{font-size:13px;color:#6b7299;min-width:84px;text-align:right}
#st{font-size:12.5px;color:#6b7299;margin-top:6px;min-height:16px}
</style></head><body><div id="wrap">
<canvas id="cv" width="960" height="540"></canvas>
<div id="bar">
<button id="bR" title="Về đầu">⏮</button><button id="bP" title="Bước trước">⏪</button>
<button id="bPlay" class="pri" style="min-width:92px">▶ Phát</button>
<button id="bN" title="Bước sau">⏩</button>
<input id="sl" type="range" min="0" max="1000" value="0">
<span id="tm">0:00</span>
<span style="display:flex;align-items:center;gap:6px;font-size:13px;color:#6b7299" title="Tốc độ phát tùy ý">⏱ <input id="sp" type="range" min="0.25" max="3" step="0.05" value="1" style="width:110px;accent-color:#4f5cf0"><b id="spl" style="min-width:42px">1,00×</b></span><button id="bVoice" title="Bật hoặc tắt giọng đọc lời dẫn">🗣️ Giọng đọc: Bật</button><button id="bSfx" title="Bật hoặc tắt hiệu ứng âm thanh">🔊 Âm thanh: Bật</button><button id="bTeach" title="Hiện hoặc ẩn cô giáo làm thí nghiệm">👩‍🏫 Cô giáo: Bật</button>
<select id="vsel" style="display:none" title="Chọn giọng đọc của trình duyệt"></select>
<button id="bRec" title="Ghi lại thành video .mp4">🎬 Tải video (.mp4)</button>
<button id="bHtml" title="Lưu bản mô phỏng tự chạy được">💾 Tải .html</button>
</div><div id="st"></div></div>
<script>
const D = __DATA__;
const cv = document.getElementById("cv"), g = cv.getContext("2d"), W = 960, H = 540;
const FONT = 'Arial,"DejaVu Sans",sans-serif';
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const lerp = (a, b, t) => a + (b - a) * t;
const hex2 = (h) => { h = String(h || "#ffffff").replace("#", ""); if (h.length === 3) h = h.split("").map(c => c + c).join(""); return [parseInt(h.substr(0, 2), 16) || 0, parseInt(h.substr(2, 2), 16) || 0, parseInt(h.substr(4, 2), 16) || 0]; };
const mixc = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
const rgba = (c, a = 1) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;
const rnd = (i) => { const x = Math.sin(i * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };
const SUBD = "₀₁₂₃₄₅₆₇₈₉";
const sub = (s) => String(s || "").replace(/(?<=[A-Za-z\)])(\d+)/g, m => m.split("").map(d => SUBD[+d]).join("")).replace(/->/g, "→");
const ease = (p) => p < .5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;

// ---------- dụng cụ ----------
const GEO = { ong_nghiem: { w: 66, h: 230, cap: 190 }, coc: { w: 150, h: 170, cap: 140 }, binh_tam_giac: { w: 170, h: 190, cap: 105 } };
const VS = (D.dung_cu || []).slice(0, 3);
const GAS = D.thu_khi && D.thu_khi.tu ? D.thu_khi : null;
const GAS_V = GAS ? Math.max(0, VS.findIndex(v => v.id === GAS.tu)) : -1;
const lampV = (() => { let k = -1; (D.buoc || []).forEach(s => (s.hanh_dong || []).forEach(a => { if (a.loai === "dun_nong" && k < 0) k = Math.max(0, VS.findIndex(v => v.id === a.dung_cu)); })); return k; })();
VS.forEach((v, i) => {
  const n = VS.length, left = GAS ? 40 : 60, right = GAS ? 560 : 900;
  v.x = left + (right - left) * (i + .5) / n;
  v.base = (i === lampV) ? 336 : 398;
  v.geo = GEO[v.loai] || GEO.ong_nghiem;
});
let SC = 1;
if (!GAS && lampV < 0 && VS.length) { const mt = Math.min(...VS.map(v => v.base - v.geo.h)); SC = Math.max(1, Math.min(VS.length === 1 ? 1.4 : VS.length === 2 ? 1.25 : 1.1, (398 - 66) / (398 - (mt - 72)))); }
function vIndex(id) { const k = VS.findIndex(v => v.id === id); return k >= 0 ? k : 0; }

// ---------- kịch bản thời gian ----------
const narrDur = (txt) => String(txt || "").length / 15 + 1.0;   // ước lượng khi chưa có tệp giọng đọc
const BLOCK = { them_long: 2.6, them_ran: 1.8, dun_nong: 2.6, doi_mau: 3, doi_mau_ran: 3, ket_tua: 2.8, tan: 3, thu_khi: 4, que_dom: 3.2 };
const steps = (D.buoc || []).map(s => Object.assign({}, s));
const LEAD = 1.0;   // 1 giây đầu: cô bước vào bàn thí nghiệm
const events = []; let T = LEAD;
steps.forEach((s, si) => {
  s.t0 = T; let tt = .35, lastOff = .35; const evs = [];
  (s.hanh_dong || []).forEach(a => {
    const e = Object.assign({}, a), dur = Math.max(.4, +a.thoi_gian || BLOCK[a.loai] || .5);
    e.off0 = a.dong_thoi ? lastOff : tt; e.dur = dur; lastOff = e.off0;
    if (BLOCK[a.loai] && !a.dong_thoi) tt = e.off0 + dur + .15; else if (!BLOCK[a.loai]) tt = Math.max(tt, e.off0 + .4);
    evs.push(e);
  });
  const speech = s.am_dur ? s.am_dur + .6 : narrDur(s.mo_ta);
  s.auto = !s.thoi_gian_cung;
  const dur = s.thoi_gian_cung ? Math.max(2, +s.thoi_gian_cung) : Math.max(+s.thoi_gian || 4, tt + .9, speech);
  // kéo giãn (hoặc nén) chuyển động để phim chạy liền mạch suốt lời đọc, không đứng hình
  const body = tt - .35, room = dur - .35 - .9, k = body > 0 ? clamp(room / body, .5, 3) : 1;
  evs.forEach(e => { e.t0 = T + .35 + (e.off0 - .35) * k; e.t1 = e.t0 + e.dur * k; e.si = si; events.push(e); });
  s.k = (s.am_dur && s.thoi_gian_cung) ? clamp(s.am_dur / Math.max(1, dur - .8), .7, 1.6) : 1;   // tốc độ đọc để vừa với thời lượng tự đặt
  s.t1 = T + dur; T += dur;
});
const endText = "Kết luận. " + (D.hien_tuong || []).slice(0, 5).join(". ") + ". " + (D.giai_thich || "");
const endDur = D.thoi_gian_ket ? Math.max(3, +D.thoi_gian_ket) : Math.max(8, D.am_ket_dur ? D.am_ket_dur + 1 : narrDur(endText));
const endCard = { tieu_de: "Kết luận", t0: T, t1: T + endDur, end: true, am: D.am_ket, am_dur: D.am_ket_dur, mo_ta: endText, k: (D.am_ket_dur && D.thoi_gian_ket) ? clamp(D.am_ket_dur / Math.max(1, endDur - 1), .7, 1.6) : 1 };
steps.push(endCard); const TOTAL = endCard.t1;

// ---------- trạng thái tại thời điểm t ----------
function stateAt(t) {
  const vs = VS.map(() => ({ vol: 0, col: [235, 240, 255], solid: null, scol: null, ssize: 1, pr: 0, prcol: [255, 255, 255], rate: 0, items: [], prNew: 0, fx: [] }));
  let lamp = false, gasVol = 0, gasCol = hex2(GAS && GAS.mau || "#d8dde8"), splint = null, gasOn = false, capOn = false, lift = 0;
  for (let ei = 0; ei < events.length; ei++) {
    const e = events[ei]; if (t < e.t0) continue;
    const p = clamp((t - e.t0) / (e.t1 - e.t0)), k = vIndex(e.dung_cu), v = vs[k] || vs[0]; if (!v) continue;
    switch (e.loai) {
      case "them_long": {
        const dv = clamp(+e.muc || .3, .03, .85) * (TEACH_ON ? dripP(e, t) : p), v0 = v.vol, c1 = hex2(e.mau || "#dfe8ff");
        v.col = v0 + dv > 0 ? mixc(v.col, c1, v0 < .001 ? 1 : dv / (v0 + dv)) : c1; v.vol = clamp(v0 + dv, 0, .95);
        if (p < 1) v.fx.push({ t: "long", c: c1, p, id: ei }); if (p > .5 && !v.items.includes(e.chat)) v.items.push(e.chat); break; }
      case "them_ran": {
        let sp = p; if (TEACH_ON) { const tr = relT(e); if (t - e.t0 < tr) { v.ranPend = true; break; } sp = clamp((t - e.t0 - tr) / 1.2); }   // chỉ rơi khi cô buông tay
        v.solid = e.kieu || "vien"; v.scol = hex2(e.mau || "#999999"); v.ssize = 1; v.sp = sp;
        if (sp < 1) v.fx.push({ t: "ran", c: v.scol, p: sp, kieu: v.solid, id: ei }); if (sp > .5 && !v.items.includes(e.chat)) v.items.push(e.chat); break; }
      case "doi_mau": v.col = mixc(v.col, hex2(e.mau || "#ffffff"), ease(p)); break;
      case "doi_mau_ran": if (v.scol) v.scol = mixc(v.scol, hex2(e.mau || "#999999"), ease(p)); break;
      case "ket_tua": v.prcol = hex2(e.mau || "#ffffff"); v.pr = clamp(v.pr + clamp(+e.luong || .5) * p * 1, 0, 1); if (p < 1) { v.prNew = p; v.fx.push({ t: "tua", p, id: ei }); } if (p > .5 && e.chat && !v.items.includes(e.chat)) v.items.push(e.chat); break;
      case "sui_bot": if (TEACH_ON && v.ranPend) break; v.rate = clamp(+e.cuong_do || 0); break;
      case "tan": v.ssize = lerp(1, clamp(e.con_lai === undefined ? .15 : +e.con_lai), p); break;
      case "dun_nong": { if (TEACH_ON) { const el = t - e.t0, A = phs(e).A; if (e.bat) { lamp = el >= A + .4; capOn = false; } else { lamp = el < A + .2; capOn = el >= A + .2; } } else { lamp = !!e.bat; capOn = false; } break; }
      case "thu_khi": gasOn = p < 1; gasVol = clamp(gasVol + clamp(+e.luong || .7) * p); break;
      case "que_dom": { if (TEACH_ON) { const si = splintInfo(e, t); lift = si.lift; splint = si.vis ? { p, kq: e.ket_qua || "bung_chay", id: ei, eh: si.eh } : null; } else splint = { p, kq: e.ket_qua || "bung_chay", id: ei }; break; }
    }
  }
  return { vs, lamp, gasVol, gasCol, splint, gasOn, capOn, lift };
}

// ---------- vẽ ----------
function outline(v) {
  const p = new Path2D(), x = v.x, b = v.base, G = v.geo, w = G.w, h = G.h, top = b - h;
  if (v.loai === "coc") { p.moveTo(x - w / 2, top); p.lineTo(x - w / 2 + 4, b - 8); p.quadraticCurveTo(x - w / 2 + 4, b, x - w / 2 + 14, b); p.lineTo(x + w / 2 - 14, b); p.quadraticCurveTo(x + w / 2 - 4, b, x + w / 2 - 4, b - 8); p.lineTo(x + w / 2, top); }
  else if (v.loai === "binh_tam_giac") { const nw = 46; p.moveTo(x - nw / 2, top); p.lineTo(x - nw / 2, top + 66); p.lineTo(x - w / 2 + 8, b - 10); p.quadraticCurveTo(x - w / 2, b, x - w / 2 + 14, b); p.lineTo(x + w / 2 - 14, b); p.quadraticCurveTo(x + w / 2, b, x + w / 2 - 8, b - 10); p.lineTo(x + nw / 2, top + 66); p.lineTo(x + nw / 2, top); }
  else { const r = w / 2; p.moveTo(x - r, top); p.lineTo(x - r, b - r); p.arc(x, b - r, r, Math.PI, 0, true); p.lineTo(x + r, top); }
  return p;
}
function surfaceY(v, vol) { const G = v.geo; return v.base - 5 - vol * G.cap; }
function halfW(v, y) { // nửa bề rộng bên trong tại độ cao y
  const G = v.geo, top = v.base - G.h;
  if (v.loai === "binh_tam_giac") { const nb = top + 66; if (y <= nb) return 20; const r = clamp((y - nb) / (v.base - nb)); return lerp(20, G.w / 2 - 8, r); }
  if (v.loai === "coc") return G.w / 2 - 6; return G.w / 2 - 6;
}
function drawBench() {
  const gr = g.createLinearGradient(0, 0, 0, H); gr.addColorStop(0, "#1c2670"); gr.addColorStop(.75, "#141b52"); gr.addColorStop(1, "#0d1240");
  g.fillStyle = gr; g.fillRect(0, 0, W, H);
  g.fillStyle = "rgba(255,255,255,.04)"; for (let i = 0; i < 16; i++) { g.beginPath(); g.arc(80 + i * 58, 70 + rnd(i) * 160, 20 + rnd(i + 9) * 40, 0, 7); g.fill(); }
  const wd = g.createLinearGradient(0, 398, 0, 424); wd.addColorStop(0, "#caa270"); wd.addColorStop(1, "#8d6a3f");
  g.fillStyle = wd; g.fillRect(0, 398, W, 26); g.fillStyle = "rgba(0,0,0,.18)"; g.fillRect(0, 424, W, 6);
}
function drawLamp(x, on, t, cap) {
  g.fillStyle = "#cfd8e8"; g.strokeStyle = "#8aa0c0"; g.lineWidth = 2;
  g.beginPath(); g.moveTo(x - 16, 382); g.lineTo(x - 26, 394); g.quadraticCurveTo(x - 28, 398, x - 20, 398); g.lineTo(x + 20, 398); g.quadraticCurveTo(x + 28, 398, x + 26, 394); g.lineTo(x + 16, 382); g.closePath(); g.fill(); g.stroke();
  g.fillStyle = "rgba(255,210,120,.55)"; g.fillRect(x - 21, 388, 42, 9);
  g.fillStyle = "#6b7280"; g.fillRect(x - 8, 372, 16, 11); g.fillStyle = "#333"; g.fillRect(x - 1.5, 362, 3, 11);
  if (cap) { capShape(x, 357); g.fillStyle = "rgba(205,228,250,.62)"; g.fill(); g.strokeStyle = "rgba(140,172,215,.98)"; g.lineWidth = 2; g.stroke(); g.fillStyle = "#cfd8e8"; g.beginPath(); g.arc(x, 344, 3.4, 0, 7); g.fill(); }
  if (on) {
    const sw = Math.sin(t * 11) * 2, hh = 36 + Math.sin(t * 17) * 3;
    const fl = (col, s) => { g.fillStyle = col; g.beginPath(); g.moveTo(x, 366); g.bezierCurveTo(x - 13 * s, 354, x - 8 * s, 366 - hh * s * .6, x + sw, 366 - hh * s); g.bezierCurveTo(x + 8 * s, 366 - hh * s * .6, x + 13 * s, 354, x, 366); g.fill(); };
    const gl = g.createRadialGradient(x, 340, 4, x, 340, 70); gl.addColorStop(0, "rgba(255,170,60,.35)"); gl.addColorStop(1, "rgba(255,170,60,0)"); g.fillStyle = gl; g.fillRect(x - 80, 270, 160, 130);
    fl("rgba(255,120,20,.75)", 1); fl("rgba(255,210,70,.9)", .68); fl("rgba(120,170,255,.9)", .32);
  }
}
function drawStand(v) {
  const x = v.x - v.geo.w / 2 - 34; g.fillStyle = "#6b7280"; g.fillRect(x - 3, 168, 6, 232); g.fillStyle = "#4b5563"; g.fillRect(x - 24, 396, 48, 6);
  const y = v.base - v.geo.h + 40; g.fillStyle = "#6b7280"; g.fillRect(x, y - 3, v.x - x, 6); g.fillStyle = "#374151"; g.fillRect(v.x - v.geo.w / 2 - 5, y - 9, v.geo.w + 10, 8);
}
function drawGlass(v, st, t) {
  const path = outline(v), G = v.geo, b = v.base, x = v.x;
  g.save(); g.clip(path);
  if (st.vol > 0.002) {
    const sy = surfaceY(v, st.vol), grd = g.createLinearGradient(0, sy, 0, b); grd.addColorStop(0, rgba(st.col, .72)); grd.addColorStop(1, rgba(st.col, .92));
    g.fillStyle = grd; g.fillRect(x - G.w, sy, G.w * 2, b - sy + 4);
    g.fillStyle = rgba(mixc(st.col, [255, 255, 255], .5), .8); g.beginPath(); g.ellipse(x, sy, halfW(v, sy), 3, 0, 0, 7); g.fill();
  }
  // chất rắn
  if (st.solid && st.ssize > .02) {
    const sc = st.scol || [150, 150, 150], s = st.ssize, sp = st.sp === undefined ? 1 : st.sp;
    const fall = sp >= 1 ? 0 : (1 - ease(clamp(sp / .5))) * (TEACH_ON ? G.h * .6 : 120);
    g.fillStyle = rgba(sc, 1); g.strokeStyle = rgba(mixc(sc, [0, 0, 0], .35), 1); g.lineWidth = 1.5;
    if (st.solid === "bot") { g.beginPath(); g.ellipse(x, b - 4 - fall, 28 * s, 15 * s + 2, 0, Math.PI, 0); g.fill(); g.stroke(); }
    else if (st.solid === "dinh") { g.save(); g.translate(x + 2, b - 6 - fall); g.rotate(-.12); g.fillRect(-3, -G.h * .5, 6, G.h * .5 * clamp(s + .15, 0, 1)); g.restore(); }
    else if (st.solid === "mieng") { const fy = surfaceY(v, st.vol) - 5 + Math.sin(t * 5) * 1.5; g.fillRect(x - 10 * s + Math.sin(t * 3) * 6 * (st.rate), (st.vol > .05 ? fy : b - 10) - fall, 20 * s, 10 * s); }
    else { g.beginPath(); g.ellipse(x - 8, b - 9 - fall, 15 * s + 1, 8 * s + 1, -.2, 0, 7); g.fill(); g.stroke(); }
  }
  // kết tủa
  if (st.pr > .01) {
    const hgt = 6 + st.pr * G.cap * .24; g.fillStyle = rgba(st.prcol, .96);
    g.beginPath(); g.moveTo(x - G.w, b + 2); for (let i = 0; i <= 24; i++) { const xx = x - G.w / 2 + 6 + (G.w - 12) * i / 24; g.lineTo(xx, b - hgt * (.8 + .25 * rnd(i + 3))); } g.lineTo(x + G.w, b + 2); g.closePath(); g.fill();
    if (st.prNew > 0 && st.prNew < 1 && st.vol > .05) { const top = surfaceY(v, st.vol); for (let i = 0; i < 46; i++) { const px = x + (rnd(i) - .5) * halfW(v, b - 20) * 1.7, ph = (t * (22 + rnd(i + 5) * 26) + rnd(i + 9) * 100) % (b - top - hgt); g.fillStyle = rgba(st.prcol, .85); g.beginPath(); g.arc(px, top + ph, 2 + rnd(i + 2) * 2, 0, 7); g.fill(); } }
  }
  // bọt khí
  if (st.rate > .02 && (st.vol > .04 || st.solid)) {
    const sy = st.vol > .04 ? surfaceY(v, st.vol) : b - 30, n = Math.round(8 + st.rate * 34), hh = b - 8 - sy;
    for (let i = 0; i < n; i++) { const sp = 26 + rnd(i + 90) * 46, ph = (t * sp * (.6 + st.rate) + rnd(i) * hh) % hh, hw = Math.max(6, halfW(v, b - ph) - 6), bx = x + (rnd(i + 50) - .5) * hw * 1.5 + Math.sin(t * 4 + i) * 2, r = 1.8 + rnd(i + 70) * 3.2;
      g.strokeStyle = "rgba(255,255,255,.85)"; g.fillStyle = "rgba(255,255,255,.28)"; g.lineWidth = 1.2; g.beginPath(); g.arc(bx, b - 8 - ph, r, 0, 7); g.fill(); g.stroke(); }
  }
  g.restore();
  g.fillStyle = "rgba(210,230,255,.10)"; g.fill(path);
  g.strokeStyle = "rgba(190,215,250,.95)"; g.lineWidth = 3; g.stroke(path);
  g.strokeStyle = "rgba(255,255,255,.45)"; g.lineWidth = 3; g.beginPath(); g.moveTo(x - G.w / 2 + 9, b - G.h + 22); g.lineTo(x - G.w / 2 + 9, b - 38); g.stroke();
}
function drawFx(v, st, t) { // dòng chảy, giọt, vật rơi
  const x = v.x, top = v.base - v.geo.h;
  if (TEACH_ON) { const dr = POSE && POSE.drip; if (dr && dr.vi === VS.indexOf(v)) { const sy = surfaceY(v, Math.max(st.vol, .02)); g.fillStyle = rgba(dr.c, .95); g.strokeStyle = "rgba(120,150,200,.6)"; g.lineWidth = 1; for (let k = 0; k < 3; k++) { const ph = (t * 1.6 + k / 3) % 1; g.beginPath(); g.ellipse(dr.x, dr.y + 4 + ph * Math.max(2, sy - dr.y - 4), 2.7, 4.3, 0, 0, 7); g.fill(); g.stroke(); } }
    st.fx.forEach(f => { if (f.t === "ran" && f.kieu === "bot" && f.p < .6) { g.fillStyle = rgba(f.c, .95); for (let i = 0; i < 16; i++) { const pr = clamp(f.p / .6 * 1.5 - i * .045, 0, 1); if (pr <= 0 || pr >= 1) continue; g.beginPath(); g.arc(x + Math.sin(i * 7.3) * 4 * pr, lerp(top - 26, v.base - 14, pr * pr), 1.7, 0, 7); g.fill(); } } });   // bột chảy từ thìa xuống đáy
    return; }
  st.fx.forEach(f => {
    if (f.t === "long") {
      const sy = surfaceY(v, Math.max(st.vol, .02)), tx = x + 40;
      g.fillStyle = "#8b3a3a"; g.beginPath(); g.arc(tx, top - 78, 11, 0, 7); g.fill();
      g.fillStyle = "rgba(235,240,255,.85)"; g.strokeStyle = "rgba(150,170,210,.9)"; g.lineWidth = 2; g.fillRect(tx - 6, top - 70, 12, 50); g.strokeRect(tx - 6, top - 70, 12, 50);
      g.beginPath(); g.moveTo(tx - 6, top - 20); g.lineTo(tx - 2, top - 8); g.lineTo(tx + 2, top - 8); g.lineTo(tx + 6, top - 20); g.closePath(); g.fill(); g.stroke();
      g.fillStyle = rgba(f.c, .95); g.fillRect(tx - 4, top - 62, 8, 38);
      for (let k = 0; k < 4; k++) { const ph = (t * 1.6 + k / 4) % 1, yy = top - 8 + ph * (sy - top + 8); g.beginPath(); g.ellipse(tx + (x - tx) * ph * .98, yy, 3, 5, 0, 0, 7); g.fill(); }
    } else if (f.t === "ran") {
      const y = lerp(top - 60, v.base - 20, ease(clamp(f.p / .5))); if (f.p < .55) { g.fillStyle = rgba(f.c, 1); g.beginPath(); g.ellipse(x - 6, y, 13, 7, -.3, 0, 7); g.fill(); }
      g.fillStyle = "rgba(255,255,255,.6)"; g.fillRect(x - 38, top - 70, 70, 5); g.fillRect(x - 38, top - 70, 5, 14);
    }
  });
}
function drawGasKit(st, t) {
  if (!GAS) return; const v = VS[GAS_V], x = v.x, top = v.base - v.geo.h, tx = 690;
  // nút cao su + ống dẫn khí
  g.fillStyle = "#8b5a2b"; g.beginPath(); g.moveTo(x - 17, top - 6); g.lineTo(x + 17, top - 6); g.lineTo(x + 13, top + 18); g.lineTo(x - 13, top + 18); g.closePath(); g.fill();
  g.strokeStyle = "rgba(210,230,250,.95)"; g.lineWidth = 6; g.lineJoin = "round"; g.beginPath(); g.moveTo(x, top + 6); g.lineTo(x, top - 46); g.lineTo(tx - 40, top - 46); g.lineTo(tx - 40, 372); g.stroke();
  g.strokeStyle = "rgba(60,80,120,.5)"; g.lineWidth = 1.5; g.stroke();
  // chậu nước
  const bx = tx - 130, by = 340, bw = 260, bh = 58;
  g.fillStyle = "rgba(90,160,230,.55)"; g.fillRect(bx + 3, by + 14, bw - 6, bh - 17);
  g.strokeStyle = "rgba(190,215,250,.95)"; g.lineWidth = 4; g.strokeRect(bx, by, bw, bh);
  g.strokeStyle = "rgba(255,255,255,.5)"; g.lineWidth = 2; g.beginPath(); g.moveTo(bx + 4, by + 14); for (let i = 0; i <= 26; i++) g.lineTo(bx + 4 + i * 9.6, by + 14 + Math.sin(t * 3 + i) * 1.3); g.stroke();
  // ống thu khí úp ngược
  const LF = st.lift || 0, jx = tx - 40, jw = 70, jt = 232 - LIFT_PX * LF, jb = 372 - LIFT_PX * LF, inner = jb - jt;
  const waterTop = lerp(jt + st.gasVol * inner * .95, jb + 6, ease(clamp(LF * 2.4)));   // nhấc lên khỏi chậu thì nước chảy hết
  g.save(); g.beginPath(); g.rect(jx - jw / 2 + 2, jt + 2, jw - 4, inner); g.clip();
  g.fillStyle = "rgba(90,160,230,.55)"; g.fillRect(jx - jw / 2, waterTop, jw, Math.max(0, jb - waterTop));
  if (st.gasVol > .01) { g.fillStyle = rgba(st.gasCol, .35); g.fillRect(jx - jw / 2, jt, jw, waterTop - jt); }
  g.restore();
  g.strokeStyle = "rgba(190,215,250,.95)"; g.lineWidth = 3; g.beginPath(); g.moveTo(jx - jw / 2, jb + 8); g.lineTo(jx - jw / 2, jt + 8); g.quadraticCurveTo(jx - jw / 2, jt, jx - jw / 2 + 8, jt); g.lineTo(jx + jw / 2 - 8, jt); g.quadraticCurveTo(jx + jw / 2, jt, jx + jw / 2, jt + 8); g.lineTo(jx + jw / 2, jb + 8); g.stroke();
  g.fillStyle = "rgba(255,255,255,.9)"; g.font = `bold 14px ${FONT}`; g.textAlign = "center"; g.fillText(sub(GAS.khi || "Khí"), jx, jt - 8);
  if (st.gasOn) for (let i = 0; i < 9; i++) { const ph = (t * 1.3 + i / 9) % 1, by2 = 372 - ph * 90; g.fillStyle = "rgba(255,255,255,.8)"; g.beginPath(); g.arc(jx + Math.sin(i * 3 + t * 4) * 6, by2, 2.5 + rnd(i) * 2, 0, 7); g.fill(); }
}
function drawSplint(st, t) { if (TEACH_ON) { if (POSE && POSE.splint) drawSplintFx(POSE.splint, t); return; } drawSplintOld(st, t); }
function drawSplintOld(st, t) {
  if (!st.splint) return; const p = st.splint.p, kq = st.splint.kq, jx = 650, top = 232;
  const mv = ease(clamp(p / .55)), x = lerp(860, jx + 6, mv), y = lerp(120, top - 20, mv);
  g.save(); g.translate(x, y); g.rotate(.55); g.fillStyle = "#c9a36a"; g.fillRect(-4, -110, 8, 110); g.restore();
  const tipx = x + Math.sin(.55) * 0, tipy = y;
  const lit = kq !== "tat" ? 1 : clamp(1 - (p - .6) * 3);
  if (p > .5 && kq === "bung_chay") { const r = 8 + (p - .5) * 60; const gr = g.createRadialGradient(tipx, tipy, 2, tipx, tipy, r); gr.addColorStop(0, "rgba(255,255,200,1)"); gr.addColorStop(.4, "rgba(255,190,60,.9)"); gr.addColorStop(1, "rgba(255,120,0,0)"); g.fillStyle = gr; g.beginPath(); g.arc(tipx, tipy, r, 0, 7); g.fill(); }
  else if (p > .75 && kq === "no_nho") { const r = (p - .75) * 160; g.strokeStyle = `rgba(255,230,120,${1 - (p - .75) * 3})`; g.lineWidth = 4; g.beginPath(); g.arc(tipx, tipy, r, 0, 7); g.stroke(); g.fillStyle = "rgba(255,240,180,.9)"; g.font = `bold 22px ${FONT}`; g.textAlign = "center"; g.fillText("pop!", tipx, tipy - r - 8); }
  else { g.fillStyle = `rgba(255,${90 + lit * 50},30,${.5 + .5 * lit})`; g.beginPath(); g.arc(tipx, tipy, 5, 0, 7); g.fill(); }
}
function wrap(text, maxW, font) { g.font = font; const words = String(text || "").split(/\s+/), lines = []; let cur = ""; words.forEach(w => { const tt = cur ? cur + " " + w : w; if (g.measureText(tt).width > maxW && cur) { lines.push(cur); cur = w; } else cur = tt; }); if (cur) lines.push(cur); return lines; }
function rrect(x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }
function curStep(t) { for (let i = 0; i < steps.length; i++) if (t < steps[i].t1) return i; return steps.length - 1; }
function drawHud(t) {
  const si = curStep(t), s = steps[si], n = steps.length - 1;
  g.fillStyle = "rgba(8,12,40,.7)"; g.fillRect(0, 0, W, 44);
  g.fillStyle = "#fff"; g.textAlign = "left"; g.font = `bold 21px ${FONT}`; g.fillText(sub(D.ten || "Mô phỏng thí nghiệm"), 18, 29);
  g.fillStyle = "#9fb3ff"; g.font = `13px ${FONT}`; g.textAlign = "right"; g.fillText("MolSnap · Mô phỏng thí nghiệm", W - 16, 28);
  if (s.end) return;
  const x = 20, y = 440, w = W - 40, h = 90; g.fillStyle = "rgba(8,12,40,.86)"; rrect(x, y, w, h, 14); g.fill();
  g.fillStyle = "#6ee7ff"; g.textAlign = "left"; g.font = `bold 16px ${FONT}`; g.fillText(`Bước ${si + 1}/${n}  ·  ${s.tieu_de || ""}`, x + 16, y + 24);
  const lines = wrap(s.mo_ta, w - 32, `16px ${FONT}`).slice(0, 3); g.fillStyle = "#fff"; g.font = `16px ${FONT}`; lines.forEach((l, i) => g.fillText(l, x + 16, y + 48 + i * 21));
  g.fillStyle = "rgba(255,255,255,.14)"; g.fillRect(x, y + h + 2, w, 3); g.fillStyle = "#6ee7ff"; g.fillRect(x, y + h + 2, w * clamp((t - s.t0) / (s.t1 - s.t0)), 3);
}
function drawEnd(t) {
  const p = clamp((t - endCard.t0) / 1.2); g.fillStyle = `rgba(8,12,40,${.98 * p})`; g.fillRect(0, 44, W, H - 44);
  g.globalAlpha = p; g.textAlign = "center"; g.fillStyle = "#6ee7ff"; g.font = `bold 20px ${FONT}`; g.fillText("KẾT LUẬN", W / 2, 90);
  g.fillStyle = "#fff"; g.font = `bold 28px ${FONT}`; const eq = wrap(sub(D.phuong_trinh || ""), W - 100, `bold 28px ${FONT}`).slice(0, 2); eq.forEach((l, i) => g.fillText(l, W / 2, 134 + i * 36));
  let y = 134 + eq.length * 36 + 22; g.textAlign = "left"; g.fillStyle = "#9fb3ff"; g.font = `bold 17px ${FONT}`; g.fillText("Hiện tượng quan sát được:", 70, y); y += 28;
  g.fillStyle = "#fff"; g.font = `17px ${FONT}`;
  (D.hien_tuong || []).slice(0, 5).forEach(h => { wrap("• " + h, W - 150, `17px ${FONT}`).slice(0, 2).forEach((l, i) => { g.fillText((i ? "   " : "") + l, 70, y); y += 24; }); y += 4; });
  if (D.giai_thich && y < H - 70) { g.fillStyle = "#9fb3ff"; g.font = `bold 17px ${FONT}`; y += 6; g.fillText("Giải thích:", 70, y); y += 26; g.fillStyle = "#fff"; g.font = `16px ${FONT}`; wrap(D.giai_thich, W - 150, `16px ${FONT}`).slice(0, 3).forEach(l => { g.fillText(l, 70, y); y += 22; }); }
  g.globalAlpha = 1;
}
// ---------- cô giáo làm thí nghiệm ----------
// Cô đứng sau bàn thí nghiệm, tự đi đến từng dụng cụ, tay làm đúng thao tác, mắt nhìn theo thí nghiệm, miệng cử động theo giọng đọc.
let TEACH_ON = true, POSE = null, mouthOpen = 0;
const C_SK = "#f2c8a2", C_SKD = "#d4a07a", C_HAIR = "#2a1c1e", C_COAT = "#f8faff", C_COATD = "#b9c5e4", C_GL = "#7cc3f0", C_GLD = "#3b8fc8";
const ARM1 = 106, ARM2 = 106, SH_Y = 172, BENCH = 398, SH_W = 50;
const MANUAL = { them_long: 1, them_ran: 1, dun_nong: 1, que_dom: 1, thu_khi: 1 };
const JAR = GAS ? { x: 650, top: 232, bot: 372 } : null;   // ống thu khí (khớp với drawGasKit)
const JAR_ST = 775, LIFT_PX = 118;
const lampX = () => lampV >= 0 ? VS[lampV].x : (VS[0] ? VS[0].x : 480);
const rotOf = (u) => Math.atan2(u.x, -u.y);                 // góc xoay để trục "lên" của dụng cụ trùng hướng u
const along = (p, u, d) => ({ x: p.x + u.x * d, y: p.y + u.y * d });
const tiltFor = (len, tipY) => Math.acos(clamp((tipY - 56) / len, .3, .96));   // nghiêng dụng cụ để tay/bầu cao su không chạm thanh tiêu đề
const unit = (x, y) => { const d = Math.hypot(x, y) || 1; return { x: x / d, y: y / d }; };

// các pha của một thao tác (giây): A = đưa tay tới, R = rút tay về; Le = thời lượng thao tác thực sự
function phs(e) {
  const L = e.t1 - e.t0, Le = e.loai === "dun_nong" ? Math.min(L, 3.4) : e.loai === "them_ran" ? Math.min(L, 4.4) : e.loai === "que_dom" ? Math.min(L, 7) : L;
  return { L: Le, A: Math.min(1.1, Le * .32), R: Math.min(1, Le * .3) };
}
function relT(e) { const q = phs(e); return q.A + Math.min(.55, Math.max(.15, (q.L - q.A - q.R) * .4)); }   // lúc buông chất rắn
function dripP(e, t) { const q = phs(e), s = q.A + .15, f = Math.max(s + .3, q.L - q.R - .1); return clamp((t - e.t0 - s) / (f - s)); }
function splintInfo(e, t) {
  const q = phs(e), el = Math.max(0, t - e.t0), L = q.L, A = q.A, R = q.R, jx = JAR ? JAR.x : 650;
  const hitT = A + .45, endT = L - R;
  const lift = ease(clamp(el / A)) * (1 - ease(clamp((el - endT) / R)));
  const mouthY = (JAR ? JAR.bot : 372) + 8 - LIFT_PX * lift;
  const t0p = { x: JAR_ST - 20, y: 318 }, t1p = { x: jx + 4, y: mouthY + 14 };
  const s1 = ease(clamp((el - .25) / Math.max(.3, hitT - .25))), s2 = ease(clamp((el - endT) / (R * .75))), qq = s1 * (1 - s2);
  const tip = { x: lerp(t0p.x, t1p.x, qq), y: lerp(t0p.y, t1p.y, qq) - Math.sin(Math.PI * qq) * 26 };
  return { tip, lift, eh: el - hitT, hit: el >= hitT, vis: el <= L + .05, qq };
}

// ---------- đường đi của cô ----------
function stationX(e) {
  if (e.loai === "que_dom" || e.loai === "thu_khi") return JAR_ST;
  const vi = e.loai === "dun_nong" && lampV >= 0 ? lampV : vIndex(e.dung_cu), v = VS[vi] || { x: 480 };
  let x = v.x - (e.loai === "dun_nong" ? 108 : 125); if (x < 100) x = v.x + (e.loai === "dun_nong" ? 108 : 125);
  return clamp(x, 100, 860);
}
function targetX(e) { return (e.loai === "que_dom" || e.loai === "thu_khi") ? (JAR ? JAR.x : 650) : e.loai === "dun_nong" ? lampX() : (VS[vIndex(e.dung_cu)] || { x: 480 }).x; }
const TASKS = events.filter(e => MANUAL[e.loai]).map(e => ({ e, x: stationX(e), t0: e.t0, t1: e.t1 })).sort((a, b) => a.t0 - b.t0);
const HOME = TASKS.length ? Math.max(-70, TASKS[0].x - 330) : clamp((VS[0] ? VS[0].x : 480) - 125, 100, 860);
const WALK = [];
(function () {
  let px = HOME, pend = 0;
  TASKS.forEach(k => {
    const need = clamp(Math.abs(k.x - px) / 280, .5, 2.2), b = k.t0 - .1; let a = Math.max(pend, b - need);
    if (b - a < .3) a = Math.max(0, b - .3);
    WALK.push({ a, b, x0: px, x1: k.x, task: k }); px = k.x; pend = k.t1;
  });
})();
function teacherPos(t) {
  let x = HOME, walking = false, dist = 0, task = null;
  for (let i = 0; i < WALK.length; i++) {
    const w = WALK[i];
    if (t >= w.b) { x = w.x1; continue; }
    if (t > w.a && Math.abs(w.x1 - w.x0) > 2) { const q = ease(clamp((t - w.a) / (w.b - w.a))); x = lerp(w.x0, w.x1, q); walking = q > .001 && q < .999; dist = Math.abs(x - w.x0); task = w.task; }
    else x = w.x0;
    break;
  }
  return { x, walking, dist, task };
}
function activeTask(t) { let best = null; for (const k of TASKS) if (t >= k.t0 - .05 && t <= k.t1 + .1) best = k; return best; }
function lastTask(t) { let best = null; for (const k of TASKS) if (k.t0 - .6 <= t) best = k; return best || TASKS[0] || null; }
function focusPt(t) {
  let e = null; for (const x of events) if (x.t0 <= t + .05 && (!e || x.t0 >= e.t0)) e = x;
  if (!e) e = events[0]; if (!e) return { x: 480, y: 250 };
  if (e.loai === "que_dom" || e.loai === "thu_khi") return { x: JAR ? JAR.x : 650, y: 300 };
  if (e.loai === "dun_nong") return { x: lampX(), y: 352 };
  const v = VS[vIndex(e.dung_cu)] || VS[0]; return { x: v.x, y: v.base - v.geo.h * .45 };
}

// ---------- tay: tính khớp khuỷu ----------
function ik(sx, sy, hx, hy, outS, cx) {
  const dx = hx - sx, dy = hy - sy, d = Math.hypot(dx, dy) || 1, dd = Math.min(d, ARM1 + ARM2 - 1.5), ux = dx / d, uy = dy / d;
  const a = (ARM1 * ARM1 - ARM2 * ARM2 + dd * dd) / (2 * dd), h = Math.sqrt(Math.max(0, ARM1 * ARM1 - a * a));
  const bx = sx + ux * a, by = sy + uy * a, c1 = { x: bx - uy * h, y: by + ux * h }, c2 = { x: bx + uy * h, y: by - ux * h };
  const score = c => (c.y - (sy + hy) / 2) + .7 * outS * (c.x - (sx + hx) / 2);   // khuỷu hướng xuống và ra ngoài
  const el = score(c1) >= score(c2) ? c1 : c2;
  return { sx, sy, ex: el.x, ey: el.y, hx: sx + ux * dd, hy: sy + uy * dd };
}

// ---------- tư thế tại thời điểm t ----------
function teacherPose(t, ta) {
  const P = teacherPos(t), k = activeTask(t), lk = k || P.task || lastTask(t);
  const cx0 = P.x, dir = lk ? (targetX(lk.e) >= lk.x ? 1 : -1) : 1;
  const ph = P.dist / 24, sw = P.walking ? Math.sin(ph) : 0, bob = P.walking ? Math.abs(Math.sin(ph)) * 3.2 : 0;
  const cx = cx0 + Math.sin(ta * 1.3) * (P.walking ? 0 : 1.2);
  const rest = { n: { x: cx + dir * 64 + sw * 12 * dir, y: 378 - sw * 8 }, f: { x: cx - dir * 64 - sw * 12 * dir, y: 378 + sw * 8 } };
  const out = { cx, dir, walking: P.walking, tools: [], drip: null, busyV: -1, splint: null, hn: rest.n, hf: rest.f, look: null, bob };
  if (k) {
    const e = k.e, q = phs(e), L = q.L, A = q.A, R = q.R, el = clamp(t - e.t0, 0, L + .3);
    const bl = ease(clamp(el / .45)) * (1 - ease(clamp((el - (L - .45)) / .45)));
    const ap = ease(clamp(el / A)), rt = ease(clamp((el - (L - R)) / R)), qq = ap * (1 - rt);
    const arc = (a, b, h) => ({ x: lerp(a.x, b.x, qq), y: lerp(a.y, b.y, qq) - Math.sin(Math.PI * qq) * h });
    if (e.loai === "them_long") {
      const vi = vIndex(e.dung_cu), v = VS[vi], top = v.base - v.geo.h, bx = cx - dir * 30, by = 270;
      const tip0 = { x: bx, y: by - 40 }, tip1 = { x: v.x, y: top - 18 }, tip = arc(tip0, tip1, 30);
      if (qq > .999) tip.y += Math.sin(el * 2.3) * 1.2;
      const al = Math.max(.3, tiltFor(98, tip1.y)), u = unit(-dir * Math.sin(al), -Math.cos(al)), grip = along(tip, u, 42), dp = dripP(e, t);
      const dripping = qq > .98 && el > A + .15 && el < L - R - .05;
      out.tools.push({ k: "bottle", x: bx, y: by, col: e.mau, label: e.chat || "", a: bl });
      out.tools.push({ k: "dropper", tip, u, fill: .95 - .8 * dp, col: e.mau, sq: dripping ? .5 + .5 * Math.cos(t * 1.6 * 6.2832) : 0, a: bl });
      out.hn = { x: lerp(rest.n.x, grip.x, bl), y: lerp(rest.n.y, grip.y, bl) }; out.hf = { x: lerp(rest.f.x, bx, bl), y: lerp(rest.f.y, by + 15, bl) };
      if (dripping) out.drip = { vi, x: tip.x, y: tip.y, c: hex2(e.mau || "#dfe8ff") };
      out.busyV = vi; out.look = { x: tip.x, y: tip.y + 20 };
    } else if (e.loai === "them_ran") {
      const vi = vIndex(e.dung_cu), v = VS[vi], top = v.base - v.geo.h, kind = e.kieu || "vien", tr = relT(e);
      const tip0 = { x: cx + dir * 44, y: 282 }, tip1 = { x: v.x, y: top - 34 }, tip = arc(tip0, tip1, 28);
      const pour = kind === "bot" ? ease(clamp((el - A) / Math.max(.25, tr - A))) * (1 - rt) : 0, al = Math.max(.4, tiltFor(82, tip1.y));
      const u = unit(-dir * (Math.sin(al) + pour * .75), -Math.cos(al) * (1 - pour * .6)), grip = along(tip, u, 44);
      out.tools.push({ k: kind === "bot" ? "spoon" : "tweezers", tip, u, kind, col: e.mau || "#9aa4ad", carry: el < tr, gap: ease(clamp((el - tr) / .3)), a: bl });
      out.hn = { x: lerp(rest.n.x, grip.x, bl), y: lerp(rest.n.y, grip.y, bl) };
      out.busyV = vi; out.look = { x: tip.x, y: tip.y + 14 };
    } else if (e.loai === "dun_nong") {
      const lx = lampX(), wick = { x: lx - 3, y: 366 };
      if (e.bat) {
        const tip0 = { x: cx + dir * 46, y: 330 }, tip = arc(tip0, wick, 22), u = unit(-dir * .82, .57), grip = along(tip, u, 30);
        out.tools.push({ k: "match", tip, u, lit: el > A * .55 && el < A + .9, a: bl });
        out.hn = { x: lerp(rest.n.x, grip.x, bl), y: lerp(rest.n.y, grip.y, bl) }; out.look = { x: tip.x, y: tip.y - 8 };
      } else {
        const c0 = { x: cx + dir * 46, y: 318 }, c1 = { x: lx, y: 357 }, cp = arc(c0, c1, 24), done = el >= A + .2;
        const capPos = done ? c1 : cp, grip = { x: capPos.x - dir * 21, y: capPos.y - 2 };
        if (!done) out.tools.push({ k: "cap", x: capPos.x, y: capPos.y, a: bl });
        out.hn = { x: lerp(rest.n.x, grip.x, bl), y: lerp(rest.n.y, grip.y, bl) }; out.look = { x: capPos.x, y: capPos.y - 6 };
      }
    } else if (e.loai === "que_dom") {
      const si = splintInfo(e, t), jx = JAR ? JAR.x : 650, jm = ((JAR ? JAR.top : 232) + (JAR ? JAR.bot : 372)) / 2 - LIFT_PX * si.lift;
      const u = unit(-dir * .82, .57), grip = along(si.tip, u, 58), gj = { x: jx + 37, y: jm + 12 };
      out.tools.push({ k: "splint", tip: si.tip, u, a: bl });
      out.hn = { x: lerp(rest.n.x, gj.x, bl), y: lerp(rest.n.y, gj.y, bl) }; out.hf = { x: lerp(rest.f.x, grip.x, bl), y: lerp(rest.f.y, grip.y, bl) };
      out.splint = { tip: si.tip, kq: e.ket_qua || "bung_chay", eh: si.eh, a: bl }; out.look = { x: si.tip.x, y: si.tip.y };
    } else if (e.loai === "thu_khi") {
      const gj = { x: (JAR ? JAR.x : 650) + 37, y: 296 };
      out.hn = { x: lerp(rest.n.x, gj.x, bl), y: lerp(rest.n.y, gj.y, bl) }; out.look = { x: gj.x - 30, y: 270 };
    }
  }
  // ánh nhìn: vào đầu dụng cụ đang cầm; nếu không làm gì thì nhìn vào chỗ đang xảy ra hiện tượng
  if (!out.look) { const tg = P.walking && P.task ? { x: targetX(P.task.e), y: 280 } : focusPt(t); out.look = tg; }
  const hy = Math.max(out.hn.y, out.hf.y), lean = 22 * clamp((hy - 380) / 22, 0, 1);
  out.sy = SH_Y + lean + Math.sin(ta * 1.8) * 1 + bob;
  const aN = ik(cx + dir * SH_W, out.sy, out.hn.x, out.hn.y, dir, cx), aF = ik(cx - dir * SH_W, out.sy, out.hf.x, out.hf.y, -dir, cx);
  out.aN = aN; out.aF = aF;
  return out;
}

// ---------- vẽ cô giáo (phần thân, sau dụng cụ thủy tinh) ----------
function drawSleeve(a) {
  g.lineCap = "round"; g.lineJoin = "round";
  [[C_COATD, 26], [C_COAT, 22]].forEach(([c, w]) => { g.strokeStyle = c; g.lineWidth = w; g.beginPath(); g.moveTo(a.sx, a.sy); g.lineTo(a.ex, a.ey); g.lineTo(a.hx, a.hy); g.stroke(); });
  g.strokeStyle = "#dbe3f6"; g.lineWidth = 3; g.beginPath(); const ux = a.hx - a.ex, uy = a.hy - a.ey, d = Math.hypot(ux, uy) || 1;   // viền tay áo
  g.moveTo(a.hx - ux / d * 9 - uy / d * 10, a.hy - uy / d * 9 + ux / d * 10); g.lineTo(a.hx - ux / d * 9 + uy / d * 10, a.hy - uy / d * 9 - ux / d * 10); g.stroke();
}
function drawTeacherBack(P, ta) {
  const cx = P.cx, sy = P.sy, blink = (ta * 1000) % 3400 < 130;
  g.save(); g.beginPath(); g.rect(0, 0, W, BENCH); g.clip();
  // thân áo blouse
  const gr = g.createLinearGradient(cx - 64, 0, cx + 64, 0); gr.addColorStop(0, "#e5ebfa"); gr.addColorStop(.5, "#ffffff"); gr.addColorStop(1, "#e0e7f7");
  g.fillStyle = gr; g.strokeStyle = C_COATD; g.lineWidth = 2.5; g.beginPath();
  g.moveTo(cx - 22, sy - 16); g.bezierCurveTo(cx - 44, sy - 12, cx - 66, sy - 6, cx - 66, sy + 26); g.lineTo(cx - 70, BENCH + 6); g.lineTo(cx + 70, BENCH + 6); g.lineTo(cx + 66, sy + 26);
  g.bezierCurveTo(cx + 66, sy - 6, cx + 44, sy - 12, cx + 22, sy - 16); g.closePath(); g.fill(); g.stroke();
  g.fillStyle = "#77a9e6"; g.beginPath(); g.moveTo(cx - 21, sy - 15); g.lineTo(cx, sy + 44); g.lineTo(cx + 21, sy - 15); g.closePath(); g.fill();      // áo trong
  g.fillStyle = C_SK; g.fillRect(cx - 10, sy - 38, 20, 26); g.fillStyle = "rgba(0,0,0,.10)"; g.fillRect(cx - 10, sy - 18, 20, 5);                    // cổ
  g.fillStyle = C_SK; g.beginPath(); g.moveTo(cx - 12, sy - 14); g.lineTo(cx, sy + 14); g.lineTo(cx + 12, sy - 14); g.closePath(); g.fill();
  g.strokeStyle = C_COATD; g.lineWidth = 2.2; g.beginPath(); g.moveTo(cx - 24, sy - 15); g.lineTo(cx - 4, sy + 52); g.moveTo(cx + 24, sy - 15); g.lineTo(cx + 4, sy + 52); g.moveTo(cx, sy + 52); g.lineTo(cx, BENCH + 6); g.stroke();
  g.fillStyle = "#c9d3ec"; for (let i = 0; i < 3; i++) { g.beginPath(); g.arc(cx + 3, sy + 90 + i * 52, 3, 0, 7); g.fill(); }
  g.strokeStyle = C_COATD; g.lineWidth = 2; rrect(cx + 24, sy + 100, 32, 34, 5); g.stroke(); g.fillStyle = "#3b6cf6"; g.fillRect(cx + 33, sy + 94, 3.5, 16); g.fillStyle = "#e0457b"; g.fillRect(cx + 40, sy + 96, 3.5, 14);   // túi và bút
  // tay áo
  drawSleeve(P.aF); drawSleeve(P.aN);
  // đầu
  const lk = P.look, hx0 = cx, hy0 = sy - 60 + Math.sin(ta * 7) * mouthOpen * 1.3, ddx = lk.x - hx0, ddy = lk.y - hy0;
  const turn = clamp(ddx / 90, -1, 1), gx = clamp(ddx / 110, -1, 1), gy = clamp(ddy / 130, -1, 1), tilt = clamp(ddx / 700, -.08, .08) - clamp(ddy / 2500, -.03, .03) * 0;
  const hx = hx0 + turn * 3, hy = hy0;
  g.save(); g.translate(hx, hy + 34); g.rotate(tilt); g.translate(-hx, -(hy + 34));
  g.fillStyle = C_HAIR; g.beginPath(); g.ellipse(hx, hy - 4, 37, 39, 0, 0, 7); g.fill();                                                               // tóc sau
  g.beginPath(); g.arc(hx + turn * 2, hy - 42, 15, 0, 7); g.fill(); g.strokeStyle = "#e0457b"; g.lineWidth = 3; g.beginPath(); g.arc(hx + turn * 2, hy - 42, 15, 3.5, 5.9); g.stroke();   // búi tóc và dây buộc
  g.fillStyle = C_SK; g.beginPath(); g.arc(hx - 32, hy + 4, 7, 0, 7); g.arc(hx + 32, hy + 4, 7, 0, 7); g.fill();                                         // tai
  g.beginPath(); g.ellipse(hx, hy + 3, 31, 34, 0, 0, 7); g.fill();                                                                                       // mặt
  g.fillStyle = C_HAIR; g.beginPath(); g.moveTo(hx - 33, hy - 2); g.bezierCurveTo(hx - 37, hy - 42, hx + 37, hy - 42, hx + 33, hy - 2);
  g.bezierCurveTo(hx + 24, hy - 24, hx - 4, hy - 27, hx - 33, hy - 2); g.fill();                                                                         // tóc mái
  const ey = hy - 1, fx = turn * 4;
  g.strokeStyle = "#1e3a8a"; g.lineWidth = 6; g.lineCap = "butt"; g.beginPath(); g.moveTo(hx - 34, ey); g.lineTo(hx + 34, ey); g.stroke();             // dây kính
  for (const s of [-1, 1]) {                                                                                                                              // mắt
    const ex = hx + s * 14 + fx; g.fillStyle = "#fff"; g.beginPath(); g.ellipse(ex, ey, 7.4, blink ? .9 : 6.4, 0, 0, 7); g.fill();
    if (!blink) { g.fillStyle = "#2b2233"; g.beginPath(); g.arc(ex + gx * 3.2, ey + gy * 2.4, 3.5, 0, 7); g.fill(); g.fillStyle = "#fff"; g.beginPath(); g.arc(ex + gx * 3.2 + 1.2, ey + gy * 2.4 - 1.2, 1.1, 0, 7); g.fill(); }
    g.strokeStyle = C_HAIR; g.lineWidth = 2.4; g.lineCap = "round"; g.beginPath(); g.moveTo(ex - 7, ey - 15 - mouthOpen * 1.5); g.quadraticCurveTo(ex, ey - 19 - mouthOpen * 1.5, ex + 7, ey - 15.5 - mouthOpen); g.stroke();   // lông mày
  }
  g.fillStyle = "rgba(200,235,255,.28)"; g.strokeStyle = "#2554c7"; g.lineWidth = 3; rrect(hx + fx - 30, ey - 12.5, 29, 25, 9); g.fill(); g.stroke(); rrect(hx + fx + 1, ey - 12.5, 29, 25, 9); g.fill(); g.stroke();   // kính bảo hộ
  g.strokeStyle = "rgba(255,255,255,.8)"; g.lineWidth = 2; g.beginPath(); g.moveTo(hx + fx - 25, ey - 6); g.lineTo(hx + fx - 17, ey - 9); g.moveTo(hx + fx + 6, ey - 6); g.lineTo(hx + fx + 14, ey - 9); g.stroke();
  g.fillStyle = "rgba(240,120,130,.28)"; g.beginPath(); g.ellipse(hx + fx - 21, ey + 17, 6, 3.4, 0, 0, 7); g.ellipse(hx + fx + 21, ey + 17, 6, 3.4, 0, 0, 7); g.fill();   // má
  g.strokeStyle = C_SKD; g.lineWidth = 1.8; g.beginPath(); g.moveTo(hx + fx * .8 - 2, ey + 12); g.quadraticCurveTo(hx + fx * .8 + 2, ey + 17, hx + fx * .8 - 1, ey + 18); g.stroke();   // mũi
  const mx = hx + fx * .9, my = ey + 27, o = mouthOpen;                                                                                                  // miệng
  if (o > .06) { g.fillStyle = "#7d2433"; g.beginPath(); g.ellipse(mx, my + o * 2.5, 6.5 + o * 2.2, 1.6 + o * 7.5, 0, 0, 7); g.fill(); g.strokeStyle = "#c4545e"; g.lineWidth = 1.6; g.stroke(); if (o > .35) { g.fillStyle = "#f6f0f0"; g.fillRect(mx - 4.5, my - o * 2.6 + 1.6, 9, 2.4); } }
  else { g.strokeStyle = "#c4545e"; g.lineWidth = 2.2; g.lineCap = "round"; g.beginPath(); g.moveTo(mx - 7, my - 1); g.quadraticCurveTo(mx, my + 4, mx + 7, my - 1); g.stroke(); }
  g.restore(); g.restore();
}

// ---------- dụng cụ cầm trên tay (vẽ phía trước kính) ----------
function drawBottle(tl) {
  const { x, y } = tl; g.save(); g.globalAlpha = tl.a; const c = mixc(hex2(tl.col || "#dfe8ff"), [110, 140, 200], .22);
  g.fillStyle = "rgba(225,235,250,.6)"; g.strokeStyle = "rgba(110,140,195,.95)"; g.lineWidth = 2; rrect(x - 18, y - 22, 36, 48, 8); g.fill(); g.stroke();
  g.save(); rrect(x - 18, y - 22, 36, 48, 8); g.clip(); g.fillStyle = rgba(c, .92); g.fillRect(x - 20, y - 8, 40, 36); g.restore();
  g.fillStyle = "rgba(225,235,250,.75)"; g.fillRect(x - 8, y - 34, 16, 13); g.strokeRect(x - 8, y - 34, 16, 13);
  g.fillStyle = "#fff"; rrect(x - 15, y - 18, 30, 17, 3); g.fill(); g.fillStyle = "#1b2150"; g.font = `bold 8px ${FONT}`; g.textAlign = "center"; g.fillText(sub(tl.label).slice(0, 9), x, y - 6);
  g.restore();
}
function drawDropper(tl) {
  g.save(); g.globalAlpha = tl.a; g.translate(tl.tip.x, tl.tip.y); g.rotate(rotOf(tl.u));
  const tube = () => { g.beginPath(); g.moveTo(-1.6, 0); g.lineTo(-4.6, -15); g.lineTo(-4.6, -64); g.lineTo(4.6, -64); g.lineTo(4.6, -15); g.lineTo(1.6, 0); g.closePath(); };
  tube(); g.fillStyle = "rgba(238,245,255,.6)"; g.fill();
  if (tl.fill > .02) { g.save(); tube(); g.clip(); g.fillStyle = rgba(mixc(hex2(tl.col || "#dfe8ff"), [110, 140, 200], .25), .95); g.fillRect(-6, -2 - tl.fill * 60, 12, tl.fill * 60 + 2); g.restore(); }
  tube(); g.strokeStyle = "rgba(100,130,185,.95)"; g.lineWidth = 1.6; g.stroke();
  g.fillStyle = "#222c4f"; g.fillRect(-6.6, -69, 13.2, 6);
  g.fillStyle = "#c8403a"; g.strokeStyle = "#8f2a27"; g.lineWidth = 1.5; g.beginPath(); g.ellipse(0, -82, 8.4 - tl.sq * 2, 13.5 - tl.sq * 3.6, 0, 0, 7); g.fill(); g.stroke();
  g.fillStyle = "rgba(255,255,255,.38)"; g.beginPath(); g.ellipse(-2.8, -86, 1.8, 5, 0, 0, 7); g.fill();
  g.restore();
}
function drawTweezers(tl) {
  g.save(); g.globalAlpha = tl.a; g.translate(tl.tip.x, tl.tip.y); g.rotate(rotOf(tl.u)); const op = tl.gap * 5;
  g.lineCap = "round"; g.strokeStyle = "#aeb8c8"; g.lineWidth = 3.2; g.beginPath(); g.moveTo(-1.5 - op, 0); g.lineTo(-6.5, -74); g.moveTo(1.5 + op, 0); g.lineTo(6.5, -74); g.stroke();
  g.strokeStyle = "#7d889b"; g.lineWidth = 1; g.beginPath(); g.moveTo(-1.5 - op, 0); g.lineTo(-6.5, -74); g.moveTo(1.5 + op, 0); g.lineTo(6.5, -74); g.stroke();
  if (tl.carry) { const c = hex2(tl.col); g.fillStyle = rgba(c, 1); g.strokeStyle = rgba(mixc(c, [0, 0, 0], .35), 1); g.lineWidth = 1.3;
    if (tl.kind === "dinh") { rrect(-2.6, 1, 5.2, 46, 2); g.fill(); g.stroke(); g.beginPath(); g.ellipse(0, 1, 5.6, 2.2, 0, 0, 7); g.fill(); g.stroke(); }
    else if (tl.kind === "mieng") { rrect(-10, 1, 20, 5, 1.5); g.fill(); g.stroke(); }
    else { g.beginPath(); g.ellipse(0, 3, 8, 5.2, 0, 0, 7); g.fill(); g.stroke(); } }
  g.restore();
}
function drawSpoon(tl) {
  g.save(); g.globalAlpha = tl.a; g.translate(tl.tip.x, tl.tip.y); g.rotate(rotOf(tl.u));
  g.lineCap = "round"; g.strokeStyle = "#a9b3c4"; g.lineWidth = 3.4; g.beginPath(); g.moveTo(0, -4); g.lineTo(0, -76); g.stroke();
  g.fillStyle = "#c6cedb"; g.strokeStyle = "#7d889b"; g.lineWidth = 1.2; g.beginPath(); g.ellipse(0, -7, 5.6, 10, 0, 0, 7); g.fill(); g.stroke();
  if (tl.carry) { const c = hex2(tl.col); g.fillStyle = rgba(c, 1); g.beginPath(); g.ellipse(0, -7, 4.4, 8, 0, 0, 7); g.fill(); }
  g.restore();
}
function flameAt(x, y, s, t, blue) {
  const sw = Math.sin(t * 11) * 2 * s, hh = (36 + Math.sin(t * 17) * 3) * s;
  const gl = g.createRadialGradient(x, y - 14 * s, 3, x, y - 14 * s, 46 * s); gl.addColorStop(0, blue ? "rgba(120,170,255,.4)" : "rgba(255,170,60,.38)"); gl.addColorStop(1, "rgba(255,170,60,0)"); g.fillStyle = gl; g.fillRect(x - 50 * s, y - 60 * s, 100 * s, 100 * s);
  const fl = (col, k) => { g.fillStyle = col; g.beginPath(); g.moveTo(x, y); g.bezierCurveTo(x - 13 * k * s, y - 12 * s, x - 8 * k * s, y - hh * k * .6, x + sw, y - hh * k); g.bezierCurveTo(x + 8 * k * s, y - hh * k * .6, x + 13 * k * s, y - 12 * s, x, y); g.fill(); };
  if (blue) { fl("rgba(110,160,255,.7)", 1); fl("rgba(190,215,255,.9)", .6); } else { fl("rgba(255,120,20,.78)", 1); fl("rgba(255,210,70,.92)", .68); fl("rgba(255,250,200,.9)", .32); }
}
function drawMatch(tl, ta) {
  g.save(); g.globalAlpha = tl.a; g.translate(tl.tip.x, tl.tip.y); g.rotate(rotOf(tl.u));
  g.fillStyle = "#d9b27a"; g.fillRect(-1.8, -48, 3.6, 48); g.fillStyle = tl.lit ? "#2f2420" : "#b13a22"; g.beginPath(); g.arc(0, 0, 3.8, 0, 7); g.fill(); g.restore();
  if (tl.lit) { g.save(); g.globalAlpha = tl.a; flameAt(tl.tip.x, tl.tip.y - 2, .5, ta, false); g.restore(); }
}
function capShape(x, y) { g.beginPath(); g.moveTo(x - 12, y + 16); g.lineTo(x - 12, y + 2); g.quadraticCurveTo(x - 12, y - 12, x, y - 12); g.quadraticCurveTo(x + 12, y - 12, x + 12, y + 2); g.lineTo(x + 12, y + 16); g.closePath(); }
function drawCap(tl) {
  g.save(); g.globalAlpha = tl.a; capShape(tl.x, tl.y); g.fillStyle = "rgba(205,228,250,.62)"; g.fill(); g.strokeStyle = "rgba(140,172,215,.98)"; g.lineWidth = 2; g.stroke();
  g.fillStyle = "#cfd8e8"; g.beginPath(); g.arc(tl.x, tl.y - 13, 3.4, 0, 7); g.fill(); g.restore();
}
function drawSplintStick(tl) {
  g.save(); g.globalAlpha = tl.a; g.translate(tl.tip.x, tl.tip.y); g.rotate(rotOf(tl.u));
  g.fillStyle = "#d2a86c"; g.fillRect(-2.6, -98, 5.2, 98); g.fillStyle = "#3a2b20"; g.fillRect(-2.6, -12, 5.2, 12); g.restore();
}
function glove(x, y, dir, grip) {
  g.fillStyle = C_GL; g.strokeStyle = C_GLD; g.lineWidth = 2;
  g.beginPath(); g.ellipse(x, y, 11.5, 10.5, 0, 0, 7); g.fill(); g.stroke();
  g.beginPath(); g.ellipse(x + dir * 9, y - 6, 4.6, 6.2, dir * .5, 0, 7); g.fill(); g.stroke();                       // ngón cái
  if (grip) { g.strokeStyle = "rgba(60,140,200,.7)"; g.lineWidth = 1.5; g.beginPath(); g.moveTo(x - 7, y - 3); g.lineTo(x + 7, y - 3); g.moveTo(x - 7, y + 2); g.lineTo(x + 7, y + 2); g.stroke(); }
}
function drawTeacherFront(P, ta) {
  g.save(); g.beginPath(); g.rect(0, 0, W, BENCH); g.clip();
  P.tools.forEach(tl => { if (tl.a < .02) return; ({ bottle: drawBottle, dropper: drawDropper, tweezers: drawTweezers, spoon: drawSpoon, match: m => drawMatch(m, ta), cap: drawCap, splint: drawSplintStick })[tl.k](tl); });
  const holding = P.tools.some(t => t.a > .3);
  glove(P.aF.hx, P.aF.hy, -P.dir, holding); glove(P.aN.hx, P.aN.hy, P.dir, holding);
  g.restore();
}
// hiệu ứng ở đầu que đóm (tàn đỏ, bùng cháy, nổ nhỏ, tắt)
function drawSplintFx(S, t) {
  const x = S.tip.x, y = S.tip.y, kq = S.kq, eh = S.eh; g.save(); g.globalAlpha = S.a;
  const ember = () => { const r = 9 + Math.sin(t * 9) * 1.2, gr = g.createRadialGradient(x, y, 1, x, y, r); gr.addColorStop(0, "rgba(255,110,40,.95)"); gr.addColorStop(1, "rgba(255,70,20,0)"); g.fillStyle = gr; g.beginPath(); g.arc(x, y, r, 0, 7); g.fill(); g.fillStyle = "#ff7a3a"; g.beginPath(); g.arc(x, y, 2.6, 0, 7); g.fill(); };
  if (kq === "bung_chay") {
    if (eh < .05) ember(); else { const s = .8 + clamp((eh - .05) / .8) * .9, r = 14 + clamp((eh - .05) / .8) * 34, gr = g.createRadialGradient(x, y, 2, x, y, r); gr.addColorStop(0, "rgba(255,255,210,1)"); gr.addColorStop(.4, "rgba(255,190,60,.9)"); gr.addColorStop(1, "rgba(255,120,0,0)"); g.fillStyle = gr; g.beginPath(); g.arc(x, y, r, 0, 7); g.fill(); flameAt(x, y, s, t, false); }
  } else if (kq === "no_nho") {
    if (eh < .12) flameAt(x, y, .7, t, false);
    else { const pp = clamp((eh - .12) / .45);
      if (pp < 1) { g.strokeStyle = `rgba(255,230,120,${1 - pp})`; g.lineWidth = 4; g.beginPath(); g.arc(x, y - 10, pp * 56, 0, 7); g.stroke(); g.fillStyle = `rgba(255,243,190,${1 - pp * .6})`; g.font = `bold 22px ${FONT}`; g.textAlign = "center"; g.fillText("póp!", x, y - 14 - pp * 56); }
      flameAt(x, y, .7, t, true); }
  } else { if (eh < .1) flameAt(x, y, .7, t, false); else { const k2 = clamp((eh - .1) / .5); g.globalAlpha = S.a * (1 - k2); flameAt(x, y, .7 * (1 - k2 * .7), t, false); g.globalAlpha = S.a; if (k2 > .1) { g.fillStyle = "rgba(200,205,220,.5)"; for (let i = 0; i < 4; i++) { g.beginPath(); g.arc(x + Math.sin(t * 3 + i) * 5, y - 12 - ((t * 24 + i * 11) % 36), 2.5 + i * .6, 0, 7); g.fill(); } } ember(); } }
  g.restore();
}
let an = null, anBuf = null;
function updMouth(now) {   // miệng cử động theo biên độ giọng đọc (giọng AI), hoặc nhịp giả khi trình duyệt tự đọc
  if (!playing || !narrOn) { mouthOpen = 0; return; }
  let mt = 0;
  if (narrSrc && an) { an.getByteTimeDomainData(anBuf); let s = 0; for (let i = 0; i < anBuf.length; i++) { const v = (anBuf[i] - 128) / 128; s += v * v; } mt = clamp(Math.sqrt(s / anBuf.length) * 6.5); }
  else if (pending > 0) mt = .25 + .55 * Math.abs(Math.sin(now / 105 + Math.sin(now / 410) * 2));
  mouthOpen += (mt - mouthOpen) * (mt > mouthOpen ? .6 : .35); if (mouthOpen < .03) mouthOpen = 0;
}
let curT = 0;
function render(t, ta) {
  ta = ta === undefined ? t : ta; curT = t; const st = stateAt(t); drawBench();
  POSE = TEACH_ON ? teacherPose(t, ta) : null; if (POSE) drawTeacherBack(POSE, ta);
  if (lampV >= 0) { const v = VS[lampV]; drawStand(v); drawLamp(v.x, st.lamp, ta, st.capOn); }
  VS.forEach((v, i) => { drawGlass(v, st.vs[i], ta); });
  drawGasKit(st, ta); drawSplint(st, ta);
  VS.forEach((v, i) => drawFx(v, st.vs[i], ta));
  VS.forEach((v, i) => { g.textAlign = "center"; g.fillStyle = "#3b2a14"; g.font = `bold 13px ${FONT}`; g.fillText(v.nhan || v.id, v.x, 416);
    const its = st.vs[i].items.slice(0, 2).join(" + ");
    if (its && !(POSE && POSE.busyV === i)) { const s = sub(its).slice(0, 38), yy = v.base - v.geo.h - (i === lampV ? 6 : 10) - (!POSE && st.vs[i].fx.length ? 76 : 0); g.font = `12.5px ${FONT}`;
      if (POSE) { const w = g.measureText(s).width + 16; g.fillStyle = "rgba(8,12,40,.72)"; rrect(v.x - w / 2, yy - 14, w, 21, 8); g.fill(); }
      g.fillStyle = "rgba(255,255,255,.95)"; g.fillText(s, v.x, yy); } });
  if (POSE) drawTeacherFront(POSE, ta);
  if (st.lamp) { g.fillStyle = "rgba(255,200,120,.95)"; g.font = `bold 13px ${FONT}`; g.textAlign = "left"; g.fillText("🔥 Đang đun nóng", 18, 66); }
  drawHud(t); if (steps[curStep(t)].end) drawEnd(t);
}

// ---------- điều khiển, âm thanh, giọng đọc ----------
let playing = false, last = 0, speed = 1, recording = null, AMB = 0;
let AC = null, master = null, sfxBus = null, narBus = null, rdest = null, noiseBuf = null, flame = null, sfxOn = true, narrOn = true;
const bufs = {};
function initAudio() {
  if (AC) { if (AC.state === "suspended") AC.resume(); return; }
  try {
    AC = new (window.AudioContext || window.webkitAudioContext)();
    master = AC.createGain(); master.gain.value = .95; master.connect(AC.destination);
    try { rdest = AC.createMediaStreamDestination(); master.connect(rdest); } catch (e) { rdest = null; }
    sfxBus = AC.createGain(); sfxBus.gain.value = steps.some(s => s.am) ? .45 : 1; sfxBus.connect(master);   // hiệu ứng nhỏ lại khi có giọng đọc
    narBus = AC.createGain(); narBus.gain.value = 1; narBus.connect(master);
    try { an = AC.createAnalyser(); an.fftSize = 512; anBuf = new Uint8Array(an.fftSize); narBus.connect(an); } catch (e) { an = null; }
    noiseBuf = AC.createBuffer(1, AC.sampleRate * 2, AC.sampleRate); const d = noiseBuf.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    const src = AC.createBufferSource(); src.buffer = noiseBuf; src.loop = true;
    const lp = AC.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 520; flame = AC.createGain(); flame.gain.value = 0;
    src.connect(lp); lp.connect(flame); flame.connect(sfxBus); src.start();
    steps.forEach((s, i) => { if (s.am) fetch(s.am).then(r => r.arrayBuffer()).then(ab => new Promise((ok, no) => AC.decodeAudioData(ab, ok, no))).then(b => { bufs[i] = b; if (playing && curStep(curT) === i) playNarr(i); }).catch(() => { }); });
  } catch (e) { AC = null; }
}
function blip(f0, f1, dur, vol) {
  if (!AC || !sfxOn) return; const o = AC.createOscillator(), gn = AC.createGain(), t = AC.currentTime;
  o.type = "sine"; o.frequency.setValueAtTime(f0, t); o.frequency.exponentialRampToValueAtTime(Math.max(30, f1), t + dur);
  gn.gain.setValueAtTime(Math.min(1, vol * 4), t); gn.gain.exponentialRampToValueAtTime(.0001, t + dur); o.connect(gn); gn.connect(sfxBus); o.start(t); o.stop(t + dur + .02);
}
function burst(dur, vol, type, freq) {
  if (!AC || !sfxOn) return; const s = AC.createBufferSource(), f = AC.createBiquadFilter(), gn = AC.createGain(), t = AC.currentTime;
  s.buffer = noiseBuf; f.type = type; f.frequency.value = freq; gn.gain.setValueAtTime(Math.min(1, vol * 4), t); gn.gain.exponentialRampToValueAtTime(.0001, t + dur);
  s.connect(f); f.connect(gn); gn.connect(sfxBus); s.start(t, Math.random()); s.stop(t + dur + .02);
}
const fired = new Set(); const acc = { b: 0, d: 0, g: 0 }; let prevStep = -1;
function audioTick(t, st, rdt) {
  if (!AC) return;
  if (flame) flame.gain.setTargetAtTime(sfxOn && st.lamp ? .16 : 0, AC.currentTime, .15);
  if (!sfxOn) return;
  let rate = 0; st.vs.forEach(v => { rate = Math.max(rate, v.rate); });
  acc.b += rdt * rate * 12; while (acc.b >= 1) { acc.b -= 1; const f = 280 + Math.random() * 520; blip(f, f * 1.9, .06 + Math.random() * .04, .035 + Math.random() * .03); }
  if (st.gasOn) { acc.g += rdt * 7; while (acc.g >= 1) { acc.g -= 1; const f = 420 + Math.random() * 360; blip(f, f * 1.7, .05, .03); } }
  let drip = false; st.vs.forEach(v => v.fx.forEach(f => { if (f.t === "long") drip = true; }));
  if (drip) { acc.d += rdt * 4.5; while (acc.d >= 1) { acc.d -= 1; blip(1000 + Math.random() * 500, 520, .08, .05); } }
  st.vs.forEach(v => v.fx.forEach(f => {
    if (f.t === "ran" && f.p > .5 && !fired.has("r" + f.id)) { fired.add("r" + f.id); burst(.14, .16, "lowpass", 260); blip(190, 90, .12, .12); }
    if (f.t === "tua" && f.p > .02 && !fired.has("k" + f.id)) { fired.add("k" + f.id); burst(.7, .035, "bandpass", 2200); }
  }));
  if (st.splint) { const s = st.splint;
    if (s.kq === "bung_chay" && (TEACH_ON ? s.eh > .06 : s.p > .5) && !fired.has("q" + s.id)) { fired.add("q" + s.id); burst(.6, .12, "bandpass", 1400); }
    if (s.kq === "no_nho" && (TEACH_ON ? s.eh > .14 : s.p > .78) && !fired.has("q" + s.id)) { fired.add("q" + s.id); burst(.09, .4, "lowpass", 1800); blip(220, 80, .1, .25); } }
  const si = curStep(t); if (si !== prevStep) { if (prevStep >= 0 && si > prevStep) { blip(660, 990, .22, .05); if (steps[si].end) setTimeout(() => blip(990, 1320, .3, .05), 180); } prevStep = si; }
}
// --- giọng đọc: ưu tiên tệp giọng AI đã thu sẵn; nếu không có thì dùng giọng của trình duyệt ---
let narrSrc = null, spokenStep = -1, pending = 0, holdFor = 0;
function stopNarr() { if (narrSrc) { try { narrSrc.onended = null; narrSrc.stop(); } catch (e) { } narrSrc = null; } stopSpeech(); }
function playNarr(si, offMovie = 0) {
  stopNarr(); if (!narrOn) return; const s = steps[si];
  if (AC && bufs[si]) {
    const src = AC.createBufferSource(); src.buffer = bufs[si]; src.playbackRate.value = clamp(s.k * speed, .5, 3); src.connect(narBus);
    const start = Math.max(0, offMovie - .25) * s.k;
    if (start < bufs[si].duration - .05) { src.start(0, start); narrSrc = src; }
    return;
  }
  if (s.am && !bufs[si]) return;   // đang giải mã, sẽ tự phát khi xong
  speak(s.end ? endText : s.mo_ta);
}
const HAS_TTS = "speechSynthesis" in window; let viVoice = null; const vsel = document.getElementById("vsel");
function pickVoice() {
  if (!HAS_TTS) return; const vi = speechSynthesis.getVoices().filter(v => /^vi([-_]|$)/i.test(v.lang));
  const score = v => (/natural|neural|online/i.test(v.name) ? 3 : 0) + (/google/i.test(v.name) ? 2 : 0) + (v.localService ? 0 : 1);
  vi.sort((a, b) => score(b) - score(a)); viVoice = vi[0] || null;
  if (vsel) { vsel.innerHTML = vi.map((v, i) => `<option value="${i}">${v.name.replace(/Microsoft |Google /, "")}</option>`).join(""); vsel.style.display = vi.length > 1 ? "" : "none"; vsel.onchange = () => { viVoice = vi[+vsel.value]; }; }
}
if (HAS_TTS) { pickVoice(); speechSynthesis.onvoiceschanged = pickVoice; }
const SAY = [["H2SO4", "a xít sun phu ríc"], ["HCl", "a xít clo hi đríc"], ["Cu(OH)2", "đồng hai hi đrô xít"], ["NaOH", "na tri hi đrô xít"], ["CuSO4", "đồng hai sun phát"], ["FeSO4", "sắt hai sun phát"],
  ["Na2SO4", "na tri sun phát"], ["Na2CO3", "na tri các bô nát"], ["AgNO3", "bạc ni trát"], ["AgCl", "bạc clo rua"], ["NaCl", "na tri clo rua"], ["NaNO3", "na tri ni trát"], ["KMnO4", "ka li pê man ga nát"],
  ["K2MnO4", "ka li măng ga nát"], ["MnO2", "man gan đi ô xít"], ["ZnCl2", "kẽm clo rua"], ["CO2", "khí các bô níc"], ["H2O", "nước"], ["H2", "khí hi đrô"], ["O2", "khí ô xi"], ["Zn", "kẽm"], ["Fe", "sắt"], ["Cu", "đồng"]];
function spoken(text) { let s = String(text || ""); SAY.forEach(([k, v]) => { s = s.split(k).join(v); }); return s.replace(/->|→/g, " tạo thành ").replace(/[↑↓]/g, "").replace(/°C/g, " độ xê").replace(/\bmL\b/g, "mi li lít").replace(/\s+/g, " ").trim(); }
function chunks(s) { const parts = s.split(/(?<=[.!?])\s+/), out = []; let cur = ""; parts.forEach(p => { if ((cur + " " + p).length > 230 && cur) { out.push(cur); cur = p; } else cur = cur ? cur + " " + p : p; }); if (cur) out.push(cur); return out; }
function stopSpeech() { if (HAS_TTS) { try { speechSynthesis.cancel(); } catch (e) { } } pending = 0; }
function speak(text) {
  if (!HAS_TTS || !narrOn) return; stopSpeech();
  chunks(spoken(text)).forEach(p => { const u = new SpeechSynthesisUtterance(p); u.lang = "vi-VN"; if (viVoice) u.voice = viVoice; u.rate = clamp(speed * .95, .6, 2); u.pitch = 1;
    pending++; u.onend = u.onerror = () => { pending = Math.max(0, pending - 1); }; try { speechSynthesis.speak(u); } catch (e) { pending = Math.max(0, pending - 1); } });
}
// --- bộ điều khiển phát ---
const sl = document.getElementById("sl"), tm = document.getElementById("tm"), bPlay = document.getElementById("bPlay"), stl = document.getElementById("st"), spR = document.getElementById("sp"), spL = document.getElementById("spl");
const fmt = (s) => Math.floor(s / 60) + ":" + String(Math.floor(s % 60)).padStart(2, "0");
function setT(t) { curT = clamp(t, 0, TOTAL); render(curT, AMB); sl.value = Math.round(curT / TOTAL * 1000); tm.textContent = fmt(curT) + " / " + fmt(TOTAL); }
function seekTo(t) { fired.clear(); stopNarr(); spokenStep = -1; prevStep = -1; holdFor = 0; AMB = clamp(t, 0, TOTAL); setT(t); if (playing) { spokenStep = curStep(curT); playNarr(spokenStep, curT - steps[spokenStep].t0); } }
function tick(now) {
  const rdt = Math.min(.1, (now - last) / 1000); last = now;
  if (playing) {
    AMB += rdt * speed; let t = curT + rdt * speed; const si0 = curStep(curT);
    // chưa có tệp giọng AI mà trình duyệt vẫn đang đọc: giữ phim ở cuối bước tối đa 6 giây để không cắt giữa câu
    if (t >= steps[si0].t1 && !steps[si0].am && narrOn && pending > 0 && holdFor < 6) { t = steps[si0].t1 - .001; holdFor += rdt; }
    if (t >= TOTAL) { t = TOTAL; playing = false; bPlay.textContent = "↻ Xem lại"; if (recording) finishRec(); }
    updMouth(now); setT(t); const si = curStep(t);
    if (si !== spokenStep && playing) { spokenStep = si; holdFor = 0; playNarr(si, 0); }
    audioTick(t, stateAt(t), rdt);
  }
  requestAnimationFrame(tick);
}
function pauseUI() { playing = false; bPlay.textContent = "▶ Phát"; stopNarr(); spokenStep = -1; mouthOpen = 0; setT(curT); }
bPlay.onclick = () => { initAudio(); if (!playing) { if (curT >= TOTAL - .05) seekTo(0); playing = true; spokenStep = -1; last = performance.now(); bPlay.textContent = "⏸ Dừng"; } else pauseUI(); };
document.getElementById("bR").onclick = () => { pauseUI(); seekTo(0); };
document.getElementById("bN").onclick = () => { const i = curStep(curT); seekTo(steps[Math.min(i + 1, steps.length - 1)].t0 + .01); };
document.getElementById("bP").onclick = () => { const i = curStep(curT); seekTo((curT - steps[i].t0 > 1.5 ? steps[i].t0 : steps[Math.max(i - 1, 0)].t0) + .01); };
sl.oninput = () => { seekTo(sl.value / 1000 * TOTAL); };
spR.oninput = () => { speed = +spR.value; spL.textContent = speed.toFixed(2).replace(".", ",") + "×"; if (playing) { const si = curStep(curT); playNarr(si, curT - steps[si].t0); } };
const bVoice = document.getElementById("bVoice"), bSfx = document.getElementById("bSfx");
bVoice.onclick = () => { narrOn = !narrOn; bVoice.textContent = "🗣️ Giọng đọc: " + (narrOn ? "Bật" : "Tắt"); bVoice.classList.toggle("off", !narrOn); if (!narrOn) stopNarr(); else if (playing) { const si = curStep(curT); playNarr(si, curT - steps[si].t0); } };
const bTeach = document.getElementById("bTeach");
bTeach.onclick = () => { TEACH_ON = !TEACH_ON; bTeach.textContent = "👩‍🏫 Cô giáo: " + (TEACH_ON ? "Bật" : "Tắt"); bTeach.classList.toggle("off", !TEACH_ON); setT(curT); };
bSfx.onclick = () => { sfxOn = !sfxOn; bSfx.textContent = "🔊 Âm thanh: " + (sfxOn ? "Bật" : "Tắt"); bSfx.classList.toggle("off", !sfxOn); initAudio(); };
setTimeout(() => { if (!steps.some(s => s.am) && HAS_TTS && !viVoice && !stl.textContent) stl.textContent = "Máy này chưa có giọng đọc tiếng Việt nên chưa nghe được lời đọc (hiệu ứng âm thanh vẫn có). Hãy cài giọng Tiếng Việt trong phần Giọng nói của hệ điều hành."; }, 2500);
document.getElementById("bHtml").onclick = () => { const b = new Blob(["<!DOCTYPE html>" + document.documentElement.outerHTML], { type: "text/html" }); const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = "mo_phong_thi_nghiem.html"; a.click(); };
function finishRec() { try { recording.rec.stop(); } catch (e) { } }
document.getElementById("bRec").onclick = () => {
  if (recording) return;
  if (!window.MediaRecorder || !cv.captureStream) { stl.textContent = "Trình duyệt này chưa hỗ trợ ghi video. Hãy dùng Chrome hoặc Edge, hoặc bấm “Tải .html” để lưu bản mô phỏng."; return; }
  try {
    initAudio();
    const vt = cv.captureStream(30).getVideoTracks(), at = (AC && rdest) ? rdest.stream.getAudioTracks() : [];
    const MP4 = ["video/mp4;codecs=avc1.42E01E,mp4a.40.2", "video/mp4;codecs=avc1,mp4a.40.2", "video/mp4;codecs=avc1.42E01E,opus", "video/mp4;codecs=avc1", "video/mp4;codecs=vp9,opus", "video/mp4"];
    const WEBM = at.length ? ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"] : ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"];
    let mt = MP4.find(m => MediaRecorder.isTypeSupported(m)) || "", warn = "";
    if (!mt) { mt = WEBM.find(m => MediaRecorder.isTypeSupported(m)) || ""; warn = "Trình duyệt này chưa ghi được .mp4 nên sẽ tải ra .webm. Hãy dùng Chrome hoặc Edge bản mới (từ 126) để tải .mp4. "; }
    const rec = new MediaRecorder(new MediaStream(vt.concat(at)), mt ? { mimeType: mt, videoBitsPerSecond: 4000000 } : {}), chunks = [];
    rec.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.onstop = () => { const blob = new Blob(chunks, { type: rec.mimeType || "video/webm" }); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "mo_phong_thi_nghiem." + ((rec.mimeType || "").includes("mp4") ? "mp4" : "webm"); a.click(); recording = null; stl.textContent = steps.some(s => s.am) ? "Đã lưu video (có giọng đọc và hiệu ứng âm thanh)." : "Đã lưu video (có hiệu ứng âm thanh; giọng đọc của trình duyệt không thu được vào video)."; document.getElementById("bRec").textContent = "🎬 Tải video (.mp4)"; };
    recording = { rec }; stl.textContent = warn + "Đang ghi video, vui lòng đợi đến hết phim…"; document.getElementById("bRec").textContent = "⏺ Đang ghi…";
    speed = 1; spR.value = 1; spL.textContent = "1,00×"; seekTo(0); rec.start(); playing = true; spokenStep = -1; last = performance.now(); bPlay.textContent = "⏸ Dừng";
  } catch (e) { stl.textContent = "Không ghi được video: " + e.message; recording = null; }
};
window.__seek = seekTo; window.__total = TOTAL; window.__steps = steps;
setT(0); requestAnimationFrame(tick);
</script></body></html>
'''

SIM_EXAMPLES = ["Kẽm + dung dịch HCl", "CuSO4 + NaOH", "AgNO3 + NaCl", "Nhiệt phân KMnO4 thu khí oxi", "Sắt + dung dịch CuSO4", "Trung hòa NaOH bằng HCl (phenolphtalein)"]
SIM_PROMPT = """Bạn là giáo viên Hóa học trung học phổ thông ở Việt Nam. Hãy lập KỊCH BẢN MÔ PHỎNG THÍ NGHIỆM cho yêu cầu: "__Q__".
Kịch bản này sẽ được máy dựng thành phim hoạt hình nên phải rõ ràng, cụ thể, đúng hiện tượng thật.
Chỉ trả về MỘT đối tượng JSON, không markdown:
{"ten":"tên thí nghiệm bằng tiếng Việt",
 "dung_cu":[{"id":"A","loai":"ong_nghiem | coc | binh_tam_giac","nhan":"tên dụng cụ ngắn"}],
 "thu_khi":null hoặc {"tu":"id dụng cụ sinh khí","khi":"công thức khí, ví dụ H2","mau":"#rrggbb"},
 "buoc":[{"tieu_de":"ngắn","mo_ta":"2 câu: thao tác cụ thể (lượng hóa chất, cách làm) và hiện tượng quan sát được","thoi_gian":6,
   "hanh_dong":[ ... ]}],
 "hien_tuong":["các hiện tượng quan sát được, mỗi ý một câu ngắn"],
 "phuong_trinh":"phương trình phản ứng, viết chỉ số dạng số thường, ví dụ Zn + 2HCl -> ZnCl2 + H2↑",
 "chat_tham_gia":[{"he_so":1,"cong_thuc":"Zn","smiles":"[Zn]"}],
 "san_pham":[{"he_so":1,"cong_thuc":"ZnCl2","smiles":"Cl[Zn]Cl"}],
 "giai_thich":"1-2 câu giải thích bản chất",
 "an_toan":["lưu ý an toàn cụ thể"]}
Các hành động hợp lệ trong "hanh_dong" (mỗi hành động là một đối tượng có "loai"):
- them_long: {"loai":"them_long","dung_cu":"A","chat":"tên chất","mau":"#rrggbb màu dung dịch thêm vào","muc":0.05-0.8 (lượng tương đối)}
- them_ran: {"loai":"them_ran","dung_cu":"A","chat":"tên chất","mau":"#rrggbb","kieu":"vien | bot | dinh | mieng"}
- doi_mau: dung dịch đổi sang màu mới {"loai":"doi_mau","dung_cu":"A","mau":"#rrggbb","thoi_gian":3}
- doi_mau_ran: chất rắn đổi màu {"loai":"doi_mau_ran","dung_cu":"A","mau":"#rrggbb","thoi_gian":4}
- ket_tua: xuất hiện kết tủa {"loai":"ket_tua","dung_cu":"A","chat":"công thức","mau":"#rrggbb","luong":0.3-1}
- sui_bot: bọt khí trong dung dịch {"loai":"sui_bot","dung_cu":"A","cuong_do":0-1} (0 là dừng)
- tan: chất rắn nhỏ dần {"loai":"tan","dung_cu":"A","con_lai":0-1,"thoi_gian":6}
- dun_nong: bật hoặc tắt đèn cồn {"loai":"dun_nong","bat":true,"dung_cu":"A"}
- thu_khi: thu khí vào ống thu khí úp trong chậu nước (chỉ khi có "thu_khi") {"loai":"thu_khi","luong":0.3-0.9,"thoi_gian":5}
- que_dom: thử khí bằng que đóm {"loai":"que_dom","ket_qua":"bung_chay | no_nho | tat"}
Có thể thêm "dong_thoi":true để một hành động chạy cùng lúc với hành động trước.
Quy tắc:
- Dùng tối đa 3 dụng cụ, 3-7 bước, mỗi bước 4-8 giây. Mô tả đúng thứ tự thao tác thật trong phòng thí nghiệm.
- Màu sắc theo hiện tượng thật: Cu2+ xanh lam #2f7be0; Fe2+ xanh lục nhạt #bfe6cf; Fe3+ vàng nâu #c98a2b; dung dịch KMnO4 tím #7b1fa2; I2 nâu #8b4513; Cu(OH)2 xanh lam #4f93f2; Fe(OH)3 nâu đỏ #a0522d; kết tủa trắng (AgCl, BaSO4, CaCO3) #fbfbf7; dung dịch không màu #f3f7ff; phenolphtalein trong bazơ hồng #f07db8; quỳ tím: axit đỏ #e0463a, bazơ xanh #3b6cf6.
- Phương trình phải cân bằng; "smiles" của chất vô cơ ion viết dạng như [Na+].[Cl-], khí như [H][H], O=O. Không chắc thì bỏ trống smiles.
- Chỉ mô phỏng thí nghiệm có trong chương trình hoặc an toàn, quen thuộc. Nếu yêu cầu nguy hiểm (gây nổ, chất độc, ma túy, vũ khí) hoặc không phải thí nghiệm hóa học, trả {"tu_choi":"lý do ngắn bằng tiếng Việt"}.
- Mọi chất người dùng nêu trong yêu cầu đều phải xuất hiện trong kịch bản, mỗi chất bằng một hành động them_long hoặc them_ran đúng thứ tự thao tác thật, không được bỏ chất nào. Nếu chất đó là dung dịch không màu (ví dụ dung dịch peptit, protein) thì thêm bằng them_long với màu #f3f7ff.\n- Phản ứng màu biure (dung dịch peptit từ 3 gốc amino axit trở lên hoặc protein + NaOH + vài giọt CuSO4) cho dung dịch màu tím #7e3fb0.\n- Không bịa hiện tượng. Nếu thí nghiệm cần điều kiện đặc biệt, nêu rõ trong mo_ta."""

SIM_BLOCK = {"them_long": 2.6, "them_ran": 1.8, "dun_nong": 2.6, "doi_mau": 3, "doi_mau_ran": 3, "ket_tua": 2.8, "tan": 3, "thu_khi": 4, "que_dom": 3.2}
SIM_SAY = [("H2SO4", "a xít sun phu ríc"), ("HCl", "a xít clo hi đríc"), ("Cu(OH)2", "đồng hai hi đrô xít"), ("NaOH", "na tri hi đrô xít"), ("CuSO4", "đồng hai sun phát"), ("FeSO4", "sắt hai sun phát"),
           ("Na2SO4", "na tri sun phát"), ("Na2CO3", "na tri các bô nát"), ("AgNO3", "bạc ni trát"), ("AgCl", "bạc clo rua"), ("NaCl", "na tri clo rua"), ("NaNO3", "na tri ni trát"), ("KMnO4", "ka li pê man ga nát"),
           ("K2MnO4", "ka li măng ga nát"), ("MnO2", "man gan đi ô xít"), ("ZnCl2", "kẽm clo rua"), ("CO2", "khí các bô níc"), ("H2O", "nước"), ("H2", "khí hi đrô"), ("O2", "khí ô xi"), ("Zn", "kẽm"), ("Fe", "sắt"), ("Cu", "đồng")]


def sim_spoken(text):
    s = str(text or "")
    for k, v in SIM_SAY:
        s = s.replace(k, v)
    return re.sub(r"\s+", " ", s.replace("->", " tạo thành ").replace("→", " tạo thành ").replace("↑", "").replace("↓", "").replace("°C", " độ xê").replace("mL", "mi li lít")).strip()


@st.cache_data(show_spinner=False, max_entries=80)
def _tts_wav(text, model, voice):
    """Thu giọng đọc bằng Gemini TTS: trả về (tệp WAV dạng data URI, thời lượng giây).
    Model 3.8 coi toàn bộ chữ gửi vào là lời cần đọc (câu dặn giọng sẽ bị đọc to) nên chỉ gửi lời đọc, và trả về WAV có sẵn tiêu đề.
    Model 2.5 cần câu dặn giọng và trả về PCM thô."""
    import wave
    is38 = "3.8" in model
    resp = get_client().models.generate_content(
        model=model, contents=text if is38 else "Hãy đọc to bằng giọng nữ giáo viên Việt Nam, ấm áp, tự nhiên, tốc độ vừa phải, ngắt nghỉ đúng dấu câu: " + text,
        config=types.GenerateContentConfig(response_modalities=["AUDIO"], speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)))))
    data = resp.candidates[0].content.parts[0].inline_data.data
    if data[:4] == b"RIFF":
        try:
            with wave.open(io.BytesIO(data), "rb") as w:
                dur = w.getnframes() / float(w.getframerate())
        except Exception:   # tiêu đề WAV lạ (kích thước ghi 0 hoặc thiếu): tự tính từ byte
            import struct
            ch, sr = struct.unpack_from("<HI", data, 22); bits = struct.unpack_from("<H", data, 34)[0]
            dur = max(0, len(data) - 44) / float(sr * ch * bits / 8)
        return "data:audio/wav;base64," + base64.b64encode(data).decode(), dur
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(data)
    return "data:audio/wav;base64," + base64.b64encode(buf.getvalue()).decode(), len(data) / 2 / 24000


def _quota_hint():
    k = st.session_state.get("tts_err", "")
    if k.endswith("day"):
        return "Đây là hạn mức theo NGÀY nên chờ vài phút không hết: dùng lại vào ngày mới, hoặc bật thanh toán / đổi sang khóa API của dự án khác trong Google AI Studio."
    if k.endswith("min"):
        return "Đây là giới hạn theo phút: đợi khoảng 1 đến 2 phút rồi bấm Tạo mô phỏng lại, đoạn đã thu sẽ không tốn lại."
    return "Chưa rõ là hạn mức phút hay ngày. Nếu đợi vài phút vẫn lỗi thì nhiều khả năng là hạn mức ngày: dùng lại vào ngày mới, hoặc bật thanh toán / đổi khóa API khác."


def _tts_retry(text, model, voice, t0):
    """Gọi _tts_wav; gặp 429 (quá giới hạn lượt gọi theo phút) thì đợi theo gợi ý của Gemini rồi thử lại một lần.
    Đoạn đã thu thành công được lưu cache nên lần tạo lại sau không tốn thêm lượt."""
    import time, re as _re
    try:
        return _tts_wav(text, model, voice)
    except Exception as e:
        msg = str(e)
        if "429" not in msg and "RESOURCE_EXHAUSTED" not in msg:
            raise
        m = _re.search(r"retry(?: in|Delay\W+)\s*([\d.]+)\s*s", msg, _re.I)
        wait_s = float(m.group(1)) + 1 if m else 0
        if 0 < wait_s <= 35 and time.time() - t0 + wait_s < 170:
            time.sleep(wait_s)
            return _tts_wav(text, model, voice)
        raise


def sim_attach_audio(sc):
    """Thu giọng đọc cho từng bước và màn kết luận (tuần tự như bản đầu). Bước nào lỗi thì trình duyệt đọc thay.
    Trả về (kịch bản, số đoạn thu được). Lỗi cuối cùng được ghi vào st.session_state.tts_err."""
    import time
    cfg, voice = st.secrets.get("GEMINI_TTS_MODEL", ""), st.secrets.get("GEMINI_TTS_VOICE", "Kore")
    models = [cfg] if cfg else ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts", "gemini-2.5-flash-preview-tts"]   # mỗi model có hạn mức riêng; dùng model đầu tiên chạy được cho cả phim
    chosen, last_q = None, False
    out, ok, t0, quota = {**sc, "buoc": [dict(s) for s in sc["buoc"]]}, 0, time.time(), False
    st.session_state.tts_err = ""
    items = [(s, "am", sim_spoken(s["mo_ta"])) for s in out["buoc"] if s.get("mo_ta")]
    for s in out["buoc"]:
        s.pop("am", None); s.pop("am_dur", None)
    out.pop("am_ket", None); out.pop("am_ket_dur", None)
    items.append((out, "am_ket", sim_spoken("Kết luận. " + ". ".join(sc.get("hien_tuong", [])[:5]) + ". " + sc.get("giai_thich", ""))))
    for tgt, key, text in items:
        if quota or time.time() - t0 > 170:
            continue
        got = False
        for m in ([chosen] if chosen else models):
            try:
                tgt[key], tgt[key + "_dur"] = _tts_retry(text, m, voice, t0); ok += 1; chosen = m; got = True
                break
            except Exception as e:
                full = str(e); st.session_state.tts_err = f"{type(e).__name__}: {full}"[:300]
                if "429" in full or "RESOURCE_EXHAUSTED" in full:
                    last_q = "day" if "PerDay" in full else "min" if "PerMinute" in full else "?"
                    if chosen:
                        quota = last_q
        if not got and not chosen:
            quota = last_q   # thử hết các model đều lỗi: nếu do hạn mức thì báo hạn mức, còn lỗi khác thì hiện lỗi thật
            break
    if quota:
        st.session_state.tts_err = "QUOTA:" + quota
    return out, ok


def sim_auto_dur(s):
    """Thời lượng tự động của một bước, giống cách bộ dựng tính (hành động, lời đọc)."""
    tt, last = .35, .35
    for a in s.get("hanh_dong", []):
        d = max(.4, float(a.get("thoi_gian") or SIM_BLOCK.get(a["loai"], .5)))
        off = last if a.get("dong_thoi") else tt
        last = off
        if a["loai"] in SIM_BLOCK and not a.get("dong_thoi"):
            tt = off + d + .15
        elif a["loai"] not in SIM_BLOCK:
            tt = max(tt, off + .4)
    speech = s["am_dur"] + .6 if s.get("am_dur") else len(s.get("mo_ta", "")) / 15 + 1
    return round(max(float(s.get("thoi_gian") or 4), tt + .9, speech) * 2) / 2

_HEXC = re.compile(r"^#[0-9a-fA-F]{6}$")
_SIM_TYPES = {"them_long", "them_ran", "doi_mau", "doi_mau_ran", "ket_tua", "sui_bot", "tan", "dun_nong", "thu_khi", "que_dom"}


def _sim_col(c, default):
    c = str(c or "").strip()
    return c.lower() if _HEXC.match(c) else default


def _sim_num(v, lo, hi, default):
    try:
        return max(lo, min(hi, float(v)))
    except Exception:
        return default


def _sim_species(lst):
    out = []
    for s in (lst or [])[:10]:
        if isinstance(s, dict) and (s.get("cong_thuc") or s.get("smiles")):
            out.append({"he_so": to_int(s.get("he_so")), "cong_thuc": str(s.get("cong_thuc") or "")[:30], "smiles": str(s.get("smiles") or "")[:80]})
    return out


def sim_clean(raw):
    """Chuẩn hóa kịch bản do AI soạn: loại giá trị lạ, giới hạn số lượng, bảo đảm máy dựng được. Trả về (kịch bản, lỗi)."""
    if not isinstance(raw, dict):
        return None, "Chưa lập được kịch bản, hãy mô tả thí nghiệm rõ hơn."
    if raw.get("tu_choi"):
        return None, "Không mô phỏng thí nghiệm này: " + str(raw["tu_choi"])[:200]
    names = {"ong_nghiem": "Ống nghiệm", "coc": "Cốc thủy tinh", "binh_tam_giac": "Bình tam giác"}
    vessels = []
    for v in (raw.get("dung_cu") or [])[:3]:
        if isinstance(v, dict):
            loai = v.get("loai") if v.get("loai") in names else "ong_nghiem"
            vid = re.sub(r"\W", "", str(v.get("id") or chr(65 + len(vessels))))[:3] or chr(65 + len(vessels))
            if vid in [x["id"] for x in vessels]:
                vid = chr(65 + len(vessels))
            vessels.append({"id": vid, "loai": loai, "nhan": str(v.get("nhan") or names[loai])[:24]})
    if not vessels:
        vessels = [{"id": "A", "loai": "ong_nghiem", "nhan": "Ống nghiệm"}]
    ids = [v["id"] for v in vessels]
    kit = raw.get("thu_khi") if isinstance(raw.get("thu_khi"), dict) else None
    if kit and kit.get("tu") not in ids:
        kit = {**kit, "tu": ids[0]}
    steps, nact = [], 0
    for s in (raw.get("buoc") or [])[:8]:
        if not isinstance(s, dict):
            continue
        acts = []
        for a in (s.get("hanh_dong") or [])[:6]:
            if not isinstance(a, dict) or a.get("loai") not in _SIM_TYPES:
                continue
            t = a["loai"]
            e = {"loai": t, "dung_cu": a.get("dung_cu") if a.get("dung_cu") in ids else ids[0], "chat": str(a.get("chat") or "")[:30], "dong_thoi": bool(a.get("dong_thoi"))}
            if a.get("thoi_gian") is not None:
                e["thoi_gian"] = _sim_num(a.get("thoi_gian"), .5, 10, 3)
            if t == "them_long":
                e.update(mau=_sim_col(a.get("mau"), "#f3f7ff"), muc=_sim_num(a.get("muc"), .05, .8, .3))
            elif t == "them_ran":
                e.update(mau=_sim_col(a.get("mau"), "#9aa4ad"), kieu=a.get("kieu") if a.get("kieu") in ("vien", "bot", "dinh", "mieng") else "vien")
            elif t in ("doi_mau", "doi_mau_ran"):
                e["mau"] = _sim_col(a.get("mau"), "#f3f7ff")
            elif t == "ket_tua":
                e.update(mau=_sim_col(a.get("mau"), "#fbfbf7"), luong=_sim_num(a.get("luong"), .2, 1, .7))
            elif t == "sui_bot":
                e["cuong_do"] = _sim_num(a.get("cuong_do"), 0, 1, .6)
            elif t == "tan":
                e["con_lai"] = _sim_num(a.get("con_lai"), 0, 1, .2)
            elif t == "dun_nong":
                e["bat"] = bool(a.get("bat", True))
            elif t == "thu_khi":
                e["luong"] = _sim_num(a.get("luong"), .2, .95, .7)
                if not kit:
                    kit = {"tu": ids[0], "khi": "Khí", "mau": "#dfe6f2"}
            elif t == "que_dom":
                e["ket_qua"] = a.get("ket_qua") if a.get("ket_qua") in ("bung_chay", "no_nho", "tat") else "bung_chay"
            acts.append(e)
        nact += len(acts)
        steps.append({"tieu_de": str(s.get("tieu_de") or "")[:40], "mo_ta": str(s.get("mo_ta") or "")[:320], "thoi_gian": _sim_num(s.get("thoi_gian"), 3, 10, 5), "hanh_dong": acts})
    if not steps or not nact:
        return None, "Chưa lập được kịch bản có hiện tượng quan sát được, hãy mô tả thí nghiệm cụ thể hơn."
    if not kit:  # que đóm chỉ có nghĩa khi có ống thu khí
        for s in steps:
            s["hanh_dong"] = [a for a in s["hanh_dong"] if a["loai"] != "que_dom"]
    else:
        kit = {"tu": kit.get("tu"), "khi": str(kit.get("khi") or "Khí")[:8], "mau": _sim_col(kit.get("mau"), "#dfe6f2")}
    out = {"ten": str(raw.get("ten") or "Thí nghiệm")[:90], "dung_cu": vessels, "thu_khi": kit, "buoc": steps,
           "hien_tuong": [str(x)[:140] for x in (raw.get("hien_tuong") or [])[:6]], "phuong_trinh": str(raw.get("phuong_trinh") or "")[:140],
           "giai_thich": str(raw.get("giai_thich") or "")[:300], "an_toan": [str(x)[:140] for x in (raw.get("an_toan") or [])[:4]],
           "chat_tham_gia": _sim_species(raw.get("chat_tham_gia")), "san_pham": _sim_species(raw.get("san_pham"))}
    return out, None


def _formula_atoms(f):
    """Đếm nguyên tử trong công thức như Cu(OH)2, Al2(SO4)3. Trả về dict hoặc None nếu không đọc được (ion, ngậm nước...)."""
    f = re.sub(r"\((?:aq|s|l|g|k|r|khí|rắn|lỏng)\)", "", f.replace("↑", "").replace("↓", "").strip(), flags=re.I)
    if not f or not re.fullmatch(r"(?:[A-Z][a-z]?|\d+|[()\[\]])+", f):
        return None
    stack, i = [{}], 0
    while i < len(f):
        c = f[i]
        if c in "([":
            stack.append({}); i += 1
        elif c in ")]":
            if len(stack) < 2:
                return None
            grp = stack.pop(); i += 1
            m = re.match(r"\d+", f[i:]); n = int(m.group()) if m else 1
            i += len(m.group()) if m else 0
            for k, v in grp.items():
                stack[-1][k] = stack[-1].get(k, 0) + v * n
        elif c.isupper():
            m = re.match(r"[A-Z][a-z]?", f[i:]); el = m.group(); i += len(el)
            m = re.match(r"\d+", f[i:]); n = int(m.group()) if m else 1
            i += len(m.group()) if m else 0
            stack[-1][el] = stack[-1].get(el, 0) + n
        else:
            return None
    return stack[0] if len(stack) == 1 else None


def _equation_side(side):
    tot = {}
    for term in re.split(r"\s+\+\s+", side.strip()):
        m = re.match(r"^(\d+)?\s*(.+)$", term.strip())
        if not m:
            return None
        n = int(m.group(1) or 1); at = _formula_atoms(m.group(2))
        if at is None:
            return None
        for k, v in at.items():
            tot[k] = tot.get(k, 0) + v * n
    return tot


def sim_balance(sc):
    """True/False nếu đọc được phương trình ở dạng chữ (công thức thường) và đếm nguyên tử hai vế; None nếu không chắc.
    Không dựa vào SMILES do AI viết vì SMILES của chất vô cơ hay sai, gây cảnh báo nhầm."""
    eq = str(sc.get("phuong_trinh") or "")
    parts = re.split(r"\s*(?:->|-->|→|⟶|=>|=)\s*", eq)
    if len(parts) != 2 or "⇌" in eq:
        return None
    l, r = _equation_side(parts[0]), _equation_side(parts[1])
    return None if l is None or r is None else l == r


def sim_html(sc, custom=None):
    if custom and custom.get("on"):
        sc = {**sc, "buoc": [{**s, "thoi_gian_cung": custom["d"][i]} for i, s in enumerate(sc["buoc"]) if i < len(custom["d"])] + sc["buoc"][len(custom["d"]):], "thoi_gian_ket": custom.get("end")}
    data = {k: v for k, v in sc.items() if k in ("ten", "dung_cu", "thu_khi", "buoc", "hien_tuong", "phuong_trinh", "giai_thich", "am_ket", "am_ket_dur", "thoi_gian_ket")}
    return SIM_TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))


def _sim_set(txt):
    st.session_state.sim_q = txt


def _sim_finish(sc):
    """Lưu kịch bản vào phiên và tự thu giọng đọc AI cho lời dẫn."""
    for k in [k for k in st.session_state if str(k).startswith("sim_d_")]:
        del st.session_state[k]
    st.session_state.pop("voice_note", None)
    st.session_state.sim_custom = None
    if not over_quota():   # giọng AI tự nhiên luôn bật; lỗi hoặc quá hạn thì trình duyệt đọc thay
        with st.spinner("Đang thu giọng đọc tự nhiên…"):
            sc2, ok = sim_attach_audio(sc)
        need = sum(1 for x in sc["buoc"] if x.get("mo_ta")) + 1
        err = st.session_state.get("tts_err", "")
        st.session_state.voice_note = "AI tự nhiên" if ok >= need else "trình duyệt (" + (
            f"Gemini hết hạn mức giọng đọc theo ngày, thu được {ok}/{need} đoạn" if err == "QUOTA:day" else
            f"Gemini giới hạn lượt gọi giọng đọc theo phút, thu được {ok}/{need} đoạn" if err == "QUOTA:min" else
            f"Gemini hết hạn mức giọng đọc, thu được {ok}/{need} đoạn" if err.startswith("QUOTA") else
            f"thu được {ok}/{need} đoạn. Lỗi: {err[:160]}" if err else f"thu được {ok}/{need} đoạn") + ")"
        if ok >= need:   # chỉ dùng giọng AI khi thu đủ mọi đoạn; thiếu đoạn nào thì cả phim dùng giọng trình duyệt cho đồng nhất (đoạn đã thu vẫn được lưu, lần tạo lại sau chỉ gọi nốt phần thiếu)
            sc = sc2
            st.session_state.n += 1
    if over_quota() and "voice_note" not in st.session_state:
        st.session_state.voice_note = "trình duyệt (hết số lượt của phiên này)"
    st.session_state.sim = sc
    add_history(sc["ten"][:60], "Mô phỏng")


def _sim_make(top, q):
    key = sim_match_builtin(q)
    if key:
        _sim_finish({k: v for k, v in SIM_BUILTINS[key].items() if k != "kw"})
        return
    if over_quota():
        show_top_error(top, "Bạn đã dùng hết số lượt của phiên này. Hãy tải lại trang để tiếp tục.")
        return
    with st.spinner("Đang lập kịch bản và dựng phim…"):
        try:
            sc, err = sim_clean(ask_ai([SIM_PROMPT.replace("__Q__", q.replace('"', "'"))], temperature=0.2, lang_note=False))
            st.session_state.n += 1
        except Exception as e:
            show_top_error(top, "Có lỗi khi lập kịch bản, hãy thử lại.", e)
            return
    if err:
        st.session_state.sim = None
        show_top_error(top, err)
    else:
        _sim_finish(sc)


def _sim_ui(top):
    voice_text_input("sim_q", "Thí nghiệm cần mô phỏng", "Ví dụ: cho kẽm vào dung dịch HCl và thu khí hiđro")
    for row in range(0, len(SIM_EXAMPLES), 3):
        for c, e in zip(st.columns(3), SIM_EXAMPLES[row:row + 3]):
            c.button(e, key=f"sim_ex_{row}_{e[:6]}", on_click=_sim_set, args=(e,), width="stretch")
    q = (st.session_state.get("sim_q") or "").strip()
    if st.button("Tạo mô phỏng", type="primary", disabled=not q, key="sim_go"):
        _sim_make(top, q)
    sc = st.session_state.get("sim")
    if not sc:
        return
    st.divider()
    custom = st.session_state.get("sim_custom")
    page = sim_html(sc, custom)
    if st.session_state.get("voice_note"):
        st.caption("🔈 Giọng đọc của phim này: " + st.session_state.voice_note)
    if hasattr(st, "iframe"):
        st.iframe(page, height=600)
    else:
        components.html(page, height=600)
    with st.expander("⏱️ Chỉnh thời gian từng bước tùy ý"):
        with st.form("sim_time"):
            cur = custom or {}
            auto = st.checkbox("Tự động theo lời đọc (khuyên dùng)", value=not cur.get("on"))
            vals = []
            for i, s in enumerate(sc["buoc"]):
                dv = float(cur["d"][i]) if cur.get("on") and i < len(cur.get("d", [])) else sim_auto_dur(s)
                vals.append(st.number_input(f"Bước {i + 1}: {s.get('tieu_de', '')[:34]} (giây)", 2.0, 90.0, value=dv, step=0.5, key=f"sim_d_{i}"))
            endv = st.number_input("Màn kết luận (giây)", 3.0, 90.0, value=float(cur.get("end") or max(8.0, (sc.get("am_ket_dur") or 0) + 1)), step=0.5, key="sim_d_end")
            if st.form_submit_button("Áp dụng thời gian"):
                st.session_state.sim_custom = {"on": not auto, "d": vals, "end": endv}
                st.rerun()
        st.caption("Bỏ chọn “Tự động” rồi nhập số giây cho từng bước. Giọng đọc sẽ tự nhanh hoặc chậm lại cho vừa thời lượng. Muốn nhanh chậm cả phim, kéo thanh tốc độ ⏱ bên dưới phim.")
    bal = sim_balance(sc)
    if sc.get("phuong_trinh"):
        st.markdown("**Phương trình phản ứng:** " + html.escape(_sub(sc["phuong_trinh"].replace("->", "→"))))
        if bal is False:
            st.warning("Phương trình trong kịch bản **chưa cân bằng** theo hệ số đã nêu, hãy kiểm tra lại.")
    if sc.get("hien_tuong"):
        st.markdown("**Hiện tượng quan sát được:**\n" + "\n".join("- " + html.escape(x) for x in sc["hien_tuong"]))
    if sc.get("giai_thich"):
        st.markdown("**Giải thích:** " + html.escape(sc["giai_thich"]))
    if sc.get("an_toan"):
        st.warning("**An toàn khi làm thí nghiệm thật:** " + " • ".join(sc["an_toan"]))



# ---------------- Điều hướng ----------------
HOME = "Trang chủ"
ASSIST = "Trợ lý AI"
PRACTICE_TAB = "Luyện tập"
TEST_TAB = "Kiểm tra"
HISTORY_TAB = "Lịch sử tra cứu"
SECTIONS = [
    ("Công thức cấu tạo", "Công thức cấu tạo viết tay", "Chụp ảnh công thức vẽ tay kiểu SGK → mã SMILES, tên gọi, khối lượng mol, tính chất.", structure_ui, "structure"),
    ("Phương trình phản ứng", "Phương trình phản ứng", "Đọc phương trình, cho biết loại phản ứng và kiểm tra đã cân bằng chưa.", reaction_ui, "flask"),
    ("Đồng phân", "Đồng phân", "Hỏi bằng tiếng Việt hoặc gõ công thức, máy sinh và đếm đồng phân chính xác.", isomer_ui, "isomer"),
    ("Dụng cụ hóa học", "Dụng cụ hóa học", "Chụp ảnh dụng cụ để biết tên, công dụng, cách dùng, hoặc gõ tên thí nghiệm để xem phim mô phỏng.", equipment_ui, "equipment"),
    ("Sơ đồ tư duy", "Sơ đồ tư duy", "Nhập chủ đề hoặc tên chất, máy vẽ sơ đồ để ôn tập, sửa được và tải về PowerPoint, draw.io.", mindmap_ui, "mind"),
]
LABELS = [x[0] for x in SECTIONS]
NAV_OPTS = [HOME] + LABELS + [PRACTICE_TAB, TEST_TAB, HISTORY_TAB]
STRUCT, REACT, ISO, EQUIP, MIND = LABELS[0], LABELS[1], LABELS[2], LABELS[3], LABELS[4]

st.session_state.setdefault("nav", HOME)
st.session_state.setdefault("nav_side", HOME)


def go(to):
    st.session_state.nav = to
    st.session_state.nav_side = to if to in NAV_OPTS else None


def on_side():
    if st.session_state.nav_side:
        go(st.session_state.nav_side)


def _fold(s):
    s = unicodedata.normalize("NFD", (s or "").lower().replace("đ", "d"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip()


def quick_lookup(text):
    """Đưa chuỗi người dùng nhập tới công cụ phù hợp. Trả về False nếu chuỗi rỗng."""
    t = (text or "").strip()
    if not t:
        return False
    if smiles_like(t):  # giống SMILES: phân tích cấu tạo ngay
        st.session_state.st_mode = "⌨️ Nhập SMILES"
        st.session_state.st_smi = t
        st.session_state.pending_smi = t
        go(STRUCT)
        add_history(t, "Công thức", {"smi": t})
    elif is_simple_formula(t) and "C" in t:  # công thức phân tử hữu cơ: đếm đồng phân
        st.session_state.iso_q = t
        go(ISO)
        add_history(t, "Đồng phân")
    else:  # còn lại: hỏi trợ lý AI
        st.session_state.pending_chat = t
        go(ASSIST)
        add_history(t, "Hỏi đáp")
    return True


def on_quick():
    if not is_logged_in():
        st.session_state["_toast"] = tx("🔒 Vui lòng đăng nhập để sử dụng.", "🔒 Please log in to use this.")
        st.session_state.quick_in = ""
        return
    quick_lookup(st.session_state.get("quick_in", ""))
    st.session_state.quick_in = ""


SEARCH_KEYS = {
    STRUCT: "cong thuc cau tao smiles viet tay ctct ten goi khoi luong mol structure structural formula molar mass handwritten",
    REACT: "phuong trinh phan ung can bang loai phan ung reaction equation balance balanced redox",
    ISO: "dong phan dem dong phan cis trans quang hoc isomer isomers count",
    EQUIP: "dung cu hoa hoc thi nghiem ong nghiem binh cau equipment lab experiment simulation",
    MIND: "so do tu duy mindmap on tap mind map review",
    ASSIST: "tro ly ai hoi dap chat assistant ai help question",
    PRACTICE_TAB: "luyen tap bai tap cham diem giao bai practice exercise quiz homework",
    TEST_TAB: "kiem tra bai kiem tra thi test exam quiz",
    HISTORY_TAB: "lich su tra cuu history lookups",
}


def on_search():
    q = (st.session_state.get("gsearch") or "").strip()
    st.session_state.gsearch = ""
    if not q:
        return
    f = _fold(q)
    for lab, keys in SEARCH_KEYS.items():
        if f in _fold(lab) or (len(f) >= 3 and f in keys):
            go(lab)
            return
    quick_lookup(q)


def on_home_upload():
    f = st.session_state.get("home_up")
    if f is not None:
        st.session_state.pending_img = f.getvalue()
        go(STRUCT)


# ---------------- Lịch sử theo từng tab ----------------
KIND_TAB = {"Công thức": STRUCT, "Luyện tập": PRACTICE_TAB, "Phản ứng": REACT, "Đồng phân": ISO,
            "Dụng cụ": EQUIP, "Mô phỏng": EQUIP, "Sơ đồ": MIND, "Hỏi đáp": ASSIST}
HIST_SHOW = 30   # số lượt hiện trong mỗi tab


def rerun_hist(h):
    """Đưa một lượt cũ trở lại ô nhập của tab tương ứng (Công thức và Hỏi đáp tự chạy, Đồng phân chỉ điền sẵn)."""
    k, p = h.get("k"), h.get("p") or {}
    if k == "Công thức" and p.get("smi"):
        st.session_state.st_mode = "⌨️ Nhập SMILES"
        st.session_state.st_smi = p["smi"]
        st.session_state.pending_smi = p["smi"]
        go(STRUCT)
    elif k == "Đồng phân":
        st.session_state.iso_q = h.get("q", "")
        go(ISO)
    elif k == "Hỏi đáp":
        st.session_state.pending_chat = h.get("q", "")
        go(ASSIST)


def can_rerun(h):
    k = h.get("k")
    return (k == "Công thức" and bool((h.get("p") or {}).get("smi"))) or k in ("Đồng phân", "Hỏi đáp")


def clear_tab_hist(kinds):
    st.session_state.hist[:] = [h for h in st.session_state.hist if h.get("k") not in kinds]
    who = student_name()
    if who:
        try:
            cr.clear_history(cur_auth(), who, kinds)
        except OSError:
            pass


def clear_all_hist():
    st.session_state.hist.clear()
    who = student_name()
    if who:
        try:
            cr.clear_history(cur_auth(), who)
        except OSError:
            pass


def tab_history_ui(tab):
    """Khung gập cuối mỗi tab: các lượt tra cứu của học sinh ở đúng tab này, tra lại, tải CSV, xóa."""
    kinds = [k for k, t in KIND_TAB.items() if t == tab]
    who = student_name()
    items = [h for h in st.session_state.hist if h.get("k") in kinds]
    with st.expander(f'{tx("🕘 Lịch sử tra cứu ở tab này", "🕘 Lookup history in this tab")} · {len(items)}'):
        if who:
            st.caption(tx(f"Đang lưu lịch sử cho: {who}", f"Saving history for: {who}"))
        else:
            st.caption(tx("Bạn đang dùng với tư cách khách: lịch sử chỉ lưu trong phiên này. Đăng nhập để lưu cho lần sau.",
                          "You are a guest: history is kept for this session only. Log in to keep it for next time."))
        if not items:
            st.caption(tx("Chưa có lượt tra cứu nào ở tab này.", "No lookups in this tab yet."))
            return
        for i, h in enumerate(items[:HIST_SHOW]):
            c1, c2 = st.columns([5, 1.6], vertical_alignment="center")
            when = f'{h.get("d", "")} {h.get("t", "")}'.strip()
            c1.markdown(f'**{html.escape(h.get("q", "")[:90])}**<br><small>{html.escape(when)} · {html.escape(tx(h.get("k", "")))}</small>',
                        unsafe_allow_html=True)
            if can_rerun(h):
                c2.button(tx("↻ Tra lại", "↻ Look up again"), key=f"th_{tab}_{i}", on_click=rerun_hist, args=(h,))
        if len(items) > HIST_SHOW:
            st.caption(tx(f"Hiện {HIST_SHOW} lượt mới nhất trong {len(items)} lượt (tệp CSV có đủ).",
                          f"Showing the latest {HIST_SHOW} of {len(items)} (the CSV has all of them)."))
        a, b = st.columns(2)
        a.download_button(tx("⬇️ Tải lịch sử (CSV)", "⬇️ Download history (CSV)"),
                          hs.to_csv([(who or "khách", h) for h in items], tab_of=lambda k: KIND_TAB.get(k, "")),
                          file_name=f"lich_su_{hs.slug(who) or 'khach'}.csv", mime="text/csv", key=f"thd_{tab}")
        b.button(tx("🗑️ Xóa lịch sử tab này", "🗑️ Clear this tab's history"), key=f"thc_{tab}", on_click=clear_tab_hist, args=(kinds,))




def my_history_ui():
    """Lịch sử của chính học sinh đang dùng, gom từ mọi tab."""
    who = student_name()
    items = st.session_state.hist
    if who:
        st.caption(tx(f"Lịch sử của: {who}. Mọi lượt tra cứu được lưu theo tài khoản này.",
                      f"History of: {who}. Every lookup is saved to this account."))
    else:
        st.info(tx("Bạn đang dùng với tư cách khách: lịch sử chỉ lưu trong phiên này. Đăng nhập để lưu cho lần sau.",
                   "You are a guest: history is kept for this session only. Log in to keep it for next time."))
        if st.button(tx("🔐 Đăng nhập / Tham gia lớp", "🔐 Log in / Join a class"), key="mh_login", type="primary"):
            auth_dialog()
    if not items:
        st.caption(tx("Chưa có lượt tra cứu nào.", "No lookups yet."))
        return
    tabs_all = [t for t in dict.fromkeys(KIND_TAB.values())]
    counts = {t: sum(1 for h in items if KIND_TAB.get(h.get("k")) == t) for t in tabs_all}
    cols = st.columns(len(tabs_all) + 1)
    cols[0].metric(tx("Tổng", "Total"), len(items))
    for col, t in zip(cols[1:], tabs_all):
        col.metric(tx(t), counts[t])
    f1, f2 = st.columns(2)
    pick = f1.multiselect(tx("Lọc theo tab", "Filter by tab"), tabs_all, format_func=tx, key="mh_tabs")
    day = f2.selectbox(tx("Lọc theo ngày", "Filter by date"), [""] + sorted({h.get("d", "") for h in items}, reverse=True),
                       format_func=lambda d: d or tx("Tất cả", "All"), key="mh_day")
    shown = [h for h in items if (not pick or KIND_TAB.get(h.get("k")) in pick) and (not day or h.get("d") == day)]
    st.dataframe([{tx("Ngày", "Date"): h.get("d", ""), tx("Giờ", "Time"): h.get("t", ""), "Tab": tx(KIND_TAB.get(h.get("k"), "")),
                   tx("Loại", "Type"): tx(h.get("k", "")), tx("Nội dung tra cứu", "Lookup"): h.get("q", "")} for h in shown],
                 hide_index=True, width="stretch")
    a, b = st.columns(2)
    a.download_button(tx("⬇️ Tải lịch sử (CSV)", "⬇️ Download history (CSV)"), hs.to_csv([(who or "khách", h) for h in shown], tab_of=lambda k: KIND_TAB.get(k, "")),
                      file_name=f"lich_su_{hs.slug(who) or 'khach'}.csv", mime="text/csv", key="mh_dl")
    b.button(tx("🗑️ Xóa toàn bộ lịch sử của tôi", "🗑️ Clear all my history"), key="mh_clear", on_click=clear_all_hist)


def _t_class_pick(key):
    """Chọn lớp (mã lớp). Trả về mã hoặc None nếu chưa có lớp."""
    try:
        cl = cr.classes(cur_auth())
    except OSError:
        st.error(tx("Không đọc được danh sách lớp: ", "Cannot read the class list: ") + hs.last_error)
        return None
    if not cl:
        st.info(tx("Chưa có lớp nào. Tạo lớp ở mục \"Lớp & tài khoản\".", "No classes yet. Create one under \"Classes\"."))
        return None
    names = dict(cl)
    return st.selectbox(tx("Lớp", "Class"), list(names), format_func=lambda c: f"{c} · {names[c]}", key=key)


def teacher_classes_ui():
    st.markdown("#### " + tx("Tạo lớp", "Create a class"))
    a, b, c = st.columns([2, 3, 1.5], vertical_alignment="bottom")
    code = a.text_input(tx("Mã lớp (VD 10A1)", "Class code (e.g. 10A1)"), key="tc_code", max_chars=20)
    name = b.text_input(tx("Tên lớp", "Class name"), key="tc_name", max_chars=60)
    if c.button(tx("Tạo lớp", "Create"), key="tc_make"):
        try:
            if cr.create_class(cur_auth(), code, name, _now().strftime("%Y-%m-%d %H:%M")):
                st.success(tx(f"Đã tạo lớp {cr.norm_code(code)}. Học sinh đăng nhập bằng mã lớp này.", f"Class {cr.norm_code(code)} created."))
            else:
                st.error(tx("Mã lớp không hợp lệ (2-20 ký tự chữ, số, - hoặc _) hoặc đã tồn tại.", "Invalid or duplicate class code."))
        except OSError:
            st.error(hs.last_error)
    cls = _t_class_pick("tc_pick")
    if not cls:
        return
    try:
        stu = cr.students(cur_auth(), cls)
    except OSError:
        st.error(hs.last_error)
        return
    st.markdown("#### " + tx(f"Học sinh lớp {cls} ({len(stu)})", f"Students of {cls} ({len(stu)})"))
    st.caption(tx("Học sinh tự tạo tài khoản lần đầu đăng nhập (mã lớp + tên + PIN tự đặt). Quên PIN thì đặt lại ở đây.",
                  "Students create their own account at first login (class code + name + PIN). Reset a forgotten PIN here."))
    if stu:
        who = st.selectbox(tx("Học sinh", "Student"), stu, key="tc_stu")
        if st.button(tx("Đặt lại PIN (xóa tài khoản, giữ lịch sử và bài nộp)", "Reset PIN (delete account, keep history and submissions)"), key="tc_reset"):
            try:
                st.success(tx(f"Đã đặt lại {who}. Em đăng nhập lại và đặt PIN mới.", f"{who} reset. They can log in and choose a new PIN.")
                          if cr.reset_pin(cur_auth(), cls, who) else tx("Không tìm thấy.", "Not found."))
            except OSError:
                st.error(hs.last_error)
    with st.expander(tx("Xóa cả lớp", "Delete the whole class")):
        if st.checkbox(tx(f"Tôi chắc chắn muốn xóa lớp {cls} cùng tài khoản, bài giao và bài nộp", f"I am sure I want to delete class {cls} with accounts, assignments and submissions"), key="tc_sure"):
            if st.button(tx("Xóa lớp", "Delete class"), key="tc_del"):
                try:
                    cr.delete_class(cur_auth(), cls)
                    st.session_state["tc_sure"] = False
                    st.rerun()
                except OSError:
                    st.error(hs.last_error)


def teacher_assign_ui():
    cls = _t_class_pick("ta_cls")
    if not cls:
        return
    st.markdown("#### " + tx("Giao bài mới", "New assignment"))
    title = st.text_input(tx("Tên bài", "Title"), key="ta_title", max_chars=100, placeholder=tx("VD: Kiểm tra 15 phút - Hóa 12", "e.g. 15-minute quiz"))
    kind = st.text_input(tx("Dạng bài", "Type"), key="ta_kind_txt", max_chars=40,
                         placeholder=tx("VD: Trắc nghiệm, Kiểm tra 15 phút, Ôn tập, Bài tập về nhà", "e.g. Multiple choice, 15-minute quiz, Homework"))
    d1, d2 = st.columns(2)
    due_on = d1.checkbox(tx("Đặt hạn nộp", "Set a due date"), key="ta_due_on")
    due = d2.date_input(tx("Hạn nộp", "Due date"), key="ta_due", disabled=not due_on)
    minutes = st.number_input(tx("⏱️ Thời gian làm bài (phút, 0 = không giới hạn)", "⏱️ Time limit (minutes, 0 = none)"), 0, 300, 0, step=5, key="ta_mins",
                              help=tx("Áp dụng cho bài làm trên phiếu trả lời. Đồng hồ chạy khi học sinh bấm Bắt đầu; hết giờ bài tự nộp.",
                                      "Applies to the online answer sheet. The clock starts when the student presses Start; it auto-submits at the end."))
    cat = st.radio(tx("Phân loại", "Category"), [cr.PRACTICE, cr.TEST], horizontal=True, key="ta_cat", format_func=_cat_label)
    if cat == cr.TEST:
        hints = False
        st.caption(tx("Bài kiểm tra: không có gợi ý từng bước.", "Test: no step-by-step hints."))
    else:
        hints = st.checkbox(tx("Cho phép gợi ý từng bước", "Allow step-by-step hints"), value=True, key="ta_hints")
    exts = sorted(cr.ALLOWED_EXT)
    files = st.file_uploader(tx("📎 Đính kèm tệp cho học sinh tải về (đề, phiếu bài tập, tài liệu…)", "📎 Attach files for students to download (worksheet, handout…)"),
                             type=exts, accept_multiple_files=True, key=f"ta_files_{st.session_state.get('_ta_n', 0)}",
                             help=tx(f"Tối đa {cr.MAX_ATT} tệp, mỗi tệp {cr.MAX_FILE // 1000} KB (ảnh png/jpg tự nén). Bài giao gồm tệp đề và/hoặc phiếu trả lời.",
                                     f"Up to {cr.MAX_ATT} files, {cr.MAX_FILE // 1000} KB each (png/jpg auto-compressed). An assignment is the exam file and/or the answer sheet."))
    use_sheet = st.checkbox(tx("📝 Cho học sinh làm bài trực tuyến trên đề (trắc nghiệm / đúng-sai / trả lời ngắn, tự chấm)", "📝 Let students take the test online (multiple choice / true-false / short answer, auto-graded)"), value=True, key="ta_sheet_on")
    sheet_cfg, infos = None, {}
    for f in files or []:
        if cr.ext_of(f.name) == "docx":
            infos[f.name] = _analyze_docx(f.getvalue())
    if use_sheet:
        struct, key = merge_analyses(infos.values())
        prefill = cr.cfg_from_key(key, struct) if any(key.values()) or any(struct.values()) else None
        if infos:
            if prefill and any(prefill["mc"] + prefill["tf"] + prefill["sa"]):
                got, tot = key_summary(prefill)
                srcs = sorted({x for it in infos.values() for x in it["src"]})
                st.success(tx(f"✅ Đã đọc đáp án từ file ({', '.join(srcs)}): phần I {got['mc']}/{tot['mc']}, phần II {got['tf']}/{tot['tf']}, phần III {got['sa']}/{tot['sa']} câu. Kiểm tra lại bên dưới rồi giao bài.",
                              f"✅ Answer key read from the file: {got['mc']}/{tot['mc']}, {got['tf']}/{tot['tf']}, {got['sa']}/{tot['sa']}. Check it below, then assign."))
                if any(it["key_only"] for it in infos.values()):
                    st.caption(tx("File chỉ có đáp án sẽ không gửi cho học sinh.", "Answer-only files are not shared with students."))
                if any(it["has_marker"] and not it["stripped"] for it in infos.values()):
                    st.warning(tx("Không tự cắt được phần đáp án khỏi file này, học sinh có thể thấy khi xem/tải file. Hãy dùng file đề không có đáp án (đáp án để file riêng).", "Couldn't remove the key section from this file; students could see it. Upload a clean exam file and the key separately."))
                if "đáp án đánh dấu trong đề" in srcs:
                    st.warning(tx("Đáp án đang được đánh dấu (gạch chân/màu) trong đề nên học sinh có thể thấy khi tải file. Khi làm bài trực tuyến, app đã ẩn dấu này.", "The key is marked (underline/colour) inside the exam; students could see it in the downloaded file."))
            else:
                st.info(tx("Chưa tìm thấy đáp án trong file, hãy nhập tay bên dưới (hoặc tải thêm file đáp án .docx).", "No answer key found in the file; enter it below or upload a separate key file (.docx)."))
        sheet_cfg = sheet_editor_ui("ta_sh", detected=struct, existing=prefill)
    if st.button(tx("Giao bài", "Assign"), type="primary", key="ta_go"):
        qs = []
        guessed = 0
        if not int(minutes):
            guessed = cr.guess_minutes(title)
            if guessed:
                minutes = guessed
        if not title.strip() or (not files and not use_sheet):
            st.error(tx("Cần nhập tên bài và đính kèm tệp đề hoặc tạo phiếu trả lời.", "Enter a title and attach a file or add an answer sheet."))
        elif len(files or []) > cr.MAX_ATT:
            st.error(tx(f"Tối đa {cr.MAX_ATT} tệp cho mỗi bài.", f"At most {cr.MAX_ATT} files per assignment."))
        else:
            bad = [f.name for f in files or [] if len(f.getvalue()) > cr.size_limit(f.name)]
            if bad:
                st.error(tx("Tệp quá lớn: ", "File too large: ") + ", ".join(bad))
            else:
                try:
                    aid = cr.create_assignment(cur_auth(), cls, title, qs, due.isoformat() if due_on else "", hints, _now().strftime("%Y-%m-%d %H:%M"), kind, cat, int(minutes))
                    up = 0
                    for f in files or []:
                        info = infos.get(f.name)
                        data = f.getvalue()
                        if use_sheet and info:
                            if info["key_only"]:
                                continue
                            if info["stripped"]:
                                data = info["stripped"]
                        try:
                            cr.add_file(cur_auth(), aid, cr.ATT, f.name, f.type, data, _now().strftime("%Y-%m-%d %H:%M"))
                            up += 1
                        except cr.Denied as e:
                            st.error(f"{f.name}: {e}")
                    if use_sheet and sheet_cfg:
                        try:
                            cr.set_sheet(cur_auth(), aid, sheet_cfg)
                        except cr.Denied as e:
                            st.error(tx("Đã giao bài nhưng chưa lưu được phiếu: ", "Assigned, but the sheet was not saved: ") + str(e))
                    st.session_state["_ta_n"] = st.session_state.get("_ta_n", 0) + 1
                    st.session_state["_toast"] = tx(f"Đã giao bài \"{title.strip()}\" ({up} tệp) cho lớp {cls}." + (f" Tự đặt giờ làm bài {guessed} phút theo tên bài." if guessed else ""),
                                                   f"Assigned \"{title.strip()}\" ({up} file(s)) to {cls}." + (f" Time limit set to {guessed} min from the title." if guessed else ""))
                    st.rerun()
                except OSError:
                    st.error(hs.last_error)
    st.markdown("#### " + tx("Bài đã giao", "Assignments"))
    try:
        asgs = cr.assignments(cur_auth(), cls)
    except OSError:
        st.error(hs.last_error)
        return
    def _row(a):
        c1, c2 = st.columns([5, 1.5], vertical_alignment="center")
        c1.markdown(f"{_cat_label(a['cat'])} · **{html.escape(a['title'])}**" + (f" · 🏷️ {html.escape(a['kind'])}" if a["kind"] else "") + (f" · ⏱️ {a['mins']} {tx('phút', 'min')}" if a["mins"] else "") + (f" · {len(a['questions'])} {tx('câu', 'questions')}" if a["questions"] else "") + f" · {a['created']}"
                    + (f" · {tx('hạn', 'due')} {a['due']}" if a["due"] else ""), unsafe_allow_html=True)
        if c2.button(tx("Xóa", "Delete"), key=f"ta_del_{a['id']}"):
            try:
                cr.delete_assignment(cur_auth(), a["id"])
                st.rerun()
            except OSError:
                st.error(hs.last_error)
        with st.expander(tx(f"⏱️ Giờ làm bài ({a['mins']} phút)" if a["mins"] else "⏱️ Giờ làm bài (không giới hạn)",
                            f"⏱️ Time limit ({a['mins']} min)" if a["mins"] else "⏱️ Time limit (none)")):
            m1, m2 = st.columns([2, 1], vertical_alignment="bottom")
            nm = m1.number_input(tx("Số phút (0 = không giới hạn)", "Minutes (0 = none)"), 0, 300, int(a["mins"] or cr.guess_minutes(a["title"])), step=5, key=f"tmin_{a['id']}")
            if m2.button(tx("💾 Lưu giờ", "💾 Save time"), key=f"tmin_save_{a['id']}", type="primary"):
                try:
                    cr.set_assignment_minutes(cur_auth(), a["id"], int(nm))
                    st.session_state["_toast"] = tx("Đã lưu thời gian làm bài.", "Time limit saved.")
                    st.rerun()
                except (OSError, cr.Denied) as e:
                    st.error(str(e) if isinstance(e, cr.Denied) else hs.last_error)
            st.caption(tx("Chỉ áp dụng cho bài làm trên phiếu trả lời. Học sinh phải bấm Bắt đầu thì đồng hồ mới chạy.", "Applies to the online answer sheet only. The clock starts when the student presses Start."))
        try:
            atts = cr.list_files(cur_auth(), a["id"], kind=cr.ATT)
        except OSError:
            atts = []
        with st.expander(tx(f"📎 Tệp đính kèm ({len(atts)})", f"📎 Attached files ({len(atts)})")):
            file_rows_ui(atts, f"ta_{a['id']}", can_delete=True)
            if len(atts) < cr.MAX_ATT:
                upload_ui(a["id"], cr.ATT, f"tau_{a['id']}", tx("Thêm tệp đính kèm", "Add attachment"), True)
        try:
            ex_sheet = cr.get_sheet(cur_auth(), a["id"], force=True)
        except OSError:
            ex_sheet = None
        with st.expander(tx("📝 Phiếu trả lời" + (" (đã có)" if ex_sheet else " (chưa có)"), "📝 Answer sheet" + (" (set)" if ex_sheet else " (none)"))):
            cfg = sheet_editor_ui(f"tsh_{a['id']}", existing=ex_sheet)
            if st.button(tx("💾 Lưu phiếu", "💾 Save sheet"), key=f"tsh_save_{a['id']}", type="primary"):
                try:
                    cr.set_sheet(cur_auth(), a["id"], cfg)
                    st.session_state["_toast"] = tx("Đã lưu phiếu trả lời.", "Sheet saved.")
                    st.rerun()
                except (OSError, cr.Denied) as e:
                    st.error(str(e) if isinstance(e, cr.Denied) else hs.last_error)

    n_t = sum(1 for x in asgs if x["cat"] == cr.TEST)
    show = st.radio(tx("Hiện", "Show"), ["all", cr.PRACTICE, cr.TEST], horizontal=True, key="ta_show", label_visibility="collapsed",
                    format_func=lambda c: tx(f"Tất cả ({len(asgs)})", f"All ({len(asgs)})") if c == "all"
                    else f"{_cat_label(c)} ({len(asgs) - n_t if c == cr.PRACTICE else n_t})")
    sub = asgs if show == "all" else [x for x in asgs if x["cat"] == show]
    if not sub:
        st.caption(tx("Chưa có bài nào.", "Nothing here yet."))
    for a in sub:                                   # cũ và mới cùng một danh sách, mới nhất trước
        _row(a)


def teacher_results_ui():
    cls = _t_class_pick("tr_cls")
    if not cls:
        return
    try:
        asgs = cr.assignments(cur_auth(), cls)
        stu = [cr.identity(cls, n) for n in cr.students(cur_auth(), cls)]
    except OSError:
        st.error(hs.last_error)
        return
    if not asgs:
        st.info(tx("Lớp này chưa có bài giao.", "This class has no assignments yet."))
        return
    fcat = st.radio(tx("Loại bài", "Kind"), ["all", cr.PRACTICE, cr.TEST], horizontal=True, key="tr_cat",
                    format_func=lambda c: tx("Tất cả", "All") if c == "all" else _cat_label(c))
    if fcat != "all":
        asgs = [x for x in asgs if x["cat"] == fcat]
        if not asgs:
            st.info(tx("Chưa có bài nào thuộc loại này.", "No assignments of this kind."))
            return
    a = st.selectbox(tx("Bài", "Assignment"), asgs, format_func=lambda x: f"{_cat_label(x['cat'])} · {x['title']} ({x['created']})", key=f"tr_asg_{fcat}")
    if st.button(tx("🔄 Tải lại", "🔄 Refresh"), key="tr_refresh"):
        cr.submissions(cur_auth(), aid=a["id"], force=True)
    try:
        subf = cr.list_files(cur_auth(), a["id"], kind=cr.SUBF, force=True)
    except OSError:
        subf = []
    with st.expander(tx(f"📥 Tệp học sinh nộp ({len(subf)})", f"📥 Files submitted by students ({len(subf)})"), expanded=bool(subf)):
        if subf:
            file_rows_ui(subf, f"tf_{a['id']}", can_delete=True, show_student=True)
        else:
            st.caption(tx("Chưa có học sinh nào nộp tệp.", "No student has submitted a file yet."))
    sheet_results_ui(a)
    if not a["questions"]:
        return
    prog = cr.progress(a, cr.submissions(cur_auth(), aid=a["id"]))
    qs = a["questions"]
    rows, total_ok = [], 0
    for sname in sorted(set(stu) | set(prog), key=str.lower):
        row = {tx("Học sinh", "Student"): sname.rsplit(" [", 1)[0]}
        ok = 0
        for i, qd in enumerate(qs):
            d = prog.get(sname, {}).get(cr.qkey(qd))
            row[f'{i + 1}. {qd["n"]} ({"vẽ" if qd["k"] == "draw" else "tên"})'] = ("–" if not d else "✓" if d["first"] else f'✓({d["tries"]})' if d["ok"] else f'✗({d["tries"]})')
            ok += 1 if d and d["ok"] else 0
        row[tx("Điểm", "Score")] = f"{ok}/{len(qs)}"
        total_ok += ok
        rows.append(row)
    st.caption(tx("✓ đúng lần đầu · ✓(n) đúng sau n lần · ✗(n) sai n lần · – chưa làm", "✓ first try · ✓(n) correct after n tries · ✗(n) wrong n times · – not started"))
    st.dataframe(rows, hide_index=True, width="stretch")
    if rows:
        st.metric(tx("Tỉ lệ đúng trung bình", "Average correct"), f"{round(100 * total_ok / (len(rows) * max(1, len(qs))))}%")
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
        st.download_button(tx("⬇️ Tải bảng điểm (CSV)", "⬇️ Download scores (CSV)"), buf.getvalue().encode("utf-8-sig"),
                           file_name=f"diem_{cls}_{a['id']}.csv", mime="text/csv", key="tr_dl")


def teacher_weak_ui():
    cls = _t_class_pick("tw_cls")
    if not cls:
        return
    try:
        subs = cr.submissions(cur_auth(), code=cls)
        summ = [r for r in cr.history_summary(cur_auth()) if r["name"].endswith(f"[{cls}]")]
    except OSError:
        st.error(hs.last_error)
        return
    st.markdown("#### " + tx("Chỗ cả lớp hay sai (từ bài làm)", "Where the class struggles (from submissions)"))
    if not subs:
        st.info(tx("Chưa có bài nộp nào của lớp này.", "No submissions from this class yet."))
    else:
        w = cr.weak_spots(subs)
        cols = {tx("Chủ đề", "Topic"): "topic", tx("Dạng bài", "Type"): "kind", tx("Từng câu", "Question"): "question"}
        for label, k in cols.items():
            st.markdown(f"**{label}**")
            data = [{tx("Mục", "Item"): r["key"], tx("Lượt nộp", "Attempts"): r["n"], tx("Lượt sai", "Wrong"): r["wrong"],
                     tx("Số HS sai", "Students wrong"): r["students"], tx("Tỉ lệ sai %", "Wrong %"): r["pct"]} for r in w[k][:12]]
            st.dataframe(data, hide_index=True, width="stretch")
        top = w["topic"][:8]
        if top:
            st.bar_chart({tx("Tỉ lệ sai %", "Wrong %"): {r["key"]: r["pct"] for r in top}})
        st.caption(tx("Chủ đề có tỉ lệ sai cao là chỗ nên ôn lại cho cả lớp.", "Topics with a high wrong rate are worth reviewing with the whole class."))
    st.markdown("#### " + tx("Cả lớp tra cứu nhiều ở đâu", "What the class looks up most"))
    by = {}
    for r in summ:
        for k, v in r["by_kind"].items():
            by[KIND_TAB.get(k, k)] = by.get(KIND_TAB.get(k, k), 0) + v
    if by:
        st.dataframe([{"Tab": tx(t), tx("Lượt tra cứu", "Lookups"): v} for t, v in sorted(by.items(), key=lambda x: -x[1])], hide_index=True, width="stretch")
        quiet = [r["name"] for r in summ if r["total"] == 0 or r["last"][:10] < (_now().strftime("%Y-%m-%d"))]
        st.caption(tx(f"{len(summ)} học sinh của lớp đã có lịch sử; {len(quiet)} em chưa hoạt động hôm nay.",
                      f"{len(summ)} students of this class have history; {len(quiet)} were not active today."))
    else:
        st.info(tx("Chưa có lịch sử tra cứu của học sinh lớp này (học sinh cần đăng nhập lớp).", "No lookup history from this class yet (students must log in to the class)."))


def teacher_ui():
    """Tab giáo viên: ai đã truy cập, khi nào, tra cứu gì ở tab nào. Dữ liệu đọc từ các tệp đã lưu nên vẫn còn sau khi tắt app."""
    if not cr.is_teacher(cur_auth()):
        return
    t1, t2, t3, t4, t5 = st.tabs([tx("Học sinh", "Students"), tx("Lớp & tài khoản", "Classes"), tx("Giao bài", "Assign"),
                                  tx("Kết quả bài", "Results"), tx("Chỗ hay sai", "Weak spots")])
    with t1:
        teacher_students_ui()
    with t2:
        teacher_classes_ui()
    with t3:
        teacher_assign_ui()
    with t4:
        teacher_results_ui()
    with t5:
        teacher_weak_ui()


def teacher_students_ui():
    st.caption(tx("Nơi lưu: ", "Storage: ") + (tx("Google Sheets (bền, không mất khi khởi động lại)", "Google Sheets (durable, survives restarts)")
                                               if hs.backend_name() == "Google Sheets"
                                               else tx("tệp trên máy chủ (MẤT khi app khởi động lại, hãy cấu hình Google Sheets hoặc tải CSV)",
                                                       "server files (LOST on restart; set up Google Sheets or download CSV)")))
    if st.button(tx("🔄 Tải lại dữ liệu", "🔄 Refresh data"), key="th_refresh"):
        st.session_state["_th_force"] = True
    try:
        rows = cr.history_summary(cur_auth(), force=st.session_state.pop("_th_force", False))
    except OSError:
        st.error(tx("Không đọc được dữ liệu lịch sử: ", "Cannot read the history data: ") + hs.last_error)
        return
    if not rows:
        st.info(tx("Chưa có học sinh nào được lưu. Học sinh cần đăng nhập để lịch sử được ghi lại.",
                   "No students saved yet. Students must log in for their history to be recorded."))
        return
    today = _now().strftime("%Y-%m-%d")
    a, b, c = st.columns(3)
    a.metric(tx("Số học sinh", "Students"), len(rows))
    b.metric(tx("Tổng lượt tra cứu", "Total lookups"), sum(r["total"] for r in rows))
    c.metric(tx("Truy cập hôm nay", "Active today"), sum(1 for r in rows if r["last"].startswith(today)))

    kinds = list(KIND_TAB)
    st.markdown("#### " + tx("Danh sách học sinh", "Student list"))
    table = [{tx("Học sinh", "Student"): r["name"], tx("Lần đầu", "First seen"): r["first"], tx("Gần nhất", "Last seen"): r["last"],
              tx("Số lần truy cập", "Visits"): r["visits"], tx("Tổng lượt", "Lookups"): r["total"],
              **{tx(k): r["by_kind"].get(k, 0) for k in kinds}} for r in rows]
    st.dataframe(table, hide_index=True, width="stretch")

    st.markdown("#### " + tx("Chi tiết một học sinh", "Student details"))
    by_slug = {r["slug"]: r for r in rows}
    sel = st.selectbox(tx("Chọn học sinh", "Choose a student"), list(by_slug), format_func=lambda k: f'{by_slug[k]["name"]} ({by_slug[k]["total"]})', key="th_pick")
    r = by_slug[sel]
    items = cr.read_history(cur_auth(), r["name"])
    f1, f2 = st.columns(2)
    tabs_pick = f1.multiselect(tx("Lọc theo tab", "Filter by tab"), sorted({KIND_TAB.get(h.get("k"), h.get("k", "")) for h in items}),
                               format_func=tx, key="th_tabs")
    day_pick = f2.selectbox(tx("Lọc theo ngày", "Filter by date"), [""] + sorted({h.get("d", "") for h in items}, reverse=True),
                            format_func=lambda d: d or tx("Tất cả", "All"), key="th_day")
    shown = [h for h in items if (not tabs_pick or KIND_TAB.get(h.get("k"), h.get("k", "")) in tabs_pick) and (not day_pick or h.get("d") == day_pick)]
    st.caption(tx(f'{r["name"]}: {r["visits"]} lần truy cập, lần gần nhất {r["last"]}. Hiện {len(shown)}/{len(items)} lượt tra cứu.',
                  f'{r["name"]}: {r["visits"]} visits, last seen {r["last"]}. Showing {len(shown)}/{len(items)} lookups.'))
    st.dataframe([{tx("Ngày", "Date"): h.get("d", ""), tx("Giờ", "Time"): h.get("t", ""), "Tab": tx(KIND_TAB.get(h.get("k"), "")),
                   tx("Loại", "Type"): tx(h.get("k", "")), tx("Nội dung tra cứu", "Lookup"): h.get("q", "")} for h in shown],
                 hide_index=True, width="stretch")
    with st.expander(tx("Các lần truy cập (mỗi lần học sinh đăng nhập)", "Visits (each time the student logged in)")):
        st.write(", ".join(r["visit_log"][:60]) or "-")

    d1, d2 = st.columns(2)
    d1.download_button(tx("⬇️ Tải học sinh này (CSV)", "⬇️ Download this student (CSV)"), hs.to_csv([(r["name"], h) for h in items], tab_of=lambda k: KIND_TAB.get(k, "")),
                       file_name=f'lich_su_{r["slug"]}.csv', mime="text/csv", key="th_dl_one")
    d2.download_button(tx("⬇️ Tải cả lớp (CSV)", "⬇️ Download whole class (CSV)"),
                       hs.to_csv([(x["name"], h) for x in rows for h in cr.read_history(cur_auth(), x["name"])], tab_of=lambda k: KIND_TAB.get(k, "")),
                       file_name="lich_su_ca_lop.csv", mime="text/csv", key="th_dl_all")
    with st.expander(tx("Xóa dữ liệu học sinh này", "Delete this student's data")):
        if st.checkbox(tx(f'Tôi chắc chắn muốn xóa toàn bộ dữ liệu của "{r["name"]}"', f'I am sure I want to delete all data of "{r["name"]}"'), key="th_sure"):
            if st.button(tx("Xóa", "Delete"), key="th_del"):
                cr.delete_history(cur_auth(), r["name"])
                st.session_state["th_sure"] = False
                st.rerun()


# ---------------- Tài liệu học tập (dữ liệu tra cứu có sẵn, không gọi AI) ----------------
_PT_NAMES = ("Hiđro,Heli,Liti,Beri,Bo,Cacbon,Nitơ,Oxi,Flo,Neon,Natri,Magie,Nhôm,Silic,Photpho,Lưu huỳnh,Clo,Agon,Kali,Canxi,"
             "Scandi,Titan,Vanađi,Crom,Mangan,Sắt,Coban,Niken,Đồng,Kẽm,Gali,Gecmani,Asen,Selen,Brom,Kripton,Rubiđi,Stronti,Ytri,Zirconi,"
             "Niobi,Molipđen,Tecneti,Rutheni,Rodi,Palađi,Bạc,Cađimi,Inđi,Thiếc,Antimon,Telu,Iot,Xenon,Xesi,Bari,Lantan,Xeri,"
             "Prazeođim,Neođim,Prometi,Samari,Europi,Gađolini,Tecbi,Đisprozi,Honmi,Eribi,Tuli,Ytecbi,Luteti,Hafni,Tantan,Vonfram,"
             "Reni,Osmi,Iriđi,Platin,Vàng,Thủy ngân,Tali,Chì,Bitmut,Poloni,Atatin,Radon,Franxi,Radi,Actini,Thori,Protactini,Urani,"
             "Neptuni,Plutoni,Amerixi,Curi,Berkeli,Califoni,Ensteni,Fecmi,Menđelevi,Nobeli,Lorenxi,Rutherfordi,Đubni,Seaborgi,Bohri,"
             "Hassi,Meitneri,Đacmstati,Rơnghen,Copernixi,Nihoni,Flerovi,Moscovi,Livermori,Tennessin,Oganesson").split(",")
assert len(_PT_NAMES) == 118

_PT_CATS = {
    "kl-kiem": ("Kim loại kiềm", {3, 11, 19, 37, 55, 87}),
    "kl-kt": ("Kim loại kiềm thổ", {4, 12, 20, 38, 56, 88}),
    "chuyen": ("Kim loại chuyển tiếp", set(range(21, 31)) | set(range(39, 49)) | set(range(72, 81)) | set(range(104, 113))),
    "sau-chuyen": ("Kim loại khác", {13, 31, 49, 50, 81, 82, 83, 84, 113, 114, 115, 116}),
    "a-kim-loai": ("Bán kim loại", {5, 14, 32, 33, 51, 52}),
    "phi-kim": ("Phi kim", {1, 6, 7, 8, 15, 16, 34}),
    "halogen": ("Halogen", {9, 17, 35, 53, 85, 117}),
    "khi-hiem": ("Khí hiếm", {2, 10, 18, 36, 54, 86, 118}),
    "lantan": ("Họ lantan", set(range(57, 72))),
    "actini": ("Họ actini", set(range(89, 104))),
}
assert set().union(*[v[1] for v in _PT_CATS.values()]) == set(range(1, 119))
_NO_STABLE = {43, 61} | set(range(84, 90)) | set(range(93, 119))  # không có đồng vị bền: ghi số khối trong ngoặc vuông


def _pt_cat(z):
    return next(k for k, (_, s) in _PT_CATS.items() if z in s)


def _pt_pos(z):
    """Trả về (hàng, cột) trên lưới bảng tuần hoàn dạng 18 cột."""
    if z == 1: return 1, 1
    if z == 2: return 1, 18
    if 3 <= z <= 4: return 2, z - 2
    if 5 <= z <= 10: return 2, z + 8
    if 11 <= z <= 12: return 3, z - 10
    if 13 <= z <= 18: return 3, z
    if 19 <= z <= 36: return 4, z - 18
    if 37 <= z <= 54: return 5, z - 36
    if z in (55, 56): return 6, z - 54
    if 57 <= z <= 71: return 9, z - 54
    if 72 <= z <= 86: return 6, z - 68
    if z in (87, 88): return 7, z - 86
    if 89 <= z <= 103: return 10, z - 86
    return 7, z - 100


def _pt_mass(z):
    m = Chem.GetPeriodicTable().GetAtomicWeight(z)
    return f"[{round(m)}]" if z in _NO_STABLE else f"{m:.2f}"


@st.dialog("Bảng tuần hoàn các nguyên tố hóa học", width="large")
def periodic_dialog():
    pt = Chem.GetPeriodicTable()
    cells = ['<div class="ptc ptx" style="grid-row:6;grid-column:3"><b>57–71</b></div>',
             '<div class="ptc ptx" style="grid-row:7;grid-column:3"><b>89–103</b></div>']
    for z in range(1, 119):
        r, c = _pt_pos(z)
        sym, nm = pt.GetElementSymbol(z), _PT_NAMES[z - 1]
        cell_nm = i18n.ELEMENTS_EN[z - 1] if i18n.lang() == "en" else nm   # ô nhỏ: chỉ một tên; chú thích (title) hiện cả hai
        cells.append(f'<div class="ptc {_pt_cat(z)}" style="grid-row:{r};grid-column:{c}" title="{z} · {i18n.element_name(z, nm)}">'
                     f'<i>{z}</i><b>{sym}</b><span>{cell_nm}</span><em>{_pt_mass(z)}</em></div>')
    legend = "".join(f'<span><i class="{k}"></i>{v[0]}</span>' for k, v in _PT_CATS.items())
    st.markdown(f'<div class="ptwrap"><div class="ptgrid">{"".join(cells)}</div></div><div class="ptleg">{legend}</div>', unsafe_allow_html=True)
    st.caption("Khối lượng nguyên tử tính theo RDKit (đơn vị amu). Số trong ngoặc vuông [ ] là số khối của đồng vị bền nhất, "
               "dùng cho nguyên tố không có đồng vị bền.")
    opts = [f"{z} · {pt.GetElementSymbol(z)} · {i18n.element_name(z, _PT_NAMES[z - 1])}" for z in range(1, 119)]
    pick = st.selectbox("Tra cứu một nguyên tố", opts, index=5, key="pt_pick")
    z = opts.index(pick) + 1
    r, c = _pt_pos(z)
    a, b, d, e = st.columns(4)
    a.metric("Số hiệu (Z)", z)
    b.metric("Ký hiệu", pt.GetElementSymbol(z))
    d.metric("Khối lượng", _pt_mass(z))
    e.metric("Nhóm", _PT_CATS[_pt_cat(z)][0])
    if r >= 9:
        st.markdown(f"**Chu kì:** {6 if r == 9 else 7} (hàng riêng bên dưới bảng)")
    else:
        st.markdown(f"**Chu kì:** {r} · **Cột:** {c}")


def _sub(s):
    """Chuyển chữ số sau chữ cái hoặc dấu ngoặc đóng thành chỉ số dưới."""
    return re.sub(r"(?<=[A-Za-z\)])(\d+)", lambda m: m.group(1).translate(SUB), s).replace(")n", ")ₙ")


ORG_ROWS = [  # (loại hợp chất, công thức chung, nhóm chức hoặc đặc điểm, ví dụ)
    ("Ankan", "C<sub>n</sub>H<sub>2n+2</sub> (n ≥ 1)", "Chỉ có liên kết đơn", "CH4 (metan), C2H6 (etan)"),
    ("Xicloankan (1 vòng)", "C<sub>n</sub>H<sub>2n</sub> (n ≥ 3)", "Mạch vòng, liên kết đơn", "C3H6 (xiclopropan)"),
    ("Anken", "C<sub>n</sub>H<sub>2n</sub> (n ≥ 2)", "1 liên kết đôi C=C", "C2H4 (eten)"),
    ("Ankađien", "C<sub>n</sub>H<sub>2n–2</sub> (n ≥ 3)", "2 liên kết đôi C=C", "C4H6 (buta-1,3-đien)"),
    ("Ankin", "C<sub>n</sub>H<sub>2n–2</sub> (n ≥ 2)", "1 liên kết ba C≡C", "C2H2 (etin)"),
    ("Aren (đồng đẳng benzen)", "C<sub>n</sub>H<sub>2n–6</sub> (n ≥ 6)", "Có vòng benzen", "C6H6 (benzen), C7H8 (toluen)"),
    ("Dẫn xuất halogen no, đơn chức", "C<sub>n</sub>H<sub>2n+1</sub>X", "–X (F, Cl, Br, I)", "CH3Cl, C2H5Br"),
    ("Ancol no, đơn chức, mạch hở", "C<sub>n</sub>H<sub>2n+1</sub>OH (C<sub>n</sub>H<sub>2n+2</sub>O)", "–OH gắn vào C no", "CH3OH, C2H5OH"),
    ("Phenol", "C<sub>6</sub>H<sub>5</sub>OH", "–OH gắn trực tiếp vào vòng benzen", "C6H5OH"),
    ("Anđehit no, đơn chức, mạch hở", "C<sub>n</sub>H<sub>2n+1</sub>CHO (C<sub>n</sub>H<sub>2n</sub>O)", "–CHO", "HCHO, CH3CHO"),
    ("Xeton no, đơn chức, mạch hở", "C<sub>n</sub>H<sub>2n</sub>O (n ≥ 3)", ">C=O", "CH3COCH3 (propanon)"),
    ("Axit cacboxylic no, đơn chức, mạch hở", "C<sub>n</sub>H<sub>2n+1</sub>COOH (C<sub>n</sub>H<sub>2n</sub>O<sub>2</sub>)", "–COOH", "HCOOH, CH3COOH"),
    ("Este no, đơn chức, mạch hở", "C<sub>n</sub>H<sub>2n</sub>O<sub>2</sub> (n ≥ 2)", "–COO–", "HCOOCH3, CH3COOC2H5"),
    ("Amin no, đơn chức, mạch hở", "C<sub>n</sub>H<sub>2n+3</sub>N (n ≥ 1)", "–NH2 (amin bậc 1)", "CH3NH2, C2H5NH2"),
    ("Amino axit", "H<sub>2</sub>N–R–COOH", "–NH2 và –COOH", "H2NCH2COOH (glyxin)"),
    ("Glucozơ, fructozơ", "C<sub>6</sub>H<sub>12</sub>O<sub>6</sub>", "Monosaccarit", "C6H12O6"),
    ("Saccarozơ, mantozơ", "C<sub>12</sub>H<sub>22</sub>O<sub>11</sub>", "Đisaccarit", "C12H22O11"),
    ("Tinh bột, xenlulozơ", "(C<sub>6</sub>H<sub>10</sub>O<sub>5</sub>)<sub>n</sub>", "Polisaccarit", "(C6H10O5)n"),
    ("Chất béo", "(RCOO)<sub>3</sub>C<sub>3</sub>H<sub>5</sub>", "Trieste của glixerol với axit béo", "(C17H35COO)3C3H5 (tristearin)"),
]


@st.dialog("Công thức hợp chất hữu cơ", width="large")
def organic_dialog():
    rows = "".join(f"<tr><td><b>{a}</b></td><td>{b}</td><td>{_sub(c)}</td><td>{_sub(d)}</td></tr>" for a, b, c, d in ORG_ROWS)
    st.markdown('<div class="reftbl"><table><thead><tr><th>Loại hợp chất</th><th>Công thức chung</th><th>Nhóm chức / đặc điểm</th><th>Ví dụ</th></tr></thead>'
                f'<tbody>{rows}</tbody></table></div>', unsafe_allow_html=True)
    st.markdown("**Độ bất bão hòa:** k = (2C + 2 + N − H − X) / 2, trong đó X là tổng số nguyên tử halogen. "
                "k bằng tổng số vòng và số liên kết π (một liên kết đôi tính 1, một liên kết ba tính 2).")
    st.caption("Các chất đồng đẳng hơn kém nhau một hoặc nhiều nhóm CH2.")
    st.button("Mở công cụ Công thức cấu tạo", key="org_open", on_click=go, args=(STRUCT,))


# Mỗi phương trình: (loại, vế trái, vế phải, điều kiện, mũi tên). Vế là danh sách (hệ số, công thức).
RX_ORG = [
    ("Thế", [(1, "CH4"), (1, "Cl2")], [(1, "CH3Cl"), (1, "HCl")], "ánh sáng", "→"),
    ("Cộng H2", [(1, "CH2=CH2"), (1, "H2")], [(1, "CH3CH3")], "Ni, t°", "→"),
    ("Cộng Br2", [(1, "CH2=CH2"), (1, "Br2")], [(1, "CH2BrCH2Br")], "", "→"),
    ("Cộng HX", [(1, "CH2=CH2"), (1, "HCl")], [(1, "CH3CH2Cl")], "", "→"),
    ("Cộng H2O", [(1, "CH2=CH2"), (1, "H2O")], [(1, "CH3CH2OH")], "H⁺, t°", "→"),
    ("Cộng Br2 (ankin)", [(1, "CH≡CH"), (2, "Br2")], [(1, "CHBr2CHBr2")], "", "→"),
    ("Tách nước", [(1, "CH3CH2OH")], [(1, "CH2=CH2"), (1, "H2O")], "H2SO4 đặc, 170°C", "→"),
    ("Oxi hóa ancol", [(2, "CH3CH2OH"), (1, "O2")], [(2, "CH3CHO"), (2, "H2O")], "Cu, t°", "→"),
    ("Đốt cháy", [(1, "C2H4"), (3, "O2")], [(2, "CO2"), (2, "H2O")], "t°", "→"),
    ("Đốt cháy", [(2, "C2H6"), (7, "O2")], [(4, "CO2"), (6, "H2O")], "t°", "→"),
    ("Thế (benzen)", [(1, "C6H6"), (1, "Br2")], [(1, "C6H5Br"), (1, "HBr")], "Fe, t°", "→"),
    ("Nitro hóa", [(1, "C6H6"), (1, "HNO3")], [(1, "C6H5NO2"), (1, "H2O")], "H2SO4 đặc", "→"),
    ("Thế (phenol)", [(1, "C6H5OH"), (3, "Br2")], [(1, "C6H2Br3OH↓"), (3, "HBr")], "", "→"),
    ("Este hóa", [(1, "CH3COOH"), (1, "C2H5OH")], [(1, "CH3COOC2H5"), (1, "H2O")], "H2SO4 đặc, t°", "⇌"),
    ("Xà phòng hóa", [(1, "CH3COOC2H5"), (1, "NaOH")], [(1, "CH3COONa"), (1, "C2H5OH")], "t°", "→"),
    ("Tráng bạc", [(1, "CH3CHO"), (2, "AgNO3"), (3, "NH3"), (1, "H2O")], [(1, "CH3COONH4"), (2, "Ag↓"), (2, "NH4NO3")], "t°", "→"),
    ("Lên men", [(1, "C6H12O6")], [(2, "C2H5OH"), (2, "CO2↑")], "enzim, 30–35°C", "→"),
    ("Axit – bazơ", [(1, "CH3COOH"), (1, "NaOH")], [(1, "CH3COONa"), (1, "H2O")], "", "→"),
    ("Amin + axit", [(1, "C6H5NH2"), (1, "HCl")], [(1, "C6H5NH3Cl")], "", "→"),
]
RX_INORG = [
    ("Kim loại + axit", [(1, "Zn"), (2, "HCl")], [(1, "ZnCl2"), (1, "H2↑")], "", "→"),
    ("Kim loại + axit", [(2, "Al"), (6, "HCl")], [(2, "AlCl3"), (3, "H2↑")], "", "→"),
    ("Kim loại + muối", [(1, "Fe"), (1, "CuSO4")], [(1, "FeSO4"), (1, "Cu")], "", "→"),
    ("Kim loại + nước", [(2, "Na"), (2, "H2O")], [(2, "NaOH"), (1, "H2↑")], "", "→"),
    ("Trung hòa", [(1, "NaOH"), (1, "HCl")], [(1, "NaCl"), (1, "H2O")], "", "→"),
    ("Trao đổi (kết tủa)", [(1, "AgNO3"), (1, "NaCl")], [(1, "AgCl↓"), (1, "NaNO3")], "", "→"),
    ("Trao đổi (kết tủa)", [(1, "BaCl2"), (1, "H2SO4")], [(1, "BaSO4↓"), (2, "HCl")], "", "→"),
    ("Muối cacbonat + axit", [(1, "CaCO3"), (2, "HCl")], [(1, "CaCl2"), (1, "CO2↑"), (1, "H2O")], "", "→"),
    ("Oxit axit + bazơ", [(1, "Ca(OH)2"), (1, "CO2")], [(1, "CaCO3↓"), (1, "H2O")], "", "→"),
    ("Phân hủy", [(1, "CaCO3")], [(1, "CaO"), (1, "CO2↑")], "t°", "→"),
    ("Phân hủy", [(2, "KClO3")], [(2, "KCl"), (3, "O2↑")], "MnO2, t°", "→"),
    ("Hóa hợp", [(2, "H2"), (1, "O2")], [(2, "H2O")], "t°", "→"),
    ("Hóa hợp", [(2, "Mg"), (1, "O2")], [(2, "MgO")], "t°", "→"),
    ("Oxit kim loại + H2", [(1, "CuO"), (1, "H2")], [(1, "Cu"), (1, "H2O")], "t°", "→"),
    ("Luyện gang", [(1, "Fe2O3"), (3, "CO")], [(2, "Fe"), (3, "CO2")], "t°", "→"),
    ("Axit đặc", [(1, "Cu"), (2, "H2SO4")], [(1, "CuSO4"), (1, "SO2↑"), (2, "H2O")], "H2SO4 đặc, t°", "→"),
]


# Phương trình oxi hóa - khử thường gặp, kèm chất khử, chất oxi hóa (soạn tay, máy kiểm tra cân bằng nguyên tử bên dưới)
RX_REDOX = [
    ("Kim loại + axit", [(1, "Zn"), (2, "HCl")], [(1, "ZnCl2"), (1, "H2↑")], "", "→",
     "Chất khử (bị oxi hóa): Zn · Chất oxi hóa (bị khử): HCl"),
    ("Kim loại + muối", [(1, "Fe"), (1, "CuSO4")], [(1, "FeSO4"), (1, "Cu")], "", "→",
     "Chất khử (bị oxi hóa): Fe · Chất oxi hóa (bị khử): CuSO4"),
    ("Kim loại + nước", [(2, "Na"), (2, "H2O")], [(2, "NaOH"), (1, "H2↑")], "", "→",
     "Chất khử (bị oxi hóa): Na · Chất oxi hóa (bị khử): H2O"),
    ("Oxit kim loại + H2", [(1, "CuO"), (1, "H2")], [(1, "Cu"), (1, "H2O")], "t°", "→",
     "Chất khử (bị oxi hóa): H2 · Chất oxi hóa (bị khử): CuO"),
    ("Luyện gang", [(1, "Fe2O3"), (3, "CO")], [(2, "Fe"), (3, "CO2")], "t°", "→",
     "Chất khử (bị oxi hóa): CO · Chất oxi hóa (bị khử): Fe2O3"),
    ("Axit đặc", [(1, "Cu"), (2, "H2SO4")], [(1, "CuSO4"), (1, "SO2↑"), (2, "H2O")], "H2SO4 đặc, t°", "→",
     "Chất khử (bị oxi hóa): Cu · Chất oxi hóa (bị khử): H2SO4"),
    ("Điều chế Cl2", [(1, "MnO2"), (4, "HCl")], [(1, "MnCl2"), (1, "Cl2↑"), (2, "H2O")], "HCl đặc, t°", "→",
     "Chất khử (bị oxi hóa): HCl · Chất oxi hóa (bị khử): MnO2"),
    ("KMnO4 + HCl đặc", [(2, "KMnO4"), (16, "HCl")], [(2, "KCl"), (2, "MnCl2"), (5, "Cl2↑"), (8, "H2O")], "", "→",
     "Chất khử (bị oxi hóa): HCl · Chất oxi hóa (bị khử): KMnO4"),
    ("Tự oxi hóa – khử", [(1, "Cl2"), (2, "NaOH")], [(1, "NaCl"), (1, "NaClO"), (1, "H2O")], "", "→",
     "Cl2 vừa là chất khử vừa là chất oxi hóa."),
    ("Nội phân tử", [(2, "KClO3")], [(2, "KCl"), (3, "O2↑")], "MnO2, t°", "→",
     "KClO3 vừa là chất khử (bị oxi hóa) vừa là chất oxi hóa (bị khử)."),
]


def _atoms(formula):
    """Đếm nguyên tử của một công thức (hỗ trợ ngoặc), bỏ ký hiệu ↑ ↓ = ≡."""
    f = re.sub(r"[↑↓=≡]", "", formula)
    stack = [{}]
    for tok in re.findall(r"([A-Z][a-z]?)(\d*)|(\()|\)(\d*)", f):
        el, n, op, cn = tok
        if el:
            stack[-1][el] = stack[-1].get(el, 0) + (int(n) if n else 1)
        elif op:
            stack.append({})
        else:
            grp = stack.pop()
            for k, v in grp.items():
                stack[-1][k] = stack[-1].get(k, 0) + v * (int(cn) if cn else 1)
    return stack[0]


def rx_balanced(left, right):
    def tot(side):
        c = Counter()
        for k, f in side:
            for el, v in _atoms(f).items():
                c[el] += k * v
        return c
    return tot(left) == tot(right)


def _rx_html(rows):
    out = []
    for typ, L, R, cond, arrow in rows:
        side = lambda s: " + ".join((f"{k} " if k > 1 else "") + html.escape(_sub(f)) for k, f in s)
        arr = f'<span class="rxa"><small>{html.escape(_sub(cond))}</small><i>{arrow}</i></span>'
        out.append(f'<div class="rxr"><span class="rxt">{html.escape(_sub(typ))}</span><div class="rxe">{side(L)}{arr}{side(R)}</div></div>')
    return "".join(out)


def _rx_redox_html(rows):
    out = []
    for typ, L, R, cond, arrow, note in rows:
        side = lambda s_: " + ".join((f"{k} " if k > 1 else "") + html.escape(_sub(f)) for k, f in s_)
        arr = f'<span class="rxa"><small>{html.escape(_sub(cond))}</small><i>{arrow}</i></span>'
        out.append(f'<div class="rxr"><span class="rxt">{html.escape(_sub(typ))}</span><div class="rxe">{side(L)}{arr}{side(R)}</div></div>'
                   f'<div style="font-size:.86rem;color:#475569;margin:-4px 0 10px 4px;line-height:1.5">{html.escape(_sub(note))}</div>')
    return "".join(out)


@st.dialog("Phương trình phản ứng thường gặp", width="large")
def reactions_dialog():
    t1, t2, t3 = st.tabs(["Hóa hữu cơ", "Hóa vô cơ", "Oxi hóa – khử"])
    with t1:
        st.markdown(_rx_html(RX_ORG), unsafe_allow_html=True)
        st.caption("Trùng hợp: nCH₂=CH₂ → (–CH₂–CH₂–)ₙ (điều kiện: t°, p, xúc tác).")
    with t2:
        st.markdown(_rx_html(RX_INORG), unsafe_allow_html=True)
    with t3:
        st.caption("Chất khử (tính khử) = chất bị oxi hóa. Chất oxi hóa (tính oxi hóa) = chất bị khử.")
        st.markdown(_rx_redox_html(RX_REDOX), unsafe_allow_html=True)
    st.caption("Các phương trình đã được máy kiểm tra cân bằng nguyên tử. ↑ là chất khí, ↓ là chất kết tủa. Điều kiện ghi trên mũi tên.")
    st.button("Mở công cụ Phương trình phản ứng", key="rx_open", on_click=go, args=(REACT,))


@st.dialog("Mẹo & lưu ý", width="large")
def tips_dialog():
    st.markdown("**Chụp ảnh để máy đọc chính xác**\n"
                "- Viết công thức rõ nét, nền sáng, mỗi ảnh chỉ một chất.\n"
                "- Chụp thẳng góc, đủ sáng, tránh bóng đổ và nếp gấp giấy.\n"
                "- Công thức sai hóa trị sẽ được máy chỉ rõ nguyên tử sai, hãy sửa lại hình vẽ rồi chụp lại.\n"
                "- Có thể sửa mã SMILES rồi phân tích lại ngay dưới kết quả.\n\n"
                "**Gọi tên và quy tắc hay dùng (theo SGK)**\n"
                "- Danh pháp thay thế: chọn mạch chính dài nhất có nhóm chức, đánh số từ phía gần nhóm chức, "
                "gọi tên nhánh theo thứ tự chữ cái.\n"
                "- Quy tắc Mác-côp-nhi-côp: khi cộng HX hoặc H₂O vào anken bất đối xứng, H cộng vào C có nhiều H hơn, "
                "X hoặc OH cộng vào C có ít H hơn.\n"
                "- Quy tắc Zai-xép: khi tách HX hoặc H₂O, ưu tiên tách H ở C bên cạnh có bậc cao hơn.\n"
                "- Thế vào vòng benzen: –OH, –NH₂, –CH₃ định hướng vị trí o- và p-; –NO₂, –COOH, –CHO định hướng vị trí m-.\n"
                "- Khi cân bằng, kiểm tra số nguyên tử từng nguyên tố hai vế bằng nhau; C luôn có hóa trị 4.\n\n"
                "")


# ---------------- Bảng tính tan (axit, bazơ, muối) ----------------
# Cation: (nhãn hiển thị, ký hiệu để ghép công thức, điện tích)
SOL_CATIONS = [("H⁺", "H", 1), ("Na⁺", "Na", 1), ("K⁺", "K", 1), ("NH₄⁺", "NH4", 1), ("Ag⁺", "Ag", 1), ("Mg²⁺", "Mg", 2),
               ("Ca²⁺", "Ca", 2), ("Ba²⁺", "Ba", 2), ("Zn²⁺", "Zn", 2), ("Hg²⁺", "Hg", 2), ("Pb²⁺", "Pb", 2), ("Cu²⁺", "Cu", 2),
               ("Fe²⁺", "Fe", 2), ("Fe³⁺", "Fe", 3), ("Al³⁺", "Al", 3)]
# Anion (cột): (nhãn, gốc, điện tích, gốc nhiều nguyên tử cần ngoặc khi có chỉ số)
SOL_ANIONS = [("OH⁻", "OH", 1, True), ("Cl⁻", "Cl", 1, False), ("NO₃⁻", "NO3", 1, True), ("CH₃COO⁻", "CH3COO", 1, True),
              ("S²⁻", "S", 2, False), ("SO₃²⁻", "SO3", 2, True), ("SO₄²⁻", "SO4", 2, True), ("CO₃²⁻", "CO3", 2, True),
              ("SiO₃²⁻", "SiO3", 2, True), ("PO₄³⁻", "PO4", 3, True)]
# Mã: t = tan, i = ít tan, k = không tan (kết tủa), b = tan nhưng bay hơi hoặc dễ phân hủy, x = không tồn tại hoặc bị nước phân hủy, ? = chưa có số liệu chắc chắn
SOL_DATA = {
    #        OH   Cl   NO3  Ac   S    SO3  SO4  CO3  SiO3 PO4
    "H":    "x    b    b    b    b    b    t    b    k    t",
    "Na":   "t    t    t    t    t    t    t    t    t    t",
    "K":    "t    t    t    t    t    t    t    t    t    t",
    "NH4":  "b    t    t    t    t    t    t    t    ?    t",
    "Ag":   "x    k    t    i    k    k    i    k    ?    k",
    "Mg":   "k    t    t    t    x    i    t    k    k    k",
    "Ca":   "i    t    t    t    x    k    i    k    k    k",
    "Ba":   "t    t    t    t    ?    k    k    k    k    k",
    "Zn":   "k    t    t    t    k    k    t    k    k    k",
    "Hg":   "x    t    t    t    k    ?    x    x    ?    k",
    "Pb":   "k    i    t    t    k    k    k    k    k    k",
    "Cu":   "k    t    t    t    k    x    t    x    k    k",
    "Fe2":  "k    t    t    t    k    k    t    k    k    k",
    "Fe3":  "k    t    t    t    x    x    t    x    k    k",
    "Al":   "k    t    t    t    x    x    t    x    k    k",
}
SOL_KEY = {("Fe", 2): "Fe2", ("Fe", 3): "Fe3"}
SOL_TEXT = {"t": ("Tan", "sol-t"), "i": ("Ít tan", "sol-i"), "k": ("Không tan (kết tủa)", "sol-k"),
            "b": ("Tan, bay hơi hoặc dễ phân hủy", "sol-b"), "x": ("Không tồn tại hoặc bị nước phân hủy", "sol-x"),
            "?": ("Chưa có số liệu chắc chắn", "sol-q")}


def _sol_code(ci, ai):
    sym, ch = SOL_CATIONS[ci][1], SOL_CATIONS[ci][2]
    return SOL_DATA[SOL_KEY.get((sym, ch), sym)].split()[ai]


def _sol_formula(ci, ai):
    from math import gcd
    _, csym, cch = SOL_CATIONS[ci]
    _, asym, ach, apoly = SOL_ANIONS[ai]
    g = gcd(cch, ach)
    nc, na = ach // g, cch // g
    if csym == "H" and asym == "CH3COO":
        return "CH₃COOH"
    if csym == "H" and asym == "OH":
        return "H₂O"
    c = csym if nc == 1 else (f"({csym})" if csym == "NH4" else csym) + str(nc)
    a = asym if na == 1 else (f"({asym})" if apoly else asym) + str(na)
    return _sub(c + a)


def _sol_table(sel=None):
    head = "".join(f"<th>{a[0]}</th>" for a in SOL_ANIONS)
    rows = []
    for ci, c in enumerate(SOL_CATIONS):
        cells = []
        for ai in range(len(SOL_ANIONS)):
            code = _sol_code(ci, ai)
            cls = SOL_TEXT[code][1] + (" sol-sel" if sel == (ci, ai) else "")
            cells.append(f'<td class="{cls}" title="{html.escape(_sol_formula(ci, ai))}: {SOL_TEXT[code][0]}">{ "–" if code == "x" else code}</td>')
        rows.append(f"<tr><th>{c[0]}</th>{''.join(cells)}</tr>")
    return f'<div class="soltbl"><table><thead><tr><th></th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


@st.dialog("Bảng tính tan trong nước", width="large")
def solubility_dialog():
    st.markdown("Chọn một cation và một anion để tra tính tan của hợp chất tạo thành. Ô đang chọn được viền sáng trong bảng.")
    c1, c2 = st.columns(2)
    ci = c1.selectbox("Cation (kim loại, H, NH₄)", range(len(SOL_CATIONS)), format_func=lambda i: SOL_CATIONS[i][0], index=1, key="sol_cat")
    ai = c2.selectbox("Anion (gốc axit, OH)", range(len(SOL_ANIONS)), format_func=lambda i: SOL_ANIONS[i][0], index=1, key="sol_an")
    code = _sol_code(ci, ai)
    txt, cls = SOL_TEXT[code]
    st.markdown(f'<div class="solres"><b>{_sol_formula(ci, ai)}</b><span class="solbadge {cls}">{txt}</span></div>', unsafe_allow_html=True)
    st.markdown(_sol_table((ci, ai)), unsafe_allow_html=True)
    st.markdown('<div class="sollg"><span class="sol-t">t</span> tan <span class="sol-i">i</span> ít tan <span class="sol-k">k</span> không tan (kết tủa) '
                '<span class="sol-b">b</span> tan, bay hơi hoặc dễ phân hủy <span class="sol-x">–</span> không tồn tại hoặc bị nước phân hủy '
                '<span class="sol-q">?</span> chưa có số liệu chắc chắn</div>', unsafe_allow_html=True)


# ---------------- Các khối giao diện ----------------
def topbar():
    with st.container(key="topbar"):
        a, b = st.columns([5, 2], vertical_alignment="center")
        with a:
            st.text_input("Tìm kiếm", key="gsearch", placeholder="Tìm công cụ, công thức, tên chất…", on_change=on_search, label_visibility="collapsed")
        with b:
            st.markdown(f'<div class="tb-right">{icon_svg("sun", "#5b6293", 22)}{icon_svg("bell", "#5b6293", 22)}<div class="av{"" if cr.is_student(cur_auth()) or cr.is_teacher(cur_auth()) else " guest"}">{html.escape(_initials())}</div></div>',
                        unsafe_allow_html=True)


def hero():
    L, app = i18n.lang(), html.escape(APP_NAME)
    h_vi = f'Khám phá thế giới Hóa học<br>cùng <em>{app}</em>'
    h_en = f'Explore the world of Chemistry<br>with <em>{app}</em>'
    h1 = h_vi if L == "vi" else h_en if L == "en" else h_vi + f'<div style="font-size:1.05rem;font-weight:600;opacity:.85;margin-top:.5rem">Explore the world of Chemistry with {app}</div>'
    st.markdown(
        f'<div class="hero3"><div class="hl"><span class="pill">{html.escape(tx("Chào bạn !", "Hello!"))} 👋</span>'
        f'<h1>{h1}</h1>'
        f'<div class="sub"><span>{tx("Nhanh chóng")}</span><i>•</i><span>{tx("Chính xác")}</span><i>•</i><span>{tx("Thông minh")}</span></div>'
        f'<div class="chips"><span>⚡ {tx("Nhanh chóng")}</span><span>🎯 {tx("Chính xác")}</span><span>💡 {tx("Tiện lợi")}</span><span>💜 {tx("Học mọi lúc")}</span></div></div>'
        f'<div class="hr"><img class="art" src="{_uri(HERO_ART)}"><div class="slogan">{tx("Mỗi phản ứng")}<br>{tx("là một khám phá!")}<u></u></div></div></div>',
        unsafe_allow_html=True,
    )


def page_banner(icon, title, desc):
    st.markdown(f'<div class="pbanner"><div class="pb-ic">{icon_svg(icon, "#fff", 28)}</div><div><b>{html.escape(tx(title))}</b>'
                f'<span>{html.escape(tx(desc, sep=" | "))}</span></div></div>', unsafe_allow_html=True)


TILES = [("Công thức\ncấu tạo", "structure", "t-pink", STRUCT), ("Phương trình\nphản ứng", "flask", "t-blue", REACT),
         ("Đồng phân", "isomer", "t-green", ISO), ("Dụng cụ\nhóa học", "equipment", "t-orange", EQUIP), ("Sơ đồ tư duy", "mind", "t-violet", MIND)]
TILE_EN = {STRUCT: "Structure", REACT: "Reactions", ISO: "Isomers", EQUIP: "Lab equipment", MIND: "Mind map"}


def _tile_text(txt, target):
    L = i18n.lang()
    if L == "en":
        return TILE_EN[target]
    return txt if L == "vi" else f"{txt.replace(chr(10), ' ')}<small>{TILE_EN[target]}</small>"


FEATS = [("⚡", "Nhanh chóng"), ("🎯", "Chính xác"), ("💡", "Tiện lợi"), ("💜", "Học mọi lúc")]
HKIND = {"Công thức": ("structure", "c1"), "Phản ứng": ("flask", "c3"), "Đồng phân": ("isomer", "c0"), "Dụng cụ": ("equipment", "c2"),
         "Sơ đồ": ("mind", "c3"), "Mô phỏng": ("equipment", "c2"), "Luyện tập": ("practice", "c0"), "Hỏi đáp": ("chat", "c1")}


def home_ui():
    left, right = st.columns([2.15, 1], gap="large")
    with left:
        st.markdown(f'<div class="sec-title">{icon_svg("home", "currentColor", 22)}{tx("Khám phá nhanh")}</div>', unsafe_allow_html=True)
        with st.container(key="tilesrow"):
            for c, (txt, ic, cls, target), i in zip(st.columns(5, gap="small"), TILES, range(5)):
                with c, st.container(key=f"qk_{i}"):
                    st.markdown(f'<div class="tile {cls}"><div class="tt"><div class="ib">{icon_svg(ic, "currentColor", 18, 2)}</div><b>{_tile_text(txt, target)}</b></div>'
                                f'<span class="ar">{icon_svg("arrow", "currentColor", 18, 2.2)}</span></div>', unsafe_allow_html=True)
                    st.button("Mở", key=f"qkb_{i}", on_click=go, args=(target,))

        st.markdown('<div class="feat">' + '<i></i>'.join(f"<span>{e} {tx(t)}</span>" for e, t in FEATS) + '</div>', unsafe_allow_html=True)

    with right:
        with st.container(key="quick"):
            st.markdown(f'<div class="qhead"><div class="qi">{icon_svg("pen", "#fff", 24, 2)}</div><div><b>{tx("Nhập nhanh")}</b>'
                        f'<span>{tx("Nhập công thức để tra cứu ngay")}</span></div></div>', unsafe_allow_html=True)
            with st.form("quick_form", border=False, clear_on_submit=False):
                qa, qb = st.columns([5, 1.2], vertical_alignment="center", gap="small")
                with qa:
                    st.text_input("Công thức", key="quick_in", placeholder="VD: C4H10O, CCO, axit axetic…", label_visibility="collapsed")
                with qb:
                    st.form_submit_button("➜", on_click=on_quick)

        with st.container(key="res"):
            st.markdown(f'<div class="rsh">{icon_svg("equipment", "currentColor", 24)}'
                        f'<div><b>{tx("Tài liệu học tập")}</b><span>{html.escape(tx("Kho tài liệu & công thức quan trọng"))}</span></div></div>', unsafe_allow_html=True)
            if st.button("Bảng tuần hoàn", icon=":material/grid_view:", key="r_pt"):
                periodic_dialog() if is_logged_in() else auth_dialog()
            if st.button("Bảng tính tan", icon=":material/water_drop:", key="r_sol"):
                solubility_dialog() if is_logged_in() else auth_dialog()
            if st.button("Công thức hữu cơ", icon=":material/hub:", key="r_org"):
                organic_dialog() if is_logged_in() else auth_dialog()
            if st.button("Phương trình phản ứng", icon=":material/science:", key="r_rx"):
                reactions_dialog() if is_logged_in() else auth_dialog()
            if st.button("Mẹo & lưu ý", icon=":material/lightbulb:", key="r_tip"):
                tips_dialog() if is_logged_in() else auth_dialog()

        hist = st.session_state.hist
        rows = "".join(
            f'<div class="hrow"><div class="hc {HKIND.get(h.get("k"), HKIND["Công thức"])[1]}">{icon_svg(HKIND.get(h.get("k"), HKIND["Công thức"])[0], "currentColor", 20, 2)}</div>'
            f'<div><b>{html.escape(h["q"][:40] + ("…" if len(h["q"]) > 40 else ""))}</b><small>{html.escape(tx(h.get("k", "")))} · {html.escape(tx("Hôm nay", "Today") if h.get("d", _now().strftime("%Y-%m-%d")) == _now().strftime("%Y-%m-%d") else h["d"])} · {h["t"]}</small></div></div>'
            for h in hist[:6]) or f'<div class="hempty">{html.escape(tx("Chưa có lượt tra cứu nào. Hãy thử Nhập nhanh hoặc dùng một công cụ bên trái.", sep=" | "))}</div>'
        st.markdown(f'<div class="rcard"><div class="rh">{icon_svg("search", "currentColor", 22)}<b>{tx("Lịch sử tra cứu")}</b></div>{rows}</div>', unsafe_allow_html=True)
        if hist:
            with st.container(key="hclear"):
                st.button("Xóa lịch sử", key="hist_clear", on_click=clear_all_hist)
        st.markdown(f'<div class="quote"><div class="lf">🌿</div><p>“{html.escape(tx("Hóa học không khó, chỉ cần bạn có công cụ đúng!", sep=" | "))}”<em>— {html.escape(APP_NAME)}</em></p></div>',
                    unsafe_allow_html=True)


def _initials(name=None):
    au = cur_auth()
    if cr.is_teacher(au):
        return "GV"
    if not cr.is_student(au):
        return "👤"
    w = (name or au["name"]).split()
    return (w[0][0] + (w[-1][0] if len(w) > 1 else (w[0][1] if len(w[0]) > 1 else ""))).upper()


def my_profile(force=False):
    """Thống kê thật của học sinh đang đăng nhập (đọc từ bảng bài nộp, nhớ 15 giây). None nếu không đọc được."""
    au = cur_auth()
    if not cr.is_student(au):
        return None
    c = st.session_state.get("_prof")
    if c and not force and c[1] == au["key"] and time.time() - c[0] < 15:
        return c[2]
    try:
        p = cr.profile(cr.submissions(au, force=force), MAX_TRIES)
    except OSError:
        return None
    st.session_state["_prof"] = (time.time(), au["key"], p)
    return p


def conn_state():
    """(màu, chữ) trạng thái nơi lưu dữ liệu."""
    if hs.backend_name() == "Google Sheets":
        return ("err", tx("Mất kết nối Google Sheets", "Google Sheets offline")) if hs.last_error else ("ok", tx("Đã kết nối · Google Sheets", "Connected · Google Sheets"))
    return "warn", tx("Lưu tạm trên máy chủ", "Temporary server storage")


_BANK_TOPIC = {}


def bank_by_topic():
    """{chủ đề: [tên chất]} tính từ ngân hàng đề bằng RDKit (cùng cách đặt chủ đề với bài nộp)."""
    if not _BANK_TOPIC:
        for b in BANK:
            m = Chem.MolFromSmiles(b[1])
            if m is not None:
                _BANK_TOPIC.setdefault(topic_of(m), []).append(b[0])
    return _BANK_TOPIC


def _start_practice(name):
    st.session_state["pr_mode"] = "free"
    st.session_state["pr_kind"] = PRACTICE_KINDS["draw"]
    st.session_state["pq"] = new_qstate({"k": "draw", "n": name})
    st.session_state["pr_pick"] = name
    go(PRACTICE_TAB)


def _auth_form():
    """Nội dung hộp thoại: chọn vai trò, đăng ký lần đầu / đăng nhập lại, hiện-ẩn PIN, kiểm tra dữ liệu."""
    role = st.radio(tx("Bạn là", "I am a"), [cr.STUDENT, cr.TEACHER], horizontal=True, key="au_role",
                    format_func=lambda r: tx("🎓 Học sinh", "🎓 Student") if r == cr.STUDENT else tx("👩‍🏫 Giáo viên", "👩‍🏫 Teacher"))
    show = st.checkbox(tx("Hiện PIN / mã", "Show PIN / code"), key="au_show")
    ptype = "default" if show else "password"
    if role == cr.TEACHER:
        tmode = st.radio(tx("Bạn đã có mã giáo viên chưa?", "Do you have a teacher code?"), ["login", "register"], horizontal=True, key="au_tmode",
                         format_func=lambda m: tx("Đã có mã", "I have a code") if m == "login" else tx("Chưa có mã, tạo mã", "No code yet, create one"))
        if tmode == "login":
            tcode = st.text_input(tx("Mã giáo viên", "Teacher code"), type=ptype, key="au_tcode")
            if st.button(tx("Đăng nhập giáo viên", "Teacher log in"), type="primary", key="au_go_t"):
                err = submit_teacher_auth(tcode)
                if err:
                    st.error(err)
                else:
                    st.rerun()
            return
        tname = st.text_input(tx("Họ và tên giáo viên", "Teacher's full name"), key="au_tname", max_chars=40, placeholder=tx("Nguyễn Thị Lan", "Your full name"))
        if st.button(tx("🎲 Tạo mã ngẫu nhiên", "🎲 Generate a random code"), key="au_gen_t"):
            g = cr.gen_teacher_code()
            st.session_state["au_tnew"] = g
            st.session_state["au_tnew2"] = g
        tnew = st.text_input(tx("Mã giáo viên của bạn (6-24 ký tự)", "Your teacher code (6-24 characters)"), type=ptype, key="au_tnew", max_chars=24)
        tnew2 = st.text_input(tx("Nhập lại mã", "Repeat the code"), type=ptype, key="au_tnew2", max_chars=24)
        if tnew2 and tnew2 != tnew:
            st.caption("⚠️ " + tx(*_TCH_ERR["mismatch"]))
        tinv = ""
        if _TEACHER_INVITE:
            tinv = st.text_input(tx("Mã mời (quản trị viên cung cấp)", "Invitation code (from your administrator)"), type=ptype, key="au_tinv")
        st.caption(tx("Hãy ghi nhớ mã này: lần sau bạn chọn \"Đã có mã\" và nhập đúng mã để vào. Mã được lưu dạng băm, không ai xem lại được; quên mã thì phải tạo mã mới.",
                      "Remember this code: next time choose \"I have a code\" and enter it. It is stored hashed and cannot be viewed again; if you forget it you must create a new one."))
        if st.button(tx("Tạo mã và vào với vai trò giáo viên", "Create code and join as teacher"), type="primary", key="au_go_tr"):
            err = submit_teacher_register(tname, tnew, tnew2, tinv)
            if err:
                st.error(err)
            else:
                st.rerun()
        return
    mode = st.radio(tx("Bạn đã có tài khoản chưa?", "Do you have an account?"), ["login", "register"], horizontal=True, key="au_mode",
                    format_func=lambda m: tx("Đã có tài khoản", "I have an account") if m == "login" else tx("Đăng ký lần đầu", "First time here"))
    code = st.text_input(tx("Mã lớp (giáo viên cung cấp)", "Class code (from your teacher)"), key="au_code", max_chars=20, placeholder="10A1")
    name = st.text_input(tx("Họ và tên", "Full name"), key="au_name", max_chars=40, placeholder=tx("Nguyễn Văn An", "Your full name"))
    pin = st.text_input(tx("PIN cá nhân (4-12 ký tự)", "Personal PIN (4-12 characters)"), type=ptype, key="au_pin", max_chars=12)
    pin2 = ""
    if mode == "register":
        pin2 = st.text_input(tx("Nhập lại PIN", "Repeat the PIN"), type=ptype, key="au_pin2", max_chars=12)
        if pin2 and pin2 != pin:
            st.caption("⚠️ " + _auth_error("mismatch"))
        st.caption(tx("Lần sau em chỉ cần chọn \"Đã có tài khoản\" và nhập đúng PIN này. Mỗi tên chỉ có một tài khoản trong lớp.",
                      "Next time choose \"I have an account\" and enter this same PIN. Each name has one account per class."))
    if st.button(tx("Tạo tài khoản và vào lớp", "Create account and join") if mode == "register" else tx("Đăng nhập", "Log in"),
                 type="primary", key="au_go_s"):
        err = submit_student_auth(mode, code, name, pin, pin2)
        if err:
            st.error(err)
        else:
            st.rerun()


if hasattr(st, "dialog"):
    @st.dialog("🔐 Tài khoản · Account")
    def auth_dialog():
        _auth_form()
else:   # bản Streamlit cũ chưa có st.dialog: hiện ngay trong thanh bên
    def auth_dialog():
        with st.sidebar.expander("🔐 Tài khoản · Account", expanded=True):
            _auth_form()


@st.dialog("👤 Hồ sơ của tôi · My profile", width="large")
def profile_dialog():
    au = cur_auth()
    if not cr.is_student(au):
        st.info(tx("Cần đăng nhập học sinh.", "Student login required."))
        return
    st.markdown(f'<div class="acct" style="background:#eef0ff;border-color:#dcdfff"><div class="acct-top"><div class="avt">{html.escape(_initials())}</div>'
                f'<div class="who"><b style="color:#1d2a8a">{html.escape(au["name"])}</b><span style="color:#4b5280">{html.escape(tx("Lớp", "Class"))} {html.escape(au["cls"])}'
                f' · {html.escape(tx("Mã định danh", "ID"))}: {html.escape(au["uid"])}</span></div></div></div>', unsafe_allow_html=True)
    prof = my_profile(force=True)
    c1, c2, c3, c4 = st.columns(4)
    if prof is None:
        st.error(tx("Chưa đọc được dữ liệu học tập: ", "Could not read your learning data: ") + hs.last_error)
    else:
        c1.metric(tx("Câu đã làm", "Questions tried"), prof["done"])
        c2.metric(tx("Câu hoàn thành", "Finished"), prof["finished"])
        c3.metric(tx("Độ chính xác", "Accuracy"), "–" if prof["accuracy"] is None else f'{prof["accuracy"]}%')
        c4.metric(tx("Lượt tra cứu", "Lookups"), len(st.session_state.hist))
        if not prof["attempts"]:
            st.info(tx("Chưa có hoạt động học tập. Làm bài ở tab Luyện tập để thấy thống kê và gợi ý ôn tập tại đây.",
                       "No learning activity yet. Do exercises in the Practice tab to see statistics and review suggestions here."))
            if st.button(tx("📝 Vào Luyện tập", "📝 Go to Practice"), key="pf_prac", type="primary"):
                go(PRACTICE_TAB)
                st.rerun()
        else:
            st.markdown("#### " + tx("Chủ đề hay sai", "Topics you often miss"))
            if not prof["weak"]:
                st.success(tx("Chưa sai chủ đề nào. Tiếp tục luyện thêm để giữ phong độ!", "No missed topics yet. Keep practising!"))
            for w in prof["weak"][:4]:
                st.progress(w["pct"] / 100, text=tx(f'{w["topic"]}: sai {w["wrong"]}/{w["n"]} lượt ({w["pct"]}%)', f'{w["topic"]}: {w["wrong"]}/{w["n"]} wrong ({w["pct"]}%)'))
            solved = {k.split(":", 1)[1] for k in prof["solved_keys"] if ":" in k}
            recs = []
            for w in prof["weak"][:3]:
                todo = [n for n in bank_by_topic().get(w["topic"], []) if n not in solved][:3]
                if todo:
                    recs.append((w["topic"], todo))
            if recs:
                st.markdown("#### " + tx("Gợi ý ôn tập", "Suggested review"))
                st.caption(tx("Dựa trên các câu em đã làm sai; chỉ gợi ý những chất em chưa làm đúng.", "Based on the questions you got wrong; only compounds you have not solved yet."))
                for i, (topic, todo) in enumerate(recs):
                    for j, n in enumerate(todo[:2]):
                        a, b = st.columns([4, 1.6], vertical_alignment="center")
                        a.markdown(f"**{html.escape(topic)}** → {html.escape(n)}")
                        if b.button(tx("Luyện ngay", "Practise"), key=f"pf_rec_{i}_{j}"):
                            _start_practice(n)
                            st.rerun()
    with st.expander(tx("🔑 Đổi PIN", "🔑 Change PIN")):
        o = st.text_input(tx("PIN hiện tại", "Current PIN"), type="password", key="pf_old", max_chars=12)
        n1 = st.text_input(tx("PIN mới (4-12 ký tự)", "New PIN (4-12 characters)"), type="password", key="pf_new", max_chars=12)
        n2 = st.text_input(tx("Nhập lại PIN mới", "Repeat the new PIN"), type="password", key="pf_new2", max_chars=12)
        if st.button(tx("Lưu PIN mới", "Save new PIN"), key="pf_pin"):
            try:
                r = cr.change_pin(au, o, n1, n2)
            except OSError:
                r = None
                st.error(tx("Không kết nối được nơi lưu dữ liệu: ", "Cannot reach the data store: ") + hs.last_error)
            if r == "ok":
                _set_token(True, au)
                st.success(tx("Đã đổi PIN.", "PIN changed."))
            elif r:
                st.error(_auth_error(r))
    st.caption(tx("Tên và mã lớp là danh tính của em nên không tự sửa được; cần đổi thì nhờ giáo viên.", "Your name and class code are your identity and cannot be edited here; ask your teacher."))
    if st.button(tx("Đăng xuất", "Log out"), key="pf_out"):
        do_logout()
        st.rerun()


def sidebar_account():
    """Thẻ tài khoản ở thanh bên: khách / học sinh / giáo viên."""
    au = cur_auth()
    if not au:
        st.markdown(f'<div class="acct"><div class="acct-top"><div class="avt guest"><svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/></svg></div>'
                    f'<div class="who"><b>{html.escape(tx("Khách", "Guest"))}</b><span>{html.escape(tx("Chưa đăng nhập", "Not logged in"))}</span></div></div></div>',
                    unsafe_allow_html=True)
        if st.button(tx("🔐 Đăng nhập / Tham gia lớp", "🔐 Log in / Join a class"), key="sb_login", type="primary"):
            auth_dialog()
        return
    dot, label = conn_state()
    status = f'<div class="acct-st"><i class="{dot}"></i><span>{html.escape(label)}</span></div>'
    if cr.is_teacher(au):
        st.markdown(f'<div class="acct"><div class="acct-top"><div class="avt">GV</div><div class="who"><b>{html.escape(tx("Giáo viên", "Teacher"))}</b>'
                    f'<span>{html.escape(tx("Quản lý lớp học", "Class management"))}</span></div></div>{status}</div>', unsafe_allow_html=True)
        st.button(tx("Quản lý lớp", "Manage classes"), key="sb_manage", on_click=go, args=(HISTORY_TAB,))
        st.button(tx("Đăng xuất", "Log out"), key="sb_out", on_click=do_logout)
        return
    prof = my_profile()
    if prof is None:
        kpi = f'<div class="acct-none">{html.escape(tx("Chưa tải được thống kê", "Statistics unavailable"))}</div>'
    elif not prof["attempts"]:
        kpi = f'<div class="acct-none">{html.escape(tx("Chưa có hoạt động học tập", "No learning activity yet"))}</div>'
    else:
        kpi = (f'<div class="acct-kpi"><div><b>{prof["finished"]}</b><span>{html.escape(tx("Bài hoàn thành", "Finished"))}</span></div>'
               f'<div><b>{prof["accuracy"]}%</b><span>{html.escape(tx("Chính xác", "Accuracy"))}</span></div></div>')
    st.markdown(f'<div class="acct"><div class="acct-top"><div class="avt">{html.escape(_initials())}</div><div class="who"><b>{html.escape(au["name"])}</b>'
                f'<span>{html.escape(tx("Lớp", "Class"))} {html.escape(au["cls"])}<em class="role">{html.escape(tx("Học sinh", "Student"))}</em></span></div></div>'
                f'{status}{kpi}</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if c1.button(tx("Hồ sơ", "Profile"), key="sb_prof"):
        profile_dialog()
    c2.button(tx("Đăng xuất", "Log out"), key="sb_out", on_click=do_logout)


_ACCT_SLOT = None
with st.sidebar:
    st.markdown(f'<div class="sb-brand"><img src="{_uri(LOGO_SVG)}"><div><b>{html.escape(APP_NAME[:3])}<i>{html.escape(APP_NAME[3:])}</i></b>'
                f'<span>{html.escape(tx("AI trong tay – Hóa học dễ dàng", sep=" | "))}</span></div></div>', unsafe_allow_html=True)
    st.selectbox("🌐 Ngôn ngữ · Language", i18n.LANGS, format_func=i18n.LANG_NAMES.get, key="lang", on_change=on_lang)
    _ACCT_SLOT = st.container(key="sbacct")   # điền ở cuối trang để số liệu phản ánh cả bài vừa nộp
    with st.container(key="sidenav"):
        st.radio("Điều hướng", NAV_OPTS, index=None, key="nav_side", on_change=on_side, label_visibility="collapsed",
                 format_func=lambda o: o if (o == HOME or is_logged_in()) else "🔒 " + o)
    with st.container(key="aibtn"):
        st.markdown(f'<div class="aicard"><img src="{_uri(AI_FACE)}"><div><b>{tx("Trợ lý AI")}</b><span>{tx("Hỏi bất cứ điều gì về")}<br>{tx("hóa học, mình luôn ở đây!")}</span></div>'
                    '<div class="go">›</div></div>', unsafe_allow_html=True)
        st.button("Mở trợ lý AI", key="aibtn_b", on_click=go, args=(ASSIST,))
    st.markdown(f'<div class="mascot"><img src="{_uri(MASCOT_SVG)}"><div class="hw">{tx("Học hóa") if i18n.lang() != "bi" else "Học hóa"}<br>{tx("thật dễ!") if i18n.lang() != "bi" else "thật dễ!"}</div></div>', unsafe_allow_html=True)

# Trên điện thoại: tự đóng thanh bên sau khi chọn một mục (mã chạy trong trang chính để không bị hủy khi làm mới)
components.html("""<script>
(function(){const w=window.parent,d=w.document;if(w.__molsnapNav)return;w.__molsnapNav=true;
const s=d.createElement('script');
s.textContent="document.addEventListener('click',function(e){if(window.innerWidth>640)return;"
+"var o=e.target.closest('[data-testid=\\"stRadioOption\\"],.st-key-aibtn');"
+"if(o&&o.closest('[data-testid=\\"stSidebar\\"]')){setTimeout(function(){"
+"var b=document.querySelector('[data-testid=\\"stSidebarCollapseButton\\"] button');if(b)b.click();},350);}},true);";
d.head.appendChild(s);})();
</script>""", height=0)

topbar()

def login_gate():
    page_banner("search", "Cần đăng nhập", "Đăng nhập để sử dụng các tab công cụ.")
    with st.container(key="panel"):
        st.warning(tx("🔒 Bạn chưa đăng nhập nên chưa thể dùng tab này. Hãy đăng nhập (hoặc tham gia lớp) để mở khóa toàn bộ các tab.",
                      "🔒 You are not logged in, so this tab is locked. Log in (or join a class) to unlock all tabs."))
        c1, c2, _ = st.columns([1.3, 1, 2])
        if c1.button(tx("🔐 Đăng nhập / Tham gia lớp", "🔐 Log in / Join a class"), key="gate_login", type="primary"):
            auth_dialog()
        c2.button(tx("🏠 Về Trang chủ", "🏠 Back to Home"), key="gate_home", on_click=go, args=(HOME,))


nav = st.session_state.nav
if nav in NAV_OPTS + [ASSIST] and nav != HOME and not is_logged_in():
    login_gate()
elif nav == PRACTICE_TAB:
    page_banner("practice", PRACTICE_TAB, "")
    with st.container(key="panel"):
        practice_ui()
        tab_history_ui(nav)
elif nav == TEST_TAB:
    page_banner("test", TEST_TAB, "Làm bài kiểm tra giáo viên giao và xem điểm.")
    with st.container(key="panel"):
        practice_assign_ui(cr.TEST)
elif nav == HISTORY_TAB:
    page_banner("search", HISTORY_TAB, "Theo dõi học sinh, giao bài và xem kết quả cả lớp." if cr.is_teacher(cur_auth())
                else "Xem lại những gì bạn đã tra cứu ở từng tab.")
    with st.container(key="panel"):
        if cr.is_teacher(cur_auth()):
            teacher_ui()
        else:
            my_history_ui()
elif nav == HOME or (nav not in LABELS and nav != ASSIST):
    hero()
    home_ui()
elif nav == ASSIST:
    page_banner("chat", "Trợ lý AI", "Hỏi bất cứ điều gì về hóa học, mình luôn ở đây!")
    with st.container(key="panel"):
        assistant_ui()
        tab_history_ui(ASSIST)
else:
    label, title, desc, fn, ic = SECTIONS[LABELS.index(nav)]
    page_banner(ic, title, desc)
    with st.container(key="panel"):
        fn()
        tab_history_ui(nav)

# Thanh bên được điền sau cùng để thống kê gồm cả bài vừa nộp ở trang này.
_toast = st.session_state.pop("_toast", None)
if _toast:
    st.toast(_toast)
with _ACCT_SLOT:
    sidebar_account()
