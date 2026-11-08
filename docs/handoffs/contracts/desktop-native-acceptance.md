# Nghiệm thu hợp đồng trên app Windows — kế hoạch 08/11/2026

**Trạng thái: chuẩn bị xong checklist; toàn bộ ca native bên dưới là NOT RUN, chờ artifact cuối của 05 sau tích hợp lifecycle của 00.** Không có installer/exe cuối được giao cho lượt này. Không dùng browser, Docker, mocked `invoke`, Playwright download hoặc kết quả CI cũ làm bằng chứng Windows GUI.

Worktree mới: `C:\Users\NC\.codex\worktrees\cafe-fin-contracts-desktop\cafe_fin`; branch `codex/cafe-fin-contracts-desktop-20261108`; baseline đã kiểm tra: `eab8c96b851f039de515083189f4301cc09437c0`. Worktree/commits contracts cũ được giữ nguyên. Lượt chuẩn bị này chỉ thêm tài liệu này, không sửa UI/backend/shared/lifecycle, không build Cargo, sidecar hoặc installer và không mở dữ liệu vận hành.

## 1. Điều kiện nhận artifact và hồ sơ bằng chứng

05 phải giao bộ cài source-matched từ SHA cuối do điều phối chốt. Bản dựng trước tray/lifecycle mới không được coi là artifact cuối. Ghi đủ các ô sau trước khi thử; chưa có thông tin thì để NOT RUN, không điền hash hoặc phiên bản dự đoán.

| Bằng chứng | Giá trị phải thu khi chạy thật |
|---|---|
| Provenance | SHA nguồn cuối, branch/tag nếu có, build ID, thời điểm; phân biệt với baseline chuẩn bị `eab8c96` |
| Bộ cài | Tên/đường dẫn ngoài Git, kích thước, SHA-256, version và kết quả xác minh theo manifest của 05 |
| App và sidecar | Đường dẫn exe đã cài, SHA-256 app và frozen sidecar, Product/FileVersion, đối chiếu cùng manifest; baseline hiện khai báo `0.1.0` không thay cho version artifact cuối |
| Máy thử | Windows 11 x64 build, CPU/RAM, kiến trúc, màn hình/DPI, WebView2 version, currentUser thử; tình trạng Office/Python/Node/Docker không cài hoặc không được app sử dụng |
| Root tổng hợp | Đường dẫn local do GUI chọn, tách thư mục cài/sync/worktree; ví dụ `D:\CafeFinNativeQA\Contracts-20261108-<run>`; nếu không có D dùng ổ local thực có sẵn |
| Identity/lock | Root UUID từ `.cafe-fin-root.json` và root đang hiển thị trong app; PID/image path của app/sidecar; kết quả single-instance/lock probe đã được 00/05 duyệt |
| Đầu ra | Contract ID/version, export sequence/version ID, snapshot SHA-256, template version/hash, từng file ID/SHA-256 và đường dẫn bản tải thực tế trong Windows |
| GUI và byte proof | Ảnh/video bước quan trọng, danh mục file/size/hash, ảnh từng trang tài liệu; mã ca, ngày giờ và người thực hiện |

Bằng chứng và binary nằm ngoài Git trong thư mục QA riêng của 05. Không ghi mật khẩu, app-session/bearer token, HTTP header, environment hoặc toàn bộ journal/config. Chỉ dùng dữ liệu tổng hợp; không dùng ngân hàng, giấy tờ, chữ ký, con dấu hoặc thông tin khách thật. Hash/PID có thể do công cụ QA được duyệt thu; luồng sử dụng app của người nhập không cần terminal.

**Cổng cách ly trước launch:** dùng Windows profile/VM/PC nghiệm thu riêng không có config/root Cafe Fin vận hành. Worktree mới không tự cách ly `app_config_dir`: identifier hiện là `vn.cafefin.desktop`, `main.rs` đọc cấu hình/journal theo currentUser. Nếu app tự hiện root cũ không phải root QA, dừng ca và chuyển điều phối/05 xử lý; không khởi tạo lại, xóa config hoặc chuyển đè dữ liệu cũ để tiếp tục. Không truy cập volume Docker hoặc CRM cũ.

## 2. Fixture nhập qua GUI, không cần nghiệp vụ kho/tiền trước

Ngày nghiệp vụ chuẩn cho bộ ca: nhập **08/11/2026**, API/snapshot tương ứng `2026-11-08`. Các số kg/giá nhập bằng dấu chấm thập phân, không dấu phân cách nghìn. Thông tin dưới đây chỉ là nhãn tổng hợp, không phải thông tin giao dịch thật.

| Mã fixture | Tạo ở GUI hiện có | Nội dung |
|---|---|---|
| N801 | Ghi nhận cà phê → Farm → Thêm Farm | Mã Farm 4 ký tự `N801`; tên `Farm N801 — tổng hợp Đắk Lắk`; chủ `Chủ Farm Tổng Hợp`; giấy tờ `SYNTH-N801`; địa chỉ `Địa chỉ tổng hợp N801`; ghi chú `NATIVE-QA-ONLY` |
| SELF-NATIVE | Ghi nhận cà phê → Kho / phiếu → Đối tác → Thêm | Tổ chức `Công ty Cafe Fin Tổng Hợp Native`; địa chỉ/MST tổng hợp; đại diện/chức vụ; liên hệ loại Khác, giá trị `Liên hệ QA tổng hợp` |
| KH-NATIVE | Công ty khách hàng → Thêm công ty khách hàng | Tên `Công ty Khách Hàng Tổng Hợp Native`; MST `SYNTH-MST-KH`; giấy phép `SYNTH-GPKD-KH`; người liên hệ/đại diện và chức vụ, địa chỉ, một liên hệ loại Khác; tài khoản ngân hàng tổng hợp |
| CAN-NATIVE-01 | Kho / phiếu → Phiếu cân tay → Thêm | Đối tác N801; mô tả `Cà phê nguồn một`; Cách ghi số cân = Cân đầy / cân rỗng; đầy `150.000`, rỗng `26.544`; sau lưu tịnh `123.456` kg |
| CAN-NATIVE-02 | Phiếu cân tay → Thêm | Đối tác N801; mô tả `Cà phê nguồn hai`; Nhập kg tịnh trực tiếp `5.555`; không tạo cân đầy/rỗng giả |

Tài khoản tổng hợp dùng tên ngân hàng `NGÂN HÀNG TỔNG HỢP — KHÔNG GIAO DỊCH`, số `SYNTH-0001`, chủ `CHỦ TÀI KHOẢN TỔNG HỢP`, chi nhánh `CHI NHÁNH QA`. Không chuyển tiền hoặc gọi kiểm ngân hàng. Tạo tài khoản local thử qua GUI, giữ mật khẩu ngoài hồ sơ bằng chứng. Một người có thể thực hiện cả Admin/Operator; không thêm bước người khác duyệt.

Farm và công ty hiện cùng nằm trong `/records/parties`; picker hợp đồng tìm tên/mã, không yêu cầu gõ UUID. Bridge chỉ chép các trường PartyDTO chung: tên, địa chỉ, MST, liên hệ, đại diện/căn cứ, tài khoản. Giấy phép kinh doanh, hồ sơ lô/khảo sát/giấy tờ chủ Farm không thuộc PartyDTO chung; không mặc định chúng tự điền vào mẫu. Nếu ca cần ghi thêm, nhập rõ ở điều khoản tự do và kiểm tài liệu xuất.

Không lập phiếu hàng ghi kho, đơn/thu chi hoặc dòng kế toán chỉ để hợp đồng được lưu/xuất. Chụp trạng thái Tổng hợp tồn/Số dư thương mại và sổ QA trước/sau nhóm ca nếu cần kiểm không có side effect. Phiếu cân tay tự nó không ghi tồn.

## 3. Checklist thực thi trên artifact cuối

Mỗi hàng cần bổ sung PASS/FAIL/NOT RUN, thời điểm, mã evidence và lỗi cụ thể. **Hiện tất cả là NOT RUN — chờ artifact cuối**, không phải kết quả native đã đạt.

| Ca | Thao tác bằng cửa sổ Cafe Fin đã cài | Điều kiện đạt và bằng chứng |
|---|---|---|
| N01 — mở/cách ly | Cài từ kit đã xác minh, mở shortcut; chọn root QA bằng GUI, khởi tạo mới, tạo tài khoản local. Mở Hợp đồng từ menu; route nội bộ `/contracts`. | Không browser/dev server/terminal/Docker/Office; frozen sidecar tự chạy, app đọc đúng root QA; không tự tạo root rỗng khi root có lỗi. Chụp app/root/version; ghi PID/hash không kèm args/secret. |
| N02 — mua tự điền | Lập hợp đồng mới → Loại hợp đồng **Mua vào** → chọn mẫu; số `HD-NATIVE-MUA-001`, Ngày lập `08/11/2026`, Nơi lập `Đắk Lắk tổng hợp`. Mở **Tự điền từ dữ liệu đã lưu (tùy chọn)**. Với **Điền vào bên** = Công ty của bạn, tìm `SELF-NATIVE` và bấm **Xem và dùng đối tác**; kiểm hai cột cũ/nguồn rồi **Dùng thông tin nguồn**. Lặp với Đối tác = N801. Thử **Giữ thông tin đang nhập** một lần. | Tên/địa chỉ/đại diện/liên hệ/tài khoản đúng bên mua và bên bán; hủy chọn không ghi đè. Không cần UUID hoặc approval. Đối chiếu nguồn trong GUI, ghi version nguồn vào evidence. |
| N03 — nhiều cân và dòng tay | Tìm mã CAN-NATIVE-01, **Xem dòng cân**, tick dòng rồi **Thêm các dòng đã chọn vào hợp đồng**. Đổi kg hợp đồng thành `120.000`, giá `10000.25`. Thêm dòng CAN-NATIVE-02, giữ `5.555`, giá `11000.00`. **Thêm dòng hàng** thủ công mô tả `Cà phê nhập tay`, kg `10.125`, giá `9000.50`. Thử chọn lại cùng dòng cân. | Ba dòng, chỉ một bản mỗi dòng nguồn; chọn trùng bị báo rõ, không cộng đôi. Snapshot nguồn một vẫn tịnh `123.456`; cân đầy/rỗng vẫn là thông tin nguồn riêng. Sửa hợp đồng không sửa phiếu cân. |
| N04 — điều khoản/ngày | Điền Giao nhận, Đóng gói / bao bì, Chất lượng, Thời hạn thực hiện, Trách nhiệm các bên, Điều khoản bổ sung bằng chữ Việt, có xuống dòng và marker `ĐIỀU-KHOẢN-NATIVE-V1`. Thử từ ngày hợp lệ sang `31/02/2026`, `08/11/` và xóa ngày bắt buộc; bấm Lưu/Xem trước. Sửa lại ngày bằng lịch và gõ ngày. | DD/MM/YYYY rõ ràng, lỗi giữ nguyên text, không dùng lại ISO cũ; không lưu/xem trước/xuất draft lỗi. Hạn thanh toán xóa thật được phép; ngày mỗi đợt bắt buộc. Tab từ số sang ngày và nút lịch dùng được. Không timezone shift. |
| N05 — thanh toán mua | Chọn **Kết hợp**; nội dung `Thanh toán tổng hợp tiền mặt và chuyển khoản — không chuyển tiền thật`; tick **Ghi tài khoản nhận tiền trong hợp đồng**, nhập tài khoản tổng hợp; hạn `20/11/2026`; cọc `100.00`, số đã thanh toán do người nhập ghi `20.00`; thêm hai đợt `15/11/2026`/`500.00` và `20/11/2026`/`852.25`, mỗi đợt có ghi chú. Chọn **Không tính thuế** cho bộ số mua này. | Tất cả nội dung hiện trong preview và hai định dạng; cọc/số đã trả/lịch là thông tin riêng, không tự trừ hoặc đổi tổng tiền hàng, không tạo thu/chi/kế toán. Lịch ghi là thỏa thuận, không bị ép phải bằng tổng hợp đồng. |
| N06 — đóng về khay giữ nháp | Khi vẫn ở đúng form mua chưa lưu, thêm marker `NHÁP-KHAY-NATIVE-001` trong điều khoản. Bấm X cửa sổ. Dùng **Mở Cafe Fin** ở khay để quay lại. Nếu quan sát được trạng thái đang lưu/xuất, thử close/reopen thêm ở trạng thái đó theo ca lifecycle đã duyệt của 00. | Thông báo thu khay lần đầu theo thiết kế cuối; vẫn cùng form, loại/mẫu/các bên/dòng cân/giá/điều khoản/ngày/lịch/marker còn nguyên; không logout/reload/remount làm mất nháp; không tạo app/sidecar thứ hai. Ca in-flight không bắt được thì ghi NOT OBSERVED, không suy từ ca idle. Đây là gate của 00, không sửa lifecycle ở lane contracts. |
| N07 — xem trước/lưu/xuất mua | Sau reopen, bấm **Xem trước**, kiểm số liệu mục 4; **Lưu hợp đồng**, đợi xác nhận version, rồi **Xuất Word + PDF**. Mở **Bản đã xuất** và **Xem bản này**. Chưa đính kèm gì ở bước này. | Lưu/xuất không cần bản ký; snapshot/version/template/hash rõ, hai format có trạng thái độc lập. Cả DOCX/PDF có marker, đủ ba dòng, kg/giá/điều khoản/thanh toán đúng; không token thô hoặc câu thanh toán cố định trái input. |
| N08 — tệp thực trên Windows | Bấm **Tải DOCX**, **Tải PDF**. Ghi chính xác hộp thoại/đích tải thực tế, filename, hủy một lần rồi tải lại tới thư mục QA có dấu cách/chữ Việt. Đối chiếu size và SHA-256 bản Windows với từng format của snapshot. Không chỉ chụp chữ Đã tạo. | Có file `.docx`/`.pdf` thật ở đích tìm được bằng Explorer; Cancel không bị báo là đã lưu ra đĩa và không mất snapshot. Không bật browser hoặc đổi trang làm mất form. Nếu chỉ WebView2 default Downloads, ghi hành vi thực, không giả có Save As; dùng gate/interface ở mục 6 để điều phối kết luận. Không dùng tên file làm identity thay version/hash. |
| N09 — bán cho công ty | Lập hợp đồng mới, **Bán ra**, `HD-NATIVE-BAN-001`; tự điền công ty của bạn và KH-NATIVE qua picker/confirmation. Kiểm đúng thông tin khách trước nhập dòng. Hai dòng tay `2.001` × `123.45` và `3.333` × `99.99`. Chọn giá chưa gồm thuế, nhập `10.00%`; đổi điều khoản/thanh toán sang marker `BÁN-NATIVE-V1`, chọn Chuyển khoản rồi Kết hợp và ghi lịch. Lưu, preview, xuất/tải cả hai định dạng. | Thông tin bên bán/bên mua đổi đúng chiều, tên/địa chỉ dài/đại diện/MST/liên hệ/bank đầy đủ; không tự dùng giá mua làm giá bán. Số liệu mục 4 đúng. Thử thêm một hợp đồng hoàn toàn nhập tay, không chọn nguồn nào: vẫn lưu/xuất được. |
| N10 — snapshot cũ bất biến | Ghi mapping version/export ID/hash của mua V1. Sau khi lưu hết, sang Ghi nhận sửa tên/địa chỉ N801 và kg nguồn CAN-NATIVE-01 thành `124.000`, lưu nguồn V2. Quay Hợp đồng, đọc hợp đồng đã lưu rồi mở **Bản đã xuất → Xem bản này** của V1 và tải lại. Sau đó chủ động sửa hợp đồng/điều khoản, lưu/xuất V2. | V1 không đọc live nguồn mới: marker, tên, kg override `120.000`, snapshot/hash/từng file byte còn nguyên. V2 là lần xuất riêng. Tự điền lại chỉ xảy ra khi người nhập chọn và xác nhận; không sửa ngầm nguồn hoặc bản cũ. |
| N11 — bản ký tùy chọn | Sau N07/N09 mới mở **Tệp đính kèm**, chọn một PDF tổng hợp đã xuất làm scan giả; ghi chú, gắn đúng version; lưu ở Đã đính kèm rồi thử **Người nhập ghi là đã ký** trên fixture khác nếu cần. Tải tệp gốc. | Chỉ nhận loại cho phép/tối đa 20 MiB; ghi metadata đúng, không xác minh chữ ký, không buộc phê duyệt. Bản tải gốc có bytes/hash/filename đúng; không đọc file ID ngoài contract. Không có ảnh/chữ ký/con dấu thật. |
| N12 — offline, không Office | Trên máy QA tách biệt, ngắt WAN bằng GUI Windows nhưng giữ loopback; dùng lại shortcut/app/root và tài khoản local. Nhập một hợp đồng mua hoặc bán hoàn toàn tay, sửa ngày/điều khoản, preview, lưu, xuất và tải DOCX/PDF. | Không yêu cầu Microsoft Office, Python/Node/Docker hay tải font/CDN/converter; app/loopback còn hoạt động. Telegram thiếu config/giá thị trường offline không chặn hợp đồng và không giả gửi/lấy giá thành công. Ghi trạng thái Office thực tế, không suy chỉ từ việc test không mở Word. |
| N13 — format lỗi riêng | Chỉ khi 05/điều phối giao ca lỗi renderer đóng gói được duyệt: tạo PDF lỗi trong khi DOCX còn dùng được; bấm **Thử tạo PDF từ bản này** sau khôi phục. | DOCX, dữ liệu và snapshot không mất; PDF báo lỗi thật; retry giữ cùng version/snapshot/hash, không tạo export mới. Không sửa/xóa font trong bộ cài hoặc monkeypatch để gọi là native artifact proof. Chưa có ca fault được giao thì NOT RUN, backend/source proof ghi riêng. |
| N14 — lịch sử/xóa mềm | Lưu xong; dùng **Xóa**, bật **Hiện cả hợp đồng đã xóa**; đọc/tải V1 rồi **Khôi phục** nếu ca được giao. | Giữ snapshot/tệp/attachment cũ, không xóa chuỗi nguồn; không thay tồn, số dư thương mại hoặc sổ kế toán chỉ vì tạo/sửa/xuất/xóa hợp đồng. |
| N15 — Thoát thật và mở lại | Khi mọi thay đổi cần giữ đã lưu, dùng **Thoát** ở khay. Thu chứng cứ controller/OS của 00/05 về dừng sạch. Mở shortcut lại, đăng nhập local và tải V1. | GUI không còn ở khay, app/frozen sidecar dừng thật, DB được đóng sạch rồi giải phóng lock; không sidecar mồ côi. Mở lại cùng root UUID, đọc dữ liệu và hash V1 không đổi; không auto-login/lưu mật khẩu. `.instance.lock` còn tồn tại không có nghĩa lock còn giữ; không xóa file lock để làm ca pass. |

## 4. Expected số liệu chính xác của fixture

Các giá trị dưới đây được đối chiếu bằng integer kg×1.000/tiền×100 và ROUND_HALF_UP từng dòng, không dùng float. Đây là expected dữ liệu, **không phải kết quả xuất native đã chạy**.

| Ca/dòng | Kg hợp đồng | VND/kg | Thành tiền VND |
|---|---:|---:|---:|
| Mua — CAN-NATIVE-01 override | 120.000 | 10000.25 | 1200030.00 |
| Mua — CAN-NATIVE-02 | 5.555 | 11000.00 | 61105.00 |
| Mua — dòng tay | 10.125 | 9000.50 | 91130.06 |
| **Mua: không tính thuế** | **135.680** | | **1352265.06** |
| Bán — dòng 1 | 2.001 | 123.45 | 247.02 |
| Bán — dòng 2 | 3.333 | 99.99 | 333.27 |
| **Bán trước thuế** | **5.334** | | **580.29** |
| Bán thuế ngoài giá 10% | | | **58.03** |
| **Bán tổng thanh toán** | | | **638.32** |

UI có thể trình bày dấu chấm nghìn/dấu phẩy thập phân; so sánh giá trị, không so chuỗi raw theo định dạng nhập. Mua với Chưa xác định thuế là ca riêng: không thay giá trị chưa biết bằng 0 hoặc kết luận tổng thanh toán. Cọc/lịch/số đã trả không tự tạo nghiệp vụ tiền hoặc giảm tổng tiền hàng.

## 5. Kiểm trực quan tài liệu và mức bằng chứng

Đối với chính bytes đã tải ở N08/N09/N12, giữ hash và render offline ra ảnh từng trang bằng công cụ QA local được duyệt theo skills documents/pdf. Xem toàn bộ trang: tiếng Việt/font, A4, dòng dài/nhiều trang, đủ hàng hóa/điều khoản/tài khoản/lịch, không cắt/đè khu ký hoặc sót token. Structural ZIP/PDF header/text extraction chỉ là kiểm cấu trúc, không là visual PASS. Nếu máy Windows sạch không có viewer/Office, việc app tạo được bytes không phụ thuộc Office; visual QA có thể làm trên máy QA khác với cùng hash bằng LibreOffice/local PDF renderer được duyệt, ghi rõ môi trường khác và không upload tài liệu lên dịch vụ online. Không biến viewer QA thành dependency ứng dụng.

| Mức | Trạng thái của lượt chuẩn bị này |
|---|---|
| Đọc source/routes/labels/API và lập expected | **PASS — kiểm chỉ đọc** trên `eab8c96`, không chứng minh GUI/binary |
| Source/backend mới; browser | **PASS source** — harness tiến trình thật và sửa trình bày được ghi riêng trong `desktop-harness.md` / `desktop-render-qa.md`; **browser NOT RUN** trong đợt này. Không chuyển các kết quả đó thành native proof |
| Frozen sidecar đúng SHA cuối | **NOT RUN** — chưa nhận artifact cuối; không chiếm slot build của 05 |
| GUI Windows/Tauri, dialog tải, tray/lifecycle, offline/không Office | **NOT RUN** — chờ artifact sau 00 và 05 |
| Visual DOCX/PDF từ artifact cuối | **NOT RUN** — chưa có file xuất native mới |
| Windows sạch/PC2, cài/upgrade/uninstall/WebView2 offline/root move/backup | **NOT RUN / 00–05 phụ trách gate chung**; cần máy/kênh truy cập thật và bằng chứng riêng |

Khi chạy, bằng chứng root lock cần single-instance và probe được duyệt trong root QA: cửa sổ thứ hai chỉ focus/mở instance hiện có, không spawn thêm writer; probe root bận phải bị chặn; sau Thoát thật mở lại được. Không lấy sự hiện diện/biến mất của file lock làm chứng cứ đủ. Không rename/xóa live DB hoặc can thiệp lock bằng tay. Trong ca upgrade/uninstall do 05 điều phối, dùng bộ hợp đồng đã lưu để đối chiếu root UUID, snapshot và hash trước/sau, không tự chạy nâng cấp trên dữ liệu người dùng.

## 6. Phát hiện source và đề nghị interface ngoài allowlist

**NATIVE-CONTRACT-SAVE-01 — thiếu contract rõ về lưu bản tải ra đĩa Windows.** Đây là phát hiện tĩnh, chưa phải lỗi runtime đã tái hiện:

- `frontend/src/features/contracts/ContractsPage.tsx:205–214` lấy Blob qua API có auth/session fence, tạo object URL rồi `a.download`/`a.click()`. Hàm không nhận kết quả save/cancel/đích file hay hoàn tất ghi Windows. Cùng hàm dùng cho DOCX/PDF và attachment ở phạm vi contract.
- `backend/cafe_fin/contracts/module.py` scoped download xác minh file/hash trước trả bytes; `service.py` lưu bản xuất trong category **documents**. FileStore dùng tên nội bộ `<category>/<id>-<sha>.bin` (`core/storage.py:305`). Đây là lưu bản nội bộ, chưa chứng minh bản người dùng tải nằm ở đích chọn được.
- `frontend/src/shared/api.ts` facade desktop, `desktop/src/main.rs:246–257` invoke handler và `desktop/capabilities/main.json` không có lệnh save/export file. Có plugin dialog cho các lệnh native khác nhưng chưa có contract lưu chứng từ. `open_reports` chỉ cho thư mục **reports**, không phải một đường mở/tải các bản contracts trong documents.
- `main.rs` có navigation origin allowlist. Chưa chạy WebView2 nên không kết luận object URL sẽ bị chặn hoặc được tự lưu; cần quan sát N08 trên artifact cuối, không suy từ Playwright download.

**Đề nghị điều phối chuyển 00/05:** trước freeze xác định hành vi người dùng của Tải DOCX/PDF/tệp gốc trong Tauri: native Save As hay download destination được hiển thị/kiểm chứng. Nếu cần bounded native save interface, frontend chỉ truyền identity contract/version/format hoặc attachment ID và phiên hiện hành, không truyền source absolute path hoặc HTTP URL tùy ý; native chọn đích bằng dialog, kiểm quyền/generation và dùng bytes/hash từ endpoint scoped. Kết quả phân biệt đã lưu/cancel/chưa xác nhận, chỉ báo đã lưu sau khi hoàn tất ghi, giữ bảo vệ ghi đè và file nội bộ bất biến. Lỗi/cancel không tạo version mới hoặc mất draft. Không mở capability filesystem/shell tùy ý chỉ để xử lý tải.

Không sửa shared/desktop trong lane này. Chưa có native module bug nào được xác nhận bằng GUI vì artifact chưa sẵn sàng; không gọi missing-interface proof ở trên là failure của renderer hoặc khẳng định WebView2 download hỏng. Lifecycle close-to-tray/Exit mới là công việc đang chờ 00, được kiểm bằng N06/N15 sau tích hợp. Mọi phát hiện mới cần artifact SHA + bước tái hiện + chứng cứ trước khi đề nghị sửa product.
