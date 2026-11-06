# Chat triển khai 02 — Hợp đồng tự điền, Word/PDF và chứng từ local

Bạn triển khai lane `contracts` của dự án **cafe_fin** theo yêu cầu đã chốt dưới đây. Hoàn thiện module và kiểm chứng xuất tài liệu; bàn giao commit cho chat điều phối. Đây là ứng dụng ghi nhận, không sao chép workflow phê duyệt của CRM cũ.

## 1. Điểm bắt đầu bắt buộc

- Repo mới: `C:\Users\NC\Desktop\UNILA{\cafe_fin`.
- Tag đặc tả: `cafe-fin-spec-v1`.
- **Chỉ bắt đầu sửa code sau khi điều phối thông báo `FOUNDATION_READY` và tag `cafe-fin-foundation-ready-v1` đã tồn tại.** Kiểm tra chỉ đọc, không tự tạo tag hoặc tuyên bố nền sẵn sàng.
- Đọc `AGENTS.md`, `README.md`, `docs/SPEC.md`, `docs/ARCHITECTURE.md`, `docs/API_CONTRACT.md`, `docs/OWNERSHIP.md` tại tag nền và checkout. Thiếu file hoặc có xung đột interface thì báo điều phối trước phần triển khai phụ thuộc.
- Tạo worktree và branch riêng, duy nhất cho lane contracts, từ tag foundation đã xác minh. Gọi `list_artifacts`, tìm và dùng công cụ `create_worktree` của app; không tự dùng `git worktree add`. Branch đề xuất `codex/cafe-fin-contracts`, thêm hậu tố duy nhất nếu đã tồn tại. Công cụ lỗi hoặc thiếu thì báo điều phối. Không làm trực tiếp trên checkout điều phối/lane khác. Ghi đường dẫn, branch và SHA nền.

Nguồn cũ được phép đọc, không sửa:

`C:\Users\NC\Desktop\UNILA{\CAFE-CRM-readiness-base-20261028-a`

Không truy cập/sao chép DB cũ, hồ sơ thật, credential, chữ ký hoặc con dấu thật. Dự án mới dùng dữ liệu mới. Yêu cầu mới ưu tiên ghi nhận đơn giản; các quy trình bắt nhiều người duyệt của repo cũ không được tự mang sang cafe_fin.

## 2. Kết quả cần đạt

Người dùng trên một PC có thể lập **hợp đồng mua và bán** bằng cách chọn/nhập thông tin đối tác, số liệu cân do người dùng ghi, điều khoản và phương thức thanh toán; hệ thống tự điền phần đã có, cho chỉnh trước xuất, xem trước và xuất **DOCX/PDF** local.

- Stack theo foundation: Tauri + React 19, FastAPI local, SQLite WAL và tệp local.
- Operator được lập/sửa/lưu/xuất hợp đồng; admin quản trị mẫu/cấu hình. Không yêu cầu approver, verifier, QC, nghiệm thu toàn khung hoặc hoàn thành kế toán mới được xuất.
- Có thể lập hợp đồng bằng dữ liệu nhập tay hoàn toàn, kể cả khi lane records chưa có đối tác hoặc phiếu cân. Không ép tạo thỏa thuận, đơn bán, Farm, ca hoặc phiếu kho trước.
- Một hợp đồng lấy một hoặc nhiều dòng/phiếu cân do người dùng chọn hoặc nhập tay. Các dòng trong hợp đồng được phép chỉnh; không viết ngược sang phiếu cân nguồn.
- Lưu snapshot mỗi lần xuất để mở lại đúng bản cũ; sửa dữ liệu nguồn hoặc mẫu sau đó không âm thầm thay bản đã xuất.
- Có thể đính kèm chứng từ/bản ký sau; **không bắt đính kèm mới lưu/xuất**. Metadata bản ký là người dùng ghi nhận, không là kết luận xác minh chữ ký điện tử.
- Hợp đồng không tự thu/chi tiền, tạo công nợ kế toán, chuyển cọc hoặc cập nhật tồn. Nhật ký kế toán độc lập chỉ liên kết khi người dùng chủ động chọn.
- Không làm QR, AI chữ ký, quét điện thoại, theme mới hoặc tích hợp ký điện tử/network trong lane này.

## 3. Ownership và điểm tích hợp

Chỉ sửa:

- `backend/cafe_fin/contracts/**`
- `frontend/src/features/contracts/**`
- `tests/contracts/**`
- `docs/handoffs/contracts/**`

Migration SQL thuộc module contracts, theo thư mục/tên thứ tự đã quy định trong foundation. Không sửa migration đã chạy, registry trung tâm, schema core hoặc file lane records/accounting.

Backend manifest: `backend/cafe_fin/contracts/module.py`. Frontend public manifest: `frontend/src/features/contracts/index.ts`. Đăng ký đúng interface nền; điều phối wiring shell/router/dependency dùng chung. Không tự sửa package/lock hoặc thêm một framework tài liệu khác ngoài nền.

API của lane dưới `/api/v1/contracts/` theo `docs/API_CONTRACT.md`. DTO, error envelope, phân trang, storage và auth dùng core, không tạo giao thức riêng.

Bridge tùy chọn từ records là hai hàm typed DTO, chỉ đọc:

- `records.lookup_party(id)`
- `records.get_weighing(id)`

Dùng interface/adapter của foundation, không import thẳng ORM hoặc sửa code records. Khi chưa có bridge implementation, module vẫn hỗ trợ dữ liệu nhúng nhập tay và kiểm thử độc lập; ghi rõ wiring cần root nối. Không biến việc chưa có records thành blocker cho lưu/xuất hợp đồng nhập tay.

## 4. Mô hình dữ liệu và form

### 4.1. Thông tin hợp đồng và các bên

- Loại mua/bán; số hợp đồng, ngày, nơi lập; mẫu và phiên bản mẫu.
- Hồ sơ doanh nghiệp của người dùng và đối tác: tên, địa chỉ, MST/CCCD khi phù hợp, liên hệ, người đại diện/chức vụ, tài khoản/ngân hàng nếu người dùng nhập.
- Tự điền từ hồ sơ đã chọn, cho sửa bản chụp trong hợp đồng. Không bắt bổ sung trường không có trong mẫu/đặc tả để ghi một hợp đồng đơn giản.
- Không hardcode tên HTX, địa chỉ, ngân hàng, người ký hoặc thông tin riêng từ dự án cũ.
- Nếu nguồn thay đổi, cho người dùng chủ động lấy lại dữ liệu và xem phần thay đổi; không ghi đè phần đang sửa. Việc sửa bên trong hợp đồng không tự sửa hồ sơ đối tác nguồn.

### 4.2. Dòng cân, hàng và giá

- Cho chọn một/nhiều phiếu cân hoặc nhập dòng trực tiếp. Ghi số phiếu/thời điểm, tên hàng, cân đầy/rỗng/tịnh nếu có và lượng dùng cho hợp đồng.
- Nếu chỉ có kg tịnh, không bắt tạo cân đầy/rỗng giả. Người dùng chịu trách nhiệm số liệu họ ghi; ứng dụng kiểm số hợp lệ và phép tính, không tuyên bố đã đo qua thiết bị.
- Dữ liệu nhập từ phiếu cân là bản chụp có nguồn tham chiếu; cho chỉnh lượng/đơn giá/diễn giải trong hợp đồng, giữ dấu vết nguồn và override theo API.
- Tính tổng khối lượng/tiền từ đúng tập dòng hàng; không nhân cùng lượng nhiều lần chỉ vì có nhiều dòng chất lượng hoặc điều khoản.
- Tránh chọn trùng cùng một dòng cân mà cộng tiền hai lần; phát hiện trùng nguồn và cho người dùng sửa lựa chọn theo hợp đồng API. Không ngăn hai hợp đồng ghi nhận độc lập chỉ vì cùng một đối tác.
- Chất lượng, Grade, độ ẩm, bao bì, địa điểm giao là trường ghi nhận/điều khoản tùy chọn theo mẫu, không là QC gate. Không cố định mọi hợp đồng bán thành ẩm 15%, tạp 1%, đen vỡ 5%, sàng 16–18 như code cũ.
- Thuế và cách giá theo các lựa chọn đã quy định trong `SPEC`; không tự mặc định thuế 0 hoặc mang policy VAT của CRM cũ sang. Trường chưa xác định phải biểu diễn rõ, không thay thành 0 giả.

### 4.3. Điều khoản và phương thức thanh toán

- Có các trường cấu trúc thuận tiện cho giao hàng, bao bì, thời hạn, trách nhiệm các bên và thanh toán theo mẫu; có ô nội dung bổ sung tự do cho người dùng nhập/sửa.
- Phương thức thanh toán hỗ trợ `cash`, `bank`, `mixed`, `other` hoặc giá trị canonical tương ứng API. Hiển thị tiếng Việt dễ hiểu.
- Có diễn giải thanh toán, tài khoản nhận nếu dùng chuyển khoản, hạn/thời điểm thanh toán và lịch nhiều đợt tùy chọn; không ép người dùng lập payment workflow.
- Nếu nhập cọc hoặc lịch thanh toán, đó là **điều khoản đã ghi trên hợp đồng**, không xác nhận đã thực thu/chi. Số đã trả do người dùng ghi nếu có phải tách nghĩa với tiền cam kết.
- Nội dung cấu trúc phải điền vào token thực sự trong mẫu. Không chỉ thêm ô form rồi vẫn xuất lời văn thanh toán cố định cũ.
- Hợp đồng mua và bán đều cho nhập điều khoản phù hợp. Không bắt cọc bán phải treo mùa vụ/đơn cuối, không ép thanh toán sau toàn bộ khung hoặc chờ nghiệm thu cũ.
- Trình bày các đoạn tự do dưới dạng văn bản an toàn, xuống dòng đúng, không chạy HTML/script và không tải ảnh/font từ URL ngoài.

## 5. Snapshot, phiên bản và chứng từ

- Tách bản đang soạn khỏi bản xuất. Operator có thể lưu nháp, sửa và xuất trực tiếp; nút xuất là thao tác tạo tài liệu, không là một bước phê duyệt.
- Mỗi lần xuất thành công giữ snapshot: thông tin các bên, tập dòng cân/hàng, điều khoản/thanh toán, tổng, template version/hash và thời điểm/người xuất theo API.
- Lưu phiên bản và file local kèm hash. Tải lại đúng bytes bản đó, không render lại từ template mới khi người dùng mở bản cũ.
- Sửa/xóa dùng version history hoặc soft delete. Giữ các snapshot/tệp đã xuất còn tra cứu được theo chính sách nền; không xóa dây chuyền vì đối tác hoặc phiếu cân nguồn ngừng dùng.
- Sửa dùng `expected_version`; lưu/xuất command dùng `request_key` của core. Retry không tạo thêm phiên bản/tệp ngoài ý muốn; payload đổi cùng key trả conflict.
- Khi upload chứng từ/bản ký, dùng storage local, loại tệp và giới hạn của foundation. Lưu người tải, thời điểm, ghi chú, tham chiếu phiên bản; không tự chèn ảnh chữ ký/con dấu hoặc kết luận hợp đồng đã được xác thực.
- Không tạo review queue hoặc bắt người thứ hai kiểm bản ký. Có thể ghi trạng thái theo người dùng tự xác nhận, với nhãn phản ánh đúng ý nghĩa.
- ID UUID chuỗi; JSON kg/tiền là Decimal strings canonical. Dùng `Amount`/`Money` của core và integer scaling (kg ×1.000, tiền ×100), kiểm range; không float. Phép tính tổng và tiền bằng chữ phải nhất quán với quy tắc làm tròn đã chốt.

## 6. Tái sử dụng renderer cũ có chọn lọc

Có thể tham khảo và tách phần thuần xử lý tài liệu từ:

- `backend/app/contracts/rendering.py`: định dạng số/tiền bằng chữ, điền DOCX, chuyển nội dung sang PDF local.
- `backend/app/contracts/templates/{purchase,sale,appendix}.docx` và README mẫu.
- `backend/app/contracts/models.py`: ý tưởng snapshot/version/hash, không sao chép FK/workflow.

Trước sao chép, kiểm license và nguồn gốc; giữ thông báo/attribution cần thiết trong file thuộc module hoặc handoff cho root. Không sao chép dữ liệu thật. Nếu quyền tái sử dụng chưa xác định thì viết implementation mới dựa trên yêu cầu, không giả định quyền từ việc file nằm local.

**Không copy nguyên** `contracts/api.py`, `service.py`, schemas gắn Agreement/SalesOrder, acceptance, seasonal deposits hoặc finance; chúng đang ép nguồn giao dịch và nhiều gate đã bị bỏ trong sản phẩm mới.

Mẫu cũ còn một số câu lỗi được giữ nguyên từ nguồn, ví dụ hai mục 4.2 và “Bên A phải thanh toán cho bên A” nêu tại `templates/README.md`. Dùng mẫu đó như tài liệu tham khảo bố cục; không mang lỗi lời văn hoặc điều khoản cố định trái với input sang mẫu cafe_fin. Không tuyên bố mẫu đã được kiểm định pháp lý.

### Xuất DOCX và PDF độc lập

- DOCX phải xuất được dù thành phần PDF local đang thiếu/hỏng. PDF lỗi trả lỗi đúng, giữ bản soạn và file DOCX đã có; không báo cả hai thành công nếu chỉ một định dạng thành công.
- PDF và DOCX dùng cùng snapshot/version, nội dung số/điều khoản phải khớp. Theo API nền, ghi trạng thái file riêng và cách bổ sung file còn thiếu mà không thay snapshot.
- Không dùng dịch vụ chuyển đổi online, font/CDN hoặc model tải lúc chạy. Liệt kê dependency/font/native runtime cần root đóng gói local; không tự tải từ mạng trong luồng xuất.
- Chức năng xuất cốt lõi không phụ thuộc Microsoft Office đã cài, trial hoặc thư viện trả phí. Chỉ dùng thư viện miễn phí có license tương thích cách phân phối; thông báo các dependency/native runtime cần đóng gói cho root.
- Nếu dùng WeasyPrint như nguồn cũ, kiểm font tiếng Việt và native runtime trên môi trường target. Không coi DOCX zip hợp lệ hoặc PDF có header là bằng chứng layout đúng.

## 7. UI desktop

Luồng chính nên ngắn: **chọn mua/bán → chọn hoặc nhập đối tác → chọn/nhập cân → nhập giá, điều khoản và thanh toán → lưu/xem trước/xuất**.

- Trường tự điền thể hiện nguồn vừa đủ; người dùng sửa được phần cho phép mà không phải mở nhiều module khác.
- Cho tạo hợp đồng nhập tay khi không có dữ liệu nguồn. Thiếu trường thực sự cần để render phải chỉ ra rõ trường cần nhập, không đưa người dùng vào chuỗi workflow cũ.
- Cho mở phiên bản đã xuất, tải DOCX/PDF riêng, xem metadata và đính kèm tệp tùy chọn.
- Dùng thành phần UI nền, bố cục desktop và thao tác bàn phím; không phát triển theme hoặc màn mobile.
- Các thông báo không được ngụ ý đã ghi thu/chi/kho chỉ vì hợp đồng được xuất.

## 8. Kiểm thử và kiểm tra tài liệu

Tests thuộc `tests/contracts/**`. Dùng dữ liệu tổng hợp, DB/tệp tạm riêng; không dùng hồ sơ thật hoặc DB cũ.

Tối thiểu chứng minh:

1. Mua và bán đều lưu/xuất bằng dữ liệu nhập tay khi chưa có records data; không cần approval/QC/finance.
2. Tự điền từ typed bridge khi có đối tác/cân; một/nhiều phiếu, chỉnh bản chụp không sửa nguồn.
3. Phương thức tiền mặt/chuyển khoản/kết hợp/khác và điều khoản sửa tự do xuất đúng ở cả DOCX/PDF.
4. Khối lượng/giá/tổng/tiền bằng chữ và thuế nếu dùng khớp theo core precision, không double count dòng chất lượng hoặc nguồn cân trùng.
5. Unicode tiếng Việt, tên/địa chỉ dài, nhiều dòng cân, điều khoản dài và nội dung nhiều trang render được; không còn token thô.
6. Snapshot cũ/tệp cũ không đổi khi đối tác, cân, điều khoản hoặc template mới thay đổi; xóa mềm không phá lịch sử.
7. DOCX vẫn xuất khi PDF lỗi; không ghi trạng thái PDF thành công giả; tải lại đúng file/hash.
8. Idempotency/version conflict đúng; file lỗi giữa chừng không để trạng thái xuất thành công hoặc hỏng snapshot đã có.
9. Chứng từ/bản ký là tùy chọn; lưu metadata không bị gọi là xác minh e-sign và không tạo review queue.
10. Không có side effect tiền/kho khi tạo, sửa, xuất hoặc đính kèm hợp đồng.
11. Một luồng desktop thật: nhập tay hợp đồng → sửa điều khoản/thanh toán → xem trước → xuất Word/PDF → sửa nguồn → mở lại bản cũ.

Với tài liệu xuất, render DOCX bằng runtime local phù hợp và PDF thành ảnh trang; xem trực quan từng trang của bộ fixture đại diện. Kiểm trang A4, bảng không mất dòng, chữ Việt không lỗi font, điều khoản không đè chữ ký và trang dài không bị cắt. Áp dụng skills documents/pdf nếu công cụ và quy trình xuất thực tế phù hợp, trong phạm vi file lane.

Ghi chính xác lệnh/kết quả; native dependency hoặc bước visual nào chưa chạy phải báo `NOT RUN` với nguyên nhân, không dùng test dữ liệu thuần để tuyên bố xuất/hiển thị trên PC đã đạt.

## 9. Bàn giao

Commit chỉ file thuộc ownership trên branch riêng. **Không push, merge, tạo PR hoặc đổi tag nền.** Không áp migration vào runtime chung, không sửa repo cũ.

Gửi điều phối:

- Worktree, branch, SHA nền và các SHA commit để cherry-pick theo thứ tự.
- API/manifest, DTO bridge đã dùng, đường dẫn templates và migration module.
- Danh sách phần tham khảo/sao chép cùng license/attribution; không chứa thông tin riêng tư.
- Dependency/font/native runtime cần đóng gói và patch wiring ngoài allowlist nếu có.
- Kết quả test, tệp mẫu xuất, số trang và bằng chứng kiểm trực quan; phần `NOT RUN` và giới hạn thật.
- Bằng chứng DOCX/PDF độc lập, snapshot không đổi và hợp đồng không tác động sổ tiền/tồn.

Lane hoàn tất khi có chức năng chạy được trên foundation trong worktree riêng và bàn giao rõ tích hợp cho root; không thêm lại approval gates của hệ thống cũ để hoàn thành tác vụ này.
