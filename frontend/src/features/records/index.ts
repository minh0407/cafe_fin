import type { FeatureModule } from "../../app/registry";
import { RecordsPage } from "./RecordsPage";
import { FarmsPage, CustomersPage } from "./PartyCatalog";
import { InboundPage, OutboundPage } from "./TradePage";
import { DashboardPage } from "./Dashboard";

export { RecordsPage } from "./RecordsPage";
export { FarmsPage, CustomersPage } from "./PartyCatalog";
export { InboundPage, OutboundPage } from "./TradePage";
export const recordsModule: FeatureModule = Object.freeze({
  id: "records",
  title: "Ghi nhận cà phê",
  permission: "records.read",
  routes: [{ path: "/records", component: RecordsPage }, { path: "/records/farms", component: FarmsPage }, { path: "/records/customers", component: CustomersPage }, { path: "/records/inbound", component: InboundPage }, { path: "/records/outbound", component: OutboundPage }, { path: "/records/dashboard", component: DashboardPage }],
});
export default recordsModule;
