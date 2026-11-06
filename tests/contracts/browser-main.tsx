import React from "react";
import { createRoot } from "react-dom/client";
import { ConfigProvider } from "antd";
import { ContractsPage } from "../../frontend/src/features/contracts";
import { useSession } from "../../frontend/src/shared/session";

const boot = (window as any).__CONTRACTS_BOOT__;
useSession.getState().setBoot(boot.boot);
useSession.getState().login(boot.token, boot.user);
createRoot(document.getElementById("root")!).render(<ConfigProvider theme={{ token: { colorPrimary: "#176b52", borderRadius: 6 } }}><ContractsPage /></ConfigProvider>);
