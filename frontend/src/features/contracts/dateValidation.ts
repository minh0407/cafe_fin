import { isDateInputValueValid } from "../../shared/DateInput";
import type { ContractData } from "./types";

export interface ContractDateIssue { field: string; message: string }

/** Validate raw controlled drafts before any current-contract save/preview/export. */
export function contractDateIssues(data: ContractData): ContractDateIssue[] {
  const issues: ContractDateIssue[] = [];
  const check = (value: string | null | undefined, field: string, label: string, required: boolean) => {
    if (required && !value) issues.push({ field, message: `${label}: cần nhập ngày theo DD/MM/YYYY.` });
    else if (!isDateInputValueValid(value ?? undefined)) issues.push({ field, message: `${label}: ngày không hợp lệ, nhập DD/MM/YYYY.` });
  };
  check(data.occurred_on, "occurred_on", "Ngày lập", true);
  check(data.payment.due_on, "payment.due_on", "Hạn thanh toán", false);
  data.payment.schedule.forEach((item, index) => check(item.due_on, `payment.schedule.${index}.due_on`, `Ngày đợt ${index + 1}`, true));
  data.lines.forEach((line, index) => {
    if (line.source) check(line.source.occurred_on, `lines.${index}.source.occurred_on`, `Ngày phiếu cân nguồn dòng ${index + 1}`, false);
  });
  return issues;
}
