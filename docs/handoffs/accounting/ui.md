# Bàn giao giao diện kế toán

- Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-accounting\cafe_fin`.
- Branch: `codex/cafe-fin-accounting-20261106`.
- UI subtask không commit/push theo yêu cầu điều phối. Không sửa registry, dependency, shared API hoặc file của lane khác. Không có migration UI.
- Dùng React 19 và `react-data-grid` `7.0.0-beta.64` đã pin; không thêm dependency.

## Tích hợp của điều phối

`frontend/src/features/accounting/index.ts` xuất `accountingFeature: FeatureModule`, route `/accounting`, permission `accounting.read`. Thay stub kế toán trong `frontend/src/app/registry.tsx` bằng export này:

```ts
import { accountingFeature } from '../features/accounting';
// Trong defineModules([...]): accountingFeature
```

Backend cần đăng ký `accounting.module.module_manifest()` ở registry chung. Harness thật đăng ký manifest trong Runtime riêng của test; không thay registry sản phẩm.

Quyền giao diện: `accounting.read` xem; `accounting.write` CRUD/xóa mềm/import/export; `accounting.configure` tạo sổ/schema; `accounting.restore` khôi phục. Admin hoặc `*` có đầy đủ. Backend vẫn là nơi kiểm quyền và phiên bản.

## Hành vi đã triển khai

- Sổ phân trang, ID cột ổn định, đổi tên hiển thị, thứ tự/kiểu/required/editable/precision/scale/choices/formula/freeze và min/max/max_length. Ngữ nghĩa ngày/thu/chi hoặc chiều+số tiền, tiền tệ, cột nhóm/so trùng/khóa nghiệp vụ có lựa chọn cột và JSON nâng cao. Cho sổ rỗng; không đoán ngữ nghĩa tiền.
- Grid server paging 200 dòng, search/sort/filter toàn tập trong hash URL, bộ tạo điều kiện lọc, vùng Shift+click/Shift+phím, TSV có quote/newline, clipboard tối đa 500 ô/100.000 ký tự. Native drag fill và nút điền vùng đều qua preview, chỉ tác động trang đã tải. Resize và freeze cột. Không chuyển tiền sang JavaScript Number.
- Nháp tối đa 500 ô thay đổi, lịch sử 20 bước, chỉ trong trang/actor/sổ hiện tại. Save cần xác nhận; hiển thị kết quả từng dòng. Thành công cập nhật baseline/version; dòng lỗi giữ nháp. Conflict hiển thị lúc tải/bản nháp/hiện tại qua GET row ID, không tự ghi đè. Thêm dòng giữ request key khi retry cùng intent. Xóa mềm/khôi phục kiểm version và quyền; có `deleted=true` để tìm lại dòng đã xóa.
- Hints required/choice/syntax/scale/length không làm tròn; backend quyết định validation đầy đủ. Lỗi nguồn có tọa độ, tooltip và điều hướng. Trước/sau thu chi là chuỗi chính xác từ backend, tách đơn vị tiền, có cờ dự kiến.
- Guard beforeunload và rời hash route. Listener một lần lúc import feature được đăng ký trước listener shell để shell không unmount nháp trước khi hỏi. Đổi actor/generation xóa nháp, editor, selection và cache actor cũ; request loop cũ dừng trước khi gửi lệnh tiếp theo bằng actor mới. Query cache `gcTime: 0`, key có actor/generation, sổ, schema/data revision và tham số trang/bộ lọc khi thích hợp.
- Import upload gốc qua core FileStore, profile CSV/XLSX/XLSM/sheet/header/range có cấu hình, mapping theo ID cột, lưu/dùng lại hồ sơ. Job được liệt kê theo trang 50, đóng/mở lại không mất patch đã lưu/job. Staging trang 200, nguồn gốc/typed/patch riêng, patch chỉ gửi ô editable thay đổi và expected row revision.
- Validate toàn job; lỗi/ứng viên trùng có paging; lựa chọn keep/skip từng ứng viên và mặc định cho phần chưa quyết định. Confirm pin exact staging/mapping/decision revisions + validation token + `valid_rows_only`; không gửi triệu ID. UI phân biệt pending durable và published; chỉ khi published count tăng mới tự tải lại sổ/tổng. Cancel/resume theo trạng thái worker, không coi pending là nhập thành công.
- Tải gốc giữ tên/đuôi tệp, hiển thị SHA-256/byte. Xuất sổ CSV/XLSX là job dẫn xuất; xuất toàn lỗi còn mở qua job riêng, tải lỗi trang hiện tại TSV tối đa 100 cũng có nhãn rõ. Không thay tệp macro gốc hoặc cam kết fidelity đầy đủ.

Các file UI chính: `AccountingPage.tsx`, `WorkbookGrid.tsx`, `ImportWorkspace.tsx`, `SchemaEditor.tsx`, `drafts.ts`, `navigation.ts`, `client.ts`, `types.ts`, `accounting.css`, `index.ts` dưới thư mục feature accounting.

## Kiểm chứng

Chạy từ worktree root:

```powershell
npm --prefix frontend run typecheck
frontend/node_modules/.bin/playwright test --config=tests/accounting/ui/playwright.config.ts
frontend/node_modules/.bin/playwright test --config=tests/accounting/ui/real.config.ts
```

- PASS TypeScript strict, không skip module errors.
- PASS 9 test helper/browser mock: TSV quoted multiline và chuỗi tiền lớn; từ chối vượt page/500 ô/read-only atomically; encode search/filter punctuation; hint scale; preview/undo/redo/save version; conflict so sánh; reopen import/pin token; guard hash và actor/cache/permission; native drag-fill + explicit range fill không ghi trước preview/save.
- PASS 1 luồng browser thật, dùng HTTP/auth/CORS/SQLite/FileStore/serialized writer/job runner thật. Không intercept API: tạo sổ và schema revision bằng UI; thêm tiền chuỗi lớn; upload CSV tổng hợp 3 dòng; mapping; patch staging; validate 1 lỗi; xuất toàn lỗi qua job; tải original kiểm SHA-256 bằng byte; confirm 2 hợp lệ; đóng/mở job; sửa lỗi rồi validate/confirm tiếp chỉ thêm 1 dòng; tổng sổ có đúng 4 dòng kể cả dòng manual; sửa tiền bằng bàn phím/version; xóa/hiện deleted/khôi phục; export CSV giữ tiền chính xác và loại raw lỗi.
- Harness thật chỉ thay entry module phía browser để mount feature trong provider chuẩn và bootstrap một tài khoản tổng hợp. `serve.py` dùng production sidecar main với Runtime subclass đăng ký accounting. Dùng allowed origin `http://127.0.0.1:1420`; không đổi policy CORS hoặc mock API. Config từ chối port bận, không giết/reuse server lane khác. Config mock dùng 1447.
- Ảnh QA từ dữ liệu tổng hợp được render ở `frontend/test-results/accounting-real/real-real-accounting-API-s-0c1b5-e-errors-and-derived-export/accounting-real.png` (test output, không commit).
- `npm --prefix frontend run build` PASS ở baseline registry hiện tại; registry chưa wiring accounting nên bundle sản phẩm đầy đủ phải chạy lại sau tích hợp. Browser harness thật đã tải/biên dịch thực sự feature, không chỉ typecheck.

## Giới hạn còn lại / tích hợp

- Shared `ApiError` hiện bỏ `error.details`. UI đã đọc optional `details.issues` khi có, đồng thời có hints chuỗi cơ bản và nguồn lỗi staging. Điều phối cần patch shared constructor/pass-through như `shared-change-request.md` để hiển thị mọi chi tiết backend cho validation trực tiếp trên dòng sổ.
- NOT RUN bộ cài/native Tauri/WebView2/đóng cửa sổ Windows; browser tests không thay release gate native.
- Không lấy fixture CSV nhỏ làm bằng chứng hiệu năng 50k/500k/1m. Các benchmark lớn/kill-resume là bằng chứng backend/điều phối riêng; UI chỉ giữ page và vùng có giới hạn. Không tuyên bố thời gian import triệu dòng hoặc production-ready.
- Nháp chưa save không bền qua crash/đăng xuất; guard bảo vệ rời trang thông thường. Patch staging đã save và job là dữ liệu bền phía backend.

## Delta bridge v2: ý nghĩa chỉ tiêu và công thức mẫu

- SchemaEditor thêm hai lựa chọn tùy chọn `semantics.metric_meanings.income` / `expense`: `cash_receipts`, `cash_payments`, `cash_receipt_deposits`, `cash_payment_deposits`, `noncash_offsets`, `other`. Mặc định chưa phân loại (`undefined`), clear xóa trường tương ứng; không suy ý nghĩa từ tên/ID cột. Chiều không khai báo vẫn giữ nguyên trạng thái vắng mặt, không tự thêm chiều hay số 0.
- Cảnh báo phần chưa phân loại giải thích ảnh hưởng chỉ tiêu dòng tiền báo cáo ngày; không chặn lưu cấu hình hoặc CRUD sổ.
- Help công thức phân biệt mẫu cột sổ cùng dòng dùng `A{row}` / `B{row}` với phạm vi nguồn tệp. Mẫu tham chiếu cố định/chéo dòng bị backend từ chối `FORMULA_BOOK_SCOPE`.
- Delta chỉ sửa SchemaEditor và handoff. PASS `npm --prefix frontend run typecheck`; kiểm tra code các nhánh mặc định/clear không thêm ý nghĩa hoặc chiều khác. Không lặp toàn bộ E2E dữ liệu cho thay đổi cấu hình nhỏ này; kết quả browser trước đó giữ nguyên phạm vi chứng minh.
