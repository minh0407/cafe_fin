# Bổ sung Farm, khách hàng và luồng mua/bán — 07/11/2026

Điều phối chốt increment trên source `449093b`, sau baseline tích hợp đã nghiệm thu phát triển. Giữ dữ liệu mới; người dùng xác nhận chỉ giữ chức năng/mã farm, không chuyển danh sách hoặc DB CRM cũ. Các lane đọc tài liệu nền trước sửa và chỉ commit allowlist; điều phối tích hợp/push.

## API module records được thống nhất

Các đường dẫn bên dưới là tương đối trong module: tiền tố đầy đủ `/api/v1/records` (ví dụ `/api/v1/records/trades`, `/api/v1/records/records-dashboard`).

Giữ nguyên read bridge v3, lịch sử hiện có và migration records v1. Các field mới có default tương thích bản ghi cũ. Không thay stock guard hoặc tạo tiền/kho từ Excel.

- `Party` thêm `profile_kind: general|farm|customer_company` mặc định `general`, `business_license: string|null`, `farm: FarmProfile|null`.
- Farm dùng `Party.code` viết hoa đúng bốn ký tự `[A-Z0-9]{4}`, nhập thủ công, bất biến sau tạo. FarmProfile có `owner_name`, `owner_id_card`, `official_area_code`, `internal_area_code` nullable; `plots[]` gồm `plot_code`, `variety`, `area_ha` (Decimal string), `tree_count`, `tree_age`; `surveys[]` gồm `season_year`, `grade` 1–5, `ripeness_pct` (Decimal string), `notes`. Điện thoại/địa chỉ/ngân hàng dùng trường Party hiện có. Không ảnh, GPS, sơ đồ hoặc phân công nhân viên.
- Công ty khách hàng: Party.name là tên công ty, representative.name là người liên hệ/đại diện. Lưu MST, giấy phép, điện thoại, email, địa chỉ. Khi dùng luồng đầu ra bắt buộc tên công ty, người liên hệ và MST; không áp unique MST không có căn cứ.
- `GET/POST /trades`, `GET/PUT/DELETE /trades/{id}`, history/restore giống resource records hiện có. Trade kế thừa Document; thêm `direction: inbound|outbound`, `status: recorded|cancelled` mặc định recorded, `vehicle_plate`, `weighing_id` nullable; `lines[]` (1–500) gồm `farm_id` nullable, `product_id` nullable, `quantity_kg` Decimal string dương, `unit_price_vnd` nullable Decimal string không âm, `bag_count` int không âm mặc định 0, `grade` nullable 1–5, `note` nullable. Đầu vào bắt buộc farm trên từng dòng; đầu ra bắt buộc công ty ở party_id và product trên từng dòng. Mỗi trade là hồ sơ ghi nhận/đơn hàng, lưu nó chưa thay tồn.
- `Entry` thêm `trade_id` nullable. Nhập kho gắn trade inbound chỉ dùng receipt; xuất gắn trade outbound chỉ dùng issue và cùng company. Lượng nhập/xuất posted cộng dồn theo sản phẩm không vượt số lượng trade đã ghi; kiểm cả sửa/xóa/restore/cancel và sửa trade. Không áp liên kết mới cho phiếu kho cũ/phiếu độc lập. Sửa/xóa trade có chứng từ kho/thanh toán hiệu lực phải giữ toàn vẹn, trả conflict rõ thay vì gây sai danh tính. Stock ledger cũ vẫn là nguồn tồn duy nhất.
- `GET/POST /trade-payments`, GET/PUT/DELETE/history/restore theo resource. Model kế thừa Document, thêm `trade_id` required, `amount_vnd` Decimal string dương, `method: cash|bank_transfer|mixed|other`, `reference` nullable. Party bắt buộc: outbound là đúng công ty đơn hàng; inbound là farm có trong các dòng. Đây là ghi thu/chi thực tế, không chuyển tiền, không bắt chứng cứ ngân hàng hoặc duyệt. Cho ghi trước giao hàng. Không tự suy là sổ kế toán đầy đủ hoặc cộng chồng với sổ Excel.
- List bổ sung filters `profile_kind`, `direction`, `trade_id` khi phù hợp. Phân trang server, tối đa 500; lookup UI có tìm kiếm/phân trang, không nạp toàn bộ danh mục.
- `GET /records-dashboard?from_on=YYYY-MM-DD&through_on=YYYY-MM-DD` đọc một snapshot, quyền records.read. Trả `coverage='entered_records_only'`, `cutoff`, `from_on`, `through_on`; `counts` (farms, farm_surveys, customer_companies, inbound_trades, outbound_trades), `inventory` (InventorySummaryDTO cùng snapshot); `period` và `daily[]` có inbound_kg, outbound_kg từ ledger receipt/issue, cash_in_vnd/cash_out_vnd từ trade-payments, sales_order_value_vnd từ hồ sơ outbound có đủ giá, unpriced_sales_orders count. Daily thêm `occurred_on`. Tiền/kg là Decimal strings, counts integer; không gọi giá trị đơn hàng là doanh thu hoặc tiền đã thu. Không cộng vào sổ kế toán độc lập. Khoảng ngày dashboard tối đa 366 ngày, mặc định tuần hiện tại tại UI.

## UI

Route `/records` giữ công cụ kho/phiếu cũ; thêm trang `/records/farms`, `/records/customers`, `/records/inbound`, `/records/outbound` và `/records/dashboard`. Có điều hướng rõ Đầu vào / Đầu ra / Farm / Công ty khách hàng; mở chi tiết từng hồ sơ. Danh mục có form trường thật thay vì bắt nhập JSON.

Đầu vào chọn/tạo farm, số kg/bao/grade/giá và thông tin xe; đầu ra chọn/tạo công ty và hoàn tất tên/MST/liên hệ trước sang nhập đơn. Chi tiết thể hiện hồ sơ, nhập/xuất kho đã liên kết và thu/chi; tạo chứng từ kho nháp qua Entry hiện có, người nhập chọn hàng/kho rồi ghi sổ bằng guard thật. Không tự giảm tồn khi chỉ ghi đơn. Form trả lỗi server tại bước đang thao tác; danh sách URL giữ loại luồng/ngày/tìm/sort/page.

Dashboard là trang mặc định, có tuần/tháng/khoảng ngày, thẻ chỉ tiêu đúng nguồn, bảng/xu hướng theo ngày và link về danh sách đúng luồng. Không sao chép biểu đồ cộng các đơn vị khác nhau hoặc hiển thị lỗi thành số 0. Không thêm dependency biểu đồ cần phí.

## Kiểm thử bắt buộc

Giá trị đơn hàng là phép nhân suy ra từ giá (2 số lẻ) và kg (3 số lẻ), giữ chính xác tối đa 5 số lẻ, tối thiểu 2; không làm tròn ngầm hoặc đưa vào actual payment. Khoản thu/chi thực tế vẫn tối đa 2 số lẻ VND.

Field farm + code bất biến/trùng, công ty chưa đủ thông tin, liên kết sai chiều/party, nhiều lần giao không vượt đơn, sửa/xóa/hoàn tác không phá tồn hoặc đơn, tiền Decimal, payment retry/version/history, dashboard snapshot/ngày VN/không cộng tiền Excel; browser tạo farm/công ty, vào hai luồng và chi tiết, lỗi thực tế, build và regression có liên quan. Dữ liệu tổng hợp duy nhất. Cập nhật Docker sau khi kiểm, giữ nguyên volume đang dùng và sao lưu nhất quán trước nâng cấp.
