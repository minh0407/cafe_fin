# Windows build candidate 01

Run [42234204039](https://github.com/minh0407/cafe_fin/actions/runs/42234204039), job `127947491791`, ngày 06/11/2026, source `da9f189b8d34ac5b17f4e511c86f7e345685d1cb`: **SUCCESS**. Điều phối đã đọc status từng step và logs sau khi hoàn tất, không chỉ dispatch workflow.

Standard runner `windows-2025-vs2026`, Python 3.12.16 / uv 0.13.7, Node 24, Rust 1.99.1, dependencies từ lockfiles. Backend tests/lint/compile, frontend production build và browser/real-sidecar tests đều đạt. PyInstaller sidecar/notices và Tauri release `-- --locked` đạt.

Cargo release compile hoàn tất trong 5m06s. Tauri tạo `Cafe Fin_0.1.0_x64-setup.exe` (240,69 MiB) bằng NSIS với WebView2 offlineInstaller. Sidecar trên runner có SHA256 `7C77A1D567250444CBD10163582FB30390186B19D5130454EEDE44B9C6699784`. Hash sidecar khác bản build host không được dùng làm chứng minh reproducible binary; source/runtime vẫn phải đối chiếu độc lập.

Workflow đã ghi receipt/hash installer vào job summary; lượt đầu chưa in giá trị ra stdout. Bản workflow sau in receipt vào cả logs và summary, đồng thời smoke frozen sidecar mới build với PATH của child giới hạn Windows/System32. Không suy ca Python sidecar browser thành ca frozen executable nếu chưa chạy opt-in đó.

Không upload artifact, publish release hoặc cài installer. Binary của lượt này chỉ tồn tại trong runner tạm; đây là chứng minh build, không phải file bộ cài để người dùng tải. Chưa có clean-client install/update/uninstall, native GUI/folder-picker/lifecycle hoặc nghiệm thu offline. Windows host vẫn bị AppControl4551 và không thay policy. Source/relink clearance của iconv còn mở; chưa phát hành binary production.

Foundation development tag chứa cùng code ứng dụng với source đã kiểm trong run này; các commit sau chỉ thêm docs/native inventory/CI. Các module nghiệp vụ đã được mở riêng theo [biên bản baseline](FOUNDATION_BASELINE_V1.md).
