from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.session import get_session
from machine.controllers.fanpage_controller import FanpageController


async def get_fanpage_controller(
    session: AsyncSession = Depends(get_session),
) -> FanpageController:
    return FanpageController(session)
