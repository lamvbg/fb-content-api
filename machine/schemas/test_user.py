from pydantic import BaseModel


class CreateTestUserRequest(BaseModel):
    installed: bool = True
    name: str | None = None
    permissions: str = "pages_manage_posts,pages_read_engagement,pages_show_list"


class TestUserResponse(BaseModel):
    id: str
    access_token: str | None = None
    login_url: str | None = None
    email: str | None = None
    password: str | None = None


class AssignRoleRequest(BaseModel):
    user_id: str
    role: str = "administrators"  # administrators, developers, testers


class AssignRoleResponse(BaseModel):
    success: bool
    message: str
