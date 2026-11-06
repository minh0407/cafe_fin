import type { FeatureModule } from '../../app/registry';
import { AccountingPage } from './AccountingPage';
export const accountingFeature: FeatureModule = { id: 'accounting', title: 'Sổ kế toán', permission: 'accounting.read', routes: [{ path: '/accounting', component: AccountingPage }] };
