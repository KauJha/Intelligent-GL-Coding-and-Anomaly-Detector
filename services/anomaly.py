import os
from dataclasses import dataclass

import anthropic
import numpy as np
from sqlalchemy.orm import Session

from models.audit import AuditLog
from models.transaction import GLClassification, Transaction

MODEL_VERSION = "claude-sonnet-4-6"
Z_SCORE_THRESHOLD = 3.0
MIN_HISTORY_SIZE = 10


@dataclass
class AnomalyResult:
    transaction_id: str
    z_score: float
    is_anomaly: bool
    explanation: str | None


def detect(transaction: Transaction, actor_id: str, db: Session) -> AnomalyResult:
    latest_classification = (
        db.query(GLClassification)
        .filter(GLClassification.transaction_id == transaction.id)
        .order_by(GLClassification.created_at.desc())
        .first()
    )

    if not latest_classification:
        return AnomalyResult(
            transaction_id=str(transaction.id),
            z_score=0.0,
            is_anomaly=False,
            explanation=None,
        )

    peer_amounts = _peer_amounts(latest_classification.gl_code, db)

    if len(peer_amounts) < MIN_HISTORY_SIZE:
        return AnomalyResult(
            transaction_id=str(transaction.id),
            z_score=0.0,
            is_anomaly=False,
            explanation="Insufficient historical data for anomaly detection.",
        )

    arr = np.array(peer_amounts, dtype=float)
    std = arr.std()
    z_score = float((float(transaction.amount) - arr.mean()) / std) if std > 0 else 0.0
    is_anomaly = abs(z_score) > Z_SCORE_THRESHOLD

    explanation = None
    if is_anomaly:
        explanation = _explain(transaction, latest_classification.gl_code, z_score)
        db.add(
            AuditLog(
                actor_id=actor_id,
                action="anomaly_detected",
                entity_type="transaction",
                entity_id=str(transaction.id),
                before_state=None,
                after_state={
                    "z_score": z_score,
                    "amount": str(transaction.amount),
                    "vendor": transaction.vendor_name,
                    "gl_code": latest_classification.gl_code,
                    "explanation": explanation,
                },
            )
        )
        db.commit()

    return AnomalyResult(
        transaction_id=str(transaction.id),
        z_score=z_score,
        is_anomaly=is_anomaly,
        explanation=explanation,
    )


def _peer_amounts(gl_code: str, db: Session) -> list[float]:
    rows = (
        db.query(Transaction)
        .join(GLClassification, GLClassification.transaction_id == Transaction.id)
        .filter(GLClassification.gl_code == gl_code)
        .order_by(Transaction.created_at.desc())
        .limit(200)
        .all()
    )
    return [float(r.amount) for r in rows]


def _explain(transaction: Transaction, gl_code: str, z_score: float) -> str:
    prompt = (
        f"A transaction has been flagged as statistically anomalous (z-score: {z_score:.2f}).\n"
        f"Vendor: {transaction.vendor_name}\n"
        f"Amount: {transaction.amount} {transaction.currency}\n"
        f"GL Code: {gl_code}\n"
        f"Description: {transaction.description or 'N/A'}\n\n"
        "In 2-3 sentences, explain why this amount is unusual for this GL code "
        "and what an accountant should verify."
    )
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL_VERSION,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()
