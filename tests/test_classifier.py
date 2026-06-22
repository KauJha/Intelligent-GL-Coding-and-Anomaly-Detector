import json
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from models.transaction import Transaction
from services.classifier import AUTO_POST_CONFIDENCE_THRESHOLD, HIGH_VALUE_THRESHOLD, classify


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.refresh = MagicMock(side_effect=lambda obj: obj)
    return db


@pytest.fixture
def transaction():
    return Transaction(
        id=uuid4(),
        vendor_name="Office Depot",
        amount=Decimal("450.00"),
        currency="USD",
        description="Office supplies Q1",
        transaction_date=datetime(2024, 1, 15),
    )


@pytest.fixture
def high_value_transaction():
    return Transaction(
        id=uuid4(),
        vendor_name="Acme Corp",
        amount=Decimal("15000.00"),
        currency="USD",
        description="Equipment purchase",
        transaction_date=datetime(2024, 1, 15),
    )


def _fake_response(gl_code="6100", confidence=0.95, rationale="Operating expense."):
    content = MagicMock()
    content.text = json.dumps(
        {"gl_code": gl_code, "confidence_score": confidence, "rationale": rationale}
    )
    response = MagicMock()
    response.content = [content]
    return response


@patch("services.classifier.anthropic.Anthropic")
def test_classify_returns_classification(mock_cls, mock_db, transaction, monkeypatch):
    monkeypatch.setenv("PROMPT_VERSION", "v1.0")
    mock_cls.return_value.messages.create.return_value = _fake_response()

    result = classify(transaction, actor_id="user-1", db=mock_db)

    assert result.gl_code == "6100"
    assert float(result.confidence_score) == 0.95
    assert result.reviewed_by is None
    assert result.model_version == "claude-sonnet-4-6"
    assert result.prompt_version == "v1.0"


@patch("services.classifier.anthropic.Anthropic")
def test_high_value_always_requires_review(mock_cls, mock_db, high_value_transaction, monkeypatch):
    monkeypatch.setenv("PROMPT_VERSION", "v1.0")
    mock_cls.return_value.messages.create.return_value = _fake_response(confidence=0.99)

    with patch("services.classifier._enqueue_review"):
        result = classify(high_value_transaction, actor_id="user-1", db=mock_db)

    assert result.requires_review is True
    assert high_value_transaction.amount >= HIGH_VALUE_THRESHOLD


@patch("services.classifier.anthropic.Anthropic")
def test_low_confidence_requires_review(mock_cls, mock_db, transaction, monkeypatch):
    monkeypatch.setenv("PROMPT_VERSION", "v1.0")
    low_confidence = AUTO_POST_CONFIDENCE_THRESHOLD - 0.05
    mock_cls.return_value.messages.create.return_value = _fake_response(confidence=low_confidence)

    with patch("services.classifier._enqueue_review"):
        result = classify(transaction, actor_id="user-1", db=mock_db)

    assert result.requires_review is True


@patch("services.classifier.anthropic.Anthropic")
def test_high_confidence_normal_value_no_review(mock_cls, mock_db, transaction, monkeypatch):
    monkeypatch.setenv("PROMPT_VERSION", "v1.0")
    mock_cls.return_value.messages.create.return_value = _fake_response(confidence=0.95)

    result = classify(transaction, actor_id="user-1", db=mock_db)

    assert result.requires_review is False


def test_missing_prompt_version_raises(mock_db, transaction, monkeypatch):
    monkeypatch.delenv("PROMPT_VERSION", raising=False)

    with pytest.raises(KeyError):
        classify(transaction, actor_id="user-1", db=mock_db)


@patch("services.classifier.anthropic.Anthropic")
def test_audit_log_and_classification_both_written(mock_cls, mock_db, transaction, monkeypatch):
    monkeypatch.setenv("PROMPT_VERSION", "v1.0")
    mock_cls.return_value.messages.create.return_value = _fake_response()

    classify(transaction, actor_id="user-42", db=mock_db)

    # db.add must be called twice: once for GLClassification, once for AuditLog
    assert mock_db.add.call_count == 2
    assert mock_db.commit.called
