"""OAuth 2.1 authorization-server state for the remote MCP assistant connector.

Only hashes of codes and tokens are stored; the raw values are returned once to
the OAuth client and never persisted or logged.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class OAuthClient(Base):
    """A dynamically registered public client (RFC 7591), e.g. claude.ai."""

    __tablename__ = "oauth_clients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    client_name: Mapped[str | None] = mapped_column(String(200))
    redirect_uris: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    grant_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    scope: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OAuthAuthorizationRequest(Base):
    """One /authorize request: pending until the user approves, then holds the code."""

    __tablename__ = "oauth_authorization_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(String(200))
    resource: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OAuthToken(Base):
    """Access or refresh token issued to a client on behalf of one user."""

    __tablename__ = "oauth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    token_type: Mapped[str] = mapped_column(String(10), nullable=False)  # access | refresh
    client_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    scope: Mapped[str | None] = mapped_column(String(200))
    resource: Mapped[str | None] = mapped_column(Text)
    # Tokens of one grant share a family id so a reused refresh token revokes the family.
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GaAssistantItemTime(Base):
    """Per-day time set by the GA assistant for one agenda item.

    Used for items whose time is otherwise a day-level value (task due dates) or
    a template-level value (BZ alignment time), so a "2 at 11:00" answer changes
    only that day and never the task's due date or the system template.
    ``removed`` hides the item from the assistant agenda for that day (soft, GA-scoped).
    """

    __tablename__ = "ga_assistant_item_times"
    __table_args__ = (UniqueConstraint("user_id", "item_key", "day_date", name="uq_ga_assistant_item_time"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    item_key: Mapped[str] = mapped_column(String(120), nullable=False)
    day_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    time_value: Mapped[str | None] = mapped_column(String(5))
    # True when the time row is an explicit choice (a NULL time then means "no time").
    has_time_override: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Soft "remove from GA's day": hides the item from the assistant agenda for this day only.
    removed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    removed_reason: Mapped[str | None] = mapped_column(String(1000))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
