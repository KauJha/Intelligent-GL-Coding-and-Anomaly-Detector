import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from database import Base


class AuditLog(Base):
    """INSERT-only. Never UPDATE or DELETE. Required for SOX compliance."""

    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id = Column(String(255), nullable=False)
    action = Column(String(100), nullable=False)  # classify | review | anomaly_detected | config_change
    entity_type = Column(String(100), nullable=False)
    entity_id = Column(String(255), nullable=False)
    before_state = Column(JSONB, nullable=True)
    after_state = Column(JSONB, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
