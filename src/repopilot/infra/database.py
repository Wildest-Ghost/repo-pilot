"""SQLAlchemy 数据库连接与会话工厂。

数据库连接只在真正使用 SessionLocal 或 init_db 时发挥作用；API 当前
默认使用内存仓库，因此开发环境不需要先启动 PostgreSQL。
"""

from os import environ

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = environ.get(
    "REPOPILOT_DATABASE_URL",
    "postgresql+psycopg://repopilot:repopilot@localhost:5432/repopilot",
)


class Base(DeclarativeBase):
    """所有 SQLAlchemy ORM 模型的声明基类。"""

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
    """创建当前 ORM 模型对应的表。

    这是早期原型的初始化入口，不替代正式迁移工具，也不会在 API 启动时
    自动执行。
    """

    # 当前 API 尚未接入该适配器，但保留这个入口以便后续持久化里程碑启用。
    Base.metadata.create_all(bind=engine)
