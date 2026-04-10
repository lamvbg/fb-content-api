from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.session import get_session
from core.exceptions.http import UnauthorizedException
from machine.controllers.auth_controller import AuthController
from machine.repositories.user_repository import UserRepository
from machine.models.user import User

security = HTTPBearer()


async def get_auth_controller(
    session: AsyncSession = Depends(get_session),
) -> AuthController:
    return AuthController(session)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
    session: AsyncSession = Depends(get_session),
) -> User:
    token = credentials.credentials
    try:
        user_id = AuthController.verify_jwt(token)
    except (JWTError, ValueError):
        raise UnauthorizedException(detail="Invalid or expired token")

    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(user_id)
    if not user or not user.is_active:
        raise UnauthorizedException(detail="User not found or inactive")
    return user
