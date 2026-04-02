"""AI module database models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.core.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AiMessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class AiInsightSeverity(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ---------------------------------------------------------------------------
# Conversations & Messages
# ---------------------------------------------------------------------------

class AiConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    title: Mapped[str] = mapped_column(String(255), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), server_default=func.now(), onupdate=func.now(),
    )

    messages: Mapped[list["AiMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AiMessage.created_at",
    )


class AiMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True,
    )
    role: Mapped[AiMessageRole] = mapped_column(
        Enum(AiMessageRole, name="ai_message_role", native_enum=True),
    )
    content: Mapped[str] = mapped_column(Text)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), server_default=func.now(),
    )

    conversation: Mapped["AiConversation"] = relationship(back_populates="messages")


# ---------------------------------------------------------------------------
# Insights (from log analyzer)
# ---------------------------------------------------------------------------

class AiInsight(Base):
    __tablename__ = "ai_insights"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    severity: Mapped[AiInsightSeverity] = mapped_column(
        Enum(AiInsightSeverity, name="ai_insight_severity", native_enum=True),
    )
    issue_type: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)
    auto_fix_available: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_fix_action: Mapped[Optional[str]] = mapped_column(Text, default=None)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), server_default=func.now(),
    )


# ---------------------------------------------------------------------------
# Token usage tracking
# ---------------------------------------------------------------------------

class AiTokenUsage(Base):
    __tablename__ = "ai_token_usage"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None,
    )
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), server_default=func.now(),
    )


# ---------------------------------------------------------------------------
# AI Settings (singleton-style, one row)
# ---------------------------------------------------------------------------

class AiSettings(Base):
    __tablename__ = "ai_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    provider: Mapped[str] = mapped_column(String(32), default="openai")
    model: Mapped[str] = mapped_column(String(64), default="gpt-4o")
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(Text, default=None)
    base_url: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    auto_fix_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    log_analysis_interval: Mapped[str] = mapped_column(String(16), default="6h")
    max_tokens_per_request: Mapped[int] = mapped_column(Integer, default=2000)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
