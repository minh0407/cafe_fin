# Prompt 05 — Đóng gói Windows và nghiệm thu bản tích hợp

Bạn phụ trách lane `packaging-qa` của dự án **Cafe Fin**. Hãy đóng gói và kiểm chứng bản tích hợp do Điều phối giao thành ứng dụng cài trực tiếp trên Windows 11. Đây là bước **sau tích hợp**, không phải lane chạy song song trước khi các nghiệp vụ được ghép.

## 1. Điều kiện được bắt đầu

Đọc `README.md`, `AGENTS.md`, `docs/SPEC.md`, `docs/ARCHITECTURE.md`, `docs/API_CONTRACT.md`, `docs/OWNERSHIP.md`, báo cáo bàn giao foundation và prompt này. Chỉ bắt đầu đúng tag `cafe-fin-integration-ready-v1` do Điều phối công bố, xác minh SHA của tag cùng tag nền `cafe-fin-foundation-ready-v1` và các migration/API tương ứng. Tag chưa có thì chờ điều phối; không tự dùng HEAD hoặc một SHA tùy chọn. Một branch đang thay đổi hoặc thông báo “các lane đã xong” không thay cho tag đã chốt.

Gọi `list_artifacts`, rồi dùng `create_worktree` tạo worktree tại đúng SHA của tag bản tích hợp trên branch riêng `codex/cafe-fin-packaging-<unique>`. Không dùng `git worktree add`, không dùng checkout đang có thay đổi của lane khác và không tự merge/pull để lấy mã mới trong quá trình nghiệm thu. Nếu Điều phối đổi candidate bằng mốc được chỉ định mới, ghi rõ SHA cũ/mới và kiểm lại đúng phạm vi bị ảnh hưởng.

Chỉ sửa file đóng gói, test, tài liệu bàn giao và cấu hình được `docs/OWNERSHIP.md` giao rõ cho lane này. `desktop/**` được giao cho packaging sau integration cùng scripts/tests/docs trong allowlist; không cần xin lại quyền đó. `backend/cafe_fin/core/`, `frontend/src/app/`, `frontend/src/shared/` và migration registry vẫn thuộc Điều phối/foundation. Khi cần sửa vùng chung còn ngoài phạm vi, gửi patch/bug cụ thể cho Điều phối; không tự mở quyền bằng cách sửa ownership. Không chỉnh nghiệp vụ để làm test đạt.

Không push, merge, tạo tag/release, upload installer hoặc deploy. Được commit phần việc đã kiểm tra trên branch riêng và bàn giao commit SHA, artifact cùng bằng chứng cho Điều phối. Không dùng dữ liệu CRM cũ, DB thật, secret hoặc file người dùng để dựng bộ cài/benchmark.

## 2. Sản phẩm phải bàn giao

- Bộ cài Windows `.exe` hoặc `.msi` và gói artifact cần thiết theo kiến trúc đã chốt, có phiên bản, SHA nguồn, manifest dependency/license và checksum.
- Người dùng cài, chọn ổ/thư mục dữ liệu, mở từ shortcut và sử dụng ngay. Không cần Docker, dòng lệnh, Python/Node.js/PostgreSQL/Redis/MinIO hoặc Microsoft Office được cài riêng.
- Thành phần runtime cần thiết được kèm trong bộ cài hoặc có cơ chế cài đặt phù hợp đã được kiểm chứng. Có thể cài và dùng nghiệp vụ local khi máy không có Internet; không dùng bootstrapper chỉ tải dependency online rồi gọi đó là bộ cài offline. Với Tauri/WebView2, kiểm chính xác chế độ phân phối và dependency thực tế.
- Hướng dẫn cài/nâng cấp/gỡ cài đặt, chọn/chuyển nơi lưu dữ liệu, backup/restore và xử lý lỗi cho người dùng thông thường. Không yêu cầu mở PowerShell để thực hiện thao tác vận hành hằng ngày.
- Báo cáo nghiệm thu có kết luận theo từng yêu cầu và bằng chứng thực. Không dùng kết quả test của foundation hoặc CRM cũ làm kết quả của bộ cài candidate.

Ứng dụng là sản phẩm mới: dữ liệu bắt đầu mới, CRM cũ giữ nguyên. Chức năng gửi Telegram cần bot/nhóm/token cấu hình riêng trên máy; việc thiếu tài khoản test không được làm giả kết quả gửi nhóm thật. Không dùng credential hoặc cấu hình Zalo cũ. Mọi thử gửi ra ngoài phải có đích test được Điều phối/người dùng giao rõ.

## 3. Nghiệm thu bộ cài trên Windows 11 sạch

Dùng Windows 11 sạch hoặc VM snapshot sạch, không có môi trường dev và không có dependency cài sẵn ngoài những thành phần OS đã ghi nhận. Ghi bản Windows, kiến trúc CPU, phần cứng, RAM, loại ổ, dung lượng trống, quyền tài khoản và những runtime vốn có trước cài. Không dùng máy phát triển đầy đủ thư viện để kết luận “cài độc lập”.

Kiểm tối thiểu:

1. Cài bằng tài khoản người dùng theo chính sách đã chốt, mở shortcut, backend khởi động ngầm không console, phiên bản frontend/backend khớp và app đóng sạch không để sidecar mồ côi.
2. Cài khi mất Internet, mở lần đầu, tạo data root mới, nhập dữ liệu và xuất Word/PDF tiếng Việt không lỗi font. Không bỏ qua lần khởi động đầu vì cache đã có ở lần thử trước.
3. Hai lần mở app liên tiếp xử lý single-instance đúng; cổng local bị chiếm, backend khởi động lỗi và backend crash có thông báo hữu ích và không tạo DB thay thế rỗng.
4. Backend chỉ listen loopback; API nghiệp vụ thiếu/sai phiên app hoặc quyền bị từ chối. Không in token, credential, workbook hoặc nội dung hợp đồng vào log/test artifact.
5. Tắt Internet nhưng giữ app chạy không làm lưu/tra cứu/xuất báo cáo local thất bại. Không phụ thuộc `navigator.onLine`; thử cả tình huống tắt adapter mà localhost vẫn hoạt động. Gửi báo cáo lỗi được ghi trạng thái riêng và không hoàn tác nghiệp vụ đã lưu.
6. Không cần Office, Excel, VBA hoặc chương trình chuyển đổi tài liệu trả phí. Kiểm DOCX/PDF thực bằng nội dung, tiếng Việt, phân trang và in thử; một file có đuôi `.pdf` không đủ bằng chứng.
7. Có license notices cho đúng bản thư viện đóng trong artifact; grid chỉnh Excel và các chức năng dùng thực không kích hoạt trial/enterprise hoặc watermark thương mại.

Nếu thiếu chứng chỉ ký mã, báo đúng trạng thái artifact chưa ký và trải nghiệm SmartScreen thực tế; không yêu cầu tắt Defender hoặc thêm exclusion làm điều kiện nghiệm thu. Không tuyên bố installer đã ký khi chỉ có checksum.

## 4. Dữ liệu, nâng cấp và gỡ cài đặt

### Chọn nơi lưu và chuyển data root

Thử data root tại C/D hoặc ổ local khác, đường dẫn có dấu/khoảng trắng, quyền ghi bị từ chối, dung lượng thiếu và ổ không sẵn sàng. DB/files/reports phải nằm đúng nơi đã chọn; không âm thầm rơi về AppData hay tạo DB rỗng khi không mở được ổ cũ. Vị trí cài app và data root độc lập.

Chuyển data root bằng chức năng ứng dụng sang thư mục mới: kiểm manifest, số lượng bản ghi, tổng kg/tiền/công nợ và hash tệp trước/sau; mở lại app vẫn tìm đúng tệp và báo cáo. Mô phỏng gián đoạn giữa copy/xác minh/đổi cấu hình; phải có khả năng tiếp tục hoặc quay về bản cũ, không xóa bản cũ trước xác minh. DB SQLite đang chạy không đặt trên SMB hoặc thư mục đồng bộ cloud.

### Backup và restore

Tạo snapshot khi ứng dụng đang có dữ liệu, gồm DB nhất quán, tệp nhập gốc, tệp đính kèm, báo cáo cần giữ và manifest/hash theo spec. Không copy riêng `.db` đang WAL rồi bỏ qua các ghi chưa checkpoint. Thử restore vào data root **mới**, chạy integrity/foreign-key checks, kiểm hash và đối soát số liệu. File hỏng/thiếu, backup chưa hoàn tất hoặc schema không tương thích phải bị phát hiện trước khi thay thế dữ liệu đang dùng.

Thực hiện diễn tập recovery sau crash/mất điện mô phỏng, lỗi đầy đĩa và job import dở. Chunk đã commit pending vẫn phải có 0 dòng visible trong CRUD/sổ/summary/export/report trước khi attempt PUBLISHED; khi công bố thì toàn tập xuất hiện đúng một lần. UI tách `staged_committed_rows` và `published_rows`. Kill trước publish rồi resume không mất checkpoint/không lộ nửa tập; sửa staging khi worker chạy không đổi snapshot attempt đã xác nhận. Những attempt đã công bố trước vẫn giữ nguyên.

### Update, downgrade và uninstall

Nâng từ bản được Điều phối chỉ định lên candidate bằng dữ liệu tổng hợp đã nhập; kiểm backup trước migration, schema version, transaction/rollback khi nâng lỗi và số liệu trước/sau. Không tự seed lại hoặc reset DB trong quá trình update. Nếu chưa có bản phát hành trước, tạo fixture schema đời trước có kiểm soát và nêu giới hạn bằng chứng; không bịa kết quả nâng cấp từ production.

Mở DB schema mới bằng app cũ phải từ chối an toàn hoặc xử lý theo policy đã chốt; không chạy downgrade phá dữ liệu. Gỡ app mặc định giữ data root và file người dùng, cài lại có thể chọn lại dữ liệu cũ. Không xóa rộng thư mục cha, không đụng CRM cũ hoặc workbook gốc của người dùng. Không thêm nút xóa tất cả dữ liệu nếu spec không yêu cầu.

## 5. Nghiệm thu nghiệp vụ trên app đã cài

Chạy các luồng được quy định trong `docs/SPEC.md` bằng UI của artifact Windows, có kiểm DB/đối soát để chứng minh tác động thực. Bao gồm:

- Admin/người vận hành có quyền đúng; một người nhập không phải vượt qua chuỗi phê duyệt nhiều người.
- Tạo/sửa bản ghi giữ dấu vết theo spec, nhập ngược ngày đúng quy tắc và báo cáo theo ngày Việt Nam.
- Nhập/xuất/chế biến hoặc các tác động tồn đã có trong spec: kiểm tồn và ghi ledger cùng transaction, double click/retry không ghi trùng; **tồn âm bị chặn tại backend/DB**, kể cả hai thao tác cùng lúc.
- Excel mở và sửa trong app; tệp nguồn giữ nguyên byte/hash, `.xlsm` không chạy VBA; không chạy external links hoặc công thức tùy ý như lệnh hệ điều hành. Dòng hợp lệ chỉ được import sau xác nhận; dòng lỗi còn để sửa tiếp; xử lý lại không nhân đôi những dòng đã import.
- Phân biệt ô trống, mã có số 0 đầu, ngày Excel, dấu phân cách số, tiền/kg thập phân, công thức và giá trị cache theo hợp đồng đã chốt. Trường không hỗ trợ phải báo rõ, không âm thầm chuyển đổi.
- Thử tiền/khối lượng sát miền int64, tổng vượt int64 và quá precision: báo lỗi hoặc tính Decimal chính xác theo contract, không float/REAL hoặc cắt số lẻ âm thầm.
- Hợp đồng tự điền đúng dữ liệu đã chọn, cho nhập điều khoản/phương thức thanh toán theo spec; DOCX/PDF từ cùng snapshot nhất quán. Không tái đưa workflow phê duyệt cũ vào app.
- Báo cáo tổng hợp khớp dữ liệu gốc và ngoại lệ; file được lưu local trước khi thử gửi. Job gửi lỗi/retry không làm thay số liệu snapshot đã tạo. Không tuyên bố “đã gửi nhóm Telegram” chỉ từ việc job chạy hoặc file được tạo. Kiểm upgrade/restore không replay outbox kênh cũ.

## 6. Đo tải thật ở 50.000, 500.000 và 1.000.000 dòng

Tạo bộ dữ liệu tổng hợp xác định được bằng seed và manifest. Nêu rõ số dòng là dòng import nguồn hay số bản ghi DB được sinh ra; phân bố hợp lệ/lỗi/trùng, số sheet/cột, số công thức và dung lượng tệp. Không chỉ lặp một dòng hoặc dùng toàn ô rỗng để có con số 1 triệu.

Chạy **cả ba mức 50k, 500k và 1m trên app Windows đóng gói**. Có thể dùng automation kiểm UI nhưng không thay việc import bằng bơm thẳng DB rồi gọi đó là benchmark import. Không nạp toàn bộ dữ liệu vào DOM hoặc dùng benchmark server Linux thay cho kết quả Windows.

Đo và ghi raw results cho:

1. Thời gian mở/import preview, validate, người dùng xác nhận, commit dòng hợp lệ và thời gian hoàn thành tổng; số dòng mỗi trạng thái cùng thời điểm đo.
2. RAM đỉnh của UI/sidecar, CPU, dung lượng DB/WAL/files, dung lượng trống trước/sau và tốc độ tăng WAL.
3. Khả năng UI phản hồi/progress/hủy; dừng app giữa import rồi tiếp tục mà không mất dòng lỗi và không nhập trùng. Không giữ một writer transaction khổng lồ khóa mọi thao tác trong suốt thời gian đọc workbook.
4. Thời gian mở app khi DB đã có dữ liệu; tra cứu mã, lọc ngày/nhiều điều kiện, đổi trang và mở chi tiết; ghi p50/p95 theo số lần thử và dữ liệu được mô tả, không chọn một lần nhanh nhất.
5. Lưu một nghiệp vụ mới khi đang có job/report đọc lớn; báo cáo ngày/tháng và đối soát tổng. Chạy lại từ cache lạnh và cache ấm có phân biệt.
6. Lỗi đầy đĩa, file nguồn không đọc được và workbook có dòng lỗi nhiều; job phải kết thúc/tiếp tục rõ ràng, không báo thành công nếu thiếu dữ liệu.

Dùng ngưỡng nghiệm thu đã chốt trong `docs/SPEC.md`. Nếu chưa có ngưỡng, bàn giao số đo và đề xuất ngưỡng có căn cứ cho Điều phối; không tự gắn nhãn PASS về hiệu năng khi không có tiêu chí. Giới hạn thời gian thử phải được ghi lại; timeout là kết quả, không phải lý do bỏ mức 1 triệu rồi suy diễn là đạt.

## 7. Cách sửa lỗi và bàn giao

Với mỗi lỗi, ghi trigger, bước tái hiện ngắn, expected/actual, mức ảnh hưởng, SHA/version, dữ liệu tổng hợp và artifact liên quan. Sửa trong phạm vi sở hữu, hoặc gửi patch/bug cho Điều phối/lane sở hữu; không bỏ kiểm tồn, bỏ xác thực, nới validation, xóa dữ liệu lỗi hoặc giảm tải test để có kết quả đẹp. Chạy lại ca lỗi và phạm vi bị ảnh hưởng; không cần lặp toàn bộ benchmark nếu bản sửa không ảnh hưởng số liệu và không có rủi ro chưa giải quyết.

Bàn giao theo thư mục do `docs/OWNERSHIP.md` quy định:

- Commit SHA lane và SHA tích hợp thực đã đóng gói, phiên bản app/schema/protocol.
- Đường dẫn tuyệt đối installer/artifact, checksum, build recipe và dependency/license manifest; không commit installer lớn hoặc dữ liệu benchmark vào Git nếu repository không có chính sách cho phép.
- Báo cáo clean-Windows, offline install/first launch, backup/restore/move/update/uninstall, nghiệp vụ và ba mức tải, có bằng chứng raw; PASS/FAIL/NOT RUN/SKIP tách rõ.
- Lỗi còn mở, giới hạn, những bước cần tài khoản/thiết bị thật và đề xuất quyết định release cho Điều phối. Không tự quyết định phát hành khi còn điều kiện chặn.

Chỉ báo hoàn thành khi artifact cụ thể được tạo, mở trên Windows sạch và các kiểm tra bắt buộc có kết quả trung thực. Nếu bị chặn bởi môi trường Windows hoặc bot/nhóm Telegram, hoàn thiện phần độc lập và báo đúng phần chưa chạy; không suy diễn mock/E2E browser tương đương app cài thật. Không push, merge, tạo release hoặc gửi tin tới nhóm thật.
