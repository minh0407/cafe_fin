import type { ComponentType } from "react";
import { Empty } from "antd";
import { recordsModule } from "../features/records";

export interface FeatureRoute {
  path: string;
  component: ComponentType;
}
export interface FeatureModule {
  id: string;
  title: string;
  permission: string;
  routes: readonly FeatureRoute[];
}
export function defineModules(
  modules: readonly FeatureModule[],
): readonly FeatureModule[] {
  const ids = new Set<string>();
  const paths = new Set<string>();
  for (const module of modules) {
    if (ids.has(module.id)) throw new Error(`Duplicate module: ${module.id}`);
    ids.add(module.id);
    for (const route of module.routes) {
      if (!route.path.startsWith(`/${module.id}`) || paths.has(route.path))
        throw new Error(`Invalid module route: ${route.path}`);
      paths.add(route.path);
    }
  }
  return Object.freeze([...modules]);
}
const Pending = () => (
  <Empty description="Module chưa được triển khai trên foundation candidate." />
);
// Coordinator adds feature-owned index.ts exports here after the foundation gate.
export const modules = defineModules([
  recordsModule,
  {
    id: "contracts",
    title: "Hợp đồng",
    permission: "contracts.read",
    routes: [{ path: "/contracts", component: Pending }],
  },
  {
    id: "accounting",
    title: "Sổ kế toán",
    permission: "accounting.read",
    routes: [{ path: "/accounting", component: Pending }],
  },
  {
    id: "reporting",
    title: "Báo cáo",
    permission: "reporting.read",
    routes: [{ path: "/reporting", component: Pending }],
  },
]);
