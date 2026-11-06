"""Synthetic browser-test bootstrap; production auth/CORS/HTTP/job machinery is unchanged."""
from cafe_fin import __main__ as sidecar
from cafe_fin.accounting.module import module_manifest
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime


class AccountingRuntime(Runtime):
    def __init__(self, path, *, initialize=False):
        super().__init__(path, initialize=initialize, modules=ModuleRegistry((module_manifest(),)))


sidecar.Runtime = AccountingRuntime
if __name__ == '__main__':
    raise SystemExit(sidecar.main())
