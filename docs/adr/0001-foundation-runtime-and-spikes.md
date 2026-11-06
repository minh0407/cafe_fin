# ADR 0001 Nền tảng local và các bản thử

Trạng thái: candidate để Điều phối review, chưa thông qua foundation READY.
Ngày: 06/11/2026. Không thay stack, spec, API contract thiết kế hoặc ownership.

## Quyết định

Giữ Tauri 2, React 19/TypeScript/Ant Design/TanStack Query/Zustand và Python
3.12/FastAPI/SQLAlchemy 2/SQLite WAL. Direct dependency được pin; lockfiles Python,
npm và Cargo được commit. Python sidecar mang runtime riêng, không dùng Python
hoặc Microsoft Office trên máy người dùng. Tiền/kg đi qua scaled int64, JSON
Decimal strings; tổng lớn cộng bằng Python integer, không SQLite SUM(integer).

Runtime build được kiểm thực là Python 3.12.16, PBS 20261026, SQLite 3.53.1.
Core từ chối SQLite trước 3.51.3 và bản 3.52.0 đã rút. Giữ synchronous FULL,
foreign keys, recursive triggers, WAL và một writer; engine dùng URI mode=rw
để không tạo DB thay thế khi file cũ biến mất. Cơ sở upstream về WAL-reset:
[SQLite WAL](https://www.sqlite.org/wal.html),
[lịch sử SQLite](https://www.sqlite.org/changes.html).
Upstream đã có3.54.1 ngày16/10/2026; runtime được đo ở đây là3.53.1, không phải
bản mới nhất. Bằng chứng hiện tại xác nhận WAL fix và các hành vi đã chạy, không
phải tuyên bố mọi bugfix upstream sau đó đều không liên quan. Upgrade runtime
cần cập nhật pins/native notices và chạy lại regressions/packaging.

## Grid và workbook

Chọn `react-data-grid@7.0.0-beta.64`, MIT, peer React ^19.2. Bản này đã chạy với
React 19.3.1 trong browser tests thực. Không ép peer của Glide stable 6.0.3
(React16–18), không dùng Handsontable/AG Enterprise, key trial hoặc tính năng
Excel import/export thương mại. Dùng virtualization, editing, resize/frozen
column, selection/copy và paste giới hạn. Phiên bản beta phải được review khi
nâng cấp. Nguồn chính thức: [source](https://github.com/Comcast/react-data-grid),
[tarball phiên bản](https://registry.npmjs.org/react-data-grid/-/react-data-grid-7.0.0-beta.64.tgz).
License nguyên bản được đưa vào `desktop/notices/frontend.txt`.

Spike đọc workbook tổng hợp 10.000 dòng bằng openpyxl 3.1.5 (MIT), defusedxml
0.7.1 (PSF) và et-xmlfile 2.0.0 (MIT). Kho nguồn giữ nguyên bytes/hash; preview
không save nguồn, chạy macro, giải quyết external links hoặc tính formula.
Reader dùng read_only và bounded page500. Tệp mẫu/mã/ngày/số lớn/formula được
kiểm thực, không phải bằng chứng import500k/1m. Nguồn:
[openpyxl optimized modes](https://openpyxl.readthedocs.io/en/stable/optimized.html).

Không chọn evaluator trong foundation này. Công thức được hiển thị nguyên text
với issue FORMULA_NOT_EVALUATED; không dùng cached value như kết quả đã tính lại.
Lane accounting phải bàn giao engine/tập hàm có kiểm thử và đề nghị dependency
chung qua Điều phối. Không eval, network formula hoặc arbitrary script.

## Word PDF và native dependencies

ReportLab 4.4.9 BSD tạo PDF; python-docx 1.2.0 MIT tạo DOCX độc lập từ cùng
snapshot, không chuyển DOCX qua Office. Noto Sans regular/bold OFL1.1 được
nhúng trong PDF. DOCX chỉ định font, không cam kết font máy đọc đã cài. Pillow
13.0.0 MIT-CMU và lxml 6.1.1 BSD/native notices nằm trong bộ dependency đã khóa.
Không rlextra/pyRXP, WeasyPrint/Pango hoặc Office automation. PyInstaller 6.22.3
đóng gói console-enabled sidecar để giữ stdin/stdout; Tauri CREATE_NO_WINDOW
ẩn console. Các font DarkGarden không dùng được loại khỏi bundle.

Giấy phép/nguồn exact package, Rust, npm, Python/PBS, SQLite, OpenSSL, libffi,
zlib/xz/bzip2, libxml2/libxslt và Microsoft runtime được phân phối tại
`desktop/notices/`; native license URL/SHA và DLL/PYD inventory có JSON riêng.
Đây không thay thế xác minh nghĩa vụ giấy phép transitive. Wheel lxml hiện có
iconv feature nhưng chưa xác định được exact native iconv build/source/relink
artifacts. **Chưa chốt phân phối production** cho dependency này; Điều phối
cần giải quyết provenance/obligations hoặc phê duyệt lựa chọn thay thế có bằng
chứng. Không đổi dependency để lách yêu cầu license.

## Các gate chưa đạt

Frozen sidecar và PDF tiếng Việt đã thử trên Windows phát triển; browser/UI
đã nối API thật. Cargo check native PASS. NSIS release bị AppControl4551 chặn
ở artifact Rust, chưa có installer để nghiệm thu. Windows sạch, native GUI
folder dialog/lifecycle, Office-free mở/in và DOCX visual còn thiếu bằng chứng.
Backup/restore/move primitive đã kiểm links/hash; workflow native đổi cấu hình
và relaunch sau move chưa được tích hợp/kiểm end-to-end.

Không được diễn giải ADR này, notices hoặc test primitive thành quyết định READY.
Điều phối sở hữu policy development/API baseline và release acceptance; ADR này
chỉ ghi bằng chứng/lựa chọn kỹ thuật, không sửa gate hay yêu cầu nghiệp vụ.
Theo `docs/adr/20261106_COORDINATION_GATES.md`, installer/clean-client là release
gate. Việc freeze interface/mở lane dựa vào code/API/UI tracked đã được Điều phối
review, không phải một tuyên bố native acceptance đã hoàn tất.
Xem handoff foundation để có SHA, lệnh, snapshot sạch và giới hạn từng phép thử.
