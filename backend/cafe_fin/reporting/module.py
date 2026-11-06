"""Explicit manifest factory; coordinator supplies concrete public providers/adapters."""

from uuid import uuid4
from weakref import WeakKeyDictionary

from fastapi import APIRouter, Query, Request

from cafe_fin.core.errors import CoreError
from cafe_fin.core.jobs import JobHandler
from cafe_fin.core.modules import ModuleManifest

from . import models
from .migrations import MIGRATIONS
from .sender import check_connection, reconcile
from .service import ReportingService


def module_manifest(
    *, source=None, source_factory=None, secret_store=None, transport=None, heartbeat_bound=False
) -> ModuleManifest:
    if source is not None and source_factory is not None:
        raise ValueError("Choose source or source_factory")
    services = WeakKeyDictionary()

    def service(runtime):
        if runtime not in services:
            services[runtime] = ReportingService(
                runtime,
                source=source_factory(runtime) if source_factory else source,
                secret_store=secret_store,
                transport=transport,
                heartbeat_bound=heartbeat_bound,
            )
        return services[runtime]

    router = APIRouter(tags=["Reporting"])

    def current(request):
        return service(request.app.state.runtime), request.state.principal

    @router.post("/reports/preview")
    def preview(command: models.Preview, request: Request):
        instance, actor = current(request)
        return instance.preview(actor, command)

    @router.get("/reports")
    def reports(
        request: Request,
        page: int = Query(1, ge=1),
        page_size: int = Query(25, ge=1, le=500),
        search: str = Query("", max_length=128),
        sort: str = "created_at:desc",
        state: str | None = None,
    ):
        return current(request)[0].list(
            "reports", page=page, page_size=page_size, search=search, sort=sort, state=state
        )

    @router.get("/reports/{identity}")
    def detail(identity: str, request: Request):
        return current(request)[0].detail(identity)

    @router.post("/reports/{identity}/save")
    def save(identity: str, command: models.Save, request: Request):
        instance, actor = current(request)
        return instance.save(actor, identity, command)

    @router.post("/reports/{identity}/exports")
    def export(identity: str, command: models.Export, request: Request):
        instance, actor = current(request)
        return instance.export(actor, identity, command)

    @router.post("/reports/{identity}/deliveries")
    def enqueue(identity: str, command: models.Enqueue, request: Request):
        instance, actor = current(request)
        return instance.enqueue(actor, identity, command)

    @router.get("/deliveries")
    def deliveries(
        request: Request,
        page: int = Query(1, ge=1),
        page_size: int = Query(25, ge=1, le=500),
        search: str = Query("", max_length=128),
        sort: str = "created_at:desc",
        state: str | None = None,
    ):
        return current(request)[0].list(
            "deliveries", page=page, page_size=page_size, search=search, sort=sort, state=state
        )

    @router.get("/deliveries/{identity}/attempts")
    def attempts(
        identity: str,
        request: Request,
        page: int = Query(1, ge=1),
        page_size: int = Query(25, ge=1, le=500),
    ):
        return current(request)[0].attempts(identity, page, page_size)

    @router.post("/deliveries/{identity}/retry")
    def retry(identity: str, command: models.Retry, request: Request):
        instance, actor = current(request)
        return instance.retry(actor, identity, command)

    @router.post("/deliveries/{identity}/reconcile")
    def reconcile_delivery(identity: str, command: models.Retry, request: Request):
        instance, actor = current(request)
        try:
            return reconcile(instance, actor, identity, command)
        except CoreError:
            raise
        except Exception:
            raise CoreError(
                "DELIVERY_RECONCILE_UNAVAILABLE", "Chưa đối chiếu được; bản gửi vẫn chưa rõ.", 503
            ) from None

    @router.get("/settings")
    def settings(request: Request):
        instance, actor = current(request)
        actor.require("core.manage")
        return instance.public_settings()

    @router.put("/settings")
    def settings_update(command: models.DeliverySettings, request: Request):
        instance, actor = current(request)
        return instance.update_settings(actor, command)

    @router.put("/credentials")
    def credentials(command: models.Credentials, request: Request):
        instance, actor = current(request)
        try:
            return instance.set_credentials(actor, command)
        except CoreError:
            raise
        except Exception:
            raise CoreError(
                "SECRET_STORE_UNAVAILABLE",
                "Không lưu được credential trong kho bí mật Windows.",
                503,
            ) from None

    @router.post("/connection-check")
    def connection_check(command: models.Command, request: Request):
        # No send is made by a connection check. Never expose provider responses.
        try:
            return check_connection(*current(request))
        except CoreError:
            raise
        except Exception:
            raise CoreError("ZALO_CHECK_FAILED", "Không kiểm tra được kết nối Zalo.", 503) from None

    @router.post("/scheduler/tick")
    def tick(command: models.Command, request: Request):
        instance, actor = current(request)
        return request.app.state.runtime.jobs.submit(
            actor.id,
            "reporting.dispatch",
            {},
            command.request_key,
            authorize=instance.authorize(actor),
        )

    def run_dispatch(context, payload):
        instance = None
        # Runtime is held by registration closure, not a private JobService extension.
        for runtime, candidate in list(services.items()):
            if runtime.jobs is context.service:
                instance = candidate
                break
        if instance is None:
            raise CoreError("REPORT_RUNTIME_UNBOUND", "Báo cáo chưa kết nối runtime.", 503)
        context.check_cancelled()
        instance.tick()
        context.finalize(lambda conn: {"tick_complete": True})

    def startup(runtime):
        instance = service(runtime)
        instance.recover()
        instance.catch_up()
        # One finite job; core owns execution and shutdown. No separate job runner.
        runtime.jobs.submit(
            "reporting.scheduler", "reporting.dispatch", {}, "startup-" + uuid4().hex
        )

    return ModuleManifest(
        "reporting",
        "/reporting",
        permissions=("reporting.read", "reporting.write"),
        migrations=MIGRATIONS,
        router=router,
        job_handlers={"reporting.dispatch": JobHandler(run_dispatch, resumable=False)},
        on_startup=startup,
    )
