# Capture records bằng connection snapshot do caller cấp

Theo yêu cầu bổ sung của điều phối sau candidate3e6f0a9. Snapshot binding không
đổi migration hoặc reader protocol; DTO hiện dùng read bridge v2 qua shared
commit57a2ed2 đã được root phê duyệt.

```python
from cafe_fin.records.module import RecordsReadProvider

records = RecordsReadProvider(runtime, principal)
with runtime.reader() as conn:
    conn.exec_driver_sql("BEGIN")
    bound_records = records.bind_connection(conn)
    # Root binds its accounting provider to THIS SAME conn as well.
    inventory = bound_records.inventory_summary(from_on, through_on, cutoff=cutoff)
    classified = inventory.movement_breakdown  # v2, nullable khi chưa biết nguồn
    receivables = bound_records.receivable_summary(as_of, cutoff=cutoff)
    # accounting_summary = bound_accounting.book_summary(...)
```

Constructor `RecordsReadProvider(runtime, principal, connection=conn)` cũng được
hỗ trợ. Factory bind_connection kiểm trạng thái và quyền ngay lúc bind. Mỗi lần
đọc đều revalidate quyền records.read trên đúng conn/snapshot đó. Các method trả
core DTO v2 (hoặc extension typed InventoryBreakdownDTO cho HTTP local detail); không lộ
private ORM, không tự mở runtime.reader khi đã được cấp connection.

Caller phải bắt đầu SQLite BEGIN thực, giữ PRAGMA query_only=1 và quản lý lifetime.
SQLAlchemy autobegin do PRAGMA đơn thuần chưa phải SQLite snapshot và bị từ chối.
Records không commit/rollback/close conn của caller, kể cả khi có lỗi hoặc lookup
không tìm thấy. Transaction kết thúc/connection đóng hoặc đổi sang transaction
mới phải tạo bound reader mới; lỗi READ_ONLY_SNAPSHOT_REQUIRED thay vì âm thầm
đọc snapshot khác. Không dùng conn/bound reader đồng thời trên nhiều thread.

Authorization trong snapshot phản ánh quyền tại snapshot capture. Mutation vẫn
dùng writer revalidation của core. Root nên giữ capture ngắn; không giữ read
transaction trong khi render/network/send hoặc chờ người dùng.

Test `test_records_shared_snapshot.py` dùng SQLite WAL file thật, second Database/
WriteCoordinator connection thật. Writer cập nhật records và synthetic probe cùng
transaction; bound records+probe giữ old snapshot trong khi fresh provider thấy
cặp mới dù cutoff cho phép bản mới. Các5 read methods, caller ownership, lỗi
read-only/BEGIN/ended/closed/rebound transaction và revoked actor được kiểm.
Probe tổng hợp không phải bằng chứng đã tích hợp accounting production. Root
vẫn cần Source.capture test records+accounting cùng conn sau khi ghép module.
