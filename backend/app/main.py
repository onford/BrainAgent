from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents import build_agent_registry
from app.agents.orchestrator import Orchestrator
from app.agents.planner.agent import PlannerAgent
from app.api.routes import agents, chat, integrations, sessions, preprocessing
from app.preprocessing.service import PreprocessingService
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import Database
from app.llm.client import LLMClient, create_llm_client
from app.llm.config import LLMConfig
from app.integrations.registry import ExternalToolRegistry
from app.integrations.security import CredentialCipher
from app.tools.registry import ToolRegistry


def create_app(
    settings: Settings | None = None, llm_client: LLMClient | None = None
) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(
        app_settings.log_dir,
        max_bytes=app_settings.log_max_bytes,
        backup_count=app_settings.log_backup_count,
    )
    database = Database(app_settings.database_url)
    llm = llm_client or create_llm_client(
        LLMConfig(
            api_key=app_settings.llm_api_key,
            base_url=app_settings.llm_base_url,
            model=app_settings.llm_model,
            timeout_seconds=app_settings.llm_timeout_seconds,
        )
    )
    credential_cipher = CredentialCipher(
        app_settings.brain_agent_credential_encryption_key
    )
    external_tool_registry = ExternalToolRegistry(
        database,
        credential_cipher,
        timeout_seconds=app_settings.external_tool_timeout_seconds,
        max_retries=app_settings.external_tool_max_retries,
    )
    preprocessing_service = PreprocessingService(app_settings.preprocessing_root, app_settings.preprocessing_input_roots, llm)
    tool_registry = ToolRegistry(external_tool_registry, evidence_store=preprocessing_service.store)
    registry = build_agent_registry(llm, tool_registry, preprocessing_service)
    registry.register(PlannerAgent(llm))
    orchestrator = Orchestrator(registry)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if app_settings.db_create_tables:
            await database.create_tables()
        yield
        await database.dispose()

    app = FastAPI(title=app_settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.database = database
    app.state.agent_registry = registry
    app.state.orchestrator = orchestrator
    app.state.credential_cipher = credential_cipher
    app.state.external_tool_registry = external_tool_registry
    app.state.tool_registry = tool_registry
    app.state.preprocessing = preprocessing_service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[app_settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(chat.router, prefix="/api")
    app.include_router(agents.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(integrations.router, prefix="/api")
    app.include_router(preprocessing.router, prefix="/api")

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "llm_mode": "configured"}

    return app
