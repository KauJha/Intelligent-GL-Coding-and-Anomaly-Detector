# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# GL Coding & Anomaly Detector

## Project overview
AI-powered GL classification and anomaly detection system for accounting teams.
FastAPI backend, React frontend, PostgreSQL + Redis, deployed on Railway (dev) / AWS ECS (prod).

## Tech stack
- Backend: Python 3.11, FastAPI, SQLAlchemy, Alembic
- AI: anthropic SDK, model claude-sonnet-4-6
- DB: PostgreSQL (audit-grade, append-only for SOX compliance)
- Queue: Redis + RQ for async batch jobs
- Frontend: React + Tailwind

## Key architectural rules (NEVER violate these)
- gl_classifications table is APPEND-ONLY. Never UPDATE or DELETE rows. Corrections insert new rows.
- Every AI inference must log model_version and prompt_version.
- No transaction auto-posts without reviewed_by being non-null.
- Transactions above $10,000 always route to review queue regardless of confidence score.
- PROMPT_VERSION env var must be pinned — never let it float.

## Commands
- Start dev server: `uvicorn main:app --reload`
- Run tests: `pytest tests/ -v`
- DB migrations: `alembic upgrade head`
- Start worker: `rq worker --with-scheduler`
- Lint: `ruff check . && mypy .`

## File structure
- services/classifier.py — Claude classification logic
- services/anomaly.py — z-score + LLM explanation layer
- models/ — SQLAlchemy ORM models
- api/ — FastAPI route handlers
- prompts/ — versioned prompt templates (v1.0.txt, v1.1.txt, etc.)
- tests/ — pytest test suite

## SOX compliance notes
- audit_log table: INSERT only, no UPDATE/DELETE ever
- Every financial action needs actor_id, before_state, after_state in JSONB
- Prompt changes must be logged as config_change events before taking effect
