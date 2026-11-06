# Prompt 03 — Khu kế toán độc lập, grid như Excel và nhập dữ liệu lớn

Bạn là agent phụ trách lane kế toán của dự án `cafe_fin`. Hãy triển khai đầy đủ phần việc bên dưới, tạo thay đổi có thể chạy và kiểm chứng, không dừng ở bản mô phỏng giao diện. Prompt này là yêu cầu sản phẩm và kỹ thuật; đọc tài liệu chung để lấy tên API, quyền, cấu trúc và giao thức tích hợp chính thức trước khi viết code.

## 1. Đọc trước và phạm vi sở hữu

Đọc `AGENTS.md`, `README.md`, `docs/SPEC.md`, `docs/ARCHITECTURE.md`, `docs/API_CONTRACT.md`, `docs/OWNERSHIP.md` và các cập nhật của điều phối. Kiểm tra branch, working tree và mã hiện có; bảo toàn thay đổi của người khác. Làm trên branch/worktree đã giao. Không push, merge hoặc thao tác dữ liệu thật.

Repo: `C:\Users\NC\Desktop\UNILA{\cafe_fin`, remote `https://github.com/minh0407/cafe_fin.git`. Chỉ bắt đầu từ tag bất biến `cafe-fin-foundation-ready-v1` do điều phối công bố; tag thiếu thì chờ, không tự dùng HEAD khác hoặc tạo tag thay. Dùng list_artifacts để tìm worktree phù hợp, create_worktree để tạo nếu cần, tại SHA tag đã xác minh; branch riêng `codex/cafe-fin-accounting-<unique>`. Không sửa checkout điều phối hoặc lane khác.

Lane này sở hữu:

- `backend/cafe_fin/accounting/`;
- `frontend/src/features/accounting/`;
- `tests/accounting/`;
- `docs/handoffs/accounting/**`;
- migration riêng của lane đúng vị trí/quy ước trong `docs/OWNERSHIP.md`.

Chỉ sửa file được giao. Registration route, menu chung, dependency manifest/lockfile, DB factory, serialized writer, job registry, shell Tauri và chính sách mạng là file chung: gửi patch tích hợp cụ thể cho điều phối nếu không thuộc allowlist. Không sửa ownership để mở rộng quyền. Nếu contract còn thiếu một thành phần cần thiết, đưa đề xuất rõ payload, lỗi và test tích hợp; không tự tạo API trùng hoặc hai DB writer cạnh tranh.

## 2. Yêu cầu đã chốt

- Đây là ứng dụng **một máy tính**, bắt đầu bằng **dữ liệu mới**. Toàn bộ sổ, tệp nguồn, bản nháp, xử lý import, công thức và báo cáo nằm local.
- Stack chung: Tauri 2, React 19, TypeScript, Ant Design, TanStack React Query, Zustand; FastAPI; SQLite WAL; serialized writer và local job runner. Không tự đổi stack hoặc kéo dữ liệu lên dịch vụ ngoài.
- Kế toán là **khu riêng để nhập và ghi chép thu chi**, vận hành độc lập với CRM. Không bắt từng dòng phải khớp hoặc bao phủ mọi hoạt động nhập kho/sản xuất/bán hàng. Không tự ghi vào ledger kho, công nợ hoặc quy trình duyệt CRM.
- Cột sổ kế toán chưa được doanh nghiệp cung cấp đầy đủ: xây **sổ và ánh xạ cột có cấu hình**, không tự áp một template cứng rồi coi đó là nghiệp vụ đã chốt.
- Người dùng thao tác và chỉnh sửa ngay trong ứng dụng. Không mở Microsoft Excel/LibreOffice để xử lý thay, không dùng COM hoặc yêu cầu cài Office.
- Cần grid nhập theo ô, chọn vùng, copy/paste, lọc, tìm kiếm, CRUD, import/export và một tập công thức thông dụng bằng thư viện miễn phí tương thích giấy phép. Không cam kết tương thích Excel 100%.
- Tệp gốc, kể cả `.xlsm`, phải được giữ **nguyên byte**, có hash kiểm tra. Không chạy macro, script, DDE, external queries hoặc liên kết ngoài. Không mở rồi save lại tệp nguồn bằng openpyxl.
- Tệp 500.000–1.000.000 dòng phải qua streaming/background job có staging, tiến độ bền vững, preview theo trang, lỗi tới ô, khôi phục sau dừng và chống nhập lặp.
- Sau người dùng xác nhận, được nhập **những dòng hợp lệ được chọn**, giữ các dòng lỗi để sửa rồi gửi lại. Lần gửi lại không chèn lại những dòng đã nhập thành công.

## 3. Mô hình sổ có cấu hình

Triển khai book, schema revision, column definitions và mapping profile được lưu trong DB. Mỗi cột có ID ổn định, tên hiển thị, thứ tự, kiểu dữ liệu, nullable/required, precision/scale nếu áp dụng, quy tắc validation, có cho sửa hay là cột công thức và cấu hình hiển thị. Hỗ trợ ít nhất text/mã, ngày, số nguyên, số thập phân, tiền, lựa chọn và công thức thuộc tập được hỗ trợ.

Phân biệt tên cột hiển thị với ID cột. Đổi tên không được làm mất mapping/công thức. Không tự đổi kiểu cột đã có dữ liệu theo suy đoán; thay schema có kiểm tương thích, phiên bản và ảnh hưởng dữ liệu cũ. Có thể tạo sổ trống, cấu hình cột, lưu profile ánh xạ và tái sử dụng cho lần nhập sau.

Ngữ nghĩa thu/chi phục vụ báo cáo được cấu hình rõ: ví dụ cột ngày, số tiền thu/chi riêng hoặc chiều giao dịch + số tiền, đơn vị tiền và các chiều nhóm. Không mặc định mọi số là tiền hoặc mọi dòng sản phẩm là một giao dịch thanh toán. Nếu sổ chưa ánh xạ đủ ngữ nghĩa báo cáo, giao diện chỉ ra phần cần cấu hình và không dựng tổng thu/chi giả.

Cho phép cột tham chiếu mã đơn/sản phẩm tùy chọn. Không bắt FK tới CRM cho dữ liệu độc lập; không tự tạo đơn hàng hoặc sản phẩm từ tên trong tệp. Không tự gộp nhiều đơn vị tiền vào một tổng duy nhất.

Tiền và số có precision phải có biểu diễn chính xác. Core Money đã chốt VND scale 2, DB integer đơn vị 0,01 VND có kiểm int64; core Amount kg scale 3. Dùng đúng helpers/DTO, giữ Decimal cho phép tính authoritative. Cột decimal tùy cấu hình có thể có scale riêng nhưng không tự đổi Money/Amount hoặc silently round. Không dựa vào SQLite REAL, float Python hoặc Number JavaScript để quyết định tổng tiền. Gửi số chính xác qua API dạng chuỗi theo contract. Kiểm cả overflow khi cộng hàng triệu dòng; không chữa overflow bằng chuyển sang REAL.

## 4. Grid dùng ngay trong ứng dụng

Ưu tiên spike Glide Data Grid vì MIT và thiết kế render theo ô nhìn thấy. Xác minh **đúng phiên bản package đã chọn** với React 19, peer dependencies và WebView2/Tauri; không coi README của nhánh main là chứng cứ release bất kỳ đã tương thích. Không dùng `--legacy-peer-deps` hoặc bỏ kiểm TypeScript để che lỗi. Nếu candidate không đạt, đề xuất thư viện miễn phí khác cùng tradeoff cho điều phối. Không đưa Handsontable vào production bằng key non-commercial/evaluation; không lấy tính năng Enterprise của thư viện khác mà không có giấy phép.

Grid phải có:

- điều hướng bằng phím, Enter/Tab, sửa ô, chọn vùng, copy/paste bảng TSV tương thích thao tác Excel;
- kéo điền trong phạm vi giới hạn rõ, có preview và validation như paste; kiểm cả vùng vượt trang đang xem, không tự coi dữ liệu chưa tải là trống;
- thêm dòng, sửa, xóa/khôi phục theo quyền; thao tác nhiều dòng với kết quả từng dòng rõ;
- resize/freeze cột, định dạng ngày/số/tiền đúng schema; lọc, sort, search và jump tới dòng/lỗi;
- trạng thái đang sửa/chờ lưu/đã lưu/lỗi, bảo vệ rời trang khi còn thay đổi chưa lưu;
- validation tại ô, tooltip/lý do lỗi và bảng lỗi có thể điều hướng về ô;
- không dùng toast “thành công” trước khi backend xác nhận;
- draft undo/redo có phạm vi rõ; thay đổi đã lưu dùng version/audit và thao tác khôi phục được kiểm quyền, không xóa lịch sử.

Modal preview có thể gần toàn màn hình, có thanh tiến độ và tổng hợp; vẫn giữ được dữ liệu khi đóng modal rồi mở lại job. Không đổ toàn bộ dataset vào React state, Zustand, React Query cache hoặc một `getCellsForSelection` trả hàng triệu ô. Dùng viewport/page cache có giới hạn; dữ liệu chưa tải không được tự coi là ô trống. Copy/export phạm vi lớn dùng job/range endpoint có giới hạn và thông báo rõ; thao tác paste lớn phải staging/validate ở backend, không treo main thread.

Filter/sort/search trên toàn dataset do backend thực hiện với whitelist trường/toán tử, giá trị parameterized và thứ tự phụ ổn định theo ID. UI phải phân biệt tổng bộ lọc với số dòng của trang đang xem. Cache key có actor, book, schema/data revision, filter/sort và trang để không hiện nhầm dữ liệu sau đổi tài khoản.

CRUD dùng row ID/version ổn định, optimistic concurrency và audit trước/sau. Khi conflict, hiển thị dữ liệu cũ/mới và cho tải lại/chọn xử lý; không silent overwrite. Xóa không được làm thay đổi bản snapshot báo cáo đã phát hành. Không tự tạo chức năng sửa trực tiếp sổ CRM ngoài lane này.

## 5. Tệp nguồn và diễn giải dữ liệu

Nhận XLSX, CSV và XLSM theo contract. XLSM chỉ đọc dữ liệu hỗ trợ và bảo quản nguyên bản; macro tuyệt đối không được thực thi. Nếu hỗ trợ thêm XLS/TSV thì phải có thư viện/parser, định dạng và tests rõ; không đổi phần mở rộng để giả hỗ trợ.

Lưu tệp nguồn bất biến trong vùng app data, tên nội bộ không phụ thuộc tên người dùng, SHA-256, kích thước, loại đã kiểm, metadata upload và manifest sheet. Không cho tên tệp/path traversal ghi ra ngoài thư mục dữ liệu. Giới hạn upload, tổng giải nén, số entry ZIP, kích thước chuỗi/ô và tài nguyên parser; bảo vệ XML theo hướng dẫn thư viện. Không parse tệp lớn trong request API giữ event loop hoặc trong UI thread.

Tệp gốc không bị thay bởi kết quả sửa preview. Patch của người dùng, mapping và kết quả chuẩn hóa nằm riêng, có version và provenance. Download nguyên bản trả đúng bytes/hash; export tạo **tệp dẫn xuất mới** từ dataset được hỗ trợ. Không tuyên bố tệp dẫn xuất giữ toàn bộ macro, biểu đồ, style, pivot hoặc mọi đặc tính workbook gốc.

CSV: cho xem/chọn encoding và delimiter khi không chắc; xử lý BOM, quote, newline trong ô, UTF-8 tiếng Việt. XLSX/XLSM: chọn sheet, dòng header, phạm vi dữ liệu, cách xử lý dòng trống/ẩn và merged cell cần minh bạch. Không tự nhập tổng cuối bảng hoặc header lặp như giao dịch nếu mapping chưa xác nhận.

Bảo toàn mã có số 0 đầu dưới dạng text. Nếu Excel đã lưu giá trị mã như number và làm mất số 0, không tự tuyên bố khôi phục được; người dùng chọn quy tắc đệm có cấu hình hoặc sửa. Hiển thị giá trị gốc và giá trị diễn giải ở các chỗ có nguy cơ nhầm.

Ngày phải xử lý kiểu date Excel và epoch 1900/1904, text ngày có format được cấu hình và múi giờ nghiệp vụ `Asia/Ho_Chi_Minh`. Ngày mơ hồ như `01/02/2026` không tự đoán khác profile. Giữ riêng ngày ghi sổ/ngày giao dịch nếu sổ cấu hình cả hai; không thay ngày người dùng bằng timestamp import. Dấu phẩy/chấm ngăn nghìn và thập phân phải theo profile rõ; phân biệt empty, zero, text lỗi và số âm/hoàn tiền.

XLSX có tối đa 1.048.576 dòng mỗi worksheet, kể cả header. Tập lớn hơn phải chia sheet/file hoặc dùng CSV. Không dùng số dòng hiển thị trong metadata làm bằng chứng đã đọc/validate thực tế tất cả dòng.

## 6. Job import bền vững và partial import

Thiết kế ít nhất các thực thể: import batch/source file, sheet/source row identity, mapping/schema revision, normalized staged rows, versioned cell patches, validation issues, duplicate candidates/decisions, import attempt/selection manifest, chunk receipts/checkpoints và audit. Dùng schema/migration riêng của lane, không auto-create hoặc sửa DB chung tùy tiện.

Row identity phải tồn tại qua retry, filter/sort và sửa giá trị: sheet ID + vị trí dòng nguồn trong batch hoặc synthetic UUID cho dòng được thêm bằng paste. Không lấy index của trang hoặc fingerprint nội dung làm row ID. Dòng đã nhập có lineage tới batch/source row/attempt và bản sửa đã được xác nhận.

Luồng bắt buộc:

1. Upload và kiểm tệp → tạo job bền vững; API trả job ID sớm.
2. Parse streaming/batch vào staging; lưu checkpoint và tiến độ đã commit. `openpyxl` dùng read-only/lazy iterator, đóng workbook đúng cách; không `list(ws.rows)` hoặc load cả file thành dataframe. CSV dùng iterator. Không giữ transaction DB mở trong thời gian đọc/giải nén tệp.
3. Preview theo trang và ánh xạ cột; sửa/copy/paste chỉ tạo patch có version. Người dùng có thể lọc tất cả lỗi/chưa xử lý, mở bất kỳ trang nào và tải danh sách lỗi local.
4. Validate toàn bộ dataset hoặc incremental đúng dependency; validation UI chỉ hỗ trợ, backend quyết định. Mọi mapping/schema/cell edit liên quan làm stale kết quả cũ.
5. Cho xem số dòng nguồn, hợp lệ, lỗi, cảnh báo, nghi trùng trong tệp, nghi trùng DB, đã nhập trước và những dòng sẽ nhập lần này. Các nhóm thống kê phải định nghĩa rõ có giao nhau hay không; có công thức đối chiếu tổng không đếm lặp.
6. Người dùng chọn **nhập phần hợp lệ** sau màn hình xác nhận cụ thể. Manifest xác nhận pin batch revision, mapping/schema revision, validation version, lựa chọn dòng và quyết định duplicate. Không dùng danh sách hàng triệu ID trong một request; lưu selection/filter manifest bền vững ở server và kiểm lại tập chọn.
7. Commit qua local job runner và serialized writer. Lưu chunk receipt, kết quả dòng, checkpoint và committed count **trong cùng transaction**; crash sau commit nhưng trước ACK không được chèn lại. Job có lease/owner và khôi phục để không hai runner xử lý cùng attempt.
8. Những dòng lỗi/chưa chọn ở lại batch để sửa và revalidate. Lần confirm tiếp chỉ xử lý dòng chưa nhập, với version mới. Dòng đã nhập không được chèn lại vì batch được gửi lại; sửa giao dịch đã lưu đi qua CRUD/điều chỉnh rõ ràng.

Attempt đang chạy phải đọc snapshot staging/patch revision bất biến đã xác nhận, không đọc giá trị mới đang được người dùng sửa. Khóa tập dòng đang được attempt claim hoặc tạo revision/copy-on-write riêng; UI giải thích cách hủy/tiếp tục. Không chỉ pin một số version ở header rồi để worker đọc bảng staging đã bị sửa dưới cùng ID. Error list, duplicate candidates và progress đều phân trang/aggregate, không trả một mảng triệu lỗi hoặc triệu row IDs trong một response.

### Atomic visibility và tiến độ

Không giữ một write transaction cho hàng triệu dòng. Thực hiện write chunks ngắn, giới hạn theo tài nguyên đo được. Theo ARCHITECTURE/API_CONTRACT đã chốt, bắt buộc publication theo import attempt để báo cáo không đọc nửa một lần xác nhận:

- Chunk có thể ghi durable entries/receipts nhưng dữ liệu mới ở trạng thái pending, chưa xuất hiện như giao dịch đã nhập.
- Tất cả list, tổng, tìm kiếm, export và báo cáo nghiệp vụ dùng chung predicate visible/published; không có endpoint quên điều kiện này.
- Sau khi đủ chunk, kiểm đối chiếu manifest/count/hash và publish attempt bằng transaction ngắn. Chỉ lúc này số dòng được tính là imported/visible.
- UI phân biệt parsed/validated, `staged_committed_rows` và `published_rows` đúng contract; không gắn nhãn “đã nhập” cho checkpoint staging.
- Lỗi hoặc hủy không publish phần pending. Resume cùng attempt tiếp tục từ receipts; hủy đã kết thúc không được worker cũ publish. Dọn pending sau đó là job an toàn, không xóa originals/audit.
- Attempt mới cho các dòng lỗi đã sửa không làm thay đổi các dòng published trước. Claim/uniqueness cho lineage phải ngăn hai attempt publish cùng source row; không dùng fingerprint nội dung để chặn giao dịch lặp hợp lệ.

Cần mô tả và kiểm visibility, count và cách phục hồi tại mọi điểm crash, không dùng từ “atomic” chung chung. Không tự thay publication semantics; đề xuất thay đổi phải qua điều phối và cập nhật tất cả consumer trước triển khai.

Checkpoint XLSX không phải offset byte có thể seek tùy ý trong ZIP. Chọn resume bằng staging đã hoàn tất hoặc re-read rồi skip theo source identity/checkpoint, kiểm hash tệp không đổi; tài liệu hóa thời gian/tài nguyên phục hồi. Không hứa resume O(1) khi parser không hỗ trợ.

SQLite WAL chỉ có một writer tại một thời điểm. Parse/calculate/validate ngoài transaction; ưu tiên công việc foreground và backpressure job. Không tự tạo SQLite connection ghi riêng để bypass serialized writer. Có timeout/busy handling hữu hạn, không retry vô hạn che deadlock hoặc treo UI. Dung lượng đĩa phải tính originals + staging + pending records + indexes + WAL + export/temp; báo lỗi disk-full có thể phục hồi.

## 7. Duplicate: cảnh báo theo cấu hình, không xóa giao dịch hợp lệ

Chưa có business unique key được doanh nghiệp chốt. Tuyệt đối không đặt UNIQUE trên ngày + đơn + sản phẩm hoặc ngày + sản phẩm theo suy đoán. Một đơn có nhiều dòng cùng sản phẩm, thanh toán nhiều lần và giao dịch giống nhau có thể hợp lệ.

Triển khai ba tầng riêng:

- Idempotency của request/job/chunk và lineage source row: bắt buộc chống cùng thao tác nhập bị chạy lại.
- Candidate match theo các cột được người dùng cấu hình, ví dụ ngày + mã đơn + mã sản phẩm: chỉ là **cảnh báo** và hiển thị cặp/nhóm cần xem, không tự coi là khóa duy nhất.
- Exact normalized row fingerprint: cũng là cảnh báo; có thể chọn giữ cả hai như giao dịch hợp lệ. Fingerprint versioned, canonical và không làm mất phân biệt text mã/ngày/Decimal/null.

So trùng trong file và với dữ liệu published cũ phải có index/query theo tập, không một truy vấn DB cho từng dòng. Không giữ hash set một triệu dòng đầy đủ trên browser. Không dùng fuzzy match tự động để ghi đè hoặc loại giao dịch.

Các quyết định có audit: giữ như giao dịch mới, bỏ qua dòng nguồn, hoặc gắn với bản ghi cũ để so sánh. Cùng candidate ngày/đơn/hàng nhưng khác tiền/nội dung vẫn chỉ POTENTIAL_DUPLICATE nếu chưa có business key được cấu hình và xác nhận; hiển thị cũ/mới, không merge hoặc chặn nhầm. Chỉ CONFLICT khi cùng explicit business key có dữ liệu khác hoặc expected_version của update target không còn đúng. Chỉ update bản ghi cũ khi action rõ, có quyền và version; mặc định import thêm mới, không silent overwrite. Kiểm lại conflict tại publish để tránh validation lỗi thời khi foreground CRUD thay dữ liệu.

Một file cùng hash được upload lại cần báo batch đã có và cho tiếp tục batch cũ; không âm thầm nhập lần nữa. Nếu người dùng chủ động tạo batch mới vì đây là giao dịch hợp lệ lặp lại, đi qua duplicate warning và quyết định rõ. Không dùng file hash như unique business rule vĩnh viễn.

## 8. Lỗi tới từng ô và sửa lại

Issue có tối thiểu: batch/attempt nếu áp dụng, sheet ID/tên, source row number, source column index/letter, stable column ID, error code, message tiếng Việt, giá trị gốc được giới hạn độ dài, gợi ý xử lý, severity, validation revision và trạng thái resolved. Không chỉ trả chuỗi “file không hợp lệ”.

Phân biệt lỗi parse cấu trúc tệp, lỗi mapping, lỗi từng ô, lỗi xuyên dòng/công thức, cảnh báo duplicate, conflict version, lỗi permission và lỗi hệ thống/disk. Thông báo không lộ SQL/path/secret. Trả mã lỗi ổn định theo API contract, không bắt frontend parse message.

Sửa một ô phải cập nhật version và kiểm lại các quy tắc phụ thuộc; dòng đã hết lỗi xuất hiện trong tập có thể confirm mới. Người dùng sửa lại job sau restart không mất patch. Download lỗi CSV/XLSX phải bảo vệ formula injection và giữ tọa độ gốc; không cần tải dữ liệu lên dịch vụ nào.

## 9. Công thức thông dụng, phạm vi an toàn và chính xác

Triển khai, kiểm thử và tài liệu hóa tập đầu: `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, `IF`, `ROUND`, `SUMIF`, `COUNTIF`, cùng phép tính/so sánh và tham chiếu ô/range nằm trong phạm vi hỗ trợ. Không thêm lời hứa toàn bộ hàm Excel. Không chạy formula string bằng `eval`, `new Function`, Python eval/exec hoặc shell.

Dùng parser/AST với allowlist grammar và function registry, kiểu dữ liệu rõ, dependency graph, phát hiện cycle, reference lỗi, division by zero, giới hạn range/cost/depth và hủy tính toán. Tham chiếu phải gắn vị trí logic ổn định/row identity; sort/filter viewport không được đổi nghĩa công thức. Insert/delete hàng/cột, relative/absolute references và copy/paste phải có semantics được mô tả và test. Những trường hợp chưa hỗ trợ phải báo rõ, không tính theo chỉ các ô đang được tải.

Formula.js có giấy phép MIT và bộ hàm có thể tham khảo, nhưng **không thay thế** parser/dependency graph hoặc Decimal authoritative. Chỉ đưa thư viện miễn phí vào khi kiểm giấy phép phiên bản và dependency thực tế, hành vi tính số và tương thích gói. Không thêm HyperFormula GPL/commercial hoặc paid SDK vào ứng dụng trái yêu cầu. Có thể tự triển khai tập AST/hàm giới hạn bằng Decimal khi việc đó đơn giản và kiểm chứng được; không viết một engine Excel đầy đủ.

Backend là nguồn kết quả được lưu/báo cáo; frontend có thể preview nhưng phải khớp cùng semantics. Lazy `IF` không thực thi nhánh không được chọn. Định nghĩa/test blank vs text vs zero, COUNT, round số âm, criteria/wildcard/escape của SUMIF/COUNTIF và locale dấu ngăn tham số. Công thức trên range lớn xử lý ngoài UI thread, theo streaming/chunk hoặc truy vấn chính xác; không dựng toàn bộ workbook trên browser.

Với công thức trong tệp nhập, lưu tách `formula_text`, `cached_value`, `calculated_value`, `calculation_status`, engine/version và dependency/source revision. `openpyxl` không tính công thức; `data_only=True` chỉ đọc cached value, có thể thiếu hoặc cũ. Không gắn nhãn cache là đã tính lại. Có trạng thái rõ cho supported_calculated, unsupported, external_reference, cache_only, missing_cache, circular và lỗi tính toán.

Ô required cần số authoritative nhưng chỉ có formula unsupported/cache chưa được xác nhận phải giữ lỗi hoặc yêu cầu người dùng nhập giá trị/xác nhận lấy giá trị với provenance theo policy; không tự thay bằng 0. Giữ raw formula ngay cả khi người dùng chọn nhập giá trị. Cấm external workbook references, network functions/queries, macro, DDE và custom JS/Python trong công thức. Tính lại dataset phụ thuộc ngoài phạm vi đã import không được đoán bằng dữ liệu thiếu.

## 10. Báo cáo và export của khu kế toán

Có báo cáo tổng hợp theo khoảng ngày/cột đã ánh xạ, loại thu/chi, sổ, đơn vị tiền và các chiều cấu hình; xem dữ liệu **trước import / batch mới / tổng sau import** để người dùng kiểm. Báo số dòng/tiền được nhập, bỏ qua, giữ lỗi, conflict và duplicate được giữ có chủ ý. Không gọi số dư đầu kỳ hoặc lợi nhuận là chính xác nếu chưa cấu hình đủ nguồn/ngữ nghĩa.

Báo cáo chỉ tính published active records, có filter/schema/data revision và mốc tạo rõ. Dữ liệu ngày dùng giờ Việt Nam, khoảng thời gian nửa mở; không dùng UTC date hoặc ngày host để lệch kỳ. Đừng buộc báo cáo khu này khớp mọi số CRM. Nếu có snapshot để gửi báo cáo cuối ngày, cung cấp dữ liệu/tệp đã đóng băng cho lane báo cáo theo contract; lane này không gửi Zalo hoặc tự đăng ký lịch.

Export XLSX/CSV từ dataset đã hỗ trợ bằng job cho tập lớn, không load tất cả vào RAM hoặc browser. Xuất số/mã/ngày đúng kiểu và precision; chống formula injection ở text untrusted mà không phá giá trị numeric âm. Chỉ export công thức được ứng dụng chủ động hỗ trợ/cho phép; text nguồn bắt đầu `=`, `+`, `-`, `@` không tự trở thành công thức. Tệp dẫn xuất phải được đặt tên/phạm vi rõ; giữ nút tải nguyên bản riêng. Giữ byte hash của originals qua toàn bộ vòng import/edit/export.

## 11. API, bảo mật và tích hợp local

Thực hiện đúng `docs/API_CONTRACT.md`: books/schema/mapping, row CRUD/list/filter, upload, job status, paged staging rows, versioned patches, validate, confirmation/attempt, retry/cancel, issues, duplicate review và export. Thiếu route hoặc payload thì bàn giao patch cho điều phối, không sửa contract chung ngoài allowlist.

Backend kiểm quyền đọc/sửa sổ, cấu hình cột, import, export và phục hồi theo role contract. Quyền ở API và job context, không chỉ ẩn nút. Job sử dụng actor và phạm vi được xác nhận; không mang quyền `admin` ngầm. Tệp/job giữa các tài khoản phải được kiểm quyền. Đổi user không rò draft/cache của người trước.

Tất cả API loopback phải qua phiên xác thực và boundary của app; không tự bind 0.0.0.0, không mở LAN/Internet, không thêm CDN/telemetry/cloud formula/import service. Thư viện/assets cần để chạy được đóng gói local. Không đưa dữ liệu/raw values nhạy cảm vào log benchmark. Dùng allowlist SQL sorting/filtering và parameterized values; không build SQL từ tên cột tùy ý.

Không chạy migration trên dữ liệu thật hoặc production. Tạo migration lane, test trên DB tạm mới và nâng từ version dự án do điều phối chỉ định. Không down/drop/truncate để làm tests pass. Bàn giao registration/import hooks/job handlers/dependency updates bằng patch cụ thể, kèm tests điều phối cần chạy.

## 12. Kiểm chứng bắt buộc

Viết và chạy tests hành vi có ý nghĩa, ghi đúng PASS/FAIL/SKIP/NOT RUN. Không coi stub, SQLite in-memory thiếu WAL/job crash hoặc API mock là đủ cho các bất biến persistence.

- Unit: schema/mapping, leading zeros, unicode, ngày/epoch, separators, Decimal/overflow, blank/zero; formula whitelist, precision, dependency/cycle, unsupported/cache-only, injection.
- Integration SQLite file thật: WAL + serialized writer, foreground CRUD trong import, conflict versions, unique lineage, chunk checkpoint/count atomicity, publish predicate ở mọi query/report/export, rollback/cancel/resume và disk/parser lỗi.
- Partial import: batch có valid/invalid/duplicate warning; confirm valid, sửa bad rows, confirm lại; tổng và số bản ghi cuối đúng, không thêm lại rows cũ, audit đủ.
- Crash probes: dừng trước/giữa/sau chunk commit, sau final publish trước ACK, hết lease, worker cũ quay lại, app restart và retry request. Mỗi case so DB count/hash/receipt với expected; không chỉ kiểm progress UI.
- Duplicate: ngày/đơn/sản phẩm giống nhưng giao dịch hợp lệ lặp vẫn giữ khi người dùng chọn; exact fingerprint cảnh báo không tự xóa; file upload lại; same candidate key khác amount không ghi đè.
- Files: source XLSM chứa macro mẫu không thực thi; SHA-256 nguyên bản trước/sau không đổi; derived export không tuyên bố là original; unsupported formulas và external link không được chạy.
- UI trong WebView2/Tauri hoặc harness tương đương được chỉ rõ: edit, paste vùng, filter toàn tập, jump lỗi, modal đóng/mở, đổi user, refresh/restart, optimistic conflict, cancel và giữ draft. Browser E2E mock không thay cho end-to-end local backend thật.
- Bulk: tạo fixture streaming 50k, 500k và 1m dòng với số cột/chuỗi/kiểu và tỉ lệ lỗi/trùng ghi rõ; đo parse/validate/dedup/commit/export duration, peak RAM của parser/API/worker/UI, dung lượng staging/WAL/temp và độ phản hồi CRUD/filter. Không commit fixture triệu dòng vào Git; tạo bằng script deterministic.

Kết quả bulk phải kèm cấu hình CPU/RAM/SSD, phiên bản runtime/package, số dòng/ô thực, chunk/page/cache settings, nguồn đo và log local không nhạy cảm. Đo restart/resume và max-size XLSX gần giới hạn. Không hứa “1m dòng trong X giây” hoặc “không bao giờ treo” từ demo nhỏ; nếu chưa đủ tài nguyên ghi NOT RUN và điều kiện chạy lại, không bịa benchmark.

## 13. Điều kiện hoàn thành và bàn giao

Hoàn thành khi sổ cấu hình được, app grid CRUD thật, import staged tới triệu dòng có bản đo, partial valid-row import/sửa tiếp không trùng, công thức trong tập đã nêu chạy chính xác, lỗi ô dễ sửa, báo cáo/export đúng published data và originals nguyên byte. Mọi khoảng chưa làm phải được nêu rõ với bằng chứng, không để TODO/pseudo-code thay phần việc đã nhận.

Bàn giao cho điều phối: tóm tắt hành vi; file/migration thay đổi; endpoint/permission/job handler; dependency/license và phiên bản đã kiểm; patch file chung; migration/rollback bảo toàn dữ liệu; lệnh và kết quả test; benchmark; UAT; giới hạn Excel/formula được hiển thị cho người dùng. Không push/merge và không tự triển khai môi trường thật.

## 14. Tài liệu nguồn để kiểm tra quyết định

Các tài liệu dưới đây là nguồn kỹ thuật, không thay yêu cầu đã chốt hoặc contract repo. Trước cài dependency, kiểm lại đúng phiên bản và giấy phép thay vì sao chép ví dụ cloud/CDN.

- [Glide Data Grid — source, tính năng và MIT](https://github.com/glideapps/glide-data-grid), [package trên main để đối chiếu React nhưng không thay release đã khóa](https://github.com/glideapps/glide-data-grid/blob/main/package.json).
- [Formula.js — MIT license](https://github.com/formulajs/formulajs/blob/master/LICENSE), [danh mục hàm để đối chiếu phạm vi](https://formulajs.info/functions/). Đây là bộ functions, không phải cam kết parser, dependency graph hoặc Decimal hoàn chỉnh.
- [Microsoft — giới hạn worksheet Excel](https://support.microsoft.com/en-us/excel/excel-specifications-and-limits).
- [openpyxl — read-only/write-only tối ưu](https://openpyxl.readthedocs.io/en/stable/optimized.html), [load_workbook và cached formula](https://openpyxl.readthedocs.io/en/3.1/api/openpyxl.reader.excel.html), [không tự tính công thức](https://openpyxl.readthedocs.io/en/stable/simple_formulae.html), [cảnh báo XML security](https://openpyxl.readthedocs.io/en/stable/index.html).
- [Python — csv reader/writer](https://docs.python.org/3/library/csv.html).
- [SQLite — WAL và giới hạn một writer](https://www.sqlite.org/wal.html), [kiểu dữ liệu/dynamic typing](https://www.sqlite.org/datatype3.html), [transaction](https://www.sqlite.org/lang_transaction.html).
- [OWASP — CSV/formula injection](https://community.owasp.org/attacks/CSV_Injection).
