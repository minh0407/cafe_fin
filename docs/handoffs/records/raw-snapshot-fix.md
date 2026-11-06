# Fix borrowed snapshot sau raw SQL transaction control

QA root tìm thấy P2 sau c82044d: RootTransaction của SQLAlchemy không đổi khi
caller exec_driver_sql('ROLLBACK') rồi exec_driver_sql('BEGIN'). Bound reader
cũ có thể đọc snapshot mới sau writer khác đã commit, dù giữ nguyên wrapper.

Regression WAL thật đã RED trước fix: tồn10.001→15.003 và công nợ100.01→150.03
của writer connection khác xuất hiện qua stale provider. Fix records-only thêm
epoch observer per Connection, không chỉ so RootTransaction identity. Epoch tăng
với public SQLAlchemy transaction-control statements và commit/rollback events;
binding đã chụp epoch cũ trả READ_ONLY_SNAPSHOT_REQUIRED. Fresh bind được đọc trạng
thái mới, caller vẫn sở hữu connection/transaction.

SQL controls được nhận biết sau comments/BOM/semicolons, hỗ trợ execute(text())
và exec_driver_sql. Conservatively invalidate cả failed control/savepoint; không
chặn caller thực thi chúng. Cùng connection chỉ đăng ký một observer, mọi provider
(bind_connection hoặc connection keyword) cùng thấy epoch thay đổi. Connection
owner weakref ngăn tái dùng observer của wrapper cũ khi pool tái dùng DBAPI handle.
Không thay trace/authorizer callback của SQLite hoặc sửa core.

Guard còn vô hiệu hóa reader khi có PRAGMA setting attempt, tránh OFF→write→ON
của query_only trong cùng RootTransaction. Plain read PRAGMAs không bị vô hiệu hóa.
Boundary public SQLAlchemy facade và các giới hạn raw DBAPI được ghi rõ trong
snapshot-reader.md. Ngày through_on vẫn bao gồm ngày cuối, không đổi contract.

Không thay schema/migration/dependency/frontend, không root wiring hoặc push/merge.
File regression tests: tests/records/test_records_raw_snapshot.py. Sau fix52
focused tests PASS/25.44s; full records131 PASS/61.86s; Ruff/compileall/diff PASS.
Một warning nền Starlette/httpx vẫn có. Core/browser/build không chạy lại vì
không đổi core/schema/UI; các bằng chứng mốc c82044d được giữ riêng trong tests.md.
