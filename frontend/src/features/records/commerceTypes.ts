import type { Entity, Party } from "./types";

export type ProfileKind = "farm" | "customer_company";
export interface FarmPlot { plot_code?: string | null; variety?: string | null; area_ha?: string | null; tree_count?: number | null; tree_age?: number | null }
export interface FarmSurvey { season_year: number; grade: number; ripeness_pct?: string | null; notes?: string | null }
export interface FarmProfile { owner_name?: string | null; owner_id_card?: string | null; official_area_code?: string | null; internal_area_code?: string | null; plots: FarmPlot[]; surveys: FarmSurvey[] }
export interface CommerceParty extends Party { profile_kind: "general" | ProfileKind; business_license?: string | null; farm?: FarmProfile | null }
export type Direction = "inbound" | "outbound";
export interface TradeLine { farm_id?: string | null; product_id?: string | null; quantity_kg: string; unit_price_vnd?: string | null; bag_count: number; grade?: number | null; note?: string | null }
export interface Trade extends Entity { occurred_on: string; occurred_at?: string | null; physical_actor?: string | null; party_id?: string | null; direction: Direction; status: "recorded" | "cancelled"; vehicle_plate?: string | null; weighing_id?: string | null; lines: TradeLine[] }
export interface TradePayment extends Entity { occurred_on: string; occurred_at?: string | null; physical_actor?: string | null; party_id: string; trade_id: string; amount_vnd: string; method: "cash" | "bank_transfer" | "mixed" | "other"; reference?: string | null }
export type CommerceEntity = CommerceParty | Trade | TradePayment;
export type CommerceResource = "parties" | "trades" | "trade-payments";
export const methodLabels = { cash: "Tiền mặt", bank_transfer: "Chuyển khoản", mixed: "Kết hợp", other: "Khác" };
export function companyComplete(party?: CommerceParty, allowInactive = false): boolean { return !!party && party.profile_kind === "customer_company" && !!party.name?.trim() && !!party.tax_code?.trim() && !!party.representative?.name?.trim() && !party.deleted_at && (allowInactive || party.active); }

/** Exact multiplication: kg (3 places) × VND/kg (2 places), retains 5 places. */
export function orderValue(lines: TradeLine[]): string | null {
  if (lines.some((line) => line.unit_price_vnd == null || line.unit_price_vnd === "")) return null;
  const scaled = (value: string, places: number) => {
    if (!new RegExp(`^\\d+(?:\\.\\d{1,${places}})?$`).test(value)) throw new Error("Số thập phân không hợp lệ.");
    const [whole, fraction = ""] = value.split(".");
    return BigInt(whole) * 10n ** BigInt(places) + BigInt(fraction.padEnd(places, "0"));
  };
  try {
    const total = lines.reduce((sum, line) => sum + scaled(line.quantity_kg, 3) * scaled(line.unit_price_vnd!, 2), 0n);
    const raw = total.toString().padStart(6, "0");
    return `${raw.slice(0, -5)}.${raw.slice(-5)}`.replace(/\.?0+$/, "");
  } catch { return null; }
}
