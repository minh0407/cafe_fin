// Test harness only: coordinator registry remains untouched. All data are synthetic.
import React from "react";
import { createRoot } from "react-dom/client";
import { ConfigProvider } from "antd";
import { ReportingPage } from "../../../frontend/src/features/reporting/ReportingPage";
import { useSession } from "../../../frontend/src/shared/session";
import "../../../frontend/src/app/styles.css";

useSession.getState().setBoot({
  protocol_version: 1,
  api_base: "http://127.0.0.1:1431/api/v1",
  session_token: "synthetic-session",
  data_root: "Synthetic",
});
useSession.getState().login("synthetic", {
  id: "synthetic-admin",
  username: "demo",
  role: "admin",
  permissions: ["*"],
  version: 1,
});
(
  window as unknown as {
    reportingQA: { logout: () => void; switchActor: () => void };
  }
).reportingQA = {
  logout: () => useSession.getState().logout(),
  switchActor: () =>
    useSession
      .getState()
      .login("synthetic-next", {
        id: "synthetic-next-user",
        username: "next",
        role: "operator",
        permissions: ["reporting.read", "reporting.write", "accounting.read"],
        version: 1,
      }),
};
createRoot(document.getElementById("root")!).render(
  <ConfigProvider>
    <main style={{ maxWidth: 1240, padding: 24, margin: "auto" }}>
      <ReportingPage />
    </main>
  </ConfigProvider>,
);
