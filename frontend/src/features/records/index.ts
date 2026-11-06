import type { FeatureModule } from "../../app/registry";
import { RecordsPage } from "./RecordsPage";

export { RecordsPage } from "./RecordsPage";
export const recordsModule: FeatureModule = Object.freeze({
  id: "records",
  title: "Ghi nhận cà phê",
  permission: "records.read",
  routes: [{ path: "/records", component: RecordsPage }],
});
export default recordsModule;
