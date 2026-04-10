from machine.controllers.content_controller import ContentController


async def get_content_controller() -> ContentController:
    return ContentController()
