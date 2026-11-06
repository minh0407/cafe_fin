// Test-only host: real feature, real shared client/session, real HTTP backend.
// The coordinator's production registry is deliberately untouched by this lane.
import React from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ConfigProvider } from "antd";
import viVN from "antd/locale/vi_VN";
import { RecordsPage } from "../../../frontend/src/features/records";
import { useSession } from "../../../frontend/src/shared/session";
import type { AuthResponse, BootSession } from "../../../frontend/src/shared/types";
import "../../../frontend/src/app/styles.css";

const context = (window as unknown as { recordsTest: { boot: BootSession; auth: AuthResponse } }).recordsTest;
useSession.getState().setBoot(context.boot);
useSession.getState().login(context.auth.access_token, context.auth.user);
const cache = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
createRoot(document.getElementById("root")!).render(<React.StrictMode><ConfigProvider locale={viVN}><QueryClientProvider client={cache}><main style={{ padding: 24 }}><RecordsPage /></main></QueryClientProvider></ConfigProvider></React.StrictMode>);
