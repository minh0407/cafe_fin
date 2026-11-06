# Đề nghị tích hợp records từ foundation e668355

Không cần dependency mới hoặc sửa core. Registry backend/frontend thuộc điều phối.

Các thao tác records chưa có endpoint concrete trong OpenAPI nền được đề xuất
additive trong namespace hiện hữu: POST collection, PUT detail (full replace),
DELETE detail (body request_key/expected_version), GET detail/history,
POST detail/restore; entries thêm POST detail/post và detail/cancel.
CRUD đơn vị/vị trí đặt dưới /records/products/units và /records/products/warehouses
để giữ nguyên bảy nhóm namespace đã chốt. Các lệnh đều dùng receipt/version core.

Thứ tự tồn dùng đúng foundation: occurred_on/order_key/id. order_key cấp một lần
từ sequence DB của phiếu, giữ khi sửa; trong sản xuất out đứng trước in.
occurred_at có timezone là thông tin tùy chọn, phải nằm trong occurred_on VN;
không thay thứ tự theo ngày đã freeze của foundation.

Công nợ là commercial_amount_vnd có dấu do người nhập ghi trên phiếu, dương là
khoản đối tác còn phải trả, âm là khoản doanh nghiệp còn phải trả. Không suy
tiền đã thanh toán từ accounting, không tự sinh thu/chi. Summary luôn có flags
commercial_balances_only và accounting_not_reconciled.

Đề nghị phân loại kho đã được root giải quyết qua read bridge v2 commit57a2ed2.
Provider chuẩn inventory_summary nay trả core movement_breakdown tám thành phần;
HTTP stock-balances còn giữ local breakdown theo entry_type cho client cũ. Không
tự sửa shared DTO. Concrete provider export RecordsReadProvider(runtime,
principal) cùng module_manifest() tại cafe_fin.records.module; read permissions
được revalidate trong reader snapshot, không sửa module khác.

Wiring đề nghị: registered_modules() thêm records.module.module_manifest(); frontend
registry thay stub records bằng recordsModule từ features/records/index.ts.
Migrations được manifest mang theo; không patch central migration registry.

Theo yêu cầu capture chung của root: provider có public bind_connection(conn),
hoặc keyword constructor connection=conn. Caller cấp read-only Connection và
explicit SQLite BEGIN; records không mở/đóng connection đó. Mọi core DTO/method
giữ nguyên, actor được authorize trong snapshot. Root Source.capture bind records
và accounting vào đúng cùng conn; dùng chung cutoff nhưng mở2 readers riêng
không phải bằng chứng cùng snapshot. Code/usage chi tiết trong README.md.
