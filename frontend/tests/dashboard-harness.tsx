import { createElement } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DashboardPage } from "../src/features/records/Dashboard";
import { useSession } from "../src/shared/session";

export function mountDashboard() {
  useSession.getState().setBoot({ protocol_version: 1, api_base: `${location.origin}/api/v1`, session_token: "synthetic-dashboard-session", data_root: "D:\\SyntheticDashboard" });
  useSession.getState().login("synthetic-dashboard-user", { id: "synthetic", username: "test", role: "admin", version: 1, permissions: ["*"] });
  createRoot(document.getElementById("root")!).render(createElement(QueryClientProvider, { client: new QueryClient() }, createElement(DashboardPage)));
}
