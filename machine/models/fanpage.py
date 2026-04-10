from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import Base, TimestampMixin, UUIDMixin


class Fanpage(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "fanpages"

    facebook_page_id: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    page_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    picture_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    user: Mapped["User"] = relationship("User", back_populates="fanpages")
