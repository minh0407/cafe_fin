# Cách giao các prompt cafe_fin

Repo: https://github.com/minh0407/cafe_fin.git . Checkout điều phối: `C:\Users\NC\Desktop\UNILA{\cafe_fin`.

Mỗi file dưới đây là một prompt đầy đủ để dán vào một chat triển khai. Không giao tất cả vào cùng checkout. Các chat tự đọc source/docs, làm trong worktree riêng và trả commit về chat điều phối; không tự push.

| Thứ tự | Prompt | Khi bắt đầu |
|---|---|---|
| 00 | `00_NEN_TANG_DESKTOP.md` | Ngay sau khi tag `cafe-fin-spec-v1` đã có |
| 01 | `01_GHI_NHAN_NGHIEP_VU.md` | Có tag `cafe-fin-foundation-ready-v1` do điều phối publish |
| 02 | `02_HOP_DONG_VA_CHUNG_TU.md` | Cùng baseline foundation; có thể song song 01/03 |
| 03 | `03_KE_TOAN_EXCEL_VA_IMPORT.md` | Cùng baseline foundation; có thể song song 01/02 |
| 04 | `04_BAO_CAO_VA_ZALO.md` | Contract read bridge đã freeze; nghiệm thu sau khi tích hợp records/accounting |
| 05 | `05_DONG_GOI_VA_NGHIEM_THU.md` | Có tag `cafe-fin-integration-ready-v1` và các module đã được điều phối ghép |

Nếu mở chat trên máy này, có thể dán một câu khởi động ngắn như:

```text
Làm việc với repo C:\Users\NC\Desktop\UNILA{\cafe_fin, remote https://github.com/minh0407/cafe_fin.git. Đọc và thực hiện toàn bộ docs/prompts/00_NEN_TANG_DESKTOP.md cùng các tài liệu nó dẫn. Tạo worktree riêng theo AGENTS, không sửa checkout điều phối. Bàn giao commit và kết quả kiểm thử về đây; không push/merge. Nếu baseline tag bắt buộc chưa có, báo đang chờ điều phối và không tự thay baseline.
```

Thay tên file để giao lane khác. Các tag READY là bằng chứng điều phối đã review, không do chat triển khai tự tạo. Bộ prompt hướng tới triển khai tự động trong phạm vi rõ ràng; chưa có feature hoặc bộ cài hoàn tất chỉ vì prompt đã được viết.
