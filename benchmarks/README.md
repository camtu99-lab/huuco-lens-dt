# Bộ dữ liệu kèm theo và nguồn gốc

| Tệp | Nội dung | Nguồn đáp án | Dùng để |
|---|---|---|---|
| `loi_cau_truc_tong_hop.csv` | 40 bài làm GÕ TAY (công thức thu gọn) cho 7 loại lỗi và ca đúng | Người soạn **gán nhãn bằng suy luận hóa học trước khi chạy máy** | Kiểm thử hồi quy bộ quy tắc ErrorLab |
| `dong_phan_chuan.csv` | 18 công thức và số đồng phân cấu tạo | Dãy số đồng phân ankan (OEIS A000602) và đếm tay các lớp chất (ghi ở cột `nguon_dap_an`) | Kiểm toán thuật toán đếm đồng phân |

## Giới hạn
* Bộ ca lỗi **không phải bài làm thật của học sinh** và **không có ảnh**: không đo độ chính xác đọc ảnh, không đại diện cho cách học sinh sai trong thực tế. Người gán nhãn cũng là người viết quy tắc, nên độ khớp cao là điều dễ đạt.
* Một ca ban đầu bị lệch vì **chính tôi gán nhãn sai**, minh họa rằng nhãn gán tay cũng cần hai người kiểm.
* Số đồng phân chuẩn chỉ tính đồng phân **cấu tạo** (không lập thể). Các số "đếm tay" tôi tự đếm theo lớp chất, chưa có người thứ hai kiểm; số ankan có nguồn OEIS.
* Công thức có N và O, hoặc S, không nằm trong bộ này vì thuật toán chưa sinh đủ nitro và S hóa trị cao.
