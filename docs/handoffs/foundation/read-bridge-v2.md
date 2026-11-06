# Read bridge revision 2

Thay đổi do điều phối sở hữu sau `cafe-fin-foundation-ready-v1`, theo đề nghị reporting/records. `core.contracts.CONTRACT_VERSION=2`; không đổi API namespace, migration hoặc các trường cũ. Producer/consumer được cập nhật cùng qua commit điều phối, không đổi tag baseline.

V2 chấp nhận payload v1 nhờ default `None`. Chiều ngược lại không đảm bảo: v1 `extra='forbid'` sẽ từ chối field v2 mới, kể cả null. Không gửi dữ liệu v2 cho decoder v1 và gọi đó là tương thích hai chiều.

## Kho

`InventorySummaryDTO` thêm `breakdown_version: Literal[1] | None` và `movement_breakdown: tuple[InventoryMovementSummaryDTO,...] | None`. Hai trường cùng null khi chưa biết phân loại; không tạo số 0 giả. Producer thêm validation flag khi không cung cấp được nghĩa nguồn. Version 1 yêu cầu đúng một dòng trên mỗi `(warehouse_id,product_id)` trong `items`, không thừa/thiếu/trùng scope, cùng period/cutoff của summary. Tuple rỗng chỉ hợp lệ khi không có scope nào.

Mỗi breakdown line có đủ tám Decimal strings kg không âm: `purchased_kg`, `sold_kg`, `production_input_kg`, `production_output_kg`, `transfer_in_kg`, `transfer_out_kg`, `adjustment_in_kg`, `adjustment_out_kg`. Không có default zero; producer phải xác định thật từng thành phần.

- received = purchased + production_output + transfer_in + adjustment_in.
- issued = sold + production_input + transfer_out + adjustment_out.
- closing = opening + received - issued.

DTO kiểm đối soát từng scope bằng Python integer scale 1000, không float/int64 SUM/Decimal context làm tròn. Không ép production input bằng output (có hao hụt). Transfer chỉ triệt tiêu khi xét đủ cả kho nguồn và đích. Mỗi tác động ledger có đúng một nhóm, không cộng sản xuất/chuyển kho thành mua mới.

Phân loại reversal/return không được đoán từ dấu tiền/kg. Báo cáo state hiện hành có thể loại các effect đã bị hủy theo ledger version đúng cutoff; audit vẫn giữ lịch sử. Nếu producer chưa diễn giải được một movement/reversal/return, giữ toàn breakdown null và flag thay vì coi đó là mua mới hoặc ghi component âm. Không thêm hold/QC/phê duyệt.

## Tiền kế toán

`MappedBookMetricDTO.meaning` optional, một trong:

| Meaning | Ngữ nghĩa |
|---|---|
| `cash_receipts` | Tổng tiền thực thu đã ghi nhận theo mapping của sổ |
| `cash_payments` | Tổng tiền thực chi đã ghi nhận theo mapping của sổ |
| `cash_receipt_deposits` | Tiền cọc thu, tập con của cash_receipts nếu tổng đó có mặt |
| `cash_payment_deposits` | Tiền cọc chi, tập con của cash_payments nếu tổng đó có mặt |
| `noncash_offsets` | Đối trừ phi tiền, không cộng thành thu/chi |
| `other` hoặc null | Chỉ tiêu khác/chưa xác định, không tự diễn giải từ key |

Các known meanings có tổng không âm và tối đa một metric cho mỗi meaning trong một sổ/kỳ. Cọc không vượt tổng tương ứng khi cả hai cùng có. Cọc không được cộng thêm lần nữa vào tổng thu/chi. Không cộng tiền giữa các sổ hoặc mặc định cộng với CRM. Nhiều cột tiền cùng nghĩa được producer tổng hợp đúng một tổng, sau xác nhận mapping. Chỉ key tên `income`, `expense`, `deposit` hoặc `offset` chưa chứng minh ý nghĩa dòng tiền.

Producer chỉ tổng hợp dòng PUBLISHED, không tính pending; thiếu liên kết CRM không phải lỗi kế toán. Consumer hiển thị nhãn theo meaning đã biết; null/other vẫn xem local với flag, không tự điền vào tin nhóm như tổng thu/chi.

## Snapshot và wiring

Root bind concrete public records/accounting readers trong cùng một SQLite read transaction để capture báo cáo. Cùng timestamp cutoff nhưng tự mở hai reader không đủ chứng minh atomic snapshot. Lane cung cấp connection-bound public helpers; reporting không đọc private ORM. DTO không tự thực hiện query hoặc tạo audit/tiền/kho.

Tests `tests/core/test_read_bridge_v2.py` kiểm mua/sản xuất/chuyển/điều chỉnh, thiếu/trùng scope, đối soát từng chiều, missing-vs-zero, aggregate vượt int64, typed meaning, cọc là subset và mapping bắt buộc. Test DTO không thay integration test ledger/provider/reporting thật.
