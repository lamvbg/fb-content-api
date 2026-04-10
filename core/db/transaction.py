from functools import wraps


def transactional(func):
    """Decorator to wrap a function in a database transaction."""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        session = kwargs.get("session") or (args[0].session if args else None)
        if session is None:
            raise ValueError("No session found for transactional operation")
        try:
            result = await func(*args, **kwargs)
            await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise

    return wrapper
