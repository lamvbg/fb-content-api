from fastapi import APIRouter, Depends

from core.response.base import SuccessResponse
from machine.controllers.test_user_controller import TestUserController
from machine.providers.test_user_provider import get_test_user_controller
from machine.schemas.test_user import (
    AssignRoleRequest,
    AssignRoleResponse,
    CreateTestUserRequest,
    TestUserResponse,
)

router = APIRouter(prefix="/test-users", tags=["Facebook Test Users & Roles"])


@router.post(
    "/",
    response_model=SuccessResponse[TestUserResponse],
    summary="Create a Facebook test user for the app",
)
async def create_test_user(
    body: CreateTestUserRequest,
    controller: TestUserController = Depends(get_test_user_controller),
):
    result = await controller.create_test_user(body)
    return SuccessResponse(data=result)


@router.get(
    "/",
    response_model=SuccessResponse[list[TestUserResponse]],
    summary="List all test users of the app",
)
async def list_test_users(
    controller: TestUserController = Depends(get_test_user_controller),
):
    result = await controller.get_test_users()
    return SuccessResponse(data=result)


@router.delete(
    "/{test_user_id}",
    response_model=SuccessResponse,
    summary="Delete a test user",
)
async def delete_test_user(
    test_user_id: str,
    controller: TestUserController = Depends(get_test_user_controller),
):
    result = await controller.delete_test_user(test_user_id)
    return SuccessResponse(**result)


@router.post(
    "/roles",
    response_model=SuccessResponse[AssignRoleResponse],
    summary="Assign a role (administrators/developers/testers) to a user in the app",
)
async def assign_role(
    body: AssignRoleRequest,
    controller: TestUserController = Depends(get_test_user_controller),
):
    result = await controller.assign_role(body)
    return SuccessResponse(data=result)
