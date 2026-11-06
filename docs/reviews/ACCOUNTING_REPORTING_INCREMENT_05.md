# Kế toán độc lập và báo cáo local — increment 05

Điều phối ghép source nghiệp vụ vào nhánh review riêng, rồi chỉ chuyển phần đã kiểm sang `C:\Users\NC\Desktop\UNILA{\cafe_fin`. Increment này nối accounting/reporting với records/contracts đang có; không đổi source hoặc DB CRM cũ, không dùng dữ liệu thật và không thêm Google OAuth.

## Phạm vi đã ghép

Kế toán có sổ/cột/mapping cấu hình, CRUD/version/audit, bảng phân trang và chỉnh ô, copy/paste/fill có giới hạn, công thức đã kiểm, nguồn gốc Excel bất biến và import theo background jobs. Macro/external links không chạy. Dữ liệu chưa liên kết CRM vẫn hợp lệ; dòng kế toán không sinh tiền hoặc thay tồn kho của module khác.

Import phân loại mới/trùng/lỗi theo sheet/dòng/ô, cho xác nhận phần hợp lệ, giữ lỗi để sửa tiếp. Attempt giữ snapshot đầu vào; các chunk pending có receipt/checkpoint, chỉ hiện đồng thời sau publication. Sửa/import tiếp không tạo thêm lineage cho dòng đã ghi. Lọc ô trống nay gồm cả dòng lịch sử chưa có cell sau khi thêm cột nullable. SchemaEditor giữ nguyên payload/key/version sau mất ACK, khóa chỉnh sửa tới khi xác nhận; thử lại không tạo sổ hoặc schema revision thứ hai.

P2 trạng thái export đã được tái hiện và sửa: trước đây response có thể ghép `COMPLETED` mới với `file_id=null` cũ, làm UI dừng polling trước khi có nút tải. Core thêm `JobService.status(connection=conn)` và endpoint kiểm quyền/owner, đọc job cùng export trong một explicit snapshot. Probe worker thật sau sửa trả `RUNNING/null` rồi lần mới `COMPLETED/file UUID`; tải file 200. Instrumentation chỉ được cập nhật để forward keyword `connection`, không giả response hoặc đổi dữ liệu DB.

Registry nối báo cáo qua `AtomicSources` và hai public providers, cùng một connection/read transaction và principal hiện tại. Snapshot giữ riêng tồn kho và từng sổ có ý nghĩa tiền được khai báo, không suy từ tên cột hoặc cộng các sổ. Read bridge v3 thêm tên hàng/kho/sổ trong snapshot; ID vẫn là identity. Picker sổ dùng public API phân trang, không yêu cầu người dùng nhập UUID. Snapshot và tệp đã xuất cũ không đổi sau sửa nguồn hoặc nâng bridge.

PDF/XLSX/TXT có canonical bytes/hash và bản tên dễ nhận diện trong `reports`. Retry phục hồi bản local từ canonical, không ghi đè bản khác hash. Download kiểm reference/quyền/hash trước headers. Hẹn giờ tạo báo cáo local là opt-in, chạy theo lifecycle của app và độc lập worker import. Thiếu cấu hình Zalo vẫn lưu local và giữ `UNCONFIGURED`; không có network attempt giả. Credential adapter dùng Windows Credential Manager, không plaintext DB/file. Không gửi Zalo thật trong đợt này.

## Kiểm chứng tích hợp

Windows 11 x64, Python 3.12.16/SQLite 3.53.1, Node 24.21.0. Các kiểm tra dùng dữ liệu tổng hợp và SQLite/WAL thật.

| Phạm vi | Kết quả đã quan sát |
|---|---|
| Backend toàn module sau namespace hóa test | 1.017 PASS, 0 fail/skip, 391,82 giây |
| Core connection-bound job status bổ sung sau bộ trên | 21 focused PASS, 8,02 giây; có giao nhau, không cộng vào tổng full suite |
| Root sau sửa export snapshot: core/new race/public API/liên module | 29 focused PASS / 17,43 giây; current collection có 1.029 ca |
| Frontend build/TypeScript cuối | PASS; JS 1.491,53 KB / gzip 478,08 KB, còn cảnh báo chunk lớn |
| Frontend đầy đủ sau sửa selector/refresh | 32 PASS / 20,5 giây |
| Local-account regressions lặp ba lượt sau sửa refresh | 24 PASS / 13,9 giây; là 8 ca × 3, không phải 24 hành vi khác nhau |
| SchemaEditor, gồm POST/PATCH mất ACK sau commit thật | 11 PASS / 20,9 giây |
| Accounting helper/mock browser | 17 PASS / 23,9 giây |
| Accounting real API/import/repair/export/clipboard | 1 flow PASS / 25,9 giây |
| Chạy lại flow trên source sửa export snapshot tại root | PASS / 21,3 giây; cả export/download và partial repair giữ đúng |
| Reporting CI wrapper | 1 PASS / 13,6 giây; 21 + 10 nhóm assertion nội bộ |
| Ruff toàn backend/tests/scripts, compileall, Git whitespace | PASS |

Trước sửa namespace, việc chạy chung phát hiện hai tên test module trùng nhau. Test packages và imports có tên đầy đủ cùng `--import-mode=importlib` sửa discovery, không đổi body/assertion nghiệp vụ. Bộ 1.017 còn chạy timer 60 giây, subprocess crash/restart và genuine two-writer/snapshot cases. Không xóa cache để che lỗi hoặc chia suite để né collision.

Các ca liên module thực kiểm pending ẩn khỏi list/provider/export/report; cancel ở chunk boundary rồi resume/publish; sửa dòng lỗi và confirm lần hai; snapshot không trộn dữ liệu giữa hai provider khi writer khác sửa đồng thời; thu hồi quyền giữa capture không lưu report/receipt/audit. Hợp đồng manual và từ cân/đối tác xuất Word/PDF mà không đổi tồn hoặc sổ tiền.

App-shell browser chỉ mock native invoke, còn HTTP/auth/SQLite/default registry là thật: chọn cân/đối tác, sửa và xuất hợp đồng, sửa ô kế toán, chọn sổ theo tên, lập/lưu báo cáo và tải đủ PDF/XLSX/TXT. Hash từng download và từng bản trong thư mục `reports` khớp canonical. Menu cài đặt tạo/khóa Operator thật. Những ca mock riêng không được gọi là native acceptance.

## Bằng chứng dung lượng lớn và giới hạn

CSV full-pass trên archive `3aa8c47`, 8 cột, explicit business key: 50k/500k/1m đều PASS correctness trong 68,13 / 1.010,86 / 2.041,55 giây. Lượt 1m sửa 1.000 dòng lỗi rồi confirm tiếp: đủ 1m published/lineage/distinct targets, 2 attempts, tổng chính xác 599.994.990,00 VND; hash nguồn và code/runner archive giữ nguyên. Các delta metadata/filter/UI sau đó có tests riêng, không được gắn lại nhãn thời gian của archive.

Máy dùng chung i5-14400F, 32 GiB RAM, Kingston NVMe; không CPU/I/O isolation. 1m broad filter/page p95 7,286 giây, max 63,593 giây; WAL peak 4,459 GB, app-data peak 11,082 GB. Đây là giới hạn phản hồi đáng lưu ý, không phải cam kết nhanh nhất hoặc performance PASS theo ngưỡng chưa có.

XLSX parser gần giới hạn worksheet: 1.048.575 data rows + header, 8.388.600 cells, PASS 610,913 giây, hash toàn bộ/tail/nguồn khớp. Đây là parser-only inline-string fixture, không thay cho end-to-end XLSX import hoặc shared-string-heavy benchmark. UI Chromium trên clone 1m đã có dữ liệu giữ tối đa 200 dòng cache tại checkpoint và 19 DOM rows; không phải import native 1m hay cold-start/lifetime memory proof. Xem các handoff accounting để biết raw evidence và các lượt FAIL được giữ riêng.

## Gate tiếp theo

Chưa phát hành/production-ready. CI Windows phải kiểm riêng source increment này; native installer của increment hợp đồng trước không chứng minh native accounting/reporting. Windows sạch, native GUI/offline, update/uninstall, backup/restore/move data root, DOCX mở/in, benchmark trên app đã cài và native license/source/relink còn thuộc packaging/release gate. Zalo live cần tài khoản/loại nhóm/quyền API và đích thật đã xác minh.

Core backup giữ canonical report bytes; bản tên thân thiện là dẫn xuất và có thể tạo lại khi export sau restore. Không tự xóa tệp mà reconciliation liệt kê orphan. Báo cáo chỉ phản ánh dữ liệu đã nhập; không khẳng định bao phủ toàn bộ tiền hoặc hàng thực tế.
