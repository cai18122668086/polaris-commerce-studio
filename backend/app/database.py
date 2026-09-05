from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from starlette.requests import HTTPConnection


class Base(DeclarativeBase):
    pass


def build_database(
    database_url: str,
) -> tuple[Engine, sessionmaker[Session]]:
    connect_args = (
        {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    )
    engine = create_engine(
        database_url,
        connect_args=connect_args,
        future=True,
        pool_pre_ping=True,
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
