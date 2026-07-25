from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings
from .database import Base, build_database
from .errors import ApiError
from .routes import router
from .storage import (
    ImageStorage,
    ImageValidator,
    LocalImageStorage,
    S3ImageStorage,
)
from .task_runner import MockTaskRunner


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


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings()
    engine, session_factory = build_database(app_settings.database_url)
    validator = ImageValidator(
        app_settings.max_upload_bytes,
        app_settings.max_image_pixels,
    )
    storage: ImageStorage
    if app_settings.storage_backend == "s3":
        storage = S3ImageStorage(
            endpoint_url=app_settings.s3_endpoint_url,
            region=app_settings.s3_region,
            access_key=app_settings.s3_access_key,
            secret_key=app_settings.s3_secret_key,
            bucket=app_settings.s3_bucket,
            validator=validator,
        )
    else:
        storage = LocalImageStorage(app_settings.storage_dir, validator)
    task_runner = MockTaskRunner(
        session_factory,
        app_settings.mock_job_delay_seconds,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if isinstance(storage, LocalImageStorage):
            storage.root.mkdir(parents=True, exist_ok=True)
        if app_settings.auto_create_schema:
            Base.metadata.create_all(engine)
        yield
        engine.dispose()

    application = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        description=(
            "极光商绘 Phase 1 资产与任务 API。当前执行器只模拟状态，"
            "不会调用图片生成服务。"
        ),
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.storage = storage
    application.state.task_runner = task_runner

    application.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @application.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "请求参数校验失败。",
                    "details": _serializable_validation_errors(exc),
                }
            },
        )

    application.include_router(router)
    return application


app = create_app()
