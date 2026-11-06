# Core original file transfer

Core có đường truyền file gốc riêng để command JSON limit2MiB không chặn workbook
lớn của lane accounting. Đây là opaque storage primitive, không parse/validate
Excel nghiệp vụ và không công bố dòng kế toán.

`POST /api/v1/files?category=workbooks` nhận nguyên binary body, MIME ở Content-Type,
filename UTF-8 percent-encoded ở X-File-Name, request key ASCII1–128 ở X-Request-Key.
Category còn có documents/imports/reports. Cần app session và local-user files.write;
CORS chỉ thêm đúng hai header upload này, không wildcard. Filename/path/control,
key và format metadata được kiểm trước khi đọc body. Không multipart/base64/JSON.

Giới hạn mặc định2GiB lấy từ FileStore.max_bytes. Content-Length vượt limit bị
chặn sớm; chunked body được đếm khi nhận và dừng ở ranh giới chunk. Spool tạm dưới
data-root/imports, không buffer file-size trong UI/state/middleware. Nhận/hash/copy
ngoài writer; put dùng transaction ngắn, atomic rename, audit/receipt và authorizer
kiểm role/version lại lúc commit. Spool/put hiện đọc hai lượt, cần tối đa khoảng
hai bản source đồng thời; preflight dung lượng dựa trên độ dài khi có và ENOSPC
vẫn được xử lý nếu ổ thay đổi. Không cam kết throughput trước benchmark.

Response FileDTO: id, sha256, size, category, original_name, media_type, created_at.
Không trả absolute path hay relative store key. `GET /files/{id}` lấy metadata;
`GET /files/{id}/content` xác minh actual handle trước HTTP200 rồi stream.
Accounting nhận file_id và gọi public FileStore để parse/stage trong job của mình;
đường upload nghiệp vụ không cần nới global JSON limit hoặc tự lưu nguồn lần hai.

Frontend shared uploadOriginal(File,category,requestKey) truyền native File body
trực tiếp, percent-encode tên, dùng memory session/Bearer, sizeguard2GiB và timeout
300s; không tự retry. Người gọi phải giữ request key qua retry không rõ kết quả.
Client chỉ đánh dấu connection healthy sau khi JSON/blob đã đọc hoàn tất; lỗi body
trả ApiError đã che nội dung và không báo lưu thành công.

Kiểm thực trước commit:

- 12 transfer tests PASS /5.01s, gồm sidecar HTTP thật với source ZIP tổng hợp
  >2MiB/Unicode, chunked retry cùng ID/hash, download nguyên byte, đúng1 metadata/
  workbook và0 imports leftovers; metadata/auth/origin reject trước body; giới hạn
  known/chunked; command JSON2MiB vẫn chặn; quyền thu hồi giữa upload chặn commit.
- Browser helper/mock tests và real-sidecar integration kiểm raw bytes không UTF-8,
  CORS, filename, source/stored/download hash, DTO, replay và conflict409 khi đổi
  nội dung cùng key. Final8 browser tests PASS /9.4s; typecheck/build PASS.
- Toàn core WIP86 PASS /35.68s, Ruff PASS. Snapshot sạch sẽ được ghi trong README
  handoff sau commit, không suy từ WIP hoặc fixture nhỏ ra benchmark triệu dòng.

Body-response tests còn kiểm malformed JSON/failed Blob stream, không healthy khi
body chưa xong,204,401 logout và không tự phát request thêm. Không thay UI nghiệp vụ.
