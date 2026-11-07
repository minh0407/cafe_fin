# Yêu cầu sản phẩm cafe_fin

Phiên bản 1, thống nhất ngày 06/11/2026. Bộ này thay phương án CRM có chuỗi duyệt nhiều người trước đây. Những quyết định kỹ thuật ở ARCHITECTURE phục vụ các yêu cầu bên dưới, không tạo thêm quy trình cho người dùng.

## 1 Người dùng và môi trường

Một máy Windows 11 64 bit, thường xuyên có Internet, một nhân viên nhập liệu chính. Hai nhóm quyền cơ bản: Operator nhập/sửa/xem/xuất trong phạm vi được cấp; Admin quản lý tài khoản, mẫu và cấu hình. Admin có thể kiêm nhập liệu nhưng không có bước bắt buộc người khác duyệt. Đăng nhập local, không Google OAuth hoặc phụ thuộc dịch vụ cloud.

Người dùng cài app, chọn thư mục dữ liệu và sử dụng. Không tự cài PostgreSQL, Docker, Python hoặc mở terminal. Bộ cài phải mang theo các runtime được phép phân phối và cần thiết. Đóng gói Windows và PDF phải được thử sớm, không để tới cuối mới phát hiện thiếu phụ thuộc.

Bổ sung kiểm thử 07/11/2026: người dùng yêu cầu mở bản preview trên Docker localhost
sau khi kiểm thử. Preview dùng API/nghiệp vụ thật và volume dữ liệu thử riêng,
chỉ xuất bản cổng loopback. Đây là môi trường thử web; sản phẩm Windows vẫn có
bộ cài độc lập. Preview không giả thành công cho native controller hoặc thay
Windows Credential Manager bằng tệp plaintext trên Linux. Không mount/migrate
dữ liệu CRM cũ để dựng môi trường thử.

Dữ liệu bản đầu là dữ liệu mới. CRM cũ giữ nguyên để tra cứu. Không sửa repo cũ, không chép toàn bộ lịch sử Git hoặc runtime vào repo mới, không tự nhập dữ liệu thật.

## 2 Nguyên tắc nghiệp vụ

Ứng dụng ghi lại thực tế người dùng nhập, không điều khiển hoạt động ngoài hiện trường. Lưu người nhập, thời điểm nhập, ngày phát sinh, ghi chú và bằng chứng khi có; người làm thực tế là thông tin riêng, không giả định bằng tài khoản nhập.

- Bỏ QR từng bao, camera quét, đổi theme sáng tối, ca trưởng, giao nhận bằng hai tài khoản và chuỗi phê duyệt tài chính/QC.
- Giữ mã định danh, dữ liệu chính xác, thông báo lỗi rõ, chống ghi lặp và lịch sử trước/sau khi sửa.
- Tự tổng hợp tồn và công nợ để tham khảo, có cảnh báo bất thường; chỉ phản ánh dữ liệu đã nhập, không khẳng định bao phủ thực tế.
- **Chặn tồn âm.** Tạo, sửa, xóa hoặc đổi ngày một bản ghi ảnh hưởng kho phải kiểm lại các số dư liên quan. Không cho sửa trực tiếp số dư để vượt kiểm tra.
- Không bắt phải nhập đủ toàn bộ quy trình hoặc giao dịch CRM mới được ghi thu/chi. Không tự chuyển tiền hoặc kết nối ngân hàng.
- Sửa/xóa bản ghi đã lưu phải truy được lịch sử và khôi phục được theo quyền. Bản hợp đồng/báo cáo đã xuất không đổi ngầm.

## 3 Ghi nhận mua bán và kho

Bổ sung theo yêu cầu 07/11/2026: giữ chức năng mã Farm và các thuộc tính hồ sơ từ CRM cũ, bắt đầu dữ liệu mới. Farm có mã bốn ký tự, chủ farm/giấy tờ, liên hệ/ngân hàng, mã vùng, lô trồng và khảo sát; bỏ ảnh/sơ đồ/phân công. Công ty khách hàng giữ tên công ty, người liên hệ, MST, giấy phép và liên hệ. Tách trang Đầu vào (farm trên từng dòng) và Đầu ra (chọn công ty đủ thông tin trước nhập đơn/thu tiền), có chi tiết đơn, phiếu nhập/xuất liên kết và các lần ghi thu/chi. Không mang lại chuỗi duyệt. Lưu đơn hoặc thu/chi chưa làm thay tồn; phiếu kho ghi sổ mới ảnh hưởng ledger và bị chặn vượt đơn/tồn âm. Kế toán Excel vẫn độc lập.

Dashboard là trang mở đầu, giữ các nhóm chỉ tiêu hữu ích từ CRM cũ nhưng lấy từ nguồn Cafe Fin: hồ sơ farm/khảo sát/công ty, đơn theo chiều, kg thực nhập/xuất, tồn và thu/chi đã ghi. Giá trị đơn được phân biệt với doanh thu/tiền đã thu; đơn thiếu giá phải hiện riêng. Các nguồn tiền không cộng chồng với sổ Excel; lỗi đọc phải hiện lỗi, không thay bằng số 0. Chi tiết contract tại [increment Farm và mua/bán](handoffs/records/crm-parity-v1.md).

CRUD đối tác, khách hàng/nhà cung cấp, hàng hóa, phiếu cân, phiếu mua/bán, nhập/xuất, sản xuất hoặc chuyển đổi và ghi chú thực tế. Có tìm kiếm, lọc, sort, phân trang server; tham số xem danh sách nằm trong URL nhưng không chứa credential hoặc dữ liệu nhạy cảm.

Phiếu cân do người nhập ghi: hỗ trợ số cân trực tiếp và tùy chọn các lần đầy/rỗng/tịnh, nhiều dòng khi cần. Không buộc phải có tích hợp cân vật lý, ảnh, QR hoặc phiếu khác mới được lưu bản nháp. Giá trị được tính từ đầy/rỗng phải phân biệt với kg người dùng nhập trực tiếp; không âm thầm ghi đè số người dùng đã chọn.

Hợp đồng có thể nhập từ đầu hoặc lấy thông tin đã lưu. Thông tin Farm/Grade, sản xuất, kho và giao hàng còn hữu ích thì giữ dưới dạng trường/nhật ký đơn giản, không mang lại chuỗi trạng thái duyệt cũ.

Tồn kho có ledger, số dư đầu kỳ có căn cứ nhập và điều chỉnh có ghi chú. Chuyển kho/chuyển loại/sản xuất không làm tăng hàng ngoài nguồn. Số dư và ledger cập nhật nguyên tử, request gửi lại không tạo thêm chuyển động. Với dữ liệu nhập ngược ngày, kiểm chuỗi số dư theo ngày phát sinh, dùng thứ tự ổn định trong ngày; không chỉ kiểm số dư hiện tại. Xóa phiếu nhập cũ mà làm phiếu xuất sau nó thiếu tồn phải bị chặn và chỉ rõ phiếu liên quan.

## 4 Hợp đồng và chứng từ

Áp dụng cả mua vào và bán ra. Chọn mẫu → chọn đối tác hoặc nhập thông tin trực tiếp → nhập/chọn thông tin cân theo người dùng → tự điền bản hợp đồng → sửa điều khoản và thanh toán → xem trước → lưu và xuất Word/PDF.

Trường tối thiểu: số/ngày/nơi lập, thông tin công ty và bên mua/bán, hàng hóa, đơn vị, dòng số lượng/số cân, đơn giá, thành tiền, thuế nếu được nhập, giao nhận, chất lượng nếu cần, điều khoản bổ sung, phương thức và nội dung thanh toán. Phương thức có tiền mặt/chuyển khoản/kết hợp/khác; ghi thời hạn hoặc lịch trả nhiều đợt nếu người nhập chọn. Không tự chọn thuế hoặc điều khoản pháp lý thay người dùng.

Mẫu hiện có trong source cũ là nền tham khảo, không mặc định câu chữ đã được duyệt. Bổ sung/sửa điều khoản phải là dữ liệu nhập thật được đưa vào bản Word/PDF, không chỉ có textarea không xuất ra.

Cho nhập kg trực tiếp; liên kết phiếu cân/đối tác chỉ giúp tự điền, không là điều kiện phải hoàn tất nghiệp vụ CRM. Khi tự điền, cho xem và sửa trước khi xuất; sửa trên hợp đồng không tự thay phiếu cân nguồn.

Mỗi lần xuất lưu phiên bản, snapshot dữ liệu, mẫu và hash tệp; giữ bản cũ đã in/gửi. Word và PDF xuất độc lập, lỗi PDF không làm mất bản Word hoặc dữ liệu hợp đồng. Đính kèm bản ký/scan và tình trạng do người nhập ghi; không tuyên bố xác minh chữ ký điện tử. Không bắt bản ký hoặc người thứ hai để lưu hợp đồng.

## 5 Kế toán dạng bảng độc lập

Khu kế toán không phải bản mở rộng bắt buộc của luồng mua–kho–bán. Cho ghi nhật ký theo ngày, thêm/sửa/xóa dòng, nhập từ Excel và lưu các sổ riêng. Liên kết khách/đơn/mã hàng là tùy chọn. Dòng kế toán không tự trừ kho, tạo giao dịch CRM hoặc khẳng định đã đối chiếu ngân hàng.

Người dùng chưa xác định cấu trúc cột cố định. Cần cấu hình sổ: cột, kiểu dữ liệu, cột ngày, mã đơn/chứng từ, mã hàng, mô tả, thu/chi hoặc số tiền khi có, và cột mở rộng. Cung cấp mẫu đề xuất có thể đổi; mapping import lưu thành hồ sơ có phiên bản. Chưa ánh xạ được ý nghĩa tiền thì không tự cộng thành báo cáo dòng tiền.

Tương tác bản đầu: sửa ô bằng bàn phím, chọn vùng, copy/paste nhiều ô, kéo điền có giới hạn hợp lý, resize/freeze cột, lọc/sort/tìm, thêm/xóa dòng, undo/redo bản nháp, định dạng ngày/tiền/số và chỉ rõ trạng thái lưu. Tách sheet/sổ và giữ tọa độ nguồn. Ưu tiên thư viện miễn phí phù hợp production.

Công thức bản đầu có tập được kiểm thử như SUM, AVERAGE, MIN, MAX, COUNT, IF, ROUND, SUMIF, COUNTIF và phép toán cơ bản. Nêu rõ công thức nào hỗ trợ; lỗi hoặc không hỗ trợ hiện ngay ở ô, không dùng kết quả cache cũ như thể đã tính lại. Tham chiếu ngoài, truy vấn mạng, macro không chạy. Tập dữ liệu rất lớn cần tính theo job/range ở backend hoặc engine phù hợp; không tải một triệu dòng lên UI chỉ để tính tổng.

**Tương thích tệp:** giữ nguyên byte tệp gốc `.xlsx`/`.xlsm` theo hash và tải lại được bản gốc. Không chạy VBA; không yêu cầu Microsoft Excel cài trên máy. Grid là projection có khả năng đã xác minh, không hứa giữ mọi biểu đồ/Pivot/định dạng/extension khi tái xuất. Bản xuất dữ liệu đã sửa là tệp dẫn xuất riêng, ghi rõ phạm vi hỗ trợ; không ghi đè hoặc giả làm tệp macro gốc được bảo toàn toàn bộ.

## 6 Import tới một triệu dòng

Upload → lưu gốc → parse tuần tự vào staging → chọn sheet/header và ánh xạ → modal rộng xem/sửa/copy/paste → validate toàn bộ ở background → hiển thị phân loại → người dùng xác nhận → nhập dòng hợp lệ → giữ dòng lỗi để sửa/nhập tiếp.

Phải hỗ trợ file 500.000 và 1.000.000 dòng theo benchmark thật. Một triệu dòng là mục tiêu kiểm thử mỗi lượt import, không phải một triệu DOM row hoặc một payload JSON. XLSX có giới hạn worksheet; thông báo sớm nếu vượt định dạng. Không cam kết số giây trước khi đo máy và file.

### Phân loại và báo lỗi

- NEW: sẽ thêm mới.
- POTENTIAL_DUPLICATE: giống nội dung hoặc cùng ngày + mã đơn/mã hàng; cảnh báo với dữ liệu đối chiếu, không tự xóa vì có thể là giao dịch hợp lệ.
- ALREADY_IMPORTED: cùng dòng staging trong cùng job đã được ghi; không nhập lại.
- CONFLICT: cùng khóa nghiệp vụ được người dùng cấu hình nhưng dữ liệu khác; so sánh cũ/mới và chờ lựa chọn rõ ràng.
- INVALID: sai kiểu, thiếu cột bắt buộc theo sổ, công thức không hỗ trợ hoặc lỗi dữ liệu; chỉ rõ sheet, dòng, cột/ô, mã lỗi, thông điệp và cách sửa.
- EXCLUDED: người dùng chủ động loại dòng; ghi lựa chọn.

Kiểm trùng trong file và với dữ liệu cũ riêng biệt. Khóa nghiệp vụ do cấu hình đã được người dùng xác nhận; chưa có cấu hình thì không tạo unique `(ngày, mã hàng)` hay `(ngày, mã đơn)`. Chống retry cùng job khác với việc người dùng cố ý nhập một giao dịch lặp hợp lệ trong job mới.

### Nhập một phần và tiếp tục

Đã chốt cho nhập dòng hợp lệ sau xác nhận; số dòng lỗi/loại/nghi trùng phải hiện trước xác nhận. Xác nhận gắn với phiên bản mapping, staging và quyết định trùng. Sửa sau validate phải kiểm lại phần ảnh hưởng và xác nhận lượt mới.

Job có trạng thái và checkpoint bền vững. Mỗi lượt xác nhận tạo một attempt có snapshot staging/mapping bất biến. Các chunk ghi ngắn vào dữ liệu pending, có receipt/checkpoint và counts trong cùng transaction; retry không thêm lặp. Khi toàn bộ tập đã xác nhận hợp lệ hoàn tất, một transaction ngắn công bố attempt để các dòng cùng xuất hiện trong sổ và báo cáo. Tiến độ ghi bền vững khác số dòng đã công bố. Hủy/app dừng trước công bố giữ pending để tiếp tục hoặc dọn an toàn; không báo dữ liệu pending đã nhập thành công. Những attempt trước đã công bố vẫn giữ nguyên. Tác vụ hoàn tác batch là tác vụ riêng có kiểm lịch sử chỉnh sửa sau import.

Dòng lỗi được sửa, validate lại rồi nhập tiếp mà không nhập lại dòng đã ghi. Kết quả có số dòng nguồn/hợp lệ/mới/đã ghi/nghi trùng/lỗi/loại và tệp lỗi tải được. Lỗi không được làm mất dòng nguồn hoặc âm thầm biến số thành 0.

## 7 Lưu dữ liệu và báo cáo

Lần đầu chọn thư mục gốc trên ổ local, ví dụ `D:\CafeFinData`; app tạo `database`, `documents`, `workbooks`, `imports`, `reports`, `backups`, `logs`. Có mở thư mục, sao lưu, khôi phục và chuyển nơi lưu với xác minh. Nâng cấp/gỡ app mặc định giữ dữ liệu; không lưu dữ liệu vận hành trong thư mục cài.

Báo cáo ngày lấy theo khoảng giờ Việt Nam, trình bày nhập/sản xuất/xuất/tồn, tổng tiền theo sổ có mapping phù hợp và các cảnh báo. Ghi rõ chỉ tổng hợp phần đã nhập, không gọi là báo cáo tài chính đầy đủ. Xuất tệp vào reports; không đưa chi tiết cá nhân hoặc ngân hàng vào tin nhóm.

Theo quyết định mới ngày 07/11/2026, gửi báo cáo cuối ngày bằng **Telegram Bot chính thức**, bỏ tích hợp Zalo. Admin cấu hình bot token, nhóm Telegram và lịch; không hardcode nhóm hoặc giờ. Kiểm kết nối chỉ đọc thông tin bot/nhóm/quyền gửi, không gửi tin thử. Token chỉ nằm trong kho bí mật Windows, không vào DB, backup, audit, log hoặc báo cáo. Chưa đủ cấu hình thì vẫn tạo/lưu báo cáo local, hiển thị chưa cấu hình và không gọi mạng để gửi.

Đích là nhóm/supergroup Telegram do người dùng chọn rõ; chỉ gửi bản tổng hợp và tệp tổng hợp được chọn. Không tự gửi chứng từ, Excel gốc hoặc dữ liệu chi tiết. Receipt phải xác minh đúng nhóm và message_id; timeout sau gửi giữ UNKNOWN, không tự gửi lại. Lịch sử và payload của kênh cũ được giữ, không đổi tên thành Telegram hoặc tự chạy lại. Xem [quyết định và giới hạn gửi Telegram](adr/20261107_TELEGRAM_REPORT_DELIVERY.md).

Người dùng có máy Windows khác và đã xác nhận Windows 11 x64 để nghiệm thu; build, cấu hình máy, bộ cài và kết quả thực tế vẫn phải được ghi khi thử.

Tiến trình gửi là ngoại lệ Internet. Core không dùng Google, crawler giá, cloud AI hoặc cloud storage. Máy tắt/ngủ thì không hứa gửi đúng giờ; có catch-up và báo đúng ngày của bản còn chờ. Không dùng Codex scheduler làm scheduler vận hành sản phẩm.

## 8 Tiêu chí nghiệm thu

- Cài Windows sạch, chọn ổ D/E, dùng không Docker/terminal; tắt WAN vẫn ghi/xem/xuất local.
- Ghi đủ một vòng đối tác → số cân → mua/bán → nhập/xuất → tổng hợp; không có bước duyệt ẩn. Xuất quá tồn và chỉnh phiếu làm thiếu tồn bị chặn rõ.
- Lập mua và bán từ thông tin người nhập; điều khoản/thanh toán tự điền đúng Word và PDF; bản cũ không đổi sau sửa.
- Upload, sửa/copy/paste, lọc và import một phần; lỗi chỉ đúng ô; sửa lỗi rồi nhập tiếp không tạo lặp.
- Tệp macro gốc tải lại có hash y hệt; không có macro hoặc truy vấn ngoài được chạy trong preview.
- Chạy file tổng hợp 50k/500k/1m với cấu hình máy, số cột, RAM, thời gian từng bước, dung lượng và truy vấn đo thật. Không lấy fixture 100 dòng để tuyên bố một triệu dòng pass.
- Tắt app hoặc kill worker giữa parse/validate/commit; mở lại đúng trạng thái/counts, dữ liệu không thiếu hoặc lặp.
- Sao lưu/khôi phục DB+tệp, update và chuyển nơi lưu giữ dữ liệu và các job chưa xong.
- Gửi Telegram chỉ báo thành công khi có receipt đúng nhóm; timeout không rõ không tự gửi lại, thiếu cấu hình không chặn lưu/xem/xuất local. Nâng cấp từ cấu hình kênh cũ không phát sinh gửi lại.

## 9 Phạm vi chưa làm ở bản đầu

Chuyển DB CRM cũ; đa máy/LAN nhiều người ghi; chạy VBA hoặc tái tạo toàn bộ Excel; nối ngân hàng; tự chuyển tiền; ký số/xác minh chữ ký; QR; AI ảnh; workflow phê duyệt nhiều người. Không tự thêm các hạng mục này vì source cũ đã có.
