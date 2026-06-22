import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_name = Column(String(255), nullable=False)
    amount = Column(Numeric(15, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    description = Column(Text, nullable=True)
    transaction_date = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    classifications = relationship("GLClassification", back_populates="transaction")


class GLClassification(Base):
    """Append-only. Never UPDATE or DELETE — corrections insert new rows."""

    __tablename__ = "gl_classifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id = Column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False, index=True
    )
    gl_code = Column(String(20), nullable=False)
    confidence_score = Column(Numeric(4, 3), nullable=False)
    rationale = Column(Text, nullable=False)
    model_version = Column(String(50), nullable=False)
    prompt_version = Column(String(20), nullable=False)
    reviewed_by = Column(String(255), nullable=True)  # null = unreviewed; must be set to auto-post
    requires_review = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    transaction = relationship("Transaction", back_populates="classifications")
