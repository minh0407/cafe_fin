import { useEffect, useRef, useState } from "react";
import { Alert, Button, Pagination, Select, Space, Typography } from "antd";
import { api, messageOf } from "../../shared/api";
import { useSession } from "../../shared/session";
import type { Page } from "../../shared/types";

type BookChoice = { id: string; name: string };
const PAGE_SIZE = 50;
const MAX_SELECTED = 100;
const validId = (id: string) => /^[A-Za-z0-9_-]{1,128}$/.test(id);
function bookChoice(value: unknown): BookChoice {
  const book = value as Partial<BookChoice> | null;
  if (
    !book ||
    typeof book.id !== "string" ||
    !validId(book.id) ||
    typeof book.name !== "string" ||
    !book.name.trim()
  ) {
    throw new Error("Không đọc được tên sổ từ Kế toán.");
  }
  return { id: book.id, name: book.name };
}
function retainNames(
  previous: Record<string, string>,
  selected: string[],
  page: BookChoice[],
) {
  const next: Record<string, string> = Object.create(null);
  selected.forEach((id) => {
    if (Object.hasOwn(previous, id)) next[id] = previous[id];
  });
  page.forEach((book) => {
    next[book.id] = book.name;
  });
  return next;
}

export function BookPicker({
  value = [],
  onChange,
  id,
  label,
  disabled = false,
}: {
  value?: string[];
  onChange?: (ids: string[]) => void;
  id?: string;
  label: string;
  disabled?: boolean;
}) {
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [items, setItems] = useState<BookChoice[]>([]);
  const [total, setTotal] = useState(0);
  const [names, setNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [resolving, setResolving] = useState(false);
  const [error, setError] = useState("");
  const [unavailable, setUnavailable] = useState<string[]>([]);
  const generation = useRef(useSession.getState().generation).current;
  const selected = useRef(value);
  selected.current = value;
  const visiblePage = useRef(items);
  visiblePage.current = items;
  const listSequence = useRef(0);
  const detailSequence = useRef(0);
  const selectionKey = JSON.stringify(value);
  const live = () => useSession.getState().generation === generation;

  useEffect(() => {
    let mounted = true;
    const request = ++listSequence.current;
    setLoading(true);
    setItems([]);
    setError("");
    void api<Page<unknown>>(
      `/accounting/books?page=${page}&page_size=${PAGE_SIZE}`,
    )
      .then((result) => {
        if (
          !Array.isArray(result.items) ||
          result.items.length > PAGE_SIZE ||
          !Number.isSafeInteger(result.total) ||
          result.total < 0 ||
          result.page !== page ||
          result.page_size !== PAGE_SIZE
        ) {
          throw new Error("Danh sách sổ Kế toán chưa sẵn sàng.");
        }
        const books = result.items.map(bookChoice);
        if (new Set(books.map((book) => book.id)).size !== books.length) {
          throw new Error("Danh sách sổ Kế toán không hợp lệ.");
        }
        if (mounted && live() && request === listSequence.current) {
          setItems(books);
          setTotal(result.total);
          setNames((old) => retainNames(old, selected.current, books));
        }
      })
      .catch((cause) => {
        if (mounted && live() && request === listSequence.current) {
          setTotal(0);
          setNames((old) => retainNames(old, selected.current, []));
          setError(messageOf(cause));
        }
      })
      .finally(() => {
        if (mounted && live() && request === listSequence.current)
          setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [page, revision]);

  useEffect(() => {
    setNames((old) => retainNames(old, selected.current, visiblePage.current));
  }, [selectionKey]);

  useEffect(() => {
    let mounted = true;
    const request = ++detailSequence.current;
    setUnavailable([]);
    if (loading || error) {
      setResolving(false);
      return;
    }
    const missing = selected.current
      .filter((key) => !Object.hasOwn(names, key))
      .slice(0, MAX_SELECTED);
    setResolving(missing.length > 0);
    let cursor = 0;
    const failed: string[] = [];
    async function worker() {
      while (
        mounted &&
        live() &&
        request === detailSequence.current &&
        cursor < missing.length
      ) {
        const key = missing[cursor++];
        try {
          if (!validId(key)) throw new Error("Không đọc được tên sổ.");
          const book = bookChoice(
            await api<unknown>(`/accounting/books/${encodeURIComponent(key)}`),
          );
          if (book.id !== key) throw new Error("Tên sổ không khớp lựa chọn.");
          if (
            mounted &&
            live() &&
            request === detailSequence.current &&
            selected.current.includes(key)
          ) {
            setNames((old) =>
              retainNames(
                { ...old, [key]: book.name },
                selected.current,
                visiblePage.current,
              ),
            );
          }
        } catch {
          failed.push(key);
        }
      }
    }
    void Promise.all(
      Array.from({ length: Math.min(4, missing.length) }, worker),
    ).then(() => {
      if (mounted && live() && request === detailSequence.current) {
        setUnavailable(failed.filter((key) => selected.current.includes(key)));
        setResolving(false);
      }
    });
    return () => {
      mounted = false;
    };
  }, [selectionKey, loading, error, revision]);

  const options = new Map(
    items.map((book) => [book.id, { value: book.id, label: book.name }]),
  );
  value.slice(0, MAX_SELECTED).forEach((key, index) => {
    if (!options.has(key))
      options.set(key, {
        value: key,
        label: Object.hasOwn(names, key)
          ? names[key]
          : `Sổ đã chọn ${index + 1} (chưa đọc được tên)`,
      });
  });
  return (
    <Space
      role="group"
      aria-label={`${label} — danh sách sổ`}
      orientation="vertical"
      style={{ display: "flex", minWidth: 300 }}
    >
      <Select
        id={id}
        aria-label={label}
        mode="multiple"
        virtual={false}
        showSearch={false}
        allowClear
        maxCount={MAX_SELECTED}
        value={value}
        onChange={onChange}
        options={[...options.values()]}
        disabled={disabled}
        loading={loading || resolving}
        style={{ width: "100%" }}
        placeholder="Chọn sổ theo tên; có thể để trống"
        notFoundContent={
          error ? "Chưa tải được danh sách sổ" : "Trang này chưa có sổ"
        }
      />
      <Space wrap>
        <Pagination
          size="small"
          current={page}
          pageSize={PAGE_SIZE}
          total={total}
          showSizeChanger={false}
          showQuickJumper
          disabled={disabled || loading}
          onChange={setPage}
          aria-label={`Trang danh sách ${label}`}
        />
        <Button
          disabled={disabled || loading}
          onClick={() => setRevision((old) => old + 1)}
        >
          Tải lại danh sách sổ
        </Button>
      </Space>
      <Typography.Text type="secondary">
        Mỗi trang tối đa 50 sổ. Đã chọn {value.length}/100; giữ lựa chọn khi đổi
        trang.
      </Typography.Text>
      {error && (
        <Alert
          type="warning"
          title="Chưa tải được sổ Kế toán"
          description={`${error} Có thể bỏ chọn sổ để xem báo cáo kho.`}
        />
      )}
      {unavailable.length > 0 && (
        <Alert
          type="warning"
          title={`Chưa đọc được tên ${unavailable.length} sổ đã chọn; giữ nguyên lựa chọn. Có thể bỏ chọn hoặc tải lại.`}
        />
      )}
    </Space>
  );
}
