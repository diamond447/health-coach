"""SQLite storage for fit server: user-token links."""

import datetime as dt
import os
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import DateTime, Engine, LargeBinary, String, create_engine, event, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from health_coach.fit.settings import FitSettings


class FitTokenKeyError(RuntimeError):
    pass


def _fernet(settings: FitSettings) -> Fernet:
    if not settings.token_key:
        raise FitTokenKeyError(
            "FIT_TOKEN_KEY is not set; create one with `python -c 'from cryptography.fernet "
            "import Fernet; print(Fernet.generate_key().decode())'`"
        )
    try:
        return Fernet(settings.token_key.get_secret_value().encode())
    except Exception as exc:
        raise FitTokenKeyError(f"FIT_TOKEN_KEY is invalid: {exc}") from exc


def encrypt_token(token: str, settings: FitSettings) -> bytes:
    return _fernet(settings).encrypt(token.encode())


def decrypt_token(token_enc: bytes, settings: FitSettings) -> str:
    try:
        return _fernet(settings).decrypt(token_enc).decode()
    except InvalidToken as exc:
        raise FitTokenKeyError("stored token cannot be decrypted with FIT_TOKEN_KEY") from exc


class Base(DeclarativeBase):
    pass


class Link(Base):
    __tablename__ = "links"

    subject: Mapped[str] = mapped_column(String, primary_key=True)
    token_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    opengym_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    opengym_user_name: Mapped[str | None] = mapped_column(String, nullable=True)
    linked_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    renewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@dataclass(frozen=True)
class LinkRecord:
    subject: str
    token: str
    opengym_user_id: str | None
    opengym_user_name: str | None
    linked_at: dt.datetime
    renewed_at: dt.datetime | None
    last_used_at: dt.datetime | None


def _to_utc(val: dt.datetime | None) -> dt.datetime | None:
    if val is None:
        return None
    if val.tzinfo is None:
        return val.replace(tzinfo=dt.UTC)
    return val.astimezone(dt.UTC)


class FitStore:
    def __init__(self, settings: FitSettings, engine: Engine | None = None) -> None:
        self.settings = settings
        if engine is not None:
            self.engine = engine
        else:
            db_dir = os.path.dirname(settings.db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
            self.engine = create_engine(
                f"sqlite:///{settings.db_path}",
                connect_args={"check_same_thread": False},
            )

            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.close()

        Base.metadata.create_all(self.engine)
        self._session_factory = sessionmaker(bind=self.engine)

    def _session(self) -> Session:
        return self._session_factory()

    def get_link(self, subject: str) -> LinkRecord | None:
        with self._session() as session:
            row = session.scalar(select(Link).where(Link.subject == subject))
            if not row:
                return None
            token = decrypt_token(row.token_enc, self.settings)
            linked_at = _to_utc(row.linked_at)
            assert linked_at is not None
            return LinkRecord(
                subject=row.subject,
                token=token,
                opengym_user_id=row.opengym_user_id,
                opengym_user_name=row.opengym_user_name,
                linked_at=linked_at,
                renewed_at=_to_utc(row.renewed_at),
                last_used_at=_to_utc(row.last_used_at),
            )

    def save_link(
        self,
        subject: str,
        token: str,
        user_id: str | None = None,
        user_name: str | None = None,
    ) -> None:
        token_enc = encrypt_token(token, self.settings)
        now = dt.datetime.now(dt.UTC)
        stmt = sqlite_insert(Link).values(
            subject=subject,
            token_enc=token_enc,
            opengym_user_id=user_id,
            opengym_user_name=user_name,
            linked_at=now,
            renewed_at=None,
            last_used_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Link.subject],
            set_={
                "token_enc": stmt.excluded.token_enc,
                "opengym_user_id": stmt.excluded.opengym_user_id,
                "opengym_user_name": stmt.excluded.opengym_user_name,
                "linked_at": stmt.excluded.linked_at,
                "renewed_at": None,
                "last_used_at": stmt.excluded.last_used_at,
            },
        )
        with self._session() as session:
            session.execute(stmt)
            session.commit()

    def update_token(self, subject: str, token: str) -> None:
        token_enc = encrypt_token(token, self.settings)
        now = dt.datetime.now(dt.UTC)
        with self._session() as session:
            row = session.scalar(select(Link).where(Link.subject == subject))
            if row:
                row.token_enc = token_enc
                row.renewed_at = now
                session.commit()

    def touch_renewed(self, subject: str) -> None:
        now = dt.datetime.now(dt.UTC)
        with self._session() as session:
            row = session.scalar(select(Link).where(Link.subject == subject))
            if row:
                row.renewed_at = now
                session.commit()

    def touch_last_used(self, subject: str) -> None:
        now = dt.datetime.now(dt.UTC)
        with self._session() as session:
            row = session.scalar(select(Link).where(Link.subject == subject))
            if row:
                row.last_used_at = now
                session.commit()

    def delete_link(self, subject: str) -> bool:
        with self._session() as session:
            row = session.scalar(select(Link).where(Link.subject == subject))
            if row:
                session.delete(row)
                session.commit()
                return True
            return False
