from machine.controllers.test_user_controller import TestUserController


async def get_test_user_controller() -> TestUserController:
    return TestUserController()
