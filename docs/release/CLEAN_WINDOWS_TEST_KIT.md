# Bộ kiểm thử Windows client sạch — Cafe Fin

Ngày 07/11/2026. **Kế hoạch chuẩn bị kit, chưa có kit nhị phân để chuyển, chưa chạy
nghiệm thu client.** Người dùng đã xác nhận có PC Windows thứ hai. Cần ghi nhận
phiên bản và phần mềm sẵn có để xác định phạm vi nghiệm thu. Không thay policy;
tình trạng source/relink hiện tại được ghi riêng bên dưới.

Baseline tài liệu: d294306b63e02b51d77e80139d71f5dcdb58b812.
Đọc cùng [prompt 05](../prompts/05_DONG_GOI_VA_NGHIEM_THU.md),
[SPEC](../SPEC.md), [USER_GUIDE](../USER_GUIDE.md) và
[candidate 09](../reviews/WINDOWS_DESKTOP_CANDIDATE_09.md).

## 1. Artifact nào đã có bằng chứng, artifact nào chưa có file?

CI [42314420634](https://github.com/minh0407/cafe_fin/actions/runs/42314420634)
tại source baa8e86a20520ae0613ae5f36b3c672554c42d21 thành công.
HEAD d294306 chỉ khác source đó ở README và biên bản candidate 09.

| Dữ kiện của run đó | Giá trị |
| --- | --- |
| Installer | Cafe Fin_0.1.0_x64-setup.exe |
| Dung lượng | 253.033.714 bytes |
| SHA256 installer | 8499656CBF6CF3F092E8829A43238731D439119AC68D5F57DA1ABAA9276C9220 |
| SHA256 frozen sidecar | 672F6ACF8620EFF2930CB683F1E570C6303452B05F2940CA708F74EC46D3B9C4 |
| Nơi file từng tồn tại | Temporary GitHub build runner |
| Artifact retained/uploaded/released | Không |
| Clean-client GUI/offline/upgrade acceptance | NOT RUN |

**Hash trong log không phải đường tải file.** Không có bằng chứng file của run đó
đang được giữ để chép sang PC khác. Build lại phải lập receipt/hash mới; không
hứa tái tạo đúng hash cũ.

[Config Tauri](../../desktop/tauri.conf.json) hiện dùng NSIS x64, version0.1.0,
installMode currentUser, WebView2 offlineInstaller/silent, bundled Python
sidecar và notices/*. Config/build PASS chưa chứng minh lần cài và mở đầu tiên
offline trên PC sạch; máy đã có WebView2 cũng không chứng minh nhánh cài thiếu
runtime hoạt động.

## 2. Thông tin cần thu trước khi chọn PC và candidate

Cần tối thiểu **Windows 11 version/build và CPU architecture x64** của PC thứ hai.
Ghi edition, RAM, CPU, loại ổ/dung lượng trống và có ổ local D/E hay không.
Không gọi ARM64 chạy x64 emulation là cùng môi trường đã nghiệm thu x64.

Ghi baseline trước cài: Cafe Fin có từng được cài/chạy chưa; có Docker/Python/
Node/Rust/Build Tools hoặc môi trường dev không; WebView2 có sẵn và version;
Office/Excel hoặc viewer DOCX có sẵn không; tài khoản Windows là standard/admin.
Các runtime OS vốn có phải được ghi nhận, không tự gỡ hoặc thay chúng để tạo
một phép thử khác. Nếu máy là máy dev hoặc đã chạy app candidate, ghi giới hạn
và chọn profile/máy sạch phù hợp theo quyết định của chủ máy.

Xác định trước các thư mục local mới chỉ dành cho phép thử, ví dụ
D:/CafeFinTestKit/ và D:/CafeFinTestData/Đợt thử 01/. Nếu không có D, dùng đường dẫn
local khác và ghi rõ: không suy PASS cho tình huống ổ D/E chưa thử.
Không dùng SMB, thư mục cloud-sync, data root thật hoặc đường dẫn CRM cũ.

## 3. Bộ file tối thiểu phải chuẩn bị — hiện chưa được tạo bởi tài liệu này

| File/nhóm trong kit đề xuất | Nội dung cần có và trạng thái hiện tại |
| --- | --- |
| installer/Cafe Fin_<version>_x64-setup.exe | Candidate được điều phối chỉ định và giữ lại trong một lượt build được phép. Chưa có file retained của run tham chiếu. |
| manifest.json và SHA256SUMS.txt | Source commit/tag được giao, workflow/run/job, version/architecture, filename/bytes/SHA256 của installer, frozen sidecar, fixtures và tài liệu; build thời điểm nào, signer thực tế. Không chứa token/path riêng. Chưa tạo. |
| notices/ | backend.txt, frontend.txt, rust.txt, native-license-sources.json, sidecar-native-inventory.json sinh từ ĐÚNG artifact mới. Các file tracked hiện có là đầu vào/tham chiếu, không tự thay inventory của build mới. |
| source-relink/ hoặc material delivery đã review | Corresponding source/patch/build inputs/terms và recipient relink proof cho static iconv. Đây là deliverable đang thiếu, không thay bằng report hay một link chung. |
| docs/ | Bản hướng dẫn người dùng, tài liệu này, known-limits theo candidate, hướng dẫn cài/nâng/gỡ; kèm tình trạng chưa ký nếu thực tế chưa ký. |
| fixtures/mini.csv, mini.xlsx và manifest | Tệp tổng hợp nhỏ có schema/mapping rõ, mã số0 đầu, ngày, Decimal tiền/kg, tiếng Việt và tập NEW/INVALID/nghi trùng; expected results sau chính mapping/policy đã ghi. Chưa đóng thành kit. |
| fixtures/inert.xlsm | Tệp XLSM tổng hợp đúng định dạng, hash gốc, test nội dung macro/external-reference chỉ mang tính inert. Không đổi đuôi XLSX rồi gọi là XLSM; không chạy macro. Fixture kit chưa tạo. |
| fixtures/expected-results.json | Dữ liệu nhập qua UI, số hàng đã công bố/lỗi/còn chờ, số dư/tổng tiền, tên tệp/tập cột và hash gốc dự kiến. Không seed DB thay luồng import. |
| evidence/RESULTS.md | Mẫu phần8 dưới đây; ban đầu mọi ca NOT RUN. Chỉ chứa kết quả tổng hợp, không credential/raw HTTP/workbook thật. |
| upgrade/from/ và upgrade/to/ | Chỉ thêm khi điều phối chọn rõ hai candidate/version và nguồn fixture. Hiện chưa có bộ cặp retained để gọi upgrade test. |

Đây là danh sách material cụ thể cần làm, **không phải khẳng định các file đã sẵn có**.
Tạo fixtures ở bước chuẩn bị kit bằng source/generator được review; không yêu cầu
người dùng cài Python/Excel hoặc chạy script dev trên client để tạo chúng.
[Parser benchmark](../../tests/accounting/benchmark_xlsx.py) đo parser projection/
re-read, không phải UI/import/publication của app cài. Chạy script đó trên client
không thay phép thử đóng gói.

## 4. Gate nguồn/license trước khi gọi kit sẵn sàng chuyển

[Audit iconv](../handoffs/packaging/iconv-source-provenance-20261107.md) và
[JSON evidence](../handoffs/packaging/iconv-source-provenance-20261107.json) xác định
wheel/source/hash và nguồn native ứng viên; **chưa có legal/distribution clearance**.
Static iconv vẫn trong lxml. Exact corresponding-source/relink delivery, recipient
replacement procedure và các terms liên quan còn mở. Notices BSD/MIT của package
chính hoặc một bản LGPL text của dependency khác không khép gate này.

Đường ít thay đổi được audit đề xuất là source/relink kit cho wheel hiện tại,
không cần đổi nghiệp vụ core; nhưng chưa có bằng chứng thực hiện recipient recipe.
No-iconv trong ignored proposal vẫn NOT BUILT/NOT APPROVED, có giới hạn Unicode/
encoding và CRT nếu dùng compiler mới. Không tự chọn phương án đó cho kit.

Trước transfer, owner phải hoàn thiện các material/terms và bằng chứng đang thiếu
theo phạm vi phân phối được quyết định. Việc người dùng có PC thứ hai không thay
nghĩa vụ hoặc tự cho phép upload/release. Có thể chuẩn bị manifest/fixture/docs trước,
nhưng không gọi bộ nhị phân sẵn sàng phân phối khi các gate này còn mở.
Tài liệu này không gửi, tải binary, mở release hoặc chấp thuận legal conclusion.

## 5. Trình tự kiểm thử trên PC thứ hai

Người kiểm thao tác bằng GUI app đã cài; engineering ghi checksum/metadata riêng
không được biến thành yêu cầu mở terminal để vận hành hằng ngày.
Chỉ dùng tài khoản local và dữ liệu tổng hợp. Không cấu hình Telegram thật hay gửi
ra nhóm; phần đó có phép thử/đích được giao riêng.

| Ca | Thao tác và expected result | Bằng chứng cần ghi |
| --- | --- | --- |
| W01 — nhận đúng kit | Đối chiếu installer/fixtures với manifest, version/source được giao; ghi signer thực tế. Hash sai thì giữ kết quả FAIL, không đổi receipt để hợp thức hóa. | Filename, bytes, hashes, source/run, signer. |
| W02 — lần cài/launch đầu offline | Trước khi cài và trước lần mở đầu, ngắt WAN theo cách chủ máy chọn. Cài currentUser, mở shortcut, chọn data root mới có dấu/khoảng trắng, tạo local Admin. Không cài Python/Office/Docker hoặc tải dependency online để làm ca đạt. | OS/runtime baseline, WAN thực tế, installer result, thông báo lỗi nếu có, root đã chọn. Nếu WebView2 có trước, giới hạn kết luận phải ghi. |
| W03 — desktop lifecycle | Mở lần thứ hai; kiểm single-instance, không console sidecar. Đóng app rồi mở lại, dữ liệu tổng hợp còn. Chọn/mở thư mục báo cáo bằng native picker/Explorer thực. | GUI/native dialog/Explorer result và shutdown, không dùng browser mock thay. |
| W04 — nghiệp vụ offline | Tạo/chọn đối tác/hàng/kho, phiếu cân và phiếu hàng; ghi kho qua trạng thái thực, thử xuất vượt tồn phải bị chặn. Kế toán độc lập không tự đổi kho. Dùng USER_GUIDE và fixture manifest để đối chiếu. | IDs tổng hợp, counts, số dư trước/sau, error.code/UI message khi bị chặn, không ghi auth token. |
| W05 — mini import | Tạo sổ/schema/mapping của fixture, nhập CSV/XLSX; kiểm preview lỗi/nghi trùng, sửa/lưu nháp, validate, xác nhận phần hợp lệ. Đóng/mở lại tiếp tục job; không nhân đôi published rows, pending chưa hiện thành sổ. Tải XLSM gốc đối chiếu hash, macro/external link không chạy. | Counts NEW/INVALID/nghi trùng/published theo manifest, số hàng còn chờ, hash gốc/derived phân biệt. |
| W06 — tài liệu/báo cáo | Hợp đồng mua/bán có điều khoản/thanh toán thêm, Xuất Word + PDF khi offline và không có Office như dependency xuất. Đọc PDF tiếng Việt, kiểm nội dung/snapshot; lưu/xuất PDF/XLSX/TXT báo cáo local, mở thư mục thực. | File hashes, dữ liệu đối chiếu và layout. DOCX visual/open/print cần viewer được chủ máy cho phép; chưa có viewer thì NOT RUN phần đó, không đổi structural reopen thành visual PASS. |
| W07 — quyền | Tạo Operator tổng hợp. Operator ghi nghiệp vụ/tạo sổ theo guide, nhưng không quản trị tài khoản/cấu hình gửi/backup/move/restore hoặc tự mở khóa target. | Thao tác được/không được và message, không đưa mật khẩu vào kết quả. |
| W08 — backup/move/restore bình thường | Admin vào Quản lý dữ liệu trên máy, chọn nơi lưu/bản sao bằng native picker rồi Thực hiện. Move/restore tới root local mới. Đăng nhập Admin tại target DORMANT, chỉ Kích hoạt dữ liệu hiện tại khi UI đủ bằng chứng cho phép. Restart phải giữ target bền vững; source/backup cũ vẫn còn. | Operation status, counts/số dư/hash tệp trước-sau, reporting tạm dừng sau restore, phiên target mới. Không chép riêng DB/WAL để giả backup. |
| W09 — khả năng offline kéo dài | Trong phiên đang chạy, ngắt WAN hoặc adapter theo lựa chọn chủ máy; lưu/xem/xuất vẫn hoạt động qua loopback. Reporting chưa cấu hình chỉ tạo file local, không bịa đã gửi. | Cách ngắt, các thao tác còn hoạt động, trạng thái gửi chính xác. |
| W10 — gỡ/cài lại | Sau backup tổng hợp, gỡ app, xác nhận data root/files không bị xóa; cài lại candidate đã chỉ định và chọn lại dữ liệu cũ. | Counts/số dư/hash trước-sau, đúng root, không có DB rỗng thay thế. |
| W11 — update có phiên bản | Thực hiện phần7, chỉ sau khi có cặp from/to rõ và fixture/migration expected. | Hai receipt, schema/data/backup/result; không gọi reinstall0.1.0 là upgrade giữa versions. |

Dùng số liệu minh họa đã có trong USER_GUIDE nếu fixture kit hiện thực đúng dữ liệu:
10000.000 + 1250.500 - 800.250 = 10450.250 kg; thu15000000.00, chi10000000.00.
Cọc thu2000000.00 đã nằm trong thu, đối trừ500000.00 không phải tiền thu/chi.
Đây là expected arithmetic cho dữ liệu tổng hợp, chưa phải dữ liệu đã nhập hay
file báo cáo đã tạo. Không lấy ví dụ chữ trong guide làm bằng chứng test đã chạy.

Khi Windows chặn thực thi, ghi nguyên loại lỗi/status cần thiết và dừng ca.
Không tắt Defender/Device Guard, thêm exclusion, đổi tên/path hay ký giả để né policy.
Nếu chỉ có prompt/SmartScreen, ghi trải nghiệm và signer; quyết định tiếp tục thuộc
chủ máy/phạm vi được giao, không tự động coi việc có máy là đồng ý vượt cảnh báo.

## 6. Các ranh giới recovery phải giữ nguyên

[Candidate09](../reviews/WINDOWS_DESKTOP_CANDIDATE_09.md) và
[native06](../handoffs/packaging/native-increment-06-transition.md) công bố các giới hạn:
INTENT native khi core chưa có intent sau crash, partial activation, first-install
restore và cross-version restore chưa có acceptance đầy đủ.

Nếu gặp HELD/MAINTENANCE_GENERATION_CONFLICT, giữ root/journal/source; kiểm trạng
thái hoặc attach phiên desktop như guide. Không Restart để hủy, không sửa marker/
origin_generation, xóa intent, boot source ACTIVE hay chọn DB rỗng thay thế.
Thử move/restore bình thường W08 không chứng minh các failure boundary đó PASS.
Không cắt điện máy thật như một ca thử ngầm; power-loss và lỗi ổ/disk-full phải
được giao riêng trên dữ liệu/môi trường có thể phục hồi.

## 7. Cặp upgrade cần chuẩn bị riêng

Hiện product config đều version0.1.0 và không có installer cũ retained được chỉ định.
Chạy lại cùng installer hoặc build khác cùng0.1.0 chỉ là reinstall/replacement;
không đủ gọi version-upgrade hay production migration.

Điều phối cần chọn from/to source+version+installer hashes và expected schema.
Nếu chưa có production release, dùng schema đời trước/fixture tổng hợp có kiểm
soát theo prompt05 và ghi rõ giới hạn; không bịa lịch sử production.

Trên root tổng hợp: ghi counts/tồn/tiền/file hashes và job đã công bố/còn chờ;
tạo backup được xác minh trước update. Đóng app, cài bản to theo policy được chọn,
mở đúng root cũ và đối chiếu. Không seed/reset DB. Chỉ thử old app/new schema trên
bản dữ liệu kiểm thử tách biệt nếu đã được giao; kết quả phải theo downgrade policy,
không downgrade phá root đang dùng. Cross-version restore giữ trạng thái NOT RUN
nếu chưa có cặp tương thích và hướng dẫn được owner xác nhận.

## 8. Mẫu evidence điền cho đúng candidate

Không lưu password/token/boot frame/raw HTTP/log body chứa đường dẫn hay nội dung
cá nhân. Dùng machine_id tổng hợp, tên root tổng hợp; không cần hostname người dùng.
Chỉ dùng ảnh minh họa đã crop/redact nếu cần và đã được giao, không chụp credential.

~~~text
Kit/candidate ID:
Source commit / integration baseline:
Workflow run/job / build timestamp:
Installer filename / bytes / SHA256 / signer:
Frozen sidecar SHA256 / notice inventory identity:
License/source-relink delivery reference and current gate status:

Test machine ID: clean-pc-01
Windows11 edition / version / build / x64:
CPU / RAM / local disk / free space:
Windows account type:
WebView2 before install (present/version or unknown):
Cafe Fin/dev tools/Office/viewers before install:
Synthetic root alias(s) / fixture manifest+hash:
WAN-off method and first offline launch time:

Case | PASS / FAIL / BLOCKED / NOT RUN | observed result | safe evidence reference
W01  | NOT RUN | |
W02  | NOT RUN | |
W03  | NOT RUN | |
W04  | NOT RUN | |
W05  | NOT RUN | |
W06  | NOT RUN | |
W07  | NOT RUN | |
W08  | NOT RUN | |
W09  | NOT RUN | |
W10  | NOT RUN | |
W11  | NOT RUN | |
Upgrade from/to / schema before-after:
Data counts / stock / money / file hashes before-after:
Known recovery boundary encountered (if any):
Unresolved items and exact acceptance limits:
~~~

Bảng trên là mẫu, không phải kết quả. Không gửi evidence chứa dữ liệu thật.

## 9. Task artifact cụ thể kế tiếp cho điều phối giao

1. Thu Windows11 version/build/x64 và runtime/dev baseline của PC thứ hai.
2. Chọn một candidate source được freeze; d294306/baa8e86 chỉ khác docs, nhưng
   candidate mới phải có receipt riêng nếu build lại.
3. Tạo và **giữ lại** đúng NSIS installer, frozen
   sidecar hash, matching notices/inventory, fixture nhỏ+expected manifest và
   checksum manifest tại nơi được phép. Current CI chỉ in hashes, chưa giữ artifact.
   Chọn cách retention/transfer có phạm vi rõ; không biến thành public release.
4. Hoàn thiện corresponding-source/relink material/terms và bằng chứng phân phối
   đang thiếu trước khi gọi kit được phép chuyển. Audit facts không tự clear gate.
5. Sau khi có file kit được kiểm, thực hiện W01–W10 trên
   PC đó; W11 cần cặp upgrade riêng. Packaged50k/500k/1m timing của prompt05 là
   lượt benchmark riêng, không suy từ parser/dev-host benchmark hoặc mini import.

Lượt soạn tài liệu này không build, tải binary, retain/upload artifact, gửi file,
chạy trên PC thứ hai, sửa CI/code/policy hay phát hành; chỉ bổ sung tài liệu kit.
