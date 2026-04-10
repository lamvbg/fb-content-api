import ssl

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.settings import get_settings

settings = get_settings()

# Strip sslmode from URL (asyncpg uses ssl connect_arg instead)
db_url = settings.DATABASE_URL.replace("?sslmode=require", "").replace("&sslmode=require", "")
connect_args = {}
if "sslmode=require" in settings.DATABASE_URL or "neon.tech" in settings.DATABASE_URL:
    connect_args["ssl"] = ssl.create_default_context()

async_engine = create_async_engine(
    db_url,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    connect_args=connect_args,
)

async_session_factory = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session():
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
