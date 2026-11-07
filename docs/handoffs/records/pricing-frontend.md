# Bàn giao giao diện bảng giá — increment 13

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-pricing-ui\cafe_fin`.
Branch: `codex/cafe-fin-pricing-ui-20261107`. Baseline được điều phối giao: `e9cb099`.
Commit SHA được gửi riêng khi bàn giao; không push hoặc merge nhánh khác.

## Phạm vi

- Thêm route module `/records/prices`, liên kết CommerceNav và `PricesPage`: danh sách 25 dòng/trang, tìm/lọc/sort phía server, xem chi tiết, tạo/sửa/ngừng áp dụng, lịch sử, xóa mềm/khôi phục có version/request key. Ngày/nhóm/hàng bất biến khi sửa; mã/tên do server sinh.
- Preset mua tươi/chế biến theo Grade5, preview đủ 5 Grade qua API; giải thích giảm 90% và làm tròn 2 chữ số ở từng bước. Preset bán là giá cố định và bắt buộc hàng; chọn lại phương pháp khi cần.
- Đơn mới mặc định `daily`, đầu vào `purchase_fresh`, đầu ra `sale`. Đơn giá chỉ đọc sau quote đúng ngày/hàng/Grade, tổng dòng tính từ chuỗi decimal qua BigInt, giữ đủ 5 số lẻ. Thiếu giá/Grade không cho lưu và mở được form cấu hình bảng giá ngay trong đơn, giữ bản nháp/phiên đăng nhập.
- Đơn cũ mặc định manual khi thiếu field mới. Daily snapshot đã lưu không tra lại khi mở hoặc sửa kg/bao/ghi chú. Nút “Lấy lại giá mới” chủ động thay snapshot; đổi ngày nghiệp vụ đồng bộ ngày giá và bỏ snapshot cũ. Chi tiết/lịch sử hiện nhóm/ngày/Grade/phiên bản giá.
- Mỗi Form.List key sở hữu chuỗi request riêng; cleanup layout, scope/date/grade/product/session checks bỏ phản hồi cũ, kể cả xóa dòng đầu khi dòng còn lại có cùng tiêu chí nhưng giữ giá cũ.
- `CommerceFormModal` đóng băng cả form và tất cả nút khi lưu/chưa rõ kết quả; snapshot payload được structuredClone trước khi gửi. Retry unknown dùng nguyên body và request key. Quote/preview không ghi dữ liệu vào form đang bị khóa.
- Payload trade whitelist toàn bộ command fields và giữ metadata cũ không hiện trong dòng (farm, bao, ghi chú, ngày giờ, người thực hiện, liên kết). Không gửi metadata entity chỉ đọc.

Files: `frontend/src/features/records/{PricesPage,TradePriceFields,TradeEditor,TradeDetail,CommerceShared}.tsx`, `commerceTypes.ts`, `index.ts`; `frontend/tests/pricing.spec.ts`, `pricing.config.ts`, hai điều chỉnh legacy create trong `crm-parity.spec.ts` chọn manual rõ ràng. Không sửa dependency hoặc file app dùng chung. Không có migration frontend.

## Kiểm thử

- PASS `npm ci` trong frontend worktree riêng: 148 packages, audit 0 vulnerabilities.
- PASS `npm run typecheck`.
- PASS `npm run build`: TypeScript và Vite production build. Có cảnh báo bundle lớn hơn 500 kB, cùng kiến trúc bundle hiện hành; không coi đây là bằng chứng hiệu năng.
- PASS `npx playwright test --config tests/pricing.config.ts`: **23/23** trong 36,8 giây; gồm 15 pricing cases và 8 hồi quy Farm/công ty/mua bán/thu chi/kho. Fixture hoàn toàn tổng hợp, mock API; không chứng minh transaction/authority backend.
- Pricing cases: preview 5 Grade; reset form mới; giá bán độc lập/bắt buộc hàng; khóa scope/version/history/delete/restore; filter paging/navigation outgoing; default sale + tổng lớn chính xác; purchase Grade-required; thiếu giá + cấu hình inline; giữ snapshot khi sửa kg; manual cũ + refresh; slow criteria/date; removed row + identical scope frozen survivor; PRICE_CHANGED cần refresh; unknown 200/500 giữ chính xác payload/key/khóa tất cả nút; session change bỏ quote cũ.
- PASS `git diff --check`.
- NOT RUN lint riêng: package không có script lint; TypeScript strict được kiểm qua typecheck/build.
- Real API/SQLite, tích hợp app sidebar và Docker được điều phối/backend chạy riêng. Frontend lane không truy cập DB/volume của người dùng hoặc app Docker hiện hành.

## Tác động interface và giới hạn

Theo đúng `pricing-v1.md`: thêm PriceBoard, PriceSnapshot và optional pricing fields trên TradeLine; không đổi DTO bridge contracts/reporting. `CommerceFormModal` nhận thêm resource price-boards và khóa dùng trong module records. Shared app sidebar do điều phối sở hữu.

Không thêm thư viện, không eval hoặc float tiền/kg. Giá server vẫn là thẩm quyền; UI chỉ hiển thị quote/preview đã xác nhận. Chưa gọi production-ready; nghiệm thu API thật, Docker và bản Windows thuộc các gate tích hợp/phát hành.
