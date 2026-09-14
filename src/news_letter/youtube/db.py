from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base
from ..utils.constants import DATABASE_PATH


engine = create_engine(
    f"sqlite:///{DATABASE_PATH}",
    echo=False,
)

SessionFactory = sessionmaker(
    bind=engine,
    class_=Session,
    expire_on_commit=False,
)


def init_db() -> None:
    DATABASE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    Base.metadata.create_all(engine)


def create_session() -> Session:
    return SessionFactory()
