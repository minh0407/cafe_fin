# Prompt 00 — Nền tảng desktop Windows và hợp đồng tích hợp

Bạn phụ trách lane `foundation` của dự án **Cafe Fin**. Hãy xây dựng nền tảng dùng được và kiểm chứng được để các lane nghiệp vụ triển khai sau. Chỉ làm nền tảng, giao diện module mẫu tối thiểu và các bản thử kỹ thuật được nêu dưới đây; không triển khai thay các lane nhập Excel, nghiệp vụ cà phê, hợp đồng hoặc báo cáo.

Điều phối cập nhật phân kỳ tại `docs/adr/20261106_COORDINATION_GATES.md`: foundation READY là baseline interface cho phát triển; native install trên Windows sạch vẫn bắt buộc trước phát hành. Các phép thử native dưới đây cần làm sớm, ghi PASS/FAIL/NOT RUN đúng thực tế; thiếu môi trường không cho phép bỏ test, nhưng có thể chuyển phần nghiệm thu native cuối sang release gate. Lỗi chức năng core/API vẫn phải sửa trước baseline.

## 1. Đọc trước và xác nhận điểm xuất phát

Đọc đầy đủ `README.md`, `AGENTS.md`, `docs/SPEC.md`, `docs/ARCHITECTURE.md`, `docs/API_CONTRACT.md`, `docs/OWNERSHIP.md` và prompt này. Bắt đầu đúng tag `cafe-fin-spec-v1`, xác minh SHA của tag; không thay bằng HEAD khác. Bộ tài liệu chính thức do Điều phối cung cấp là nguồn quyết định. Nếu tài liệu hoặc tag xuất phát chưa có, báo chính xác phần thiếu cho Điều phối; không tự dựng một bộ yêu cầu khác và không lấy CRM cũ làm đặc tả thay thế.

Trước khi sửa, kiểm tra trạng thái Git. Gọi `list_artifacts` để xem worktree gắn với chat, sau đó dùng công cụ `create_worktree` tạo worktree riêng tại SHA của tag `cafe-fin-spec-v1`, trên branch duy nhất `codex/cafe-fin-foundation-<unique>`. Không tự dùng `git worktree add`, không làm trong checkout của người khác và không ghi đè thay đổi có sẵn. Nếu công cụ worktree báo lỗi, báo nguyên nhân cho Điều phối để giải quyết, không âm thầm đổi cơ chế cách ly.

Đây là ứng dụng mới trong repository `https://github.com/minh0407/cafe_fin.git`. CRM cũ chỉ được đọc để tham khảo ý nghĩa trường hoặc cách xuất chứng từ; không sao chép lịch sử Git, DB, bản dump, dữ liệu người dùng, `.env`, mật khẩu, token, chữ ký thật hoặc trạng thái workflow cũ. Dữ liệu vận hành bắt đầu mới.

## 2. Những yêu cầu đã chốt

- Ứng dụng cài trực tiếp trên Windows 11, mở từ shortcut, không yêu cầu người dùng cài Python, Node.js, Docker, PostgreSQL, Redis hoặc MinIO và không yêu cầu gõ lệnh.
- Một PC, một người nhập nghiệp vụ. Có tài khoản quản trị và người vận hành theo ma trận quyền trong `docs/SPEC.md`; không thêm chuỗi phê duyệt nhiều người, ca trưởng hoặc hai người giao nhận.
- Ghi nhận, tra cứu và thống kê nghiệp vụ; phát hiện bất thường bằng cảnh báo. **Chặn giao dịch làm tồn âm** bằng transaction trong tầng dữ liệu; không chỉ vô hiệu hóa nút ở giao diện.
- Máy có Internet, nhưng DB và tệp nghiệp vụ lưu tại máy. Internet không phải điều kiện để lưu, tra cứu hoặc xuất chứng từ local. Tích hợp gửi báo cáo Telegram thuộc lane riêng và không được chặn nghiệp vụ khi gửi lỗi.
- Người dùng chọn thư mục dữ liệu trên ổ local; DB, tệp nhập gốc, bằng chứng, báo cáo và backup nằm trong cấu trúc rõ ràng. Vị trí cài chương trình độc lập với vị trí dữ liệu.
- Excel được chỉnh trong app. Giữ nguyên tệp gốc, kể cả `.xlsm` chứa macro; không thực thi VBA, không ghi đè tệp gốc, không âm thầm đổi công thức hoặc bỏ macro khỏi nguồn gốc. Chỉ import những dòng hợp lệ sau bước xác nhận; dòng lỗi giữ để sửa và xử lý tiếp.
- Chỉ dùng thư viện có giấy phép miễn phí tương thích với cách phân phối dự án. Không dùng chức năng enterprise, trial, tài khoản trả phí hoặc phụ thuộc Microsoft Office đã cài để hoàn thành chức năng cốt lõi.

## 3. Kiến trúc phải triển khai

Theo đúng `docs/ARCHITECTURE.md`: **Tauri 2 + React 19 + TypeScript + Ant Design + TanStack React Query + Zustand**, Python 3.12/FastAPI/SQLAlchemy, SQLite WAL, local file store, một serialized writer và local job runner. Khóa phiên bản và lưu lockfile; không chuyển stack hoặc bổ sung server dịch vụ mới nếu chưa phối hợp Điều phối.

Python được đóng gói thành sidecar Windows. Tauri chịu trách nhiệm vòng đời sidecar; người dùng không nhìn thấy cửa sổ console hoặc phải khởi động backend riêng. Có một instance ứng dụng sử dụng một data root tại một thời điểm; tránh hai sidecar cùng ghi một DB. Khi app thoát, đóng writer/job/DB có trật tự; khi tiến trình lỗi, khởi động lại phải phát hiện công việc dở và phục hồi có dấu vết.

### Backend và IPC

- Backend chỉ listen `127.0.0.1` trên cổng do app quản lý; không bind `0.0.0.0`, không quảng bá ra LAN và không giả định cổng cố định luôn rảnh.
- Mọi API nghiệp vụ phải xác thực cả phiên app và quyền người dùng theo hợp đồng API. Token riêng cho phiên sidecar được truyền qua IPC/handshake nội bộ, giữ trong bộ nhớ khi có thể; không đặt trong URL, command line, log, repo hoặc localStorage. Không coi loopback là đủ xác thực.
- CORS, Host validation, CSP và phạm vi Tauri commands được giới hạn vào origin/command thực sự cần dùng. Không cho renderer chạy shell tùy ý, đọc mọi đường dẫn hoặc mở remote content với đặc quyền desktop.
- Định nghĩa rõ handshake, phiên bản protocol, API base, lỗi startup, deadline khởi động, backend mất kết nối, restart, logout và đóng app. Kiểm sức khỏe API local thực sự; không dùng `navigator.onLine` làm điều kiện chặn thao tác localhost.
- Quy ước lỗi có mã ổn định, thông điệp tiếng Việt, validation theo trường và request/job ID. Không trả exception thô, đường dẫn nhạy cảm hoặc secret cho UI.

### SQLite, writer và migrations

- Schema mới hoàn toàn, không chạy chuỗi Alembic/PostgreSQL của CRM cũ. Có migration registry do core quản lý, phiên bản schema và module migration namespace ổn định.
- Bật WAL, foreign keys, busy timeout và cấu hình durability phù hợp dữ liệu nghiệp vụ. Kiểm phiên bản SQLite thực được đóng trong sidecar và tình trạng sửa lỗi của phiên bản đó; không chỉ dựa vào phiên bản Python trên máy phát triển.
- Tất cả lệnh ghi đi qua một writer thống nhất; transaction bao trùm kiểm tồn, ghi nghiệp vụ và ghi vết. Reader/report không dùng transaction dài để giữ WAL vô hạn. Tác vụ chậm không khóa writer trong lúc xử lý CPU, đọc Excel, render PDF hoặc gọi mạng.
- Tiền, giá và khối lượng phải chính xác theo đơn vị/scale trong `docs/API_CONTRACT.md`. Không lưu số nghiệp vụ chính xác bằng binary float. Nếu dùng integer scaled, kiểm overflow cả phép tính trung gian; không âm thầm cắt số lẻ. API dùng biểu diễn số đã thống nhất.
- Chuẩn bản đầu là tiền scale 2 (integer đơn vị 0,01 VND), kg scale 3 (integer đơn vị 0,001 kg), kiểm int64 trước ghi. Tổng hàng triệu dòng có thể vượt int64 phải dùng Decimal/check, không SQLite SUM(integer) không kiểm soát hoặc chuyển sang REAL. Cột decimal tùy cấu hình không được đổi ngữ nghĩa core Money/Amount.
- Chống ghi trùng theo request/idempotency key, khóa phiên bản khi cần và ràng buộc DB. Double click, request phát lại và backend restart không được ghi thêm nghiệp vụ lần hai.
- Lưu thời điểm UTC và ngày nghiệp vụ theo múi giờ Việt Nam như spec; không lấy múi giờ host tùy ý hoặc ngày cắt từ chuỗi UTC để lập báo cáo ngày.
- Dữ liệu đã lưu cần dấu vết tạo/sửa/điều chỉnh theo spec. Không biến yêu cầu ghi vết thành workflow phê duyệt mới. Cơ chế chống tồn âm phải có giao diện để lane nghiệp vụ sử dụng, không để mỗi module tự kiểm một cách.

### Data root và file store

- Có wizard chọn data root lần đầu, kiểm quyền ghi, dung lượng, đường dẫn Unicode/khoảng trắng và phát hiện data root đã có dữ liệu. Không tự tạo DB rỗng mới khi đường dẫn cũ mất hoặc ổ đĩa không sẵn sàng.
- Tập trung cấu hình đường dẫn tại core. Dùng file key tương đối và kiểm path traversal; không lưu absolute path rải rác trong domain records. DB WAL hoạt động đặt trên ổ local, không hỗ trợ DB đang chạy trên SMB hoặc thư mục đồng bộ cloud.
- File nhập gốc được copy nguyên byte vào kho nguồn, ghi hash và metadata; bản soạn/chỉnh sửa nằm ở lớp dữ liệu riêng. File nguồn không bị VBA, sửa workbook hoặc export làm thay đổi.
- Upload/import/export phải có giới hạn, hash, atomic write/rename và xử lý mất điện/đầy đĩa. Quy định cách đối soát file mồ côi hoặc DB tham chiếu file thiếu sau crash, không xóa file không rõ nguồn gốc.
- Tách cấu hình máy, secret, dữ liệu và log. Log xoay vòng và được che thông tin nhạy cảm; không ghi toàn bộ workbook, chứng từ hay token vào log.
- Cung cấp core service cho backup/restore/move data root theo hợp đồng đã chốt. Backup DB đang mở dùng snapshot API phù hợp, không copy riêng file `.db` bỏ qua WAL. Backup có manifest/hash, liên kết tập file và kiểm phục hồi; tuyệt đối không restore đè hoặc xóa data root cũ khi chưa xác minh bản mới.

### Local jobs và module interfaces

- Job dài có trạng thái bền vững trong DB: chờ, đang chạy, hoàn tất, lỗi và trạng thái hủy/phục hồi theo hợp đồng. Có progress, cancellation an toàn, retry có giới hạn và chống phát lại tác động đã commit.
- App restart phải xử lý job `RUNNING` bị bỏ dở rõ ràng; không tự đánh dấu thành công, không chạy lại toàn bộ việc có tác động mà thiếu idempotency.
- Contract import bắt buộc theo shared docs: mỗi confirm tạo attempt/snapshot staging bất biến, chunk ghi pending cùng receipt/checkpoint trong transaction ngắn; chỉ công bố toàn attempt bằng transaction ngắn cuối. Cung cấp interface visibility để mọi list/CRUD/summary/export/report không thấy pending. UI tách `staged_committed_rows` và `published_rows`; sửa staging khi worker chạy không đổi dữ liệu của attempt đã xác nhận.
- Tạo interface cho module registration, route/menu, quyền, migrations, reader/writer, file store, job submission, audit và report/contract renderer. Dùng module mẫu nhỏ chứng minh cơ chế, không xây nghiệp vụ nhập Excel/hợp đồng/kho/báo cáo thật trong lane này.
- Mỗi feature phải dùng feature-owned directory nêu trong `docs/OWNERSHIP.md`. Module mới không cần sửa file chung ngoài manifest/registry do Điều phối quản lý; cung cấp gói bàn giao registration rõ ràng cho Điều phối.

## 4. Hai bản thử kỹ thuật bắt buộc trước khi đóng băng nền tảng

### Chứng từ Word/PDF trên Windows

Dùng dữ liệu tổng hợp và một mẫu nhỏ để chứng minh tạo DOCX/PDF tiếng Việt hoàn toàn local từ cùng snapshot; mở/đọc/in được trên Windows 11 không có Microsoft Office. Xác định font, thư viện native và giấy phép thực tế. Nếu tái sử dụng cách render từ CRM cũ, phải đóng gói và thử các dependency native của WeasyPrint/Pango hoặc lựa chọn miễn phí tương đương; không coi chạy được trên máy có Python sẵn là đã đóng gói được. Không triển khai điều khoản, số hợp đồng hay trạng thái domain của lane hợp đồng.

### Grid chỉnh Excel và giấy phép

Chứng minh hướng grid miễn phí hỗ trợ chỉnh ô trong app, virtualization, ánh xạ lỗi về sheet/dòng/cột và kết nối với dữ liệu phân trang; không đưa toàn bộ 1 triệu dòng vào DOM hoặc state frontend. Bản thử chỉ dùng workbook tổng hợp, gồm dữ liệu Unicode, ngày, mã có số 0 đầu, số lớn, công thức và file macro mẫu vô hại nếu cần kiểm bảo toàn byte.

Ghi rõ lựa chọn library và feature sử dụng, phiên bản, giấy phép, đường dẫn license nguồn và cách phân phối notices. Không chọn Handsontable/AG Grid hoặc thư viện tương tự chỉ vì tên gọi; phải kiểm **đúng phiên bản và đúng feature** có cần license thương mại không. Không dùng tính năng enterprise Excel import/export dưới trial. Việc parse workbook phải không chạy VBA, external links hay công thức tùy ý trên hệ điều hành.

Kết quả hai bản thử là bằng chứng đủ để các lane dùng chung interface và dependency đã khóa. Nếu có giới hạn về fidelity PDF/công thức/grid, ghi cụ thể để Điều phối chốt trước baseline, không giấu giới hạn trong TODO.

## 5. Quyền sở hữu và phối hợp

Bạn được sửa `backend/cafe_fin/core/`, `frontend/src/app/`, `frontend/src/shared/`, `desktop/`, tooling/build/config nền tảng và migration registry theo allowlist trong `docs/OWNERSHIP.md`. Core/shared/desktop/registry thuộc **Điều phối và foundation**, không phải khu vực mọi lane được sửa.

Chỉ thêm stub/interface trong feature-owned directory khi `docs/OWNERSHIP.md` cho phép rõ. Không viết domain implementation, không sửa prompt/spec hoặc ownership để nới quyền cho chính mình. Nếu cần thay hợp đồng chung, trình Điều phối một thay đổi cụ thể với lý do và tác động trước khi đóng băng.

Không push, merge, tạo release/tag công khai, deploy hoặc chuyển DB thật. Được commit phần việc của mình trên branch riêng sau khi kiểm tra diff và loại secret/dữ liệu/runtime khỏi index; không dùng `git add .` khi có file ngoài phạm vi.

## 6. Kiểm chứng có ý nghĩa

Ngoài lint/typecheck/build, kiểm trực tiếp các rủi ro thật của nền tảng:

1. App và sidecar khởi động trên Windows; handshake sai/thiếu token bị từ chối; không thể truy cập nghiệp vụ từ origin ngoài; renderer không có tùy chọn chạy shell tùy ý.
2. Hai lệnh ghi cạnh tranh không vượt serialized writer; rollback không để nghiệp vụ/audit/file ở trạng thái hoàn tất một phần; ghi trùng không nhân đôi; ví dụ transaction kiểm tồn không cho tồn âm.
3. Tắt tiến trình giữa job rồi mở lại: tiến độ/trạng thái phục hồi đúng, không lặp phần đã commit. Backend tạm mất kết nối và Internet mất không làm UI báo lưu thành công giả.
4. Data root Unicode/khoảng trắng, không có quyền ghi, đầy đĩa, ổ không sẵn sàng, DB đã tồn tại, schema mới hơn app và chạy instance thứ hai đều được xử lý rõ, không ghi đè dữ liệu.
5. Snapshot backup khôi phục vào thư mục mới, kiểm DB và hash file; move data root không mất liên kết. Tệp import gốc giữ nguyên hash.
6. Thử tạo bộ cài `.exe` hoặc `.msi` và chạy Word/PDF/grid trên Windows sạch khi môi trường cho phép. Nếu bị policy/môi trường chặn, ghi bằng chứng và chuyển kiểm cài sạch sang release gate theo ADR; không ghi PASS từ server dev hoặc máy đầy dependency. Không thay đổi policy hoặc đường dẫn để né enforcement.

Không viết test chỉ lặp lại implementation hoặc dùng mock để tuyên bố Windows/native packaging đã pass. Ghi PASS/FAIL/NOT RUN/SKIP cùng lệnh, máy, phiên bản và lý do; số lượng test không thay bằng chứng hành vi.

## 7. Bàn giao và cổng baseline

Bàn giao candidate commit SHA cho Điều phối, kèm báo cáo foundation trong thư mục bàn giao được ownership cho phép. Báo cáo phải có cây module, dependencies/giấy phép, hướng dẫn dev/build Windows, public interfaces, schema/migrations, API/IPC/job/file-store contracts, bằng chứng test và các giới hạn còn lại. Cung cấp ví dụ để mỗi lane thêm module, migration và job mà không sửa core.

**Không lane nghiệp vụ nào được bắt đầu triển khai trước khi Điều phối công bố tag bất biến `cafe-fin-foundation-ready-v1`.** Bạn không tự công bố tag thay Điều phối. Điều phối review candidate, tích hợp và tạo tag; mọi lane sau phải bắt đầu đúng tag đó và giữ nguyên API/ownership đã đóng băng. Mọi thay đổi interface sau baseline đi qua Điều phối, có version và kế hoạch cập nhật lane liên quan.

Kết thúc bằng commit SHA, file đã đổi, kết quả kiểm tra thực, phần chưa chạy và thông tin Điều phối cần để phát hành baseline. Không push hoặc merge.
