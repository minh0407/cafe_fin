import type { FeatureModule } from "../../app/registry";
import { ContractsPage } from "./ContractsPage";

export { ContractsPage } from "./ContractsPage";
export const contractsModule: FeatureModule = {
  id: "contracts",
  title: "Hợp đồng",
  permission: "contracts.read",
  routes: [{ path: "/contracts", component: ContractsPage }],
};
export default contractsModule;
