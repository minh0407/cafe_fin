"""Coordinator-owned registration point. Lanes deliver manifests without editing core."""

from cafe_fin.accounting.module import module_manifest as accounting_manifest
from cafe_fin.accounting.public import AccountingReadProvider
from cafe_fin.contracts.module import module_manifest as contracts_manifest
from cafe_fin.core.example import module_manifest
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.secrets import WindowsCredentialStore
from cafe_fin.records.module import RecordsReadProvider
from cafe_fin.records.module import module_manifest as records_manifest
from cafe_fin.reporting.module import module_manifest as reporting_manifest
from cafe_fin.reporting.sources import AtomicSources


def _report_sources(runtime, principal) -> AtomicSources:
    """Capture the requesting actor's public providers in one caller-owned snapshot."""
    return AtomicSources(
        runtime.reader,
        lambda conn, first, last, *, cutoff: RecordsReadProvider(
            runtime, principal, connection=conn
        ).inventory_summary(first, last, cutoff=cutoff),
        lambda conn, book_id, first, last, *, cutoff: AccountingReadProvider(
            runtime, principal, connection=conn
        ).book_summary(book_id, first, last, cutoff=cutoff),
    )


def registered_modules() -> ModuleRegistry:
    return ModuleRegistry(
        (
            module_manifest(),
            records_manifest(),
            contracts_manifest(records_factory=RecordsReadProvider),
            accounting_manifest(),
            reporting_manifest(
                actor_source_factory=_report_sources, secret_store=WindowsCredentialStore()
            ),
        )
    )
