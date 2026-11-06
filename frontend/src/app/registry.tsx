import type { ComponentType } from "react";
import { accountingFeature } from "../features/accounting";
import { contractsModule } from "../features/contracts";
import { recordsModule } from "../features/records";
import { reportingFeature } from "../features/reporting";

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
export const modules = defineModules([
  recordsModule,
  contractsModule,
  accountingFeature,
  reportingFeature,
]);
