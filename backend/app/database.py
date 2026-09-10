from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from starlette.requests import HTTPConnection


class Base(DeclarativeBase):
    pass


def build_database(
    database_url: str,
) -> tuple[Engine, sessionmaker[Session]]:
    connect_args: dict[str, object]
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        pool_options: dict[str, object] = {}
    else:
        # Fail promptly when the database is unavailable or the existing
        # bounded pool is occupied; increasing every process's pool would
        # move the overload to PostgreSQL instead of fixing connection use.
        connect_args = {"connect_timeout": 5}
        pool_options = {
            "pool_timeout": 5,
            "pool_recycle": 1800,
        }
    engine = create_engine(
        database_url,
        connect_args=connect_args,
        future=True,
        pool_pre_ping=True,
        **pool_options,
    )
    session_factory = sessionmaker(
        bind=engine,
        class_=Session,
        expire_on_commit=False,
    )
    return engine, session_factory


def get_session(request: HTTPConnection) -> Iterator[Session]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session
