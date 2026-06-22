import json
import os
from decimal import Decimal

import anthropic
from sqlalchemy.orm import Session

from models.audit import AuditLog
from models.transaction import GLClassification, Transaction

MODEL_VERSION = "claude-sonnet-4-6"
HIGH_VALUE_THRESHOLD = Decimal("10000.00")
AUTO_POST_CONFIDENCE_THRESHOLD = 0.90


def classify(transaction: Transaction, actor_id: str, db: Session) -> GLClassification:
    # KeyError here is intentional — PROMPT_VERSION must always be explicitly pinned
    prompt_version = os.environ["PROMPT_VERSION"]

    prompt = _build_prompt(prompt_version, transaction)

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL_VERSION,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    parsed = json.loads(response.content[0].text.strip())
    gl_code: str = parsed["gl_code"]
    confidence_score: float = float(parsed["confidence_score"])
    rationale: str = parsed["rationale"]

    high_value = transaction.amount >= HIGH_VALUE_THRESHOLD
    requires_review = high_value or confidence_score < AUTO_POST_CONFIDENCE_THRESHOLD

    classification = GLClassification(
        transaction_id=transaction.id,
        gl_code=gl_code,
        confidence_score=confidence_score,
        rationale=rationale,
        model_version=MODEL_VERSION,
        prompt_version=prompt_version,
        reviewed_by=None,
        requires_review=requires_review,
    )
    db.add(classification)

    db.add(
        AuditLog(
            actor_id=actor_id,
            action="classify",
            entity_type="gl_classification",
            entity_id=str(classification.id),
            before_state=None,
            after_state={
                "transaction_id": str(transaction.id),
                "gl_code": gl_code,
                "confidence_score": confidence_score,
                "model_version": MODEL_VERSION,
                "prompt_version": prompt_version,
                "requires_review": requires_review,
            },
        )
    )

    db.commit()
    db.refresh(classification)

    if requires_review:
        _enqueue_review(classification.id)

    return classification


def _build_prompt(prompt_version: str, transaction: Transaction) -> str:
    with open(f"prompts/{prompt_version}.txt") as f:
        template = f.read()
    return template.format(
        vendor=transaction.vendor_name,
        amount=str(transaction.amount),
        currency=transaction.currency,
        description=transaction.description or "",
        transaction_date=transaction.transaction_date.date().isoformat(),
    )


def _enqueue_review(classification_id) -> None:
    import redis
    from rq import Queue

    q = Queue("review", connection=redis.from_url(os.environ["REDIS_URL"]))
    q.enqueue("workers.notify_review", str(classification_id))
