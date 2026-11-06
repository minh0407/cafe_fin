# API recovery và module job boundary

Đã sửa ba repro do Điều phối audit trên snapshot `976475c`.

## Download

API mở FileStore.read và xác minh size/hash trên chính handle sẽ stream **trước**
khi tạo HTTP response-start. Tệp thiếu/hỏng trả CoreError JSON409 có request ID,
không gửi200 rồi gãy stream. VerifiedFileResponse đóng ExitStack ở finally cho
cả trường hợp client ngắt trước khi generator bắt đầu; generator cũng đóng khi
kết thúc. Không giữ toàn file trong RAM hoặc giữ writer lúc hash/read.

## Export retry và crash

Request xuất mẫu ghi một prepare receipt chứa canonical immutable snapshot trước
khi render. Mỗi format thành công có receipt FileStore riêng. Retry kiểm receipt
đó và xác minh file trước khi quyết định render; không render lại file đã commit
chỉ vì aggregate receipt chưa kịp lưu. Aggregate chỉ công bố khi không có format
lỗi; lỗi một format trả kết quả phần thành công và cho retry format lỗi với cùng
snapshot/key. Word đã lưu không bị mất khi PDF hoặc final receipt lỗi.

Retry aggregate đã có cũng chạy transactional authorizer, không dùng cached
result để vượt role/version bị thu hồi. Các bước CPU/render/file I/O đều ngoài
writer; receipt và metadata vẫn trong transaction ngắn.

## Handshake

HTTP server chạy trong thread do main kiểm soát; main chỉ phát ready sau
`server.started` (ASGI lifespan/recovery/startup và listener đã thành công).
Startup failure/SystemExit được chuyển thành error envelope đã che chi tiết,
không phát ready lạc quan. Deadline backend15s nằm trong deadline Tauri20s.
stdin shutdown/EOF và cleanup vẫn đóng server/jobs/writer/root lock.

## Module extension và HTTP quyền

Manifest có job_handlers và on_startup để lane thêm job/hook mà không sửa core.
Hook thấy core jobs RECOVERABLE trước worker. Generic HTTP job mutations chỉ là
proof foundation.sample. Module phải có typed/validated endpoint để xác nhận
payload/snapshot/quyền trước khi gọi JobService; đăng ký handler không biến raw
generic jobs.write thành quyền chạy mọi module. Status thêm check module.read.

## Kiểm chứng

`tests/core/test_api_recovery.py`:5 PASS qua sidecar subprocess và HTTP loopback
thật. Hai case tệp thiếu/hỏng409; inject503 final receipt sau2 file commit rồi
retry giữ2ID/hash và không gọi renderer; os._exit86 sau DOCX rồi restart cùng DB
giữ ID và snapshot ban đầu dù provider snapshot thay đổi; Runtime.start OSError
chỉ trả error/exit1, không ready. Không sửa snapshot audit của Điều phối.

Module registration4 tests và HTTP job boundary3 tests PASS. Toàn core tại lượt
trước commit này: **74 PASS /29.15s**, Ruff PASS, một httpx/Starlette deprecation
warning. Root sẽ ghi kết quả snapshot Git sạch của candidate trong README handoff;
không dùng số test WIP này để tuyên bố một commit chưa có đủ dependency đã pass.

Các fixes không tạo installer, không giải quyết Windows sạch/DOCX visual/iconv
provenance; các gate đó vẫn giữ nguyên. Không push/merge/tag.
