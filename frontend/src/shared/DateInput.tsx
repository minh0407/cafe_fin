import { Calendar, ConfigProvider, Input, Popover, type InputProps, type InputRef } from "antd";
import viVN from "antd/es/calendar/locale/vi_VN";
import type { Rule } from "antd/es/form";
import dayjs from "dayjs";
import customParseFormat from "dayjs/plugin/customParseFormat";
import "dayjs/locale/vi";
import { forwardRef, useLayoutEffect, useRef, useState, type AriaAttributes } from "react";

dayjs.extend(customParseFormat);

const ISO_DATE = "YYYY-MM-DD";
const DISPLAY_DATE = "DD/MM/YYYY";
const INVALID_DATE_MESSAGE = "Ngày không hợp lệ. Nhập DD/MM/YYYY.";

export interface DateInputProps
  extends AriaAttributes,
    Pick<
      InputProps,
      | "id"
      | "name"
      | "disabled"
      | "className"
      | "style"
      | "placeholder"
      | "status"
      | "size"
      | "onBlur"
      | "onFocus"
      | "autoFocus"
      | "allowClear"
    > {
  /** Valid ISO date, empty, or the user's incomplete/invalid draft text. */
  value?: string;
  /** Valid dates become ISO; invalid drafts remain text, never a stale valid date. */
  onChange?: (value: string) => void;
}

function parseISO(value: string | undefined) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = dayjs(value, ISO_DATE, true);
  return parsed.isValid() ? parsed.locale("vi") : null;
}

/** Optional empty values are valid; a draft must never pass as a saved ISO date. */
export function isDateInputValueValid(value: unknown): boolean {
  return (
    value === undefined ||
    value === "" ||
    (typeof value === "string" && parseISO(value) !== null)
  );
}

/** Include for both required and optional Form.Item dates; add required separately. */
export const dateInputRule: Rule = {
  validator: (_rule, value: unknown) =>
    isDateInputValueValid(value)
      ? Promise.resolve()
      : Promise.reject(new Error(INVALID_DATE_MESSAGE)),
};

/** Controlled text keeps invalid drafts in Form state instead of a stale ISO date. */
export const DateInput = forwardRef<InputRef, DateInputProps>(function DateInput(
  { value, onChange, ...props },
  ref,
) {
  const { componentDisabled } = ConfigProvider.useConfig();
  const disabled = props.disabled ?? componentDisabled;
  const disabledRef = useRef(disabled);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [calendarView, setCalendarView] = useState(() => dayjs().locale("vi"));
  useLayoutEffect(() => {
    // Popover may retain hidden content/handlers from its last open render.
    // Those callbacks must consult current state before mutating this field.
    disabledRef.current = disabled;
    if (disabled) setCalendarOpen(false);
  }, [disabled]);
  const selected = parseISO(value);
  const invalidValue = !isDateInputValueValid(value);
  const clearOptions =
    typeof props.allowClear === "object" ? props.allowClear : {};
  return (
    <Input
      {...props}
      ref={ref}
      disabled={disabled}
      value={selected ? selected.format(DISPLAY_DATE) : (value ?? "")}
      placeholder={props.placeholder ?? "DD/MM/YYYY"}
      allowClear={
        props.allowClear === false ? false : { label: "Xóa", ...clearOptions }
      }
      status={props.status ?? (invalidValue ? "error" : undefined)}
      aria-invalid={invalidValue || props["aria-invalid"] || undefined}
      onChange={(event) => {
        if (disabledRef.current) return;
        const text = event.target.value;
        const parsed = dayjs(text, DISPLAY_DATE, "vi", true);
        // Invalid/partial input must reach the controlled parent immediately.
        // Never clear or retain the previous ISO while showing a different date.
        onChange?.(parsed.isValid() ? parsed.format(ISO_DATE) : text);
      }}
      suffix={
        <Popover
          trigger="click"
          open={calendarOpen && !disabled}
          onOpenChange={(open) => {
            if (disabledRef.current) {
              setCalendarOpen(false);
              return;
            }
            if (open) setCalendarView(selected ?? dayjs().locale("vi"));
            setCalendarOpen(open);
          }}
          title="Chọn ngày"
          content={
            <ConfigProvider componentDisabled={disabled}>
              <Calendar
                fullscreen={false}
                locale={viVN}
                value={calendarView}
                disabledDate={() => disabledRef.current}
                onPanelChange={(date) => {
                  if (!disabledRef.current) setCalendarView(date);
                }}
                style={{ width: 300 }}
                onSelect={(date, info) => {
                  if (disabledRef.current) return;
                  setCalendarView(date);
                  if (info.source === "date") {
                    const iso = date.format(ISO_DATE);
                    if (parseISO(iso)) onChange?.(iso);
                    setCalendarOpen(false);
                  }
                }}
              />
            </ConfigProvider>
          }
        >
          <button
            type="button"
            aria-label="Mở lịch chọn ngày"
            aria-expanded={calendarOpen && !disabled}
            disabled={disabled}
            style={{ border: 0, background: "transparent", cursor: "pointer" }}
          >
            📅
          </button>
        </Popover>
      }
    />
  );
});
