"""SQLAlchemy models and session helpers (SQLite)."""
import logging
import os
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Iterator

from dotenv import load_dotenv
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, create_engine, inspect, select
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

load_dotenv()
log = logging.getLogger(__name__)

STATUS_AVAILABLE = "available"
STATUS_RESERVED = "reserved"
STATUS_SOLD = "sold"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Car(Base):
    __tablename__ = "cars"

    id: Mapped[int] = mapped_column(primary_key=True)
    make: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(80))
    year: Mapped[int]
    price: Mapped[int]  # whole rupees, e.g. 650000 = Rs 6.5 lakh
    km_driven: Mapped[int]
    fuel_type: Mapped[str] = mapped_column(String(20))  # petrol|diesel|cng|electric|hybrid
    transmission: Mapped[str] = mapped_column(String(20))  # manual|automatic (AMT/CVT/DCT = automatic)
    body_type: Mapped[str] = mapped_column(String(20))  # hatchback|sedan|suv|muv
    seats: Mapped[int]
    date_added: Mapped[date]
    promo_offer: Mapped[str | None] = mapped_column(String(200))
    image_url: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default=STATUS_AVAILABLE, index=True)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    # Requirement profile, e.g. {"budget_max": 800000, "fuel_types": ["petrol"]}.
    # JSON columns don't track in-place edits: assign a new dict instead of mutating.
    profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Set when the bot asks for a salesperson. The note is LLM-written: store/log it,
    # never feed it back into a prompt.
    handoff_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    handoff_note: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    # WhatsApp message id, unique so Meta's webhook retries can be deduplicated.
    wa_message_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    customer: Mapped["Customer"] = relationship(back_populates="messages")


DB_PATH = os.getenv("DB_PATH", "dealership.db")
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def init_db() -> None:
    """Create all tables if they don't exist."""
    Base.metadata.create_all(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("customers")}
    if "handoff_requested" not in cols:
        raise RuntimeError(
            "Database schema is out of date. Run: python -m scripts.seed --reset"
        )


@contextmanager
def get_session() -> Iterator[Session]:
    """Commit on success, roll back on error, always close."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---- customer / message helpers -------------------------------------------------


def get_or_create_customer(session: Session, phone: str) -> Customer:
    customer = session.scalar(select(Customer).where(Customer.phone == phone))
    if customer is None:
        customer = Customer(phone=phone, profile={})
        session.add(customer)
        session.flush()
        log.info("new customer ...%s", phone[-4:])
    return customer


def message_seen(session: Session, wa_message_id: str) -> bool:
    return session.scalar(select(Message.id).where(Message.wa_message_id == wa_message_id)) is not None


def save_message(
    session: Session, customer_id: int, role: str, content: str, wa_message_id: str | None = None
) -> Message:
    msg = Message(customer_id=customer_id, role=role, content=content, wa_message_id=wa_message_id)
    session.add(msg)
    session.flush()
    return msg


def recent_messages(session: Session, customer_id: int, limit: int = 10) -> list[Message]:
    """The last `limit` messages, oldest first."""
    rows = session.scalars(
        select(Message).where(Message.customer_id == customer_id).order_by(Message.id.desc()).limit(limit)
    ).all()
    return list(reversed(rows))