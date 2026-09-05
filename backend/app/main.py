from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from .admin_account_routes import router as admin_account_router
from .admin_dashboard_routes import router as admin_dashboard_router
from .admin_log_routes import router as admin_log_router
from .admin_management_routes import router as admin_management_router
from .admin_usage_routes import router as admin_usage_router
from .announcement_routes import router as announcement_router
from .auth import ensure_development_identity
from .config import Settings
from .database import Base, build_database
from .ecommerce_account_routes import router as ecommerce_account_router
from .ecommerce_crawl_tasks import (
    recover_interrupted_crawl_tasks,
    resume_queued_crawl_tasks,
)
from .ecommerce_crawl_tasks import (
    router as ecommerce_crawl_tasks_router,
)
from .ecommerce_health import (
    check_object_storage,
    check_task_broker,
    collect_crawl_metrics,
)
from .ecommerce_routes import router as ecommerce_router
from .ecommerce_session import EcommerceSessionManager
from .ecommerce_worker_routes import router as ecommerce_worker_router
from .errors import ApiError
from .inspiration_routes import router as inspiration_router
from .models import WorkspaceLimitRecord
from .routes_v1 import router as v1_router
from .schemas_v1 import HealthResponse
from .services import set_credit_enforcement_enabled, set_quota_enabled
from .storage import (
    ImageStorage,
    LocalImageStorage,
    build_image_storage,
)
from .supertokens_auth import ExternalAuthBackend, SuperTokensAuthAdapter
from .task_runner import build_task_runner, validate_task_runner_settings


def _serializable_validation_errors(
    exc: RequestValidationError,
) -> list[dict[str, object]]:
    errors: list[dict[str, object]] = []
    for item in exc.errors():
        error = dict(item)
        context = error.get("ctx")
        if isinstance(context, dict):
            error["ctx"] = {str(key): str(value) for key, value in context.items()}
        errors.append(error)
    return errors


def create_app(
    settings: Settings | None = None,
    external_auth_backend: ExternalAuthBackend | None = None,
) -> FastAPI:
    app_settings = settings or Settings()
    app_settings.validate_runtime_safety()
    validate_task_runner_settings(app_settings)
    set_quota_enabled(app_settings.provider_quota_enabled)
    set_credit_enforcement_enabled(
        app_settings.workspace_credit_enforcement_enabled
    )
    auth_backend = external_auth_backend
    if app_settings.auth_mode == "external":
        auth_backend = auth_backend or SuperTokensAuthAdapter(app_settings)
        auth_backend.initialize()
    engine, session_factory = build_database(app_settings.database_url)
    storage: ImageStorage = build_image_storage(app_settings)
    validator = storage.validator
    task_runner = build_task_runner(session_factory, app_settings, storage)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if isinstance(storage, LocalImageStorage):
            storage.root.mkdir(parents=True, exist_ok=True)
        if app_settings.auto_create_schema:
            Base.metadata.create_all(engine)
        ensure_development_identity(application)
        recover_interrupted_crawl_tasks(session_factory)
        # In Celery mode the dedicated maintenance process is the sole owner
        # of queued-message recovery. The API still repairs stale task state,
        # but must not publish duplicate crawl messages during a restart.
        if app_settings.task_dispatcher == "inline":
            resume_queued_crawl_tasks(application, session_factory)
        yield
        engine.dispose()

    application = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        description=("极光商绘 API v1。当前执行器只模拟状态，不会调用图片生成服务。"),
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.storage = storage
    application.state.image_validator = validator
    application.state.task_runner = task_runner
    application.state.ecommerce_crawl_handles = set()
    # Lazily created account-specific managers are keyed by account id and
    # use the durable profile path owned by that account.
    application.state.ecommerce_account_sessions = {}
    application.state.ecommerce_stream_accounts = set()
    # Ephemeral remote-worker login frames. Entries are byte payloads with an
    # expiry timestamp and are never written to object storage or logs.
    application.state.ecommerce_remote_login_frames = {}
    # Keep the historical Taobao manager alias for existing callers, while
    # registering an independent 1688 manager and profile. Never share a
    # persistent browser profile across platform policies.
    application.state.ecommerce_session = EcommerceSessionManager(
        app_settings.ecommerce_session_dir,
        platform="taobao",
        session_profile="domestic-taobao-tmall",
        state_style="legacy",
    )
    application.state.ecommerce_session_1688 = EcommerceSessionManager(
        app_settings.ecommerce_1688_session_dir,
        platform="alibaba1688",
        session_profile="domestic-1688",
        state_style="canonical",
    )
    application.state.ecommerce_session_jd = EcommerceSessionManager(
        app_settings.ecommerce_jd_session_dir,
        platform="jd",
        session_profile="domestic-jd",
        state_style="canonical",
    )
    application.state.ecommerce_session_pinduoduo = EcommerceSessionManager(
        app_settings.ecommerce_pinduoduo_session_dir,
        platform="pinduoduo",
        session_profile="domestic-pinduoduo",
        state_style="canonical",
    )
    application.state.ecommerce_sessions = {
        "taobao": application.state.ecommerce_session,
        "1688": application.state.ecommerce_session_1688,
        "jd": application.state.ecommerce_session_jd,
        "pinduoduo": application.state.ecommerce_session_pinduoduo,
    }
    application.state.external_auth_backend = auth_backend
    application.state.workspace_limits = lambda session, workspace_id: session.get(
        WorkspaceLimitRecord, workspace_id
    )

    auth_cors_headers: list[str] = []
    if auth_backend is not None:
        auth_backend.install_middleware(application)
        auth_cors_headers = auth_backend.cors_headers()
    allowed_headers = [
        "Content-Type",
        "Idempotency-Key",
        "X-Request-Id",
    ]
    if app_settings.auth_mode == "development":
        allowed_headers.append("X-User-Id")
    for header in auth_cors_headers:
        if header not in allowed_headers:
            allowed_headers.append(header)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
        allow_headers=allowed_headers,
        expose_headers=auth_cors_headers,
    )

    @application.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-Id") or f"req_{uuid4().hex}"
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    @application.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": request.state.request_id,
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "请求参数校验失败。",
                    "details": _serializable_validation_errors(exc),
                    "request_id": request.state.request_id,
                }
            },
        )

    @application.get(
        "/health/live",
        response_model=HealthResponse,
        tags=["system"],
    )
    def liveness() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service=app_settings.app_name,
            version=app_settings.app_version,
            checks={"process": "ok"},
        )

    @application.get(
        "/health/ready",
        response_model=HealthResponse,
        tags=["system"],
    )
    def readiness(response: Response) -> HealthResponse:
        checks = {"database": "ok"}
        try:
            with session_factory() as session:
                session.execute(text("SELECT 1"))
        except Exception:
            checks["database"] = "failed"
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        if app_settings.task_dispatcher == "celery":
            checks["task_broker"] = check_task_broker(
                app_settings.celery_broker_url
            )
            if checks["task_broker"] != "ok":
                response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        if app_settings.storage_backend == "s3":
            checks["object_storage"] = check_object_storage(storage)
            if checks["object_storage"] != "ok":
                response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        if app_settings.auth_mode == "external":
            authentication_ready = bool(auth_backend and auth_backend.is_ready())
            checks["authentication"] = "ok" if authentication_ready else "failed"
            if not authentication_ready:
                response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status=(
                "ok" if all(value == "ok" for value in checks.values()) else "degraded"
            ),
            service=app_settings.app_name,
            version=app_settings.app_version,
            checks=checks,
        )

    @application.get("/health/ecommerce", tags=["system"])
    def ecommerce_health(response: Response) -> dict[str, object]:
        try:
            metrics = collect_crawl_metrics(session_factory)
        except Exception:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "degraded", "metrics": {}}
        return {"status": "ok", "metrics": metrics}

    application.include_router(v1_router)
    application.include_router(announcement_router)
    application.include_router(admin_dashboard_router)
    application.include_router(admin_account_router)
    application.include_router(admin_usage_router)
    application.include_router(admin_log_router)
    application.include_router(admin_management_router)
    application.include_router(inspiration_router)
    application.include_router(ecommerce_router)
    application.include_router(ecommerce_account_router)
    application.include_router(ecommerce_crawl_tasks_router)
    application.include_router(ecommerce_worker_router)
    return application


app = create_app()
