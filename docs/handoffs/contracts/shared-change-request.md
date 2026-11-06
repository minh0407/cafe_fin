# Contracts integration request

Baseline: `cafe-fin-foundation-ready-v1`, peeled commit
`e668355c227322994902f7e2e38ed7ffb19ff647`.

No core, shared schema, dependency or lockfile changes are requested. All contracts
implementation and tests remain inside the lane allowlist. Coordinator owns
these registrations and packaging asset addition outside the allowlist:

```python
# backend/cafe_fin/registry.py
from cafe_fin.contracts.module import module_manifest as contracts_manifest

# Add to the existing ModuleRegistry tuple without replacing other manifests:
contracts_manifest()
# Per-request public provider once records is registered:
from cafe_fin.records.module import RecordsReadProvider
contracts_manifest(records_factory=RecordsReadProvider)
# Static records=bridge remains supported for isolated synthetic fixtures only.
```

```typescript
// frontend/src/app/registry.tsx
import { contractsModule } from "../features/contracts";
// Replace just the contracts Pending descriptor in defineModules with contractsModule.
```

The module declares its own namespace/checksummed migration and router under
`/api/v1/contracts`. The optional read provider implements the already-frozen
`core.contracts.RecordsReadBridge`; only lookup_party/get_weighing are called.
There is no dependency on a records provider for manual drafting or export.
The optional records_factory(runtime, principal) is invoked freshly for source
lookups after the endpoint's records.read check. No principal is cached globally.
Manual CRUD/preview/export do not construct the optional provider. Configure
records or records_factory, never both. The feature's bounded records list GETs
are used only to select an ID, followed by the contracts typed bridge and explicit
copy/line selection; they do not write records or autosave a contract.

Permissions use existing `contracts.read`/`contracts.write`. Only template changes
add `contracts.templates`, available through the existing Admin wildcard; no
operator or core permission-table change is necessary.

The lane uses public core renderer/storage/writer/auth/audit interfaces and the
already-locked python-docx, ReportLab and bundled Noto Sans. It adds no network
runtime or document framework. Packaging must include contracts/templates/*.json:

```diff
--- desktop/sidecar.spec
+++ desktop/sidecar.spec
-datas = collect_data_files("cafe_fin", includes=["core/assets/**/*"])
+datas = collect_data_files("cafe_fin", includes=["core/assets/**/*", "contracts/templates/*.json"])
```

Verify both JSON templates are present in the frozen archive and run purchase/sale
exports from the frozen sidecar. Native clean-Windows
and DOCX visual gates remain independent of module browser/API verification.

Source line identity is (weighing UUID, line_index) within the pinned source
version. Duplicate selection rejects the same UUID/index even if versions differ.
The frozen core bridge exposes ordered lines, not persistent line IDs. A future
provider must preserve line order for each version; explicit refresh requires the
user to review a new snapshot. This lane does not change that shared interface.
