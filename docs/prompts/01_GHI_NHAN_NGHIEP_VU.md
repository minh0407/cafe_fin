# Chat triển khai 01 — Ghi nhận nghiệp vụ, đối tác, cân và tồn kho

Bạn triển khai lane `records` của dự án **cafe_fin** theo yêu cầu đã chốt dưới đây. Thực hiện đầy đủ phần việc được giao, kiểm thử trên dữ liệu mới và bàn giao commit cho chat điều phối. Không biến tác vụ thành một đề xuất chung.

## 1. Điểm bắt đầu bắt buộc

- Repo mới: `C:\Users\NC\Desktop\UNILA{\cafe_fin`.
- Tag đặc tả: `cafe-fin-spec-v1`.
- **Chỉ bắt đầu sửa code sau khi chat điều phối thông báo `FOUNDATION_READY` và tag `cafe-fin-foundation-ready-v1` đã tồn tại.** Đọc trạng thái repo/tag bằng thao tác chỉ đọc; không tự tạo tag này hoặc giả định đã sẵn sàng. Nếu chưa sẵn sàng, báo điều phối và giữ nguyên repo.
- Đọc `AGENTS.md`, `README.md`, `docs/SPEC.md`, `docs/ARCHITECTURE.md`, `docs/API_CONTRACT.md`, `docs/OWNERSHIP.md` tại tag nền và tại checkout. Nếu thiếu file hoặc khác nhau ảnh hưởng interface, hỏi điều phối; không tự dựng interface thay thế.
- Tạo worktree và branch riêng, duy nhất cho lane records, bắt đầu từ tag foundation đã xác minh. Gọi `list_artifacts`, tìm và dùng công cụ `create_worktree` của app; không tự dùng `git worktree add`. Branch đề xuất `codex/cafe-fin-records`, thêm hậu tố duy nhất nếu đã tồn tại. Nếu công cụ lỗi hoặc thiếu, báo điều phối giải quyết. Không làm trực tiếp trên checkout điều phối và không sửa worktree lane khác.
- Ghi lại đường dẫn worktree, branch và SHA foundation. Kiểm tra thay đổi đang có, không ghi đè công việc người khác.

Nguồn cũ chỉ để đọc và tham khảo thuật toán khi hữu ích:

`C:\Users\NC\Desktop\UNILA{\CAFE-CRM-readiness-base-20261028-a`

Không sửa nguồn cũ, không kết nối DB cũ và không sao chép dữ liệu, tài khoản, credential hoặc file riêng tư. Dự án mới dùng dữ liệu mới. Quy trình nhiều người duyệt, QR, QC và các bất biến workflow của dự án cũ không phải yêu cầu của sản phẩm mới này.

## 2. Mục tiêu sản phẩm đã chốt

Ứng dụng chạy trên **một PC**, một người nhập liệu, dữ liệu xử lý và lưu local. Người dùng ghi lại nghiệp vụ đã diễn ra, xem lại, sửa và tổng hợp. Không phải hệ thống điều khiển quy trình hiện trường.

- Stack: Tauri + React 19, FastAPI local, SQLite WAL và tệp local theo foundation.
- Chỉ có hai nhóm quyền đơn giản: `operator` tác nghiệp và `admin` quản trị. Operator được nhập, sửa, ghi nhận hoàn thành và xem số liệu theo phạm vi của foundation; không có người duyệt/verifier bắt buộc.
- Giữ nghiệp vụ nhập/xuất/sản xuất/tồn có số liệu và lịch sử. **Chặn tồn âm** là yêu cầu thật, kể cả khi sửa, xóa hoặc ghi lùi ngày.
- Các cảnh báo thiếu dữ liệu, chênh lệch hoặc công nợ phục vụ người nhập; không dựng bước phê duyệt để hoàn tất hồ sơ.
- Kế toán là nhật ký giao dịch độc lập ở lane khác. Một giao dịch tiền không tự làm thay đổi hàng tồn; một phiếu hàng không mặc định sinh thu/chi tiền.
- Số tổng hợp chỉ phản ánh dữ liệu đã nhập vào cafe_fin. Không khẳng định đó là tồn thực tế hoặc toàn bộ hoạt động doanh nghiệp khi người dùng chưa ghi đủ.
- Không có QR, camera điện thoại, quét từng bao, chữ ký AI, QC gate, ca trưởng, bàn giao nhiều người, Google login, crawler hoặc giao dịch ra mạng ngoài trong lane này.
- Không thiết kế lại theme hoặc hệ thống giao diện dùng chung. Dùng UI nền để tập trung vào thao tác desktop rõ ràng, ít bước.

## 3. Phạm vi file được sở hữu

Bạn chỉ sửa trong:

- `backend/cafe_fin/records/**`
- `frontend/src/features/records/**`
- `tests/records/**`
- `docs/handoffs/records/**`

Migration SQL của lane nằm trong thư mục migration **riêng của module records** theo quy ước foundation. Không sửa migration đã áp dụng, không tạo bảng core trùng và không tự sửa registry migration trung tâm. Đặt tên theo ownership để tránh trùng với lane khác.

Backend công khai module qua `backend/cafe_fin/records/module.py`; frontend qua `frontend/src/features/records/index.ts`. Dùng đúng manifest/interface foundation đã định nghĩa. Điều phối sở hữu wiring dùng chung, router tổng, shell, dependency/package files, DB core và các hợp đồng dùng chung.

Nếu cần sửa file ngoài allowlist, bàn giao patch cụ thể và lý do trong báo cáo, không tự sửa. Nếu thiếu dependency, gửi tên, phiên bản và mục đích cho điều phối; không sửa package/lock hoặc tải gói tự phát trong tác vụ local.

## 4. Dữ liệu và thao tác cần có

### 4.1. Đối tác và hàng hóa

- CRUD đối tác dùng được cho cả khách mua và nhà cung cấp. Cho một đối tác giữ nhiều vai trò nếu cần; không bắt người dùng tạo Farm/thửa vườn hoặc hồ sơ pháp lý đầy đủ mới ghi phiếu.
- Thông tin cơ bản: mã, tên, loại/vai trò, liên hệ/địa chỉ và ghi chú. Các trường MST, đại diện, ngân hàng hoặc CCCD chỉ dùng khi người dùng nhập và hợp đồng cần, không ép trường ngoài đặc tả.
- CRUD sản phẩm/hàng hóa và đơn vị/vị trí theo `API_CONTRACT`. Grade, độ ẩm hoặc thông tin chất lượng nếu có là dữ liệu ghi nhận tùy chọn, không là điều kiện duyệt tồn.
- Không xóa cứng đối tác/hàng đang được tham chiếu. Cho ngừng sử dụng, giữ hồ sơ và lịch sử còn đọc được.

### 4.2. Phiếu cân nhập tay

- Người dùng tự ghi số cân hoặc số kg từ phiếu; không giả định kết nối cân điện tử.
- Theo hợp đồng API, hỗ trợ số phiếu, ngày/giờ nghiệp vụ, đối tác, biển xe/ghi chú nếu có, các dòng cân và nguồn nhập thủ công.
- Có thể ghi cân đầy/rỗng để tính tịnh, hoặc ghi kg tịnh trực tiếp khi chỉ có số đó. Kiểm tính hợp lệ của dạng người dùng chọn; không bắt giả số cân thiếu.
- Cho sửa số nhập với lịch sử. Không tự thay phiếu gốc khi một hợp đồng đã lấy bản chụp số cân.
- Phiếu cân là một hồ sơ độc lập; không bắt phải có đơn mua/bán, manifest, ca, chữ ký hoặc chứng từ đính kèm mới lưu.
- Chọn phiếu cân để lập phiếu hàng hoặc hợp đồng là thao tác chủ động. Không lưu một phiếu cân rồi âm thầm trừ/cộng kho.

### 4.3. Ghi nhận nhập, xuất và sản xuất

- Phiếu nhập: ngày nghiệp vụ, đối tác nếu có, dòng hàng/số kg, vị trí và diễn giải; liên kết phiếu cân tùy chọn.
- Phiếu xuất: ngày nghiệp vụ, đối tác nếu có, dòng hàng/số kg, vị trí và diễn giải; liên kết phiếu cân tùy chọn.
- Phiếu sản xuất: các dòng nguyên liệu tiêu thụ và sản phẩm thu được do người dùng ghi. Có thể nhập hao hụt/ghi chú theo đặc tả; không dựng đủ công đoạn sấy/xát/QC mới cho ghi nhận.
- Số liệu nhập chưa đầy đủ có thể giữ nháp nếu foundation có khái niệm nháp. Khi người dùng chọn ghi nhận vào sổ, cập nhật ledger trong một giao dịch nguyên tử và trả trạng thái thật; không có hàng đợi duyệt.
- Các nhãn nháp/đã ghi/hủy chỉ mô tả dữ liệu, không biến thành workflow nhiều role. Không tạo status chain hoặc nút phê duyệt ngoài API đã chốt.
- Các thông tin tiền hàng có thể dùng để tổng hợp số dư thương mại theo API, nhưng không tự tạo tiền đã thu/chi trong sổ kế toán.

## 5. Ledger và bất biến tồn âm

- Mỗi tác động nhập/xuất/tiêu thụ/thu hồi từ sản xuất có nguồn duy nhất và ledger truy ngược được; không cập nhật một con số tồn rời khỏi lịch sử.
- Dùng cơ chế transaction, khóa ghi SQLite và connection/Unit of Work của core. Khâu đọc tồn, kiểm đủ tồn, ghi ledger và ghi trạng thái phiếu phải ở cùng transaction. Không dùng mô hình đọc tồn rồi commit ở nhiều request.
- Có hai phiên gửi cạnh tranh cũng không được cùng tiêu thụ một lượng tồn. Chứng minh bằng test có hai connection/transaction, không chỉ test hàm tính riêng.
- Sửa phiếu đã ghi cần ghi phiên bản/điều chỉnh hoặc đảo bút toán ledger và áp bản mới theo thiết kế nền; thực hiện nguyên tử. Không xóa dấu vết cũ hoặc chỉ sửa balance cuối.
- Xóa/hủy phiếu đã ghi phải dùng soft delete hoặc reversal có lịch sử; nếu hủy phiếu nhập làm các phiếu xuất/sản xuất sau đó âm tồn thì từ chối toàn bộ và trả lý do cụ thể.
- Ghi lùi ngày hoặc đổi ngày phải kiểm lại chuỗi tồn của sản phẩm/vị trí và các chiều tracking theo API ở các mốc bị ảnh hưởng, không chỉ kiểm tồn cuối hiện tại. Không chấp nhận âm tại một mốc lịch sử rồi được một phiếu nhập sau đó bù lại.
- Thứ tự khi trùng ngày/giờ phải xác định được theo foundation, giữ ổn định khi retry; không dựa vào thứ tự hiển thị của trình duyệt.
- Nguồn sản xuất có nhiều dòng trùng cùng chiều tồn phải được cộng gộp trước kiểm tra và cập nhật; không kiểm từng dòng riêng rồi tiêu thụ vượt tổng.
- Khi một bước không hợp lệ, rollback cả chứng từ/ledger/số dư; không giữ nửa phiếu hoặc số tồn thay đổi.
- Không giải quyết thiếu tồn bằng cách tự sinh tồn đầu, bỏ validation, cho xuất âm hoặc sửa dữ liệu người dùng.

## 6. API, kiểu dữ liệu và điểm tích hợp

Theo `docs/API_CONTRACT.md`, các nhóm endpoint của lane nằm dưới:

- `/api/v1/records/parties`
- `/api/v1/records/products`
- `/api/v1/records/weighings`
- `/api/v1/records/entries`
- `/api/v1/records/stock-movements`
- `/api/v1/records/stock-balances`
- `/api/v1/records/receivables`

Không tự đổi tên path, DTO, error envelope hoặc cách phân trang. Nếu đặc tả thiếu một thao tác cần thiết, gửi điều phối đề xuất nhỏ trước khi triển khai phần phụ thuộc.

- ID là UUID dạng chuỗi. Lệnh sửa dùng `expected_version` dương; lệnh command dùng `request_key` theo core.
- JSON trả số chính xác dưới dạng chuỗi Decimal canonical. Dùng `Amount`/`Money` của core; không dùng float cho kg hoặc tiền. Kg lưu integer scale 1.000, tiền lưu integer scale 100 theo foundation; kiểm range trước chuyển đổi và phép nhân để tránh overflow.
- Retry cùng key/cùng payload không tạo thêm phiếu/ledger; cùng key/khác payload trả conflict. Chỉ trả thành công khi transaction đã commit.
- Cung cấp bridge chỉ đọc có typed DTO: `records.lookup_party(id)` và `records.get_weighing(id)` đúng interface nền để lane contracts lấy dữ liệu tùy chọn. Không để bridge thay đổi phiếu hoặc kích hoạt side effect.
- Cung cấp `records.inventory_summary(from,to)` và `records.receivable_summary(as_of)` cho reporting, với cutoff, `coverage='entered_records_only'` và Decimal strings theo API_CONTRACT. Kiểm thử tổng hợp, ranh giới ngày và coverage flags; không để reporting phải đọc private ORM.
- Không gọi vòng vào lane contracts/accounting. Không sửa file của lane đó. Những liên kết cần chung được điều phối wiring qua contract nền.

## 7. Giao diện desktop và tổng hợp

- Danh sách có tìm kiếm/lọc ngày, đối tác, loại phiếu và trạng thái dữ liệu theo API; thêm nhanh, mở chi tiết và sửa dễ hiểu.
- Bảng cân và phiếu hàng hỗ trợ bàn phím, định dạng số nhất quán; không gắn camera/QR hoặc màn mobile.
- Sau lưu phải hiển thị số phiếu và dữ liệu đã lưu; lỗi validation nêu dòng hàng và lượng thiếu để người dùng sửa.
- Báo cáo tồn: đầu kỳ, tăng, giảm, điều chỉnh và cuối kỳ; tách chuyển nội bộ/sản xuất khỏi mua mới và bán ra. Không cộng một lượng qua nhiều công đoạn thành lượng mua nhiều lần.
- Hiển thị phạm vi ngày/giờ cắt theo múi giờ foundation và chú thích **chỉ phản ánh dữ liệu đã nhập**.
- Tổng hợp công nợ theo API là số dư ghi nhận, không khẳng định đã đối chiếu toàn bộ doanh nghiệp. Không buộc nhật ký kế toán độc lập bao phủ tất cả phiếu CRM để trang ghi nhận hoạt động được.
- Tệp/ảnh chứng từ nếu có là tùy chọn trong lane này, lưu bằng storage API local; không đòi upload ảnh để lưu phiếu cân tay.

## 8. Kiểm thử và điều kiện hoàn thành

Viết và chạy các test có ý nghĩa trong `tests/records/**`; dùng SQLite file thật/WAL và test DB tạm riêng. Không dùng DB cũ hoặc dữ liệu production.

Tối thiểu chứng minh:

1. CRUD đối tác/sản phẩm, lịch sử và ngừng sử dụng không phá tham chiếu.
2. Cân tay dạng đầy/rỗng và dạng tịnh trực tiếp; dữ liệu thiếu không bị thay thành 0 giả.
3. Nhập → xuất → sản xuất và đối chiếu ledger/balance đúng số thập phân.
4. Xuất vượt tồn bị chặn; hai yêu cầu cạnh tranh không làm âm tồn.
5. Nhiều dòng cùng sản phẩm/vị trí không vượt tồn do kiểm riêng từng dòng.
6. Sửa giảm phiếu nhập, hủy phiếu nhập và backdate có thể làm âm lịch sử đều bị chặn nguyên tử; bản cũ/ledger còn nguyên khi thất bại.
7. Sửa/xóa hợp lệ tạo lịch sử đúng và không làm xuất hiện tác động ledger hai lần.
8. Retry idempotent, payload khác conflict và sửa bằng version cũ conflict.
9. Ngày nghiệp vụ/ranh giới qua ngày đúng múi giờ nền.
10. Phiếu cân không tự đổi kho; bản ghi kế toán không được lane này tự tạo/cập nhật kho.
11. Bridge typed DTO đọc đối tác/cân không có side effect.
12. Một luồng desktop thật với dữ liệu tổng hợp: đối tác → cân tay → nhập hàng → xuất hàng → xem tồn, không có phê duyệt/QR/QC gate.

Chạy kiểm tra build/typecheck/lint của lane theo nền đã có; không tự sửa cấu hình dùng chung để làm pass. Báo `NOT RUN` và nguyên nhân cho phần thật sự chưa chạy; không coi mock hoặc test hàm riêng là bằng chứng cạnh tranh/desktop đã đạt.

## 9. Bàn giao cho điều phối

Commit chỉ các file thuộc ownership trên branch của bạn. **Không push, không merge, không tạo PR và không đổi tag foundation.** Không sửa source cũ hoặc DB cũ. Gửi điều phối:

- Worktree, branch, SHA nền và danh sách SHA commit có thể cherry-pick theo thứ tự.
- File đã đổi và API/manifest/bridge đã cung cấp.
- Migration module và cách chạy trên DB mới, không tự áp vào runtime chung.
- Lệnh kiểm thử, kết quả thật, test chưa chạy và lỗi còn tồn tại.
- Bằng chứng test tồn âm/sửa/hủy/backdate/cạnh tranh và đối chiếu ledger.
- Patch wiring/dependency ngoài allowlist nếu có; không ghi là đã tích hợp khi root chưa ghép.

Hoàn thành khi chức năng và tests của lane chạy được trên foundation trong worktree riêng, bàn giao rõ phần cần root wiring; không đợi phê duyệt nhiều người và không thêm thủ tục không có trong yêu cầu này.
