# Thiết kế MolSnap-CVR (Chemical Structure Verification & Repair)

"CVR" là tên làm việc của quy trình trong dự án này, không phải tên một thuật toán đã được công bố. Mỗi bước dùng kỹ thuật đã có; phần do nhóm thiết kế là cách ghép nối (xem `MO_TA_TINH_MOI.md`).

## Sơ đồ

```
Ảnh -> [Gemini đọc k lần] -> k đồ thị ứng viên -> đồng thuận + vector bất đồng
    -> quy kết nguồn (máy đọc sai | học sinh vẽ sai | chưa rõ)
    -> học sinh xem hình dựng lại, xác nhận hoặc tự chỉnh
    -> ErrorLab (hóa trị, nguyên tử, công thức, bậc liên kết, mạch, nhóm chức, vị trí)
    -> StepCoach (gợi ý 1, 2, 3) -> học sinh sửa -> chạy lại từ đầu -> lưu hồ sơ
```

## Cấu trúc dữ liệu (`molsnap_core/graph.py`)

* `Atom(id, el, h, charge)`: `h` là số H học sinh đã vẽ; `None` nghĩa là công thức khung (H ngầm định).
* `MolGraph`: `atoms: {id: Atom}`, `bonds: {frozenset({i, j}): bậc}`. **Đồ thị giữ nguyên bài làm kể cả khi sai hóa trị**, không chuẩn hóa như SMILES/RDKit.
* `canonical(g, mode)`: chuỗi chuẩn bất biến khi đánh số lại nguyên tử (tinh chỉnh màu kiểu Weisfeiler–Lehman + tách nhánh khi đối xứng). Ba chế độ: `full` (đủ cấu tạo), `skeleton` (nguyên tố và liên kết, bỏ bậc và H), `carbon` (chỉ khung C).

## Mã giả các thuật toán chính

**Đồng thuận (`cvr.consensus`)**
```
ok = các ứng viên không rỗng; k = |ok|
mode = chuỗi chuẩn xuất hiện nhiều nhất; dong_thuan = số ứng viên = mode / k
vector = [1 - dong_thuan, 1 - Jaccard liên kết TB, 1 - Jaccard nguyên tử TB,
          tỉ lệ ứng viên sai hóa trị, 1 - tỉ lệ cùng công thức, tỉ lệ không liên thông]
```

**Quy kết nguồn (`cvr.attribute_source`)**
```
nếu k = 0                      -> chua_ro
nếu học sinh đã xác nhận hình  -> hoc_sinh        (coi hình dựng lại là bài làm)
nếu k = 1                      -> chua_ro, yêu cầu xác nhận
nếu dong_thuan = 1             -> hoc_sinh (có lỗi) hoặc hop_le
nếu bất đồng:
    có ứng viên hợp lệ và có ứng viên sai    -> nhan_dang_ai (máy có thể đọc nhầm)
    mọi ứng viên đều hợp lệ                  -> chua_ro
    mọi ứng viên sai CÙNG loại lỗi hóa trị    -> hoc_sinh nhưng vẫn yêu cầu xác nhận
    còn lại                                   -> chua_ro
```
Các quy tắc này **minh bạch, chưa hiệu chuẩn**. MolSnap không hiển thị phần trăm tin cậy.

**Chẩn đoán (`diagnose.diagnose`)**
```
1. không đủ căn cứ nếu: rỗng | nguyên tố chưa hỗ trợ | hình không liên thông
2. lỗi hóa trị từng nguyên tử (thừa | thiếu | không khớp)
3. so số nguyên tử nặng với đề -> thieu_thua_nguyen_tu
4. nếu có lỗi hóa trị: DỪNG, không kết luận về đồng phân (cấu trúc chưa hợp lệ)
5. cùng khung nguyên tử, khác bậc liên kết  -> sai_bac_lien_ket (+ sai_cong_thuc nếu lệch H)
6. lệch H, khung khác                       -> sai_cong_thuc (không kết luận quan hệ đồng phân)
7. cùng công thức:
     khung nguyên tử khác, nhóm chức khác    -> nham_dong_phan
     nhóm chức giống:
        khung cacbon giống                   -> sai_vi_tri_nhom_chuc
        khung cacbon khác                    -> sai_mach_cacbon
```
Nhóm chức (ancol, ete, axit, este, anđehit, xeton, amin, amit, nitro, halogen, C=C, C≡C, vòng benzen) nhận diện bằng quy tắc cục bộ trên đồ thị, không dùng AI.

## API giữa các mô-đun

| Mô-đun | Hàm chính | Vào | Ra |
|---|---|---|---|
| `parse` | `from_smiles`, `from_condensed`, `from_ai_graph` | chuỗi hoặc dict | `MolGraph` (không sửa lỗi), `ParseError` khi sai cú pháp |
| `cvr` | `verify_and_diagnose(cands, target, confirmed)` | danh sách ứng viên | dict kết quả có `trang_thai`, `loi`, `nguon`, `tinh_huong` |
| `diagnose` | `diagnose(student, target, confirmed)` | hai `MolGraph` | `trang_thai` (dung, sai, khong_du_thong_tin), danh sách lỗi có vị trí |
| `coach` | `hints_for(loi, ten)` | một lỗi | đúng 3 gợi ý hoặc `None` |
| `session` | `PracticeSession` | đề, bài nộp | gợi ý, kết quả, tóm tắt |
| `store` | `Store` | tóm tắt lượt | SQLite, xuất/nạp CSV, xóa theo mã |
| `adapt` | `next_exercise`, `skill_profile` | lịch sử | bài đề xuất kèm lý do |
| `evidence`, `ablation` | chỉ số, đối chứng A, B, C, C2 | ca kiểm thử, bản ghi Gemini | bảng chỉ số, CSV |
| `ui` | `render(st, deps, ...)` | `st` và các hàm phụ thuộc | quy trình giao diện |

## Trường hợp biên đã xử lý

Ảnh không đọc được (không tự tạo kết quả); hình rời nhau; liên kết tới nguyên tử không tồn tại; liên kết trùng; nguyên tố lạ; H vẽ riêng (gộp vào nguyên tử nặng, H nối hai nguyên tử thì giữ lại để báo lỗi hóa trị); cú pháp công thức thu gọn sai; học sinh nộp khi AI bất đồng; xem đáp án sớm bị chặn; lượt đã kết thúc không nộp thêm được; mất cơ sở dữ liệu (xuất/nạp CSV).

## Giới hạn thiết kế

Hóa trị cố định theo SGK (S, P có nhiều hóa trị nhưng điện tích chỉ hỗ trợ N⁺, O⁻/O⁺, N⁻); không xét đồng phân lập thể; vòng thơm chỉ kiểu benzen khi đọc SMILES; công thức thu gọn không viết được vòng; nhận diện nhóm chức là tập con của chương trình phổ thông; so vị trí nhóm chức dùng mạch dài nhất, mạch có vòng thì không đánh số.
