# Phân công file và quy trình tích hợp

## Mốc triển khai

1. Điều phối publish bộ yêu cầu `cafe-fin-spec-v1`.
2. Prompt 00 tạo nền tảng trên branch riêng từ tag trên; bàn giao commit, chưa push.
3. Điều phối review/test/tích hợp và tạo `cafe-fin-foundation-ready-v1` bất biến.
4. Prompt 01, 02, 03 chạy song song từ chính tag foundation. Prompt 04 có thể làm sau khi type contract của records/accounting được freeze; kiểm tích hợp sau các module.
5. Điều phối ghép module, chạy liên luồng, tạo mốc `cafe-fin-integration-ready-v1` khi đủ điều kiện.
6. Prompt 05 đóng gói và nghiệm thu trên mốc integration; điều phối xử lý findings, push và thông báo kết quả thực tế.

Không tạo tag READY nếu còn điều kiện bắt buộc chưa kiểm. Tag chưa có thì báo đang chờ điều phối, không tự đánh dấu READY hoặc đổi sang HEAD tùy ý.

## Allowlist

| Lane | Được sửa | Ngoài phạm vi |
|---|---|---|
| foundation | `backend/cafe_fin/core/**`, backend entrypoint/registry, `frontend/src/app/**`, `frontend/src/shared/**`, `desktop/**`, root tool/config/dependency manifests, core tests, shared contract docs, `docs/handoffs/foundation/**`, `docs/adr/**` và module stub ban đầu | Không tự triển khai stock, contracts hoặc accounting production |
| records | `backend/cafe_fin/records/**`, `frontend/src/features/records/**`, `tests/records/**`, `docs/handoffs/records/**` | Không sửa core auth/jobs, app registry, dependency chung hoặc module khác |
| contracts | `backend/cafe_fin/contracts/**`, `frontend/src/features/contracts/**`, `tests/contracts/**`, `docs/handoffs/contracts/**` | Không sửa records/accounting, data root hoặc shared renderer policy ngoài module |
| accounting | `backend/cafe_fin/accounting/**`, `frontend/src/features/accounting/**`, `tests/accounting/**`, `docs/handoffs/accounting/**` | Không sửa stock, hợp đồng, registry, root package/lock hoặc core job state lén |
| reporting | `backend/cafe_fin/reporting/**`, `frontend/src/features/reporting/**`, `tests/reporting/**`, `docs/handoffs/reporting/**` | Không sửa dữ liệu hoặc private ORM của records/accounting; không tự bật gửi thật |
| packaging | `desktop/**`, `scripts/packaging/**`, `tests/desktop/**`, `docs/handoffs/packaging/**`, `docs/release/**` | Sau integration mới sửa; không tự đổi ngữ nghĩa domain để làm smoke pass |
| điều phối | File chung, đăng ký module, tích hợp migrations/dependencies, CI, SPEC/ADR/contract, docs/prompts, tags và push | Giữ dữ liệu thật ngoài Git; không ghi đè sửa của lane |

Mỗi module đặt migration trong thư mục mình, có module prefix và dependency manifest. Foundation cung cấp runner; lane không tự sửa central version table hoặc migration của lane khác.

## Giao thay đổi chung

Lane cần dependency hoặc field chung thì ghi đề nghị tại `docs/handoffs/<lane>/shared-change-request.md`: lý do, file, diff dự kiến, tác động consumer và test. Điều phối áp thay đổi trên baseline có kiểm soát rồi thông báo SHA/tag mới. Không commit file chung ngoài allowlist chỉ vì build lỗi.

## Bàn giao và Git

Mỗi chat làm branch `codex/cafe-fin-<lane>-<unique>` trên checkout/worktree riêng, không cùng sửa checkout repo gốc của điều phối. Khi tool Codex hỗ trợ, dùng list_artifacts/create_worktree; branch mặc định detached sau tạo phải được đặt tên trước commit. Không tạo nhiều worktree không cần thiết hoặc để cùng một branch bị checkout hai nơi.

Chat triển khai commit phần mình; gửi đường dẫn worktree, branch, SHA, diff summary, migrations, test lệnh/kết quả và unresolved items. Không push, merge hoặc force. Điều phối tích hợp commits từ local refs hoặc patch có thể review; chỉ push nguồn đã kiểm sang `minh0407/cafe_fin`.

Handoff không bao gồm DB thực, Excel thực, credential hoặc token. Dùng fixture tổng hợp/generator cho triệu dòng; không commit file triệu dòng.

## Các vùng rủi ro phải kiểm liên luồng

- Idempotency, optimistic version, audit và transaction stock không âm.
- Decimal/scale và thời gian nhất quán giữa records, contracts, accounting và reporting.
- Stage revision, partial import visibility, counts, resume và chunk idempotency.
- Giữ Excel gốc có macro byte-for-byte; tệp dẫn xuất không tự nhận đầy đủ fidelity.
- Backup/restore, move data root và job resume khi sidecar crash.
- Bộ cài Windows sạch và PDF tiếng Việt không phụ thuộc máy phát triển.
- Sender không bịa kết quả, không gửi dữ liệu thật khi chưa cấu hình/ủy quyền gửi cụ thể.
