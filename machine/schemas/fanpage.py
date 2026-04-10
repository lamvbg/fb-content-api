from pydantic import BaseModel


class FanpageResponse(BaseModel):
    id: str
    facebook_page_id: str
    name: str
    category: str | None = None
    page_access_token: str | None = None
    picture_url: str | None = None

    model_config = {"from_attributes": True}


class FanpageSyncResponse(BaseModel):
    synced: int
    fanpages: list[FanpageResponse]


class CreatePostRequest(BaseModel):
    message: str
    link: str | None = None
    published: bool = True


class CreatePostResponse(BaseModel):
    post_id: str
    message: str


class PostResponse(BaseModel):
    id: str
    message: str | None = None
    created_time: str | None = None
    full_picture: str | None = None
    permalink_url: str | None = None


class SchedulePostRequest(BaseModel):
    message: str
    scheduled_publish_time: int
    link: str | None = None
