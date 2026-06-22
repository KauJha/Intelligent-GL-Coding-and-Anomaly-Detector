from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.audit import AuditLog
from models.transaction import GLClassification, Transaction
from services import anomaly as anomaly_service
from services import classifier as classifier_service

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    vendor_name: str
    amount: float
    currency: str = "USD"
    description: str | None = None
    transaction_date: datetime
    actor_id: str


class ReviewRequest(BaseModel):
    reviewer_id: str
    notes: str | None = None


class ClassificationOut(BaseModel):
    id: UUID
    gl_code: str
    confidence_score: float
    rationale: str
    model_version: str
    prompt_version: str
    reviewed_by: str | None
    requires_review: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TransactionOut(BaseModel):
    id: UUID
    vendor_name: str
    amount: float
    currency: str
    description: str | None
    transaction_date: datetime
    created_at: datetime
    latest_classification: ClassificationOut | None = None

    model_config = {"from_attributes": True}


# ── Helpers ────────────────────────────────────────────────────────────────

def _latest_classification(transaction_id: UUID, db: Session) -> GLClassification | None:
    return (
        db.query(GLClassification)
        .filter(GLClassification.transaction_id == transaction_id)
        .order_by(GLClassification.created_at.desc())
        .first()
    )


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("/transactions", status_code=status.HTTP_201_CREATED)
def create_transaction(body: TransactionCreate, db: Session = Depends(get_db)):
    txn = Transaction(
        vendor_name=body.vendor_name,
        amount=Decimal(str(body.amount)),
        currency=body.currency,
        description=body.description,
        transaction_date=body.transaction_date,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)

    classification = classifier_service.classify(txn, body.actor_id, db)
    anomaly_result = anomaly_service.detect(txn, body.actor_id, db)

    return {
        "transaction_id": str(txn.id),
        "classification": ClassificationOut.model_validate(classification),
        "anomaly": anomaly_result,
    }


@router.get("/transactions/{transaction_id}", response_model=TransactionOut)
def get_transaction(transaction_id: UUID, db: Session = Depends(get_db)):
    txn = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    out = TransactionOut.model_validate(txn)
    latest = _latest_classification(transaction_id, db)
    out.latest_classification = ClassificationOut.model_validate(latest) if latest else None
    return out


@router.post("/transactions/{transaction_id}/review", status_code=status.HTTP_201_CREATED)
def review_transaction(
    transaction_id: UUID,
    body: ReviewRequest,
    db: Session = Depends(get_db),
):
    """Inserts a new GLClassification row with reviewed_by set — never mutates existing rows."""
    latest = _latest_classification(transaction_id, db)
    if not latest:
        raise HTTPException(status_code=404, detail="No classification found for transaction")

    reviewed = GLClassification(
        transaction_id=latest.transaction_id,
        gl_code=latest.gl_code,
        confidence_score=latest.confidence_score,
        rationale=latest.rationale,
        model_version=latest.model_version,
        prompt_version=latest.prompt_version,
        reviewed_by=body.reviewer_id,
        requires_review=False,
    )
    db.add(reviewed)

    db.add(
        AuditLog(
            actor_id=body.reviewer_id,
            action="review",
            entity_type="gl_classification",
            entity_id=str(reviewed.id),
            before_state={"reviewed_by": None, "source_id": str(latest.id)},
            after_state={
                "reviewed_by": body.reviewer_id,
                "gl_code": reviewed.gl_code,
                "notes": body.notes,
            },
        )
    )

    db.commit()
    db.refresh(reviewed)
    return ClassificationOut.model_validate(reviewed)


@router.get("/review-queue", response_model=list[ClassificationOut])
def get_review_queue(db: Session = Depends(get_db)):
    pending = (
        db.query(GLClassification)
        .filter(
            GLClassification.requires_review == True,  # noqa: E712
            GLClassification.reviewed_by == None,  # noqa: E711
        )
        .order_by(GLClassification.created_at.asc())
        .all()
    )
    return [ClassificationOut.model_validate(c) for c in pending]
