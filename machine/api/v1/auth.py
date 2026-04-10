from fastapi import APIRouter, Depends, Query

from core.response.base import SuccessResponse
from machine.controllers.auth_controller import AuthController
from machine.models.user import User
from machine.providers.auth_provider import get_auth_controller, get_current_user
from machine.schemas.auth import FacebookLoginURL, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get(
    "/facebook/login",
    response_model=SuccessResponse[FacebookLoginURL],
    summary="Get Facebook OAuth login URL",
)
async def facebook_login():
    login_url = AuthController.get_facebook_login_url()
    return SuccessResponse(data=FacebookLoginURL(login_url=login_url))


@router.get(
    "/facebook/callback",
    response_model=SuccessResponse[TokenResponse],
    summary="Facebook OAuth callback — exchange code for JWT",
)
async def facebook_callback(
    code: str = Query(..., description="Authorization code from Facebook"),
    controller: AuthController = Depends(get_auth_controller),
):
    token = await controller.facebook_callback(code)
    return SuccessResponse(data=token)


@router.get(
    "/me",
    response_model=SuccessResponse[UserResponse],
    summary="Get current authenticated user",
)
async def get_me(current_user: User = Depends(get_current_user)):
    return SuccessResponse(data=UserResponse.model_validate(current_user))
