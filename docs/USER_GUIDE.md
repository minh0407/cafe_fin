# Hướng dẫn Cafe Fin trên một máy tính

**Bản hướng dẫn dự thảo theo UI/source hiện tại, ngày 07/11/2026.**
CI và các kiểm tra Windows đang tiếp tục; tài liệu không xác nhận đã cài đặt,
nghiệm thu giao diện native hoặc chạy trên máy Windows sạch của người dùng.
Dữ liệu nghiệp vụ nằm trong DB và tệp trên máy; nhập/xem/xuất local không cần
mạng ngoài. Gửi Telegram cần Internet, bot và nhóm do Admin cấu hình; bộ lấy giá nhân xô cũng cần Internet để đọc nguồn công khai cố định.

## Ai làm việc gì?

Một người nhập liệu có thể dùng Operator hằng ngày. Admin dùng tài khoản riêng
để quản trị máy, tài khoản và cấu hình. Không có chuỗi duyệt nhiều người,
ca trưởng, QR hoặc bước phê duyệt hợp đồng/phiếu hàng.

| Công việc | Operator | Admin |
|---|---|---|
| Xem, thêm, sửa, xóa mềm đối tác, hàng hóa, phiếu cân và phiếu hàng | Có | Có |
| Ghi nhập/xuất, sản xuất, chuyển vị trí; xem tồn và lịch sử | Có | Có |
| Lập/sửa hợp đồng; chọn mẫu; xem trước, xuất Word/PDF, đính kèm tệp | Có | Có |
| Xem sổ, thêm/sửa/xóa dòng; nhập Excel/CSV, sửa nháp, xác nhận phần hợp lệ | Có | Có |
| Tạo sổ; cấu hình cột và ngữ nghĩa tiền | Có | Có |
| Khôi phục dòng sổ kế toán đã xóa | Có | Có |
| Xem trước, lưu snapshot, xuất báo cáo PDF/XLSX/TXT | Có | Có |
| Mở thư mục báo cáo với quyền `reporting.read` | Có | Có |
| Quản lý tài khoản; sửa nội dung mẫu hợp đồng | Không | Có |
| Cấu hình báo cáo/lịch gửi/credential; sao lưu, chuyển nơi lưu, khôi phục dữ liệu | Không | Có |
| Bỏ qua kiểm tra tồn âm | Không | Không |

**Chính sách vận hành:** Operator được **Tạo sổ**, **Cấu hình cột / ngữ nghĩa** và
**Khôi phục dòng chọn** để tự làm kế toán độc lập trên một PC, không thêm bước
Admin duyệt mỗi lần làm Excel. Kiểm phiên bản, lịch sử và chống ghi lặp vẫn giữ.
Quản lý dữ liệu chỉ khả dụng khi phiên desktop xác nhận hỗ trợ maintenance.

## Một ngày làm việc

**Tổng quan / Đầu vào / Đầu ra:** menu mới tách hồ sơ mua từ farm và bán cho công ty. Trong **Hồ sơ farm**, nhập mã bốn ký tự (giữ số 0 đầu), chủ farm, mã vùng, lô trồng/khảo sát và thông tin liên hệ cần dùng; không yêu cầu ảnh. Mã farm không đổi sau khi tạo. Trong **Công ty khách hàng**, tên công ty khác với tên người liên hệ; nhập MST và người liên hệ trước khi tiếp tục đơn bán.

**Đầu vào:** chọn hoặc tạo farm cho từng dòng, ghi hàng/kg/bao/grade/giá và xe. **Đầu ra:** chọn hoặc tạo công ty → hoàn tất tên/MST/người liên hệ → nhập đơn bán. Mở chi tiết để xem/cập nhật hồ sơ, ghi các lần thu/chi hoặc tạo phiếu nhập/xuất nháp. Chọn hàng hóa và kho trước ghi sổ; tổng các lần giao không vượt đơn và không được làm tồn âm. Đơn, phiếu cân và giao dịch tiền là các ghi nhận riêng, không tự chuyển tiền hoặc tự giảm tồn. Phiếu độc lập và sổ Excel vẫn dùng được theo nhu cầu đã nhập.

**Tổng quan** có tuần/tháng/khoảng ngày và đường dẫn về đúng luồng. Kg lấy từ phiếu kho đã ghi sổ; thu/chi lấy từ giao dịch gắn đơn; giá trị đơn bán được hiển thị riêng, giữ phép tính chính xác và tách đơn chưa đủ giá. Sổ Excel kế toán được xem riêng tại Báo cáo để tránh cộng trùng. Mọi chỉ tiêu chỉ phản ánh dữ liệu đã nhập.

**Bảng giá mua / nhập / bán:** cài giá đúng ngày trước khi ghi cân. Giá mua tươi và giá nhập chế biến phục vụ đầu vào; giá bán cài riêng theo hàng hóa. Có thể dùng giá cố định hoặc nhập Grade5 rồi xem đủ năm Grade theo quy tắc 90% từng bước, làm tròn hai số lẻ. Khi tạo đơn mới, chọn hàng và ngày (Grade nếu dùng bảng Grade), sau đó nhập kg; giá và thành tiền tự hiện. Không có bảng đúng ngày thì cấu hình bảng giá trước, không tự dùng giá mua cho đơn bán. Đơn cũ giữ giá đã lưu kể cả khi bảng đổi; chỉ lấy lại giá khi chủ động chọn thao tác đó. Sửa kg sẽ tính lại thành tiền bằng giá của đơn đang lưu.

**Tự động giá nhập nhân xô:** thẻ nguồn trên trang Bảng giá dùng giá Robusta nhân xô Gia Lai làm Grade5, tự tính các Grade còn lại. Khi app đang mở và tự động đang bật, bộ lấy giá kiểm tra nguồn theo lịch, mỗi ngày chỉ áp một lần; nút kiểm tra ngay vẫn tôn trọng thời gian chờ. Giá quả tươi nhập tay; không quy đổi giá nhân thành giá quả tươi. Ngày đã có bảng sẽ được giữ nguyên. Nếu hiện nguồn bị chặn, thiếu ngày công bố, giá cũ hoặc mất mạng thì chưa có giá hợp lệ mới được áp; có thể dùng bảng nhập tay khi cần. Tắt tự động dừng lần tải mới, không đổi giá đơn đã lưu. Nguồn có link/ngày/hash và trạng thái để tra cứu.

1. **Đăng nhập local.** Kiểm tra đang mở đúng thư mục dữ liệu. Không khởi tạo
   dữ liệu mới để thay cho thư mục cũ bị mất hoặc phiên đang chờ phục hồi.
2. **Ghi nhận cà phê:** tạo/chọn **Đối tác**, **Hàng hóa**, **Vị trí / kho**.
   Nhập **Phiếu cân tay**: cân đầy/rỗng hoặc kg tịnh, có thể nhiều dòng.
   Đây là số do người dùng ghi; không mặc định lấy trực tiếp từ thiết bị cân.
3. **Ghi phiếu hàng:** từ cân chọn **Lập phiếu nhập từ cân**, hoặc mở **Phiếu hàng**
   và chọn Nhập hàng, Xuất hàng, Sản xuất, Chuyển vị trí, Tồn đầu có căn cứ hay Điều chỉnh.
   Phiếu cân độc lập chưa làm thay đổi kho. **Nháp — chưa ghi tồn** chưa cập nhật kho;
   **Đã ghi — cập nhật sổ kho khi lưu** mới ảnh hưởng kho. Kiểm tra **Tổng hợp tồn**,
   **Lịch sử kho**, **Số dư thương mại**. Sửa/xóa/đổi ngày cũng không được gây tồn âm.
4. **Hợp đồng:** chọn **Lập hợp đồng mới**, loại mua/bán, nguồn đối tác và phiếu cân
   nếu có; xem rồi áp dụng thông tin nguồn. Có thể nhập tay, sửa dòng hàng,
   điều khoản bổ sung và phương thức Tiền mặt/Chuyển khoản/Kết hợp/Khác.
   Chọn **Xem trước** → **Lưu hợp đồng** → **Xuất Word + PDF**.
   Mỗi lần xuất giữ bản nội dung riêng; sửa tiếp không đổi ngầm bản đã xuất.
   Số “đã thanh toán” và bản scan do người nhập ghi không tự sinh thu/chi,
   không thay kho và không chứng thực chữ ký điện tử.
5. **Sổ kế toán:** chọn sổ có sẵn, hoặc **Tạo sổ** và **Cấu hình cột / ngữ nghĩa**.
   Chọn **Nhập Excel / CSV · mở job đã lưu** → chọn tệp → **Lưu gốc và tạo job**.
   Kiểm tra mapping, xem lỗi/nghi trùng, sửa nháp rồi **Lưu bản nháp**;
   **Lưu mapping / profile · làm mới validation** hoặc **Validate toàn bộ** khi cần.
   Chỉ chọn **Xác nhận nhập phần hợp lệ** sau khi kiểm tra; phần lỗi/nghi trùng chưa
   giải quyết không được tính là đã nhập. Đóng/mở lại có thể tiếp tục job đã lưu.
   Sổ kế toán độc lập: không bắt buộc liên kết hay bao phủ toàn bộ dữ liệu ghi nhận,
   không tự thay tồn kho. Pending chưa công bố chưa phải dòng đã vào sổ.
6. **Báo cáo:** chọn **Từ ngày (VN)**, **Đến hết ngày (VN)** và **Sổ kế toán cho báo cáo**
   → **Xem trước báo cáo** → đọc cảnh báo → **Lưu snapshot** → **Xuất PDF**,
   **Xuất XLSX** hoặc **Xuất TXT**. Cả hai ngày đều nằm trong kỳ được chọn.
   Ghi rõ thời điểm chốt: bản tạo trước khi nhập đủ ngày chưa thể coi là đủ cả ngày.
   Nhập bổ sung thì tạo lại cùng kỳ/sổ với lý do điều chỉnh; giữ các bản cũ để đối chiếu.
7. Trong **Cài đặt trên máy**, chọn **Mở thư mục báo cáo** để xem bản đã lưu ở
   `reports` dưới thư mục dữ liệu. Đọc trạng thái bản local; chỉ “Đã xác minh”
   mới xác nhận bản sao đó hoàn tất, không đồng nghĩa báo cáo đã được gửi.

Tệp Excel gốc, kể cả tệp có macro, được giữ nguyên byte để tra cứu/tải lại.
Ứng dụng không chạy macro hoặc liên kết ngoài. Grid và tệp CSV/XLSX dẫn xuất là
dữ liệu diễn giải; không cam kết giữ nguyên toàn bộ định dạng, macro, công thức
hay tính năng nâng cao của workbook gốc. Sao chép/lưu nháp cần giữ trước khi đổi trang.

## Mẫu báo cáo ngày — chỉ là số liệu tổng hợp minh họa

Ví dụ dưới đây hoàn toàn tổng hợp, không phải dữ liệu thật hay tệp đã được xuất/gửi.
Số kg dùng ba chữ số thập phân; tiền dùng VND. Các nhãn theo bản tổng hợp hiện tại.

```text
Cafe Fin — MINH HỌA — ngày 07/11/2026
Kỳ: 07/11/2026 đến hết 07/11/2026; dữ liệu đã nhập đến 20:00 (giờ Việt Nam).
Kho 1 (Kho minh họa) / Loại 1 (Cà phê nhân):
  Đầu kỳ (kg):    10000.000
  Nhập tổng (kg):  1250.500
  Xuất tổng (kg):   800.250
  Cuối kỳ (kg):   10450.250
  Đối chiếu: 10000.000 + 1250.500 - 800.250 = 10450.250 kg.
Sổ 1 (Sổ tiền minh họa):
  Tổng thu tiền (VND):    15000000.00
  Tổng chi tiền (VND):    10000000.00
  Cọc thu (trong thu) (VND): 2000000.00
  Đối trừ không tiền (VND):   500000.00
Sổ 2 (Sổ phụ minh họa): Tiền (VND) — Chưa đủ dữ liệu: chưa đủ mapping.
Sổ chưa chọn: ngoài phạm vi tổng hợp; không được coi số liệu là 0.
Chỉ tổng hợp dữ liệu đã nhập; không phải báo cáo tài chính pháp định.
```

Cọc thu 2 triệu **đã nằm trong** tổng thu 15 triệu: không cộng thêm lần nữa.
Đối trừ 500 nghìn không phải tiền thu/chi. Chênh thu–chi không phải lợi nhuận
hay số dư quỹ. Nhập/xuất tổng đã gồm các thành phần được tách bên dưới nếu có;
không cộng tổng và chi tiết hai lần. Không có sổ/chưa đủ mapping phải ghi
**Chưa chọn sổ** hoặc **Chưa đủ dữ liệu**, không tự điền 0 hay suy ra đủ kế toán.

## Gửi cuối ngày và xử lý khi chưa rõ kết quả

Đích nhận là **nhóm Telegram**. Tích hợp Zalo đã bỏ theo yêu cầu mới.
Xem [quyết định Telegram](adr/20261107_TELEGRAM_REPORT_DELIVERY.md).

- Tạo bot qua **@BotFather** bằng `/newbot`, rồi thêm bot vào nhóm báo cáo.
  Giữ token riêng; chỉ nhập vào trường bí mật trong app, không gửi vào chat,
  Git hoặc browser URL. Chỉ cấp quyền gửi tin/tệp cần thiết cho nhóm.
- Admin vào **Cấu hình Admin**, nhập thông tin bot, Chat ID nhóm, lịch và sổ cần
  tổng hợp. **Kiểm tra kết nối** chỉ xác minh bot/nhóm/quyền, không gửi tin thử.
  Muốn đổi token cần nhập lại; app không hiển thị token đã lưu.
- Không cần tài khoản Google, OAuth hoặc thuê server. Máy phải bật, backend đang
  chạy và mạng truy cập được Telegram khi gửi. Thiếu token/nhóm vẫn lưu báo cáo
  local. Chưa có lần gửi thật được nghiệm thu khi viết hướng dẫn này.
- Đính kèm chỉ áp dụng cho tệp tổng hợp PDF/XLSX của chính báo cáo được chọn,
  tối đa **5 MiB/tệp trong Cafe Fin**. Không gửi Excel gốc hoặc chứng từ chi tiết.
  Lịch tự động gửi tin tổng hợp; không tự chọn mọi tệp local để đính kèm.
- **Chưa cấu hình** vẫn lưu/xuất báo cáo local, chưa gửi ra nhóm. Với báo cáo đã lưu,
  **Xếp gửi bản tổng hợp này** là xếp yêu cầu; xem trạng thái/nhật ký để biết kết quả.
  **Chưa rõ** không phải **Đã gửi**: kiểm tra trực tiếp nhóm, không tự thử gửi lại.
  Telegram không cung cấp lịch sử tin đã gửi để app tự kết luận một lượt timeout
  thành công. Lịch sử kênh cũ được giữ để tra cứu, không tự gửi lại qua Telegram.
  Máy tắt/ngủ không bảo đảm gửi đúng giờ; khi chạy lại cần kiểm tra các kỳ còn chờ.
- Nếu bản local báo **Trùng tên, không ghi đè** hoặc lỗi sao chép, giữ nguyên tệp
  đang có và đọc trạng thái/lỗi. Bấm **Xuất** đúng định dạng để thử lại từ bản lưu
  chuẩn của ứng dụng; không ghi đè, xóa tệp xung đột hay sửa DB để “chữa” trạng thái.
- Admin sao lưu/chuyển/khôi phục bằng **Quản lý dữ liệu trên máy**. Bản sao được
  xác minh; nguồn cũ được giữ. Khi chưa rõ kết quả, dùng kiểm tra trạng thái/thử lại
  **cùng thao tác** hoặc kết nối phiên desktop hiện tại; không Restart để hủy,
  không reset/xóa root cũ và không tự sửa/copy riêng file DB.
- Đích đang chờ kích hoạt cần đăng nhập Admin của dữ liệu đích và bằng chứng native
  cho phép kích hoạt. Operator không tự mở khóa phục hồi; không có phê duyệt nghiệp vụ.

Đối chiếu quyền: `core/auth.py`, `accounting/service.py`, `contracts/module.py`,
`reporting/module.py`; tên thao tác lấy từ các trang UI tương ứng. Đây là hướng dẫn
vận hành theo source hiện tại, không thay thế nghiệm thu bộ cài/native đang chờ.
