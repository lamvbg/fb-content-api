from machine.external.facebook import FacebookService
from machine.schemas.test_user import (
    AssignRoleRequest,
    AssignRoleResponse,
    CreateTestUserRequest,
    TestUserResponse,
)


class TestUserController:
    async def create_test_user(self, body: CreateTestUserRequest) -> TestUserResponse:
        result = await FacebookService.create_test_user(
            installed=body.installed,
            name=body.name,
            permissions=body.permissions,
        )
        return TestUserResponse(
            id=result["id"],
            access_token=result.get("access_token"),
            login_url=result.get("login_url"),
            email=result.get("email"),
            password=result.get("password"),
        )

    async def get_test_users(self) -> list[TestUserResponse]:
        users = await FacebookService.get_test_users()
        return [
            TestUserResponse(
                id=u["id"],
                access_token=u.get("access_token"),
                login_url=u.get("login_url"),
            )
            for u in users
        ]

    async def delete_test_user(self, test_user_id: str) -> dict:
        await FacebookService.delete_test_user(test_user_id)
        return {"success": True, "message": f"Test user {test_user_id} deleted"}

    async def assign_role(self, body: AssignRoleRequest) -> AssignRoleResponse:
        await FacebookService.assign_app_role(user_id=body.user_id, role=body.role)
        return AssignRoleResponse(
            success=True,
            message=f"Role '{body.role}' assigned to user {body.user_id}",
        )
