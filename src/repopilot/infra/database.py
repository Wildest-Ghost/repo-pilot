from os import environ

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DATABASE_URL = environ.get(
    "REPOPILOT_DATABASE_URL",
    "postgresql+psycopg://repopilot:repopilot@localhost:5432/repopilot",
)


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    expire_on_commit=False,
)


def init_db() -> None:

    from repopilot.infra.models import TaskEventModel, TaskModel

    Base.metadata.create_all(
        bind=engine,
        tables=[
            TaskModel.__table__,
            TaskEventModel.__table__,
        ],
    )