# Farm, công ty và hai luồng ghi nhận — frontend

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-farm-trade-ui\cafe_fin`.
Branch: `codex/cafe-fin-farm-trade-ui-20261107`, bắt đầu tại `ac34aac` do điều phối chỉ định. Commit SHA được báo trong bàn giao Git của lane.

## Phạm vi

- Đăng ký `/records/farms`, `/records/customers`, `/records/inbound`, `/records/outbound`; giữ `/records` và dành `/records/dashboard` cho `DashboardPage` do điều phối sở hữu.
- Farm: mã bốn ký tự viết hoa bất biến, chủ Farm/CCCD, hai mã vùng, lô trồng (mã lô tùy chọn), khảo sát mùa vụ/grade/tỷ lệ chín, địa chỉ/liên hệ/ngân hàng. Không đọc hoặc chuyển dữ liệu CRM cũ. Đại diện mặc định theo chủ Farm chỉ khi chưa có đại diện riêng.
- Công ty: tên, MST, giấy phép, liên hệ/đại diện, địa chỉ/liên hệ/ngân hàng. Bước đầu của đơn bán yêu cầu đủ tên/MST/người liên hệ. Cho sửa hồ sơ lịch sử giữ nguyên công ty đã ngừng sử dụng.
- Mua vào có Farm từng dòng, hàng tùy chọn, kg/bao/grade/giá, xe; bán ra có công ty và hàng từng dòng. Lưu đơn chưa tạo chuyển động kho.
- Chi tiết đơn đọc GET riêng sau lựa chọn từ list, có lịch sử/version/xóa mềm/khôi phục và danh sách phiếu kho + thu/chi liên kết có phân trang. Tạo phiếu kho **nháp** qua `RecordEditor`; ghi sổ/hủy qua API guard hiện hữu. Dòng đơn phải có hàng trước khi tạo phiếu kho. Mỗi lượt giao cần sửa lượng nháp theo thực tế; backend kiểm tổng giới hạn và tồn.
- Thu/chi có mã/ngày/đối tác/số tiền/phương thức/tham chiếu, cho sửa, xem lịch sử, xóa mềm và khôi phục. Không phê duyệt, không chuyển tiền, không cộng tự động vào Excel.
- URL giữ trang/tìm/sort/ngày/trạng thái và hồ sơ được chọn; route giữ chiều luồng. Ngày sai giữ trong form, không gửi API hoặc lưu URL. Danh sách 25 hồ sơ/trang; lookup Farm/công ty tìm server và phân trang 50 kết quả.
- Tính giá trị đơn bằng BigInt ở scale 5 (kg3 × giá2); tiền thực tế dùng Decimal string. Không float tính kg/tiền.
- Mutation dùng quyền `records.write`, version và request key; các phản hồi phiên cũ bị bỏ. Khi mất kết nối, JSON hỏng hoặc lỗi server chung chưa xác định kết quả, giữ nguyên form/payload/key và cho kiểm tra lại cùng yêu cầu. Không tự retry.
- `getFieldsValue(true)` sau validation, cùng allowlist payload, giữ các trường chưa hiển thị khi sửa. `RecordEditor` cũ giữ `trade_id` và profile Farm/công ty; không mở rộng union Resource với trade/payment.

## Kiểm thử

- PASS `npm ci --no-audit --no-fund`.
- PASS `npm run build` (TypeScript + Vite). Vite còn cảnh báo bundle >500 kB; không thêm dependency hoặc đổi shared build config.
- PASS `npx playwright test --config tests/crm-parity.config.ts --workers=1`: 8 browser contract tests, fixture tổng hợp. Bao gồm tạo Farm/lô không mã/khảo sát/mã bất biến/trùng, công ty và bước hoàn tất, hai luồng, không tự tạo kho, kho nháp, URL/list/detail GET, phản hồi tồn lỗi, thu/chi Decimal/version/history/delete/restore, unknown JSON và HTTP500 retry cùng khóa, quyền chỉ xem, giữ metadata/liên hệ ẩn và công ty lịch sử inactive.
- Bộ browser contract trên mock API chỉ chứng minh hành vi UI và payload, **không** chứng minh giao dịch ledger/SQLite. Lane backend chạy riêng browser API thật với source frontend được sao chép; điều phối nhận bằng chứng và commit test từ lane đó.
- Không chạy nghiệm thu GUI app Windows/bộ cài, không benchmark import lớn trong lane này.

## Tích hợp và giới hạn

Không migration, không dependency hoặc interface shared/core thay đổi. API additive đúng `crm-parity-v1.md`: `profile_kind`, FarmProfile, `/trades`, `/trade-payments`, `Entry.trade_id` và filters liên quan. `Dashboard.tsx` của điều phối chỉ được sao chép untracked để build; không nằm trong commit lane.

Trạng thái request chưa rõ được giữ trong phiên UI đang mở; reload ứng dụng hoặc đổi phiên cần kiểm lại danh sách/lịch sử trước khi tạo nghiệp vụ mới. Danh sách lịch sử/phụ tải theo trang; bảng dòng đơn tối đa 500 theo hợp đồng API. Chưa gọi production-ready.
