# Tự động giá nhập nhân xô theo ngày 14

Người dùng chỉ định dùng lại cơ chế lấy giá thị trường của CRM, xác nhận chỉ tự động giá nhập nhân xô; giá quả tươi tiếp tục nhập tay và giá bán cài riêng. Baseline `be1b696`, contract `fc7f03c`; backend tích hợp `8803ce0`/`2b898ef`, UI `e9d4bbf`, browser API thật `b5078f4`, relay và tích hợp chung `59013b5`, sửa import lint `c228403`. CRM cũ chỉ được đọc source; không đọc/chuyển DB hoặc sửa source cũ.

## Hành vi và giới hạn nguồn

- Nguồn cố định [Bảng Giá Nông Sản](https://banggianongsan.com/bang-gia-ca-phe/), Robusta nhân xô Gia Lai, VND/kg. Port parser và quy tắc ngày/Grade từ CRM, không mang ORM, PostgreSQL, Celery hoặc DB cũ sang. Chỉ chấp nhận giá có ngày nguồn đúng ngày Việt Nam; Grade5 từ nguồn rồi suy từng Grade thấp hơn bằng 90%, HALF_UP hai số lẻ, dùng Decimal/integer cents.
- Collector kiểm định kỳ khi app chạy, tối thiểu 5 phút giữa lượt tải; BLOCKED chờ một giờ, 429 tôn trọng Retry-After. Có bật/tắt và kiểm tra ngay theo quyền, version, request key; kiểm tra ngay không vượt cooldown. Không chạy khi máy/app tắt. GET trạng thái không ghi DB.
- Chỉ tạo bảng chung `purchase_processed` một lần/ngày. Không ghi đè bảng nhập tay, bảng đã ngừng/xóa hoặc bảng tự động đã áp dụng. Bảng tự động chỉ đọc; evidence giữ URL/ngày/giá/thời điểm tải/vùng/hàng/đơn vị/parser/hash HTML và liên kết board/version. Không sửa snapshot giá đơn cũ, không tạo tiền/kho hoặc liên kết dòng kế toán.
- Migration records v2 bổ sung ba bảng settings/days/evidence và trigger bảo vệ evidence; v1 không đổi. Claim/fetch/finalize tách giao dịch, mạng ngoài writer; recheck quyền/cấu hình/ngày/lease trước ghi. Bảng + revision + evidence + audit + trạng thái APPLIED cùng transaction.
- Direct HTTP chỉ host/URL đã chốt, xác minh TLS và IP public, không redirect/URL tùy ý/JS, tối đa 2 MiB UTF8 và deadline tổng 8 giây. DNS helper bị giới hạn một slot, không giữ DB/runtime; đóng runtime không đợi OS DNS treo. Socket kiểm deadline từng lần đọc để chặn slow-drip.
- Docker có relay riêng chỉ GET nguồn cố định, không mount dữ liệu/bí mật hoặc publish port. Backend vẫn chỉ ở mạng internal. Relay giới hạn header/request 10 giây, 8 client và 1 fetch, trả lỗi allowlist; `/health` không tải nguồn. Không CAPTCHA bypass, browser impersonation hoặc proxy tùy ý.

Nguồn thật ngày 07/11/2026 trả HTTP403 hoặc HTTP200 chứa challenge trên Windows; parser trả **BLOCKED**. Lượt qua relay Docker cũng BLOCKED. Chưa có báo giá thật hiện tại được chấp nhận hoặc tự áp dụng. App hiện lý do/thời điểm kiểm lại và giữ nguyên giá đã có; không dùng giá từ web tool, HTML fixture, giá hôm qua hoặc số 0 làm dữ liệu thật. Tự động áp giá được chứng minh bằng fixture tổng hợp qua parser/service/timer/API/SQLite thật, không phải bằng chứng nguồn công khai đang hoạt động.

[Contract](../handoffs/records/market-v1.md), [backend](../handoffs/records/market-backend.md), [UI và browser thật](../handoffs/records/market-frontend.md).

## Kiểm chứng

Môi trường Windows/Python3.12 venv, Node/Chromium theo lockfile; file-backed SQLite WAL thật. Docker Desktop Linux amd64, Python3.12.16/SQLite3.53.1. Fixture tổng hợp; các suite thông thường đặt `CAFE_FIN_MARKET_NETWORK=0`, chỉ bộ market synthetic và smoke nguồn thật bật có chủ đích.

| Gate | Kết quả |
|---|---|
| Toàn backend `python -m pytest -q` | PASS1.547/759,25s; một cảnh báo Starlette/httpx có sẵn |
| Focused market + relay | PASS 54/54 /31,85s, gồm 46 parser/transport/service/lifecycle và 8 loopback socket relay |
| Main browser | PASS 99; ca opt-in real API chạy riêng PASS1/1 /19,0s |
| Market browser API/timer/SQLite thật, chỉ transport tổng hợp | PASS2/2 /38,9s; lane PASS2/2 /39,3s |
| Market/pricing/CRM browser lane | PASS40/40, gồm17 ca market |
| Frontend typecheck/build, Docker ba image, Ruff/compileall/diff | PASS; cảnh báo bundle Vite lớn có sẵn |
| Docker HTTP/restart/production browser | PASS toàn bộ auth/guards, farm/company/trade/payment/dashboard, bảng giá/giá đơn, live market BLOCKED, import/report/contract, persistence và production browser |

Browser API thật xác minh timer hai lượt chỉ một fetch; APPLIED đúng ngày/provenance/năm Grade và readonly, bật/tắt tăng version, bảng theo hàng và đơn cũ giữ nguyên giá. Challenge rồi nguồn hôm qua lần lượt BLOCKED/STALE_SOURCE, không board/snapshot; bảng thủ công giữ CRUD. Relay socket tests dùng loopback thật kiểm route/header/verb, lỗi đã lọc, giới hạn body, concurrency, network disabled và header chậm.

Lệnh focused: `python -m pytest tests/records/test_market.py tests/records/test_market_transport.py tests/preview/test_market_relay.py -q`. Browser market thật: `node frontend/node_modules/@playwright/test/cli.js test --config tests/records/browser/playwright.config.mts market.spec.mts` với test Python/port riêng theo handoff. Main browser: `npm test`, sau đó ca opt-in với `CAFE_FIN_REAL_API=1`. Docker smoke: `python tests/preview/docker_smoke.py --project cafe-fin-preview-smoke-market-final-20261107 --browser`, chỉ chạy trên project tổng hợp có volume mới, không chạy vào volume người dùng.

## Nâng cấp localhost

Sau Docker smoke PASS, đã dừng dịch vụ, sao lưu nhất quán volume đang dùng và xác minh hash từng file/archive ngoài repo. Bản sao lưu `C:\Users\NC\AppData\Local\CafeFinPreviewBackups\market-20261107-124707`, archive SHA256 `058f12295c879ed64f7a0450c2ee7e8c3d5f847951246e04a1cf95742a558422`. Không đọc dữ liệu nghiệp vụ hoặc commit DB/backup/manifest.

Promote đúng ba image đã kiểm vào project `cafe-fin-local-preview`, giữ nguyên volume `cafe-fin-local-preview_preview-data`; backend/relay healthy. HTTP/JS/bootstrap/health xác nhận UI mới và `setup_required=false`, không đăng nhập hoặc đọc nội dung nghiệp vụ. Kiểm metadata container thật xác nhận image ID, nonroot/read-only/capabilities, volume cũ, backend internal, relay không data mount và chỉ gateway publish loopback. URL **http://127.0.0.1:1420**; Ctrl+F5 và đăng nhập lại. Smoke dùng project tổng hợp riêng `cafe-fin-preview-smoke-market-final-20261107`, đã dừng sau kiểm thử, giữ volume.

Trong lượt tạo project smoke cuối, Docker báo hết address pools vì các network của project smoke cũ còn tồn tại. Chỉ `down` hai project smoke market/pricing đã dừng, giữ nguyên volumes, rồi chạy lại thành công; không prune toàn máy hoặc xóa dữ liệu người dùng. Log tổng thể được lưu local ngoài Git để không mất bằng chứng khi session kết thúc.

Ba image đã build/kiểm thử:

- Backend `sha256:0e79bfa46dbc601cdaa65f3be6ab7100410bee70c67ab893b25bc59f208d21bd`.
- Gateway `sha256:210a293edf3ff8a4c745eeed4ca39a67931b9e2b9649da91482725922222c7e1`.
- Relay `sha256:6f6bc38ee1de156106e4fe33b94b81859df3779450a5d0c66ed9956ca4f1f9c5`.

CI baseline13 `be1b696` run42336441978 SUCCESS; không thay bằng chứng CI của increment14. NOT RUN tại máy dev: bộ cài/native GUI/Windows sạch/offline/upgrade/uninstall mới, benchmark500k/1m và gửi Telegram thật. Linux preview vẫn giữ Telegram chưa cấu hình, không lưu token plaintext. Giấy phép phân phối và các gate phát hành trước còn giữ nguyên; chưa gọi production-ready.
