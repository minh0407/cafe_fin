# Candidate đầu: backend records và ledger

Baseline e668355c227322994902f7e2e38ed7ffb19ff647 tại tag
cafe-fin-foundation-ready-v1. Worktree
C:\Users\NC\.codex\worktrees\cafe-fin-records\cafe_fin, branch
codex/cafe-fin-records-20261106. Không push/merge/tag hoặc wiring shared.

Candidate này gồm toàn backend module records, migration v1 module-owned, typed
request/response/OpenAPI, public module_manifest/RecordsReadProvider và58 tests.
Frontend vẫn đang hoàn thiện/kiểm real browser và sẽ nằm commit tiếp theo.

PASS final58 records /24.91s; Ruff/compileall/diff check PASS. Có một warning nền
Starlette/httpx. Full core+records trước đợt bổ sung cuối PASS135 /57.76s
(86core+49records); không dùng count này thay final58 records. Xem tests.md cho
commands, matrix,2physical SQLite connections và test chưa chạy.

Money/weights persisted integer, nullable missing preserved; history/line/ref/
movement immutable including OR REPLACE. Mọi create/update/post/cancel/delete/
restore thông qua writer BEGIN IMMEDIATE với actor revalidation, receipt và audit.
Ledger kiểm toàn bộ chronological prefixes, hợp scope cũ/mới, gộp dòng trùng và
consume trước produce. Cân không tự đổi kho. Các summary cutoff đọc historical
revision đúng thời điểm và coverage entered_records_only.

Root có thể bind RecordsReadProvider(runtime,principal) theo core protocol ngay.
inventory_summary giữ DTO nền; inventory_breakdown là typed additive public
extension (InventoryBreakdownDTO), tách entry_type+direction cho báo cáo. Root
chốt additive DTO chung nếu muốn tất cả consumer qua cùng core protocol.
Xem shared-change-request.md; không cần thêm dependency.

Native desktop/installer NOT RUN trong candidate này; browser thật đang được
kiểm riêng. Chưa gọi đã tích hợp hoặc production-ready.
