"""FastAPI adapter for LinePulse AI.

Run from the project root with:
    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from linepulse.service import LinePulseService


app = FastAPI(
    title="LinePulse AI",
    description=(
        "Explainable maintenance-priority API for the official synthetic "
        "hackathon workbook. Human approval is mandatory."
    ),
)

origins = [
    item.strip()
    for item in os.getenv("LINEPULSE_CORS_ORIGINS", "http://localhost:8501").split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def get_service() -> LinePulseService:
    """Build once per API process; avoids retraining on every request."""

    return LinePulseService()


class DecisionRequest(BaseModel):
    asset_id: str = Field(min_length=1)
    decision: Literal["APPROVE", "MODIFY", "REJECT"]
    rationale: str = Field(min_length=1)
    owner: str = Field(default="Equipment Owner", min_length=1)
    modified_action: str | None = None


class OutcomeRequest(BaseModel):
    outcome: Literal["RESOLVED", "PARTIAL", "UNRESOLVED"]
    notes: str = ""
    verified_by: str = Field(default="Equipment Owner", min_length=1)


class WhatIfRequest(BaseModel):
    duty_reduction_pct: float = Field(default=0, ge=0, le=100)
    start_stop_reduction_pct: float = Field(default=0, ge=0, le=100)


def _not_found(label: str, identifier: object, exc: KeyError) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Unknown {label}: {identifier}")


@app.get("/")
def root() -> dict:
    return {
        "name": "LinePulse AI",
        "purpose": "Human-led predictive maintenance decision support",
        "docs": "/docs",
        "health": "/api/v1/health",
        "readiness": "/api/v1/readiness",
        "equipment_write_capability": False,
    }


@app.get("/api/v1/health")
def health() -> dict:
    """Process liveness; intentionally does not require loading the model."""

    return {"status": "ok", "equipment_write_capability": False}


@app.get("/api/v1/readiness")
def readiness() -> dict:
    overview = get_service().overview()
    return {
        "status": overview["status"],
        "assets": overview["total_assets"],
        "model": overview["model"],
        "data_source": overview["data"]["source"],
        "decision_memory": overview["learning_summary"],
        "equipment_write_capability": False,
    }


@app.get("/api/v1/overview")
def overview() -> dict:
    return get_service().overview()


@app.get("/api/v1/portfolio")
def portfolio(
    status: str | None = Query(default=None, description="RED, AMBER or GREEN"),
    line: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=100),
) -> dict:
    try:
        return get_service().portfolio(status=status, line=line, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/assets/{asset_id}")
def asset_detail(asset_id: str) -> dict:
    try:
        return get_service().asset_detail(asset_id)
    except KeyError as exc:
        raise _not_found("asset", asset_id, exc) from exc


@app.get("/api/v1/data-quality")
def data_quality() -> dict:
    overview_payload = get_service().overview()
    return {
        "source": overview_payload["data"]["source"],
        "data_quality": overview_payload["data"]["data_quality"],
        "excluded_from_model_inputs": overview_payload["data"][
            "excluded_from_model_inputs"
        ],
    }


@app.get("/api/v1/model")
def model_information() -> dict:
    overview_payload = get_service().overview()
    return {
        "model": overview_payload["model"],
        "data": overview_payload["data"],
        "claim_boundary": (
            "The model detects supplied-workbook degradation patterns. It does "
            "not claim production failure probability or certified RUL."
        ),
    }


@app.get("/api/v1/cases")
def cases(
    limit: int = Query(default=100, ge=1, le=500),
    asset_id: str | None = Query(default=None),
) -> dict:
    items = get_service().list_cases(limit=limit, asset_id=asset_id)
    return {"total": len(items), "items": items, "equipment_action_taken": False}


@app.get("/api/v1/cases/{case_id}")
def case_detail(case_id: int) -> dict:
    try:
        return get_service().get_case(case_id)
    except KeyError as exc:
        raise _not_found("case", case_id, exc) from exc


@app.post("/api/v1/decisions", status_code=201)
def record_decision(body: DecisionRequest) -> dict:
    try:
        return get_service().record_decision(
            asset_id=body.asset_id,
            decision=body.decision,
            rationale=body.rationale,
            owner=body.owner,
            modified_action=body.modified_action,
        )
    except KeyError as exc:
        raise _not_found("asset", body.asset_id, exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/cases/{case_id}/outcome")
def record_outcome(case_id: int, body: OutcomeRequest) -> dict:
    try:
        return get_service().record_outcome(
            case_id,
            body.outcome,
            notes=body.notes,
            verified_by=body.verified_by,
        )
    except KeyError as exc:
        raise _not_found("case", case_id, exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/assets/{asset_id}/what-if")
def what_if(asset_id: str, body: WhatIfRequest) -> dict:
    try:
        return get_service().what_if(
            asset_id,
            duty_reduction_pct=body.duty_reduction_pct,
            start_stop_reduction_pct=body.start_stop_reduction_pct,
        )
    except KeyError as exc:
        raise _not_found("asset", asset_id, exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/demo/reset")
def reset_demo() -> dict:
    """Remove user-created demo decisions/outcomes; source data stays intact."""

    return get_service().reset_demo()
