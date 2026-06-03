"""Chat de titulación (1-1 con proceso) y sus mensajes."""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class ProcessChat(Base):
    __tablename__ = "titulatec_chats"

    id = Column(Integer, primary_key=True)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"), unique=True, nullable=False)
    pinned_document_id = Column(Integer, ForeignKey("titulatec_documents.id"), nullable=True)  # versión actual del proyecto
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

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
    author_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False)
    body = Column(Text, nullable=True)
    attachment_path = Column(String(255), nullable=True)
    attachment_name = Column(String(255), nullable=True)
    parent_id = Column(Integer, ForeignKey("titulatec_chat_messages.id"), nullable=True)  # reply/quote

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"), index=True)

    chat = relationship("ProcessChat", back_populates="messages")
    author = relationship("User", foreign_keys=[author_id])

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
            "parent_id": self.parent_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
