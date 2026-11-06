import { useEffect, useMemo, useState, type ClipboardEvent } from "react";
import { Alert, Button, Pagination, Space, Tag, Typography } from "antd";
import { useQuery } from "@tanstack/react-query";
import {
  DataGrid,
  renderTextEditor,
  type Column,
  type RenderCellContentProps,
} from "react-data-grid";
import "react-data-grid/lib/styles.css";
import { api, messageOf } from "./api";
import type { GridRow, Page } from "./types";

const editable = [
  "code",
  "description",
  "occurred_on",
  "amount",
  "formula",
] as const;
interface Position {
  row: number;
  col: number;
}
export function GridSpike() {
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<GridRow[]>([]);
  const [dirty, setDirty] = useState(false);
  const [notice, setNotice] = useState("");
  const [active, setActive] = useState<Position>({ row: 0, col: 1 });
  const [anchor, setAnchor] = useState<Position>({ row: 0, col: 1 });
  const source = useQuery({
    queryKey: ["grid-spike", page],
    gcTime: 0,
    queryFn: () =>
      api<Page<GridRow>>(`/spikes/grid?page=${page}&page_size=500`),
  });
  useEffect(() => {
    if (source.data) {
      setRows(source.data.items);
      setDirty(false);
      setNotice("");
    }
  }, [source.data]);
  const columns = useMemo<Column<GridRow>[]>(
    () => [
      { key: "source_row", name: "Dòng nguồn", width: 110, frozen: "start" },
      ...editable.map((key) => ({
        key,
        name: {
          code: "Mã",
          description: "Nội dung",
          occurred_on: "Ngày",
          amount: "Số tiền",
          formula: "Công thức (text)",
        }[key],
        width: key === "description" ? 260 : 180,
        resizable: true,
        renderEditCell: renderTextEditor,
        renderCell: ({ row }: RenderCellContentProps<GridRow>) => {
          const sourceColumn = {
            code: "A",
            description: "B",
            occurred_on: "C",
            amount: "D",
            formula: "E",
          }[key];
          const issue = row.issues.find(
            (item) => item.column === key || item.column === sourceColumn,
          );
          return (
            <span
              className={issue ? "cell-issue" : ""}
              title={
                issue
                  ? `${issue.sheet}!${issue.cell}: ${issue.message}`
                  : String(row[key])
              }
            >
              {row[key]}
            </span>
          );
        },
      })),
    ],
    [],
  );
  function copy(event: ClipboardEvent) {
    const startRow = Math.min(anchor.row, active.row);
    const endRow = Math.max(anchor.row, active.row);
    const startCol = Math.min(anchor.col, active.col);
    const endCol = Math.max(anchor.col, active.col);
    if ((endRow - startRow + 1) * (endCol - startCol + 1) > 500) {
      setNotice("Chọn tối đa 500 ô để copy.");
      event.preventDefault();
      return;
    }
    const content = rows
      .slice(startRow, endRow + 1)
      .map((row) =>
        columns
          .slice(startCol, endCol + 1)
          .map((col) => String(row[col.key as keyof GridRow] ?? ""))
          .join("\t"),
      )
      .join("\r\n");
    event.clipboardData.setData("text/plain", content);
    event.preventDefault();
    event.stopPropagation();
  }
  function paste(event: ClipboardEvent) {
    event.preventDefault();
    event.stopPropagation();
    const text = event.clipboardData.getData("text/plain");
    if (text.length > 100000) {
      setNotice("Nội dung dán vượt giới hạn 100.000 ký tự.");
      return;
    }
    const values = text
      .replace(/\r/g, "")
      .replace(/\n$/, "")
      .split("\n")
      .map((line) => line.split("\t"));
    if (
      values.reduce((n, line) => n + line.length, 0) > 500 ||
      active.row + values.length > rows.length ||
      active.col < 1 ||
      values.some((line) => active.col + line.length > columns.length)
    ) {
      setNotice(
        "Chỉ dán tối đa 500 ô vào vùng chỉnh sửa trong trang hiện tại.",
      );
      return;
    }
    setRows((current) =>
      current.map((row, index) => {
        const patch = values[index - active.row];
        if (!patch) return row;
        return {
          ...row,
          ...Object.fromEntries(
            patch.map((value, col) => [columns[active.col + col].key, value]),
          ),
        };
      }),
    );
    setDirty(true);
    setNotice("Đã dán vào bản nháp thử nghiệm; chưa lưu vào sổ.");
  }
  return (
    <section aria-label="Bản thử grid">
      <Typography.Title level={3}>Bản thử bảng tính</Typography.Title>
      <Alert
        title="Dữ liệu tổng hợp · bản nháp chưa ghi vào sổ"
        description="Double click hoặc Enter để sửa. Shift + click chọn vùng rồi Ctrl+C; Ctrl+V dán tối đa 500 ô. Công thức được giữ dạng text, chưa tính lại. Các giá trị tiền và mã được giữ dạng chuỗi chính xác."
        type="info"
        showIcon
      />
      <Space className="toolbar" wrap>
        <Tag color={dirty ? "orange" : "green"}>
          {dirty ? "Bản nháp chưa lưu" : "Projection nguồn"}
        </Tag>
        <span data-testid="loaded-rows">Đang giữ {rows.length} dòng</span>
        <Button
          disabled={!dirty}
          onClick={() => {
            setRows(source.data?.items ?? []);
            setDirty(false);
            setNotice("");
          }}
        >
          Bỏ bản nháp
        </Button>
      </Space>
      {source.error && (
        <Alert type="error" title={messageOf(source.error)} showIcon />
      )}
      {notice && <Alert type="warning" title={notice} showIcon />}
      <div onCopyCapture={copy} onPasteCapture={paste}>
        <DataGrid
          aria-label="Grid projection"
          className="rdg-light spike-grid"
          columns={columns}
          rows={rows}
          getRowKey={(row) => row.id}
          enableVirtualization
          onRowsChange={(next) => {
            setRows(next);
            setDirty(true);
          }}
          onCellMouseDown={(args, event) => {
            const position = { row: args.rowIdx, col: args.column.idx };
            setActive(position);
            if (!event.shiftKey) setAnchor(position);
          }}
          onActivePositionChange={(args) => {
            if (args.column)
              setActive({ row: args.rowIdx, col: args.column.idx });
          }}
          onCellKeyDown={(args, event) => {
            if (!event.shiftKey && args.column)
              setAnchor({ row: args.rowIdx, col: args.column.idx });
          }}
        />
      </div>
      <Pagination
        current={page}
        pageSize={500}
        total={source.data?.total ?? 0}
        disabled={dirty || source.isFetching}
        showSizeChanger={false}
        onChange={setPage}
        showTotal={(total) =>
          `${total.toLocaleString("vi-VN")} dòng nguồn tổng hợp`
        }
      />
      <Typography.Paragraph type="secondary">
        Dữ liệu phân trang qua API local. Mỗi trang tối đa 500 dòng; grid chỉ
        render vùng nhìn thấy. Dấu lỗi vẫn gắn sheet/dòng/cột nguồn sau chỉnh
        sửa, cần backend validate lại trong lane kế toán.
      </Typography.Paragraph>
    </section>
  );
}
