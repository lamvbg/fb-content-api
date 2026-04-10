from typing import Any, Generic, Sequence, TypeVar

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    model: type[ModelType]

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, id: str) -> ModelType | None:
        return await self.session.get(self.model, id)

    async def get_all(self) -> Sequence[ModelType]:
        result = await self.session.execute(select(self.model))
        return result.scalars().all()

    async def create(self, **kwargs: Any) -> ModelType:
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def update(self, instance: ModelType, **kwargs: Any) -> ModelType:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def update_by_id(self, id: str, **kwargs: Any) -> None:
        stmt = update(self.model).where(self.model.id == id).values(**kwargs)
        await self.session.execute(stmt)
        await self.session.flush()

    async def delete_by_id(self, id: str) -> None:
        stmt = delete(self.model).where(self.model.id == id)
        await self.session.execute(stmt)
        await self.session.flush()
