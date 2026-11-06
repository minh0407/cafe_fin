"""Synthetic browser bootstrap with an explicit test-only loopback Origin adapter.

Only this process accepts the dedicated accounting Vite origin (port 1424).
Production ALLOWED_ORIGINS, desktop manifests and CSP are never edited; actual
ScopeGuard/CORS/auth/HTTP/jobs still run against the exact requested origin.
"""
from cafe_fin import __main__ as sidecar
from cafe_fin.accounting.module import module_manifest
from cafe_fin.core import api
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime


class AccountingRuntime(Runtime):
    def __init__(self, path, *, initialize=False, activation_mode="active"):
        super().__init__(
            path,
            initialize=initialize,
            activation_mode=activation_mode,
            modules=ModuleRegistry((module_manifest(),)),
        )


TEST_ORIGIN = 'http://127.0.0.1:1424'
# Both modules import the allowlist by value. Patch both process-local aliases;
# never accept an arbitrary environment origin or wildcard.
api.ALLOWED_ORIGINS = api.ALLOWED_ORIGINS | frozenset({TEST_ORIGIN})
sidecar.ALLOWED_ORIGINS = api.ALLOWED_ORIGINS
sidecar.Runtime = AccountingRuntime
if __name__ == '__main__':
    raise SystemExit(sidecar.main())
