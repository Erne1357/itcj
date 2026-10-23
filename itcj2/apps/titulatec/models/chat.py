"""Chat de titulación (1-1 con proceso), sus mensajes y las marcas de lectura."""
from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base

# Tipos de mensaje: `message` lo escribe una persona; `system`, `version` y
# `vote` los escribe el sistema (`author_id` NULL en `system`). Fase 5.
CHAT_KINDS = ("message", "system", "version", "vote")


class ProcessChat(Base):
    __tablename__ = "titulatec_chats"

    id = Column(Integer, primary_key=True)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"), unique=True, nullable=False)
    # Legado sin uso (spec fase 5 §5, CLAUDE.md de la app §26): las versiones del
    # proyecto viven en `titulatec_review_versions`; nadie lee ni escribe esta columna.
    pinned_document_id = Column(Integer, ForeignKey("titulatec_documents.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    closed_at = Column(DateTime, nullable=True)                   # NULL = abierto (fase 5)

    process = relationship("TitulationProcess", back_populates="chat")
    messages = relationship(
        "ChatMessage", back_populates="chat",
        cascade="all, delete-orphan", order_by="ChatMessage.created_at",
    )

    def __repr__(self) -> str:
        return f"<ProcessChat p{self.process_id}>"


class ChatMessage(Base):
    __tablename__ = "titulatec_chat_messages"

    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey("titulatec_chats.id"), nullable=False, index=True)
    author_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)  # NULL = sistema
    body = Column(Text, nullable=True)
    attachment_path = Column(String(255), nullable=True)
    attachment_name = Column(String(255), nullable=True)
    attachment_mime = Column(String(100), nullable=True)
    attachment_size = Column(Integer, nullable=True)
    parent_id = Column(Integer, ForeignKey("titulatec_chat_messages.id"), nullable=True)  # reply/quote

    kind = Column(String(20), nullable=False, server_default=text("'message'"))  # CHAT_KINDS
    version_id = Column(Integer, ForeignKey("titulatec_review_versions.id"),
                        nullable=True, index=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"), index=True)

    chat = relationship("ProcessChat", back_populates="messages")
    author = relationship("User", foreign_keys=[author_id])

    __table_args__ = (
        Index("ix_titulatec_chat_messages_chat_id_id", "chat_id", "id"),
    )

    def __repr__(self) -> str:
        return f"<ChatMessage c{self.chat_id} u{self.author_id}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "author_id": self.author_id,
            "body": self.body,
            "attachment_path": self.attachment_path,
            "attachment_name": self.attachment_name,
            "attachment_mime": self.attachment_mime,
            "attachment_size": self.attachment_size,
            "parent_id": self.parent_id,
            "kind": self.kind,
            "version_id": self.version_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ChatRead(Base):
    """Último mensaje leído por un usuario en un chat (PK compuesta)."""
    __tablename__ = "titulatec_chat_reads"

    chat_id = Column(Integer, ForeignKey("titulatec_chats.id"), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("core_users.id"), primary_key=True)
    last_read_message_id = Column(Integer, nullable=False)
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"),
                        onupdate=func.now())

    def __repr__(self) -> str:
        return f"<ChatRead c{self.chat_id} u{self.user_id} m{self.last_read_message_id}>"
