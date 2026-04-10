from pydantic import BaseModel


class FacebookLoginURL(BaseModel):
    login_url: str


class FacebookCallbackRequest(BaseModel):
    code: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    name: str


class UserResponse(BaseModel):
    id: str
    facebook_id: str
    name: str
    email: str | None = None
    picture_url: str | None = None
    is_active: bool = True

    model_config = {"from_attributes": True}
