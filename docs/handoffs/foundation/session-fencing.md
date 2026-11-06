# Frontend session generation fencing

Sửa repro từ Điều phối trên commit `4133d9d`: response401 của A không được logout
B sau đổi phiên; response200/body/download của A không được trả vào B.

Zustand session có generation tăng và AbortController mới khi setBoot, login,
logout hoặc reset. State mới được công bố trước khi abort listener cũ chạy.
Không persist credential/controller; connection update không tự đổi generation.

API capture immutable session context ở lúc gọi, combine signal timeout/caller
với generation signal. Mọi ranh giới await fetch/JSON/blob đều kiểm generation,
trước khi đổi connection/logout và trước khi trả dữ liệu. Response cũ trả
ApiError STALE_SESSION; không thay token/user/connected của B. Upload giữ lỗi
stale, không đổi thành timeout và không tự retry.

App kiểm epoch cho native boot/start/auth/logout callbacks. Khi identity đổi,
cancel/clear query cache và remount authenticated subtree để bỏ draft/output
actor cũ. Document download kiểm owner generation sau await và ngay trước tạo
download link, kể cả khoảng callback rất nhỏ sau khi API đã resolve.

`frontend/tests/session-race.spec.ts` có2 tests browser dùng Zustand thật cùng
Promise/ReadableStream gates: 12 late-response cases401/200/204/network/error/
auth/boot/reset/upload/JSON/blob, signals bị abort, B giữ nguyên; một case UI giữ
response grid của B ở gate và chứng minh draft/cached private cells A đã biến mất
trước khi B nhận dữ liệu. Không thay bằng store giả hoặc chỉ test một helper.
Nếu chạy lại Node VM repro cũ, context cần browser-standard AbortController và
AbortSignal globals; browser tests thực đã có các API này.

Toàn frontend trước commit: **10 browser tests PASS /9.1s** với API sidecar thật
được bật, TypeScript/build PASS, diff check PASS. Bundle932.79KB/gzip305.06KB;
warning chunk>500KB vẫn là việc tối ưu sau đo, không phải lỗi compile.

Shared types bổ sung User.version và tách JobState generic khỏi ImportJobState,
có JobDTO gồm generation/counts/checkpoint. Đây là type contract trước baseline;
không đổi HTTP backend hoặc binary sidecar. Root sẽ ghi kết quả archive sạch của
candidate cuối trong README handoff. Không push, merge hoặc tạo tag.
