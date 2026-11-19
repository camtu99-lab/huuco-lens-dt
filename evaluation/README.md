# Thu thập dữ liệu và đánh giá có thể tái lập

**Hiện không có dữ liệu thực nghiệm nào trong gói này.** Thư mục chỉ chứa cấu trúc, quy trình và mã. Mọi con số phải đến từ dữ liệu bạn thu thập.

## 1. Bộ dữ liệu (một dòng mỗi mẫu): `dataset_template.csv`

| Cột | Ý nghĩa |
|---|---|
| `ma_mau` | Mã ẩn danh (không chứa tên, lớp, ngày sinh) |
| `tep_anh` | Tên tệp ảnh (ảnh lưu riêng, đặt tên theo mã mẫu) |
| `nguon_va_quyen` | Ai vẽ, đã có đồng ý (học sinh và phụ huynh) chưa, giấy phép sử dụng |
| `dieu_kien` | `sach`, `viet_tay`, `mo`, `lech`, `nhieu_net`... |
| `muc_kho` | 1 đến 4 |
| `dap_an_smiles` | Chất đề yêu cầu (người có chuyên môn xác nhận) |
| `do_thi_chuan_smiles` | Cấu trúc **đúng như hình đã vẽ**, kể cả khi hình sai (người vẽ lại từ ảnh) |
| `nhan_loi_nguoi_1`, `nhan_loi_nguoi_2` | Mã lỗi (ngăn bởi `;`) do hai người gán độc lập, **không thấy kết quả của MolSnap** |
| `nhan_loi_chot` | Nhãn cuối sau khi hai người thống nhất (hoặc người thứ ba quyết định) |
| `vi_tri_loi` | Mô tả vị trí lỗi trên hình (ghi chú; xem mục hạn chế) |
| `huong_sua_hop_le` | Một cách sửa đúng |
| `tap` | `phat_trien` hoặc `kiem_thu` (xem mục 3) |

Mã lỗi hợp lệ: `sai_hoa_tri`, `thieu_thua_nguyen_tu`, `sai_cong_thuc`, `sai_bac_lien_ket`, `sai_mach_cacbon`, `nham_dong_phan`, `sai_vi_tri_nhom_chuc`, `sai_yeu_cau_de`. Bài đúng để trống.

## 2. Quy trình gán nhãn
1. Hai giáo viên hóa học gán nhãn độc lập, không xem đầu ra của MolSnap hay Gemini.
2. Tính hệ số Cohen kappa (`molsnap_core.evidence.cohen_kappa`) và báo cáo kèm theo kết quả.
3. Ca bất đồng do người thứ ba (hoặc thảo luận) quyết định; ghi lại số ca bất đồng.
4. **Cấm** dùng kết quả MolSnap làm đáp án chuẩn.

## 3. Tránh rò rỉ dữ liệu
* Chia theo **học sinh**, không chia theo ảnh: mọi ảnh của một học sinh vào cùng một tập.
* Tập `phat_hien` (dùng chỉnh quy tắc, ngưỡng, lời dặn) và tập `kiem_thu` (chỉ chạy một lần cuối) **không giao nhau**.
* Không chỉnh quy tắc sau khi đã xem kết quả trên tập kiểm thử; nếu buộc phải chỉnh, ghi lại và coi tập đó đã bị "nhiễm".

## 4. Bốn phương án đối chứng
A Gemini độc lập; B thêm kiểm tra hóa trị và so cấu trúc; C thêm bộ quy tắc chẩn đoán; C2 thêm đối chứng nhiều lần đọc và từ chối kết luận; D MolSnap đầy đủ với học sinh (đo trên nhật ký học tập, cần thiết kế thực nghiệm sư phạm có nhóm đối chứng và bài kiểm tra trước/sau).

Ghi lại đầu ra của Gemini cho từng mẫu vào `recorded_outputs_template.json` (một lần, ghi cả thời gian và số lần gọi API), rồi chạy:
```
python evaluation/run_ablation.py --cases bo_du_lieu.csv --records gemini_da_ghi.json --sessions ho_so.csv --out ket_qua
```
Chỉ số: khớp đồ thị tuyệt đối, P/R/F1 mức nguyên tử và liên kết (xấp xỉ theo đa tập), P/R/macro-F1 phân loại lỗi, độ phủ và số ca từ chối, khoảng tin cậy Wilson, thời gian, số lần gọi API.

## 5. Hạn chế của mã đánh giá
* **Độ chính xác định vị lỗi chưa được đo bằng mã**: cần nhãn vị trí và ánh xạ nguyên tử giữa ảnh và đồ thị chuẩn.
* F1 mức nguyên tử và liên kết tính theo đa tập, không xét vị trí không gian.
* **Hiệu chuẩn độ tin cậy** (`calibration.py`: hồi quy logistic, Brier, ECE, đường cong độ phủ–độ chính xác) chỉ dùng khi đã có đủ ca có nhãn; tập hiệu chuẩn phải tách khỏi tập kiểm thử.
* Chi phí API tính bằng số lần gọi ghi lại, không quy đổi ra tiền.

## 6. Quyền riêng tư
Không thu tên, lớp, trường. Ảnh lưu có mã hóa hoặc ở nơi hạn chế truy cập, xóa theo yêu cầu. Trước khi dùng ảnh học sinh gửi Gemini phải có đồng ý theo quy định của nhà trường.
