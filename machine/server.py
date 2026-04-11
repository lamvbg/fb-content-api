from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.db.base import Base
from core.db.session import async_engine
from core.fastapi.middleware import RequestLoggingMiddleware
from machine.api.v1.auth import router as auth_router
from machine.api.v1.fanpage import router as fanpage_router
from machine.api.v1.test_user import router as test_user_router
from machine.api.v1.content import router as content_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup — skip silently in serverless (Vercel)
    try:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception:
        pass
    yield
    await async_engine.dispose()


app = FastAPI(
    title="Facebook Fanpage API",
    description="API for managing Facebook Fanpages — OAuth login, page management, posting, and test user management.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)

# Routes
app.include_router(auth_router, prefix="/api/v1")
app.include_router(fanpage_router, prefix="/api/v1")
app.include_router(test_user_router, prefix="/api/v1")
app.include_router(content_router, prefix="/api/v1")


# Serve downloaded video files
_downloads = Path("downloads")
_downloads.mkdir(exist_ok=True)
app.mount("/downloads", StaticFiles(directory=str(_downloads)), name="downloads")


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok"}
