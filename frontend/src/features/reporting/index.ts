import type { FeatureModule } from "../../app/registry";
import { ReportingPage } from "./ReportingPage";

export const reportingFeature: FeatureModule = {
  id: "reporting",
  title: "Báo cáo",
  permission: "reporting.read",
  routes: [{ path: "/reporting", component: ReportingPage }],
};
