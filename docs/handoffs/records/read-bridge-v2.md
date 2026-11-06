# Records producer read bridge v2

Baseline tag foundation v1 vẫn trỏ e668355c227322994902f7e2e38ed7ffb19ff647.
Commit shared do root duyệt:57a2ed26bf70b8d6b3c4d2c7a30620d3d6b3033a, được cho phép
cherry-pick riêng thành local1cd2da5. Bốn file shared của commit đó là
backend/cafe_fin/core/contracts.py, docs/API_CONTRACT.md,
docs/handoffs/foundation/read-bridge-v2.md, tests/core/test_read_bridge_v2.py.
Lane không tự sửa chúng. Khi root ghép candidate mới chỉ cherry-pick commit lane
sau đó; root đã có shared source nên không áp lại local cherry-pick.

Public `RecordsReadProvider(...).inventory_summary(from_on, through_on, cutoff=...)`
trả core InventorySummaryDTO v2. Cả provider tự quản reader và provider đã
bind_connection(conn) đều có cùng kết quả/DTO. Root/reporting gọi method chuẩn,
không dùng ORM private hoặc cần dựa vào local `.breakdown` extension của HTTP.

| Entry type | Direction | Component v2 |
|---|---|---|
| receipt | in | purchased_kg |
| issue | out | sold_kg |
| production | out / in | production_input_kg / production_output_kg |
| transfer | in / out | transfer_in_kg / transfer_out_kg |
| adjustment | in / out | adjustment_in_kg / adjustment_out_kg |
| opening | in | adjustment_in_kg, flag opening_entries_in_adjustments |

Nguồn và chiều phải được nhận diện tường minh và dấu delta phải khớp chiều.
Không đoán mua/bán/return/reversal từ dấu kg hoặc tiền. Tám component không âm,
Decimal strings scale3, không có default-zero cho dữ liệu chưa biết. Khi toàn
bộ movement trong kỳ đã được nhận diện, scope đã biết không có movement kỳ đó
được tám số0 thực; tổng hợp luôn có đúng một breakdown cho mỗi items scope.
Không có scope thì version1 + tuple rỗng. Unknown type/direction/sign trong kỳ
giữ breakdown_version và movement_breakdown cùng null, flag
inventory_movement_classification_unknown; không công bố phần classification
biết được như thể đủ toàn bộ. Unknown trước kỳ chỉ đóng góp opening, không bị
diễn giải thành mua kỳ này.

Core v2 validator đối soát received/issued với từng component và closing với
opening+received-issued. Producer cộng Python integers, không float, SUM int64
hoặc Decimal context. Sản xuất có hao hụt; chuyển kho không thành mua mới.
Chỉ revision effective ở cutoff sinh effect; edit/cancel/delete/restore giữ
audit bất biến và loại bản không hiệu lực thay vì ghi component âm.

Không đổi mutation/schema/migration/dependency. Công nợ thương mại vẫn riêng,
không tạo accounting metrics, cash receipts/payments hoặc đoán ý nghĩa từ tên.
V2 chấp nhận payload v1; decoder v1 extra=forbid không đọc fields v2 mới (kể cả
null). Root phải ghép producer và consumer v2 cùng nhau, không tự gọi đây là
tương thích hai chiều. Reporting consumer và tích hợp accounting thật thuộc
root/lane reporting; records chỉ bàn giao producer và public snapshot reader.

Kiểm chứng final:187 core+records PASS (108+79) /76.74s, focused v2 producer10
PASS/5.06s. Browser thực v2 1 PASS/19.9s, typecheck/build/feature build/Ruff/
compileall/diff checks PASS. Một warning nền Starlette/httpx và warning chunk
shell>500KB vẫn giữ nguyên. Không sửa migration/dependency; không root wiring,
push/merge/tag. Native/clean-Windows và liên module reporting/accounting chưa
nghiệm thu trong lane này. Xem tests.md và ui.md cho lệnh và bằng chứng cụ thể.
