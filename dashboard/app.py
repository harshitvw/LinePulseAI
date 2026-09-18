"""LinePulse AI maintenance operations dashboard."""

from __future__ import annotations

import html
import inspect
import logging
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from linepulse.service import LinePulseService
from linepulse.openai_assistant import (
    AssistantUnavailableError,
    answer_question,
    build_assistant_context,
    is_configured,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATUS_COLORS = {"RED": "#F04438", "AMBER": "#F79009", "GREEN": "#12B76A"}
STATUS_DARK = {"RED": "#7A271A", "AMBER": "#7A2E0E", "GREEN": "#05603A"}
STATUS_LABELS = {
    "RED": "Review now",
    "AMBER": "Plan inspection",
    "GREEN": "Continue monitoring",
}
LOGGER = logging.getLogger("linepulse.dashboard")


st.set_page_config(
    page_title="LinePulse AI | Class A Asset Intelligence",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

DARK_MODE = bool(st.session_state.get("dark_mode", False))
INK = "#F2F4F7" if DARK_MODE else "#17202D"
MUTED = "#98A2B3" if DARK_MODE else "#667085"
GRID = "#344054" if DARK_MODE else "#E4E7EC"


def _h(value: Any) -> str:
    """Escape every value originating in a workbook, database, or form."""

    return html.escape(str(value if value is not None else ""), quote=True)


def _user_error(message: str, exc: Exception) -> None:
    """Show a safe message in the UI and preserve diagnostics in server logs."""

    LOGGER.exception("%s", message, exc_info=exc)
    st.error(message)


st.markdown(
    """
    <style>
    :root {
      --lp-bg: #f4f7fa;
      --lp-panel: #ffffff;
      --lp-panel-2: #f8fafc;
      --lp-border: #d7dee7;
      --lp-ink: #17202d;
      --lp-muted: #667085;
      --lp-text-2: #344054;
      --lp-blue: #00677f;
      --lp-red: #d92d20;
      --lp-amber: #dc6803;
      --lp-green: #07883f;
      --lp-red-bg: #ffe9e7;
      --lp-amber-bg: #fff2cc;
      --lp-green-bg: #dcfae6;
    }

    html, body, [class*="css"] {
      font-family: Inter, "Segoe UI", Arial, sans-serif;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }
    .stApp { background: var(--lp-bg); color: var(--lp-ink); }
    .block-container {
      max-width:1480px; padding-top:1.1rem !important; padding-bottom:3rem;
    }
    [data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"] { display:none !important; }
    [data-testid="stAppViewContainer"] > .main { padding-top:0 !important; }
    [data-testid="stSidebar"], [data-testid="collapsedControl"] { display:none; }
    h1, h2, h3 { color: var(--lp-ink); letter-spacing: -.025em; }
    p, label { color: var(--lp-text-2); }
    hr { border-color: var(--lp-border) !important; }

    .lp-topbar {
      display:flex; align-items:center; justify-content:space-between; gap:1.5rem;
      background:var(--lp-panel); border:1px solid var(--lp-border); border-radius:1rem;
      min-height:4.25rem; padding:.8rem 1rem; margin-top:0; overflow:visible;
      box-sizing:border-box; box-shadow:0 3px 14px rgba(16,24,40,.055);
    }
    .lp-wordmark { display:flex; align-items:center; gap:.72rem; margin:0; }
    .lp-logo {
      width:2.35rem; height:2.35rem; display:grid; place-items:center;
      border:1px solid #00677f; border-radius:.7rem; color:#ffffff;
      background:#00677f; font-size:1.05rem; font-weight:800; flex:0 0 2.35rem;
    }
    .lp-brand { color:var(--lp-ink); font-size:1.08rem; font-weight:760; line-height:1.1; }
    .lp-brand-sub { color:var(--lp-muted); font-size:.72rem; margin-top:.2rem; }
    .lp-topmeta { display:flex; align-items:center; gap:.65rem; }
    .lp-snapshot { color:var(--lp-muted); font-size:.72rem; text-align:right; line-height:1.35; }
    .lp-snapshot strong { color:var(--lp-ink); display:block; font-size:.8rem; }
    .lp-readonly {
      display:inline-flex; align-items:center; gap:.34rem; color:#05603a; background:#ecfdf3;
      border:1px solid #abefc6; border-radius:999px; padding:.4rem .62rem;
      font-size:.68rem; font-weight:760; white-space:nowrap;
    }

    div[data-testid="stSegmentedControl"] { margin:0; }
    div[data-testid="stSegmentedControl"] button { min-height:2.35rem; font-weight:700; }
    .lp-page-title { margin:.25rem 0 .85rem; }
    .lp-page-title h1 { margin:0 0 .2rem; font-size:1.55rem; line-height:1.15; }
    .lp-page-title p { color:var(--lp-muted); margin:0; font-size:.82rem; }
    div[data-testid="stVerticalBlockBorderWrapper"] {
      background:var(--lp-panel); border-color:var(--lp-border); border-radius:.8rem;
      margin:.55rem 0 .95rem;
    }

    .lp-kicker {
      color:#00677f; text-transform:uppercase; letter-spacing:.11em;
      font-weight:760; font-size:.7rem;
    }

    .lp-section-head { display:flex; align-items:flex-end; justify-content:space-between; gap:1rem; margin:1.25rem 0 .65rem; }
    .lp-section-title { color:var(--lp-ink); font-size:1.12rem; font-weight:750; }
    .lp-section-copy { color:var(--lp-muted); font-size:.82rem; margin-top:.17rem; }

    .lp-summary {
      position:relative; overflow:visible; min-height:7.1rem; padding:1rem 1.05rem;
      border-radius:.9rem; color:var(--lp-ink); border:1px solid var(--lp-border);
      border-top:5px solid var(--status); box-shadow:0 4px 14px rgba(16,24,40,.06);
    }
    .lp-summary.red { --status:#d92d20; background:var(--lp-red-bg); }
    .lp-summary.amber { --status:#dc6803; background:var(--lp-amber-bg); }
    .lp-summary.green { --status:#07883f; background:var(--lp-green-bg); }
    .lp-summary-label { font-size:.77rem; font-weight:780; letter-spacing:.05em; text-transform:uppercase; }
    .lp-summary-value { color:var(--status); font-size:2.2rem; line-height:1; font-weight:800; margin:.62rem 0 .32rem; }
    .lp-summary-copy { font-size:.78rem; color:var(--lp-muted); }

    .lp-help {
      position:absolute; top:.72rem; right:.72rem; width:1.35rem; height:1.35rem;
      display:grid; place-items:center; border-radius:50%; cursor:help;
      background:var(--status, #00677f); border:1px solid var(--status, #00677f);
      color:white; font-size:.8rem; font-weight:850; z-index:20;
    }
    .lp-help .lp-tip {
      visibility:hidden; opacity:0; pointer-events:none; position:absolute;
      right:0; top:1.75rem; width:19rem; padding:.72rem .8rem;
      color:#ffffff; background:#17202d; border:1px solid #344054; border-radius:.55rem;
      box-shadow:0 14px 34px rgba(0,0,0,.45); font-size:.74rem; font-weight:500;
      line-height:1.4; text-transform:none; letter-spacing:normal; text-align:left;
      transition:opacity .12s ease;
    }
    .lp-help:hover .lp-tip, .lp-help:focus .lp-tip { visibility:visible; opacity:1; }

    .lp-asset-card {
      position:relative; overflow:visible; min-height:11.6rem; padding:1rem;
      border-radius:.9rem; color:var(--lp-ink); border:1px solid var(--lp-border);
      border-left:6px solid var(--status); box-shadow:0 4px 14px rgba(16,24,40,.06); margin-bottom:.45rem;
    }
    .lp-asset-card.red { --status:#d92d20; background:var(--lp-red-bg); }
    .lp-asset-card.amber { --status:#dc6803; background:var(--lp-amber-bg); }
    .lp-asset-card.green { --status:#07883f; background:var(--lp-green-bg); }
    .lp-asset-rank { color:var(--lp-muted); font-size:.68rem; font-weight:760; letter-spacing:.09em; text-transform:uppercase; }
    .lp-asset-name { font-size:1.05rem; font-weight:800; margin:.55rem 2rem .12rem 0; line-height:1.18; }
    .lp-asset-meta { color:var(--lp-text-2); font-size:.74rem; min-height:2.2rem; }
    .lp-days { margin:.92rem 0 .55rem; font-size:1.48rem; font-weight:830; line-height:1; }
    .lp-days small { font-size:.69rem; font-weight:620; color:var(--lp-muted); }
    .lp-card-bottom { display:flex; justify-content:space-between; gap:.6rem; font-size:.7rem; color:var(--lp-text-2); }

    .lp-panel {
      background:var(--lp-panel); border:1px solid var(--lp-border); border-radius:.9rem;
      padding:1rem 1.08rem; margin-bottom:.75rem;
    }
    .lp-panel-label { color:#00677f; font-size:.69rem; font-weight:760; letter-spacing:.1em; text-transform:uppercase; }
    .lp-panel-value { color:var(--lp-ink); font-weight:780; margin-top:.3rem; }
    .lp-panel-copy { color:var(--lp-muted); font-size:.79rem; line-height:1.45; margin-top:.35rem; }

    .lp-status-pill {
      display:inline-flex; align-items:center; gap:.38rem; color:white; padding:.3rem .57rem;
      border-radius:999px; font-size:.7rem; font-weight:790; letter-spacing:.055em;
    }
    .lp-dot { width:.46rem; height:.46rem; border-radius:50%; background:white; }

    .lp-asset-hero {
      display:grid; grid-template-columns:minmax(0,1fr) auto; gap:1.5rem; align-items:center;
      position:relative; padding:1.05rem 1.15rem; border-radius:.85rem; border:1px solid var(--lp-border); background:var(--lp-panel);
      margin-bottom:.8rem;
    }
    .lp-asset-hero h2 { margin:.25rem 0; }
    .lp-asset-hero p { margin:.15rem 0 0; color:var(--lp-muted); }
    .lp-horizon { text-align:right; min-width:9rem; }
    .lp-horizon strong { display:block; color:var(--lp-ink); font-size:2.2rem; line-height:1; }
    .lp-horizon span { color:var(--lp-muted); font-size:.73rem; }

    .lp-kpi {
      min-height:7rem; padding:.95rem 1rem; border:1px solid var(--lp-border);
      background:var(--lp-panel); border-radius:.82rem; box-shadow:0 2px 8px rgba(16,24,40,.04);
    }
    .lp-kpi-label { color:var(--lp-muted); font-size:.72rem; }
    .lp-kpi-value { color:var(--lp-ink); font-size:1.55rem; font-weight:800; margin:.42rem 0 .18rem; }
    .lp-kpi-note { color:var(--lp-muted); font-size:.68rem; line-height:1.3; }

    .lp-evidence {
      min-height:10.8rem; padding:1rem; border-radius:.85rem; background:var(--lp-panel);
      border:1px solid var(--lp-border); border-top:3px solid #00677f; margin-bottom:.5rem;
    }
    .lp-source { color:#00677f; font-size:.65rem; font-weight:780; letter-spacing:.09em; text-transform:uppercase; }
    .lp-evidence h4 { color:var(--lp-ink); margin:.48rem 0 .38rem; font-size:.94rem; }
    .lp-evidence-main { color:var(--lp-text-2); font-size:.82rem; font-weight:680; min-height:2rem; }
    .lp-evidence-reason { color:var(--lp-muted); font-size:.73rem; line-height:1.42; margin-top:.62rem; }
    .lp-evidence-foot { color:var(--lp-muted); font-size:.67rem; margin-top:.62rem; border-top:1px solid var(--lp-border); padding-top:.5rem; }

    .lp-action {
      background:var(--lp-green-bg); border:1px solid #12b76a;
      border-left:5px solid var(--lp-green); border-radius:.9rem; padding:1.1rem 1.2rem;
    }
    .lp-action h3 { margin:.28rem 0 .42rem; }
    .lp-action p { color:var(--lp-text-2); margin:.2rem 0; }

    div[data-testid="stDataFrame"] { border:1px solid var(--lp-border); border-radius:.8rem; overflow:hidden; }
    div[data-testid="stMetric"] { background:var(--lp-panel); border:1px solid var(--lp-border); padding:.8rem 1rem; border-radius:.8rem; }
    .stButton button, .stFormSubmitButton button { border-radius:.6rem; font-weight:700; }
    .stAlert { border-radius:.72rem; }
    [data-testid="stExpander"] { background:var(--lp-panel); border-color:var(--lp-border); }

    @media (max-width: 760px) {
      .lp-topbar { align-items:flex-start; }
      .lp-topmeta { align-items:flex-end; flex-direction:column; }
      .lp-snapshot { display:none; }
      .lp-asset-hero { grid-template-columns:1fr; }
      .lp-horizon { text-align:left; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if DARK_MODE:
    st.markdown(
        """
        <style>
        :root {
          --lp-bg:#0b1220;
          --lp-panel:#121c2c;
          --lp-panel-2:#172334;
          --lp-border:#334155;
          --lp-ink:#f2f4f7;
          --lp-muted:#98a2b3;
          --lp-text-2:#d0d5dd;
          --lp-blue:#22b8cf;
          --lp-red-bg:#411d22;
          --lp-amber-bg:#422f13;
          --lp-green-bg:#123526;
        }
        .lp-kicker, .lp-panel-label, .lp-source { color:#67e8f9; }
        .lp-readonly { color:#a6f4c5; background:#123526; border-color:#087443; }
        div[data-baseweb="select"] > div,
        div[data-baseweb="input"] > div,
        textarea { background:var(--lp-panel) !important; color:var(--lp-ink) !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, pd.Series):
        return value.to_dict()
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return dict(value.model_dump())
    if hasattr(value, "dict"):
        return dict(value.dict())
    return {}


def _to_records(value: Any, preferred_keys: Iterable[str] = ()) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, pd.DataFrame):
        return value.to_dict("records")
    if isinstance(value, Mapping):
        payload = dict(value)
        for key in (*preferred_keys, "items", "assets", "portfolio", "cases", "data"):
            if key in payload and payload[key] is not value:
                nested = _to_records(payload[key])
                if nested or isinstance(payload[key], (list, tuple, pd.DataFrame)):
                    return nested
        return [payload]
    if isinstance(value, (list, tuple)):
        return [_to_dict(item) for item in value]
    return []


def _get(row: Mapping[str, Any] | None, *keys: str, default: Any = None) -> Any:
    if not row:
        return default
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return default


def _num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        if pd.isna(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def _score(value: Any) -> float:
    """Normalize either 0..1 or 0..100 scores for display."""

    number = _num(value)
    return number * 100.0 if 0.0 <= number <= 1.0 else number


def _status(value: Any) -> str:
    candidate = str(value or "AMBER").upper()
    return candidate if candidate in STATUS_COLORS else "AMBER"


def _boolish(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"true", "yes", "1", "ambiguous"}
    return bool(value)


def _days_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "Not estimable"
    days = max(0.0, _num(value))
    return f"{days:.0f} day" + ("" if round(days) == 1 else "s")


def _call(method: Any, *args: Any, **kwargs: Any) -> Any:
    """Call service methods while tolerating harmless signature evolution."""

    try:
        signature = inspect.signature(method)
        accepts_kwargs = any(p.kind == p.VAR_KEYWORD for p in signature.parameters.values())
        clean = kwargs if accepts_kwargs else {key: value for key, value in kwargs.items() if key in signature.parameters}
    except (TypeError, ValueError):
        clean = kwargs
    return method(*args, **clean)


def _source_workbook() -> Path:
    configured = os.getenv("LINEPULSE_DATA_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    preferred = PROJECT_ROOT / "data" / "source" / "Synthetic_Dataset.xlsx"
    if preferred.exists():
        return preferred
    candidates = sorted((PROJECT_ROOT / "data" / "source").glob("*.xlsx"))
    return candidates[0] if candidates else preferred


@st.cache_resource(show_spinner="Preparing the maintenance view…")
def get_service(
    workbook_path: str,
    workbook_size: int,
    workbook_modified_ns: int,
) -> LinePulseService:
    """Cache by source-file identity so a replaced workbook cannot stay stale."""

    del workbook_size, workbook_modified_ns
    workbook = Path(workbook_path)
    runtime = PROJECT_ROOT / "runtime"
    artifacts = PROJECT_ROOT / "artifacts"
    runtime.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)

    candidates = {
        "data_path": workbook,
        "workbook_path": workbook,
        "db_path": Path(os.getenv("LINEPULSE_DB_PATH", runtime / "linepulse.db")),
        "model_path": Path(os.getenv("LINEPULSE_MODEL_PATH", artifacts / "degradation_model.joblib")),
    }
    try:
        signature = inspect.signature(LinePulseService)
        kwargs = {name: value for name, value in candidates.items() if name in signature.parameters}
        return LinePulseService(**kwargs)
    except TypeError:
        return LinePulseService()


def _normalize_asset(item: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(item)
    return {
        **row,
        "asset_id": str(_get(row, "asset_id", "AssetID", "id", default="Unknown")),
        "name": str(_get(row, "name", "asset_name", "AssetName", default="Class A asset")),
        "type": str(_get(row, "type", "asset_type", "AssetType", default="Asset")),
        "line": str(_get(row, "line", "Line", "area", default="Unassigned")),
        "status": _status(_get(row, "status", "operational_status", "rag_status")),
        "model_status": _status(_get(row, "model_status", "original_status", default=_get(row, "status", default="AMBER"))),
        "days_remaining": _get(row, "days_remaining", "estimated_days_remaining", "horizon_days"),
        "degradation_likelihood": _score(_get(row, "degradation_likelihood", "likelihood", "anomaly_percentile")),
        "technical_risk": _score(_get(row, "technical_risk", "risk_score")),
        "attention_priority": _score(_get(row, "attention_priority", "priority", "priority_score")),
        "business_impact": _score(_get(row, "business_impact", "business_impact_score", "BusinessImpactScore")),
        "data_confidence": _score(_get(row, "data_confidence", "confidence")),
        "failure_mode": str(_get(row, "failure_mode", "likely_failure_mode", default="Combined degradation pattern")),
        "recommended_action": str(_get(row, "recommended_action", "action", default="Review the evidence before choosing an intervention.")),
        "evidence_passport": _get(row, "evidence_passport", "evidence", default=[]),
        "data_quality_flags": _get(row, "data_quality_flags", "quality_flags", default=[]),
        "is_ambiguous": _boolish(_get(row, "is_ambiguous", "ambiguous_case", "ambiguous", "borderline", default=False)),
        "ambiguity_reason": str(_get(row, "ambiguity_reason", "uncertainty_reason", default="Evidence is mixed or close to a decision boundary.")),
        "learning_summary": _get(row, "learning_summary", "verified_outcome_memory", "similar_cases"),
    }


def _status_reason(asset: Mapping[str, Any]) -> str:
    explicit = _get(asset, "display_reason", "status_reason", "classification_reason", "why_status")
    if explicit:
        return str(explicit)
    evidence = _to_records(_get(asset, "evidence_passport", "evidence", default=[]))
    if evidence:
        reason = _get(evidence[0], "reason", "explanation", "finding", "message")
        if reason:
            return str(reason)
    return (
        f"{asset['failure_mode']} is the leading hypothesis; technical risk "
        f"{asset['technical_risk']:.0f}/100 and business impact {asset['business_impact']:.0f}/100 "
        f"produce attention priority {asset['attention_priority']:.0f}/100"
    )


def _status_tooltip(asset: Mapping[str, Any]) -> str:
    explicit = _get(asset, "tooltip", "status_tooltip")
    if explicit:
        return str(explicit)
    return (
        f"Why {asset['status']}: {_status_reason(asset)}. "
        f"Estimated time to the project-derived warning boundary: {_days_text(asset['days_remaining'])}. "
        "This is a planning estimate, not an OEM safety limit or guaranteed failure date."
    )


def _summary_card(status: str, count: int) -> None:
    policy = {
        "RED": "0–10 days from current evidence, or a technician-verified unresolved outcome",
        "AMBER": "11–30 days from current evidence, a material data gap, or a technician-verified partial outcome",
        "GREEN": "More than 30 days from current evidence, or a technician-verified resolved outcome",
    }[status]
    st.markdown(
        f"""
        <div class="lp-summary {status.lower()}">
          <span class="lp-help" tabindex="0" aria-label="Status explanation">?
            <span class="lp-tip">{_h(policy)}. Before maintenance, status comes from transparent condition and planning-horizon evidence; verified outcomes may update the workflow colour while preserving the original assessment. Business impact changes queue priority, not technical RAG.</span>
          </span>
          <div class="lp-summary-label">{_h(status)} · {_h(STATUS_LABELS[status])}</div>
          <div class="lp-summary-value">{int(count)}</div>
          <div class="lp-summary-copy">Class A assets</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _asset_card(asset: Mapping[str, Any], rank: int) -> None:
    status = asset["status"]
    model_note = ""
    if asset["model_status"] != status:
        model_note = f" · Model: {asset['model_status']}"
    ambiguity = " · HUMAN REVIEW" if asset.get("is_ambiguous") else ""
    st.markdown(
        f"""
        <div class="lp-asset-card {status.lower()}">
          <span class="lp-help" tabindex="0" aria-label="Why this status">?
            <span class="lp-tip">{_h(_status_tooltip(asset))}</span>
          </span>
          <div class="lp-asset-rank">Priority #{rank}{_h(ambiguity)}</div>
          <div class="lp-asset-name">{_h(asset['asset_id'])}</div>
          <div class="lp-asset-meta">{_h(asset['name'])}<br>{_h(asset['line'])} · {_h(asset['type'])}</div>
          <div class="lp-days">{_h(_days_text(asset['days_remaining']))}<br><small>to warning boundary</small></div>
          <div class="lp-card-bottom"><span>Priority {asset['attention_priority']:.0f}</span><span>{_h(status)}{_h(model_note)}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _section(title: str, copy: str, right: str = "") -> None:
    st.markdown(
        f"""
        <div class="lp-section-head">
          <div><div class="lp-section-title">{_h(title)}</div><div class="lp-section-copy">{_h(copy)}</div></div>
          <div class="lp-section-copy">{_h(right)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _plot_style(fig: go.Figure, height: int = 390) -> go.Figure:
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": INK, "family": "Inter, Segoe UI, Arial"},
        margin={"l": 14, "r": 14, "t": 50, "b": 20},
        legend={"orientation": "h", "y": -0.15, "title": None},
        hoverlabel={"bgcolor": "#101c2b", "font_color": "#ffffff", "bordercolor": "#496176"},
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID)
    return fig


def _flag_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)) and all(not isinstance(item, Mapping) for item in value):
        return [str(item) for item in value]
    if isinstance(value, Mapping):
        payload = dict(value)
        messages: list[str] = []
        missing_count = int(_num(payload.get("missing_sensor_row_count")))
        if missing_count:
            messages.append(f"{missing_count} expected asset-week sensor record(s) are missing; affected assets receive lower confidence.")
        orphan_ids = payload.get("orphan_maintenance_asset_ids") or []
        if orphan_ids:
            messages.append(f"Maintenance contains {len(orphan_ids)} orphan asset ID(s), excluded from asset history: {', '.join(map(str, orphan_ids))}.")
        duplicate_orders = payload.get("duplicate_work_order_ids") or []
        if duplicate_orders:
            messages.append(f"Duplicate work-order ID(s) were de-duplicated for analytics: {', '.join(map(str, duplicate_orders))}.")
        duplicate_usage = int(_num(payload.get("duplicate_usage_key_rows")))
        duplicate_sensor = int(_num(payload.get("duplicate_sensor_key_rows")))
        if duplicate_usage or duplicate_sensor:
            messages.append(f"Duplicate asset-week keys detected: usage {duplicate_usage}, sensors {duplicate_sensor}.")
        if messages:
            return messages
        explicit = _get(payload, "message", "description", "flag", "issue")
        return [str(explicit)] if explicit else []
    records = _to_records(value)
    if records:
        return [str(_get(item, "message", "description", "flag", "issue", default=item)) for item in records]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return []


def _evidence_card(item: Mapping[str, Any]) -> None:
    signal = _get(item, "signal", "label", "name", "metric", default="Cross-system evidence")
    source = _get(item, "source_sheet", "source", "dataset", "domain", default="Official workbook")
    current = _get(item, "reading", "current", "current_value", "latest_value", "value", default="Observed")
    unit = _get(item, "unit", "units", default="")
    reason = _get(item, "reason", "explanation", "finding", "message", default="Contributes to the current risk assessment.")
    trend = _get(item, "trend", "trend_per_week", "change", "three_week_change", "slope")
    boundary = _get(item, "boundary", "peer_boundary", "peer_warning_limit", "warning_boundary", "threshold")
    score = _get(item, "evidence_score", "score", "contribution")
    days_to_limit = _get(item, "days_to_peer_limit", "days_to_limit")
    method = _get(item, "limit_method", "boundary_method")
    footer_bits = []
    if trend is not None:
        footer_bits.append(f"Trend: {trend}")
    if boundary is not None:
        footer_bits.append(f"Peer boundary: {boundary}")
    if days_to_limit is not None:
        footer_bits.append(f"Horizon: {_days_text(days_to_limit)}")
    if score is not None:
        footer_bits.append(f"Evidence score: {_score(score):.0f}/100")
    if method:
        footer_bits.append(str(method))
    footer = " · ".join(footer_bits) or "Traceable to an official workbook field"
    st.markdown(
        f"""
        <div class="lp-evidence">
          <div class="lp-source">{_h(source)}</div>
          <h4>{_h(signal)}</h4>
          <div class="lp-evidence-main">{_h(current)} {_h(unit)}</div>
          <div class="lp-evidence-reason">{_h(reason)}</div>
          <div class="lp-evidence-foot">{_h(footer)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    local_drivers = _to_records(_get(item, "local_drivers", default=[]))
    if local_drivers:
        driver_text = ", ".join(
            f"{_get(driver, 'feature', default='feature')} "
            f"({_num(_get(driver, 'likelihood_point_change', default=0)):+.1f})"
            for driver in local_drivers[:3]
        )
        st.caption(f"Auxiliary model drivers: {driver_text}")


try:
    source_workbook = _source_workbook()
    source_stat = source_workbook.stat()
    service = get_service(
        str(source_workbook),
        source_stat.st_size,
        source_stat.st_mtime_ns,
    )
    overview_raw = _call(service.overview)
    overview = _to_dict(overview_raw)
    portfolio_raw = _call(service.portfolio)
    assets = [_normalize_asset(item) for item in _to_records(portfolio_raw, ("assets", "items"))]
    if not assets:
        raise RuntimeError("The service returned no Class A assets.")
except Exception as exc:
    _user_error("LinePulse AI could not load the asset data. Contact the application administrator.", exc)
    st.stop()


status_order = {"RED": 0, "AMBER": 1, "GREEN": 2}
assets = sorted(
    assets,
    key=lambda row: (status_order.get(row["status"], 9), -row["attention_priority"]),
)
asset_by_id = {asset["asset_id"]: asset for asset in assets}

legacy_workspaces = {
    "1 · Priorities": "Overview",
    "2 · Review asset": "Asset review",
    "3 · Verify outcome": "Work verification",
    "How it works": "Overview",
}
if st.session_state.get("workspace") in legacy_workspaces:
    st.session_state["workspace"] = legacy_workspaces[st.session_state["workspace"]]
if st.session_state.get("workspace") not in {"Overview", "Asset review", "Work verification", "Ask AI"}:
    st.session_state["workspace"] = "Overview"
if st.session_state.pop("_open_asset_next", False):
    st.session_state["workspace"] = "Asset review"
if "selected_asset" not in st.session_state or st.session_state.selected_asset not in asset_by_id:
    st.session_state.selected_asset = assets[0]["asset_id"]

selected_statuses = ["RED", "AMBER", "GREEN"]
selected_lines: list[str] = []
ambiguous_only = False
search = ""

latest_source_week = max(
    (str(asset.get("source_week")) for asset in assets if asset.get("source_week")),
    default="unknown",
)
st.markdown(
    f"""
    <div class="lp-topbar">
      <div class="lp-wordmark">
        <div class="lp-logo">LP</div>
        <div><div class="lp-brand">LinePulse AI</div><div class="lp-brand-sub">Class A maintenance intelligence</div></div>
      </div>
      <div class="lp-topmeta">
        <div class="lp-snapshot">Official data snapshot<strong>Week {_h(latest_source_week)} · {len(assets)} assets</strong></div>
        <div class="lp-readonly">● Decision support</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.container(border=True):
    nav_col, theme_col = st.columns([8.5, 1.5])
    with nav_col:
        workspace = st.segmented_control(
            "Navigation",
            ["Overview", "Asset review", "Work verification", "Ask AI"],
            key="workspace",
            label_visibility="collapsed",
        ) or "Overview"
    with theme_col:
        st.toggle("Dark mode", key="dark_mode")

page_heading, page_subtitle = {
    "Overview": ("Asset overview", "Class A maintenance priorities"),
    "Asset review": ("Asset review", "Evidence and recommended action"),
    "Work verification": ("Work verification", "Completed maintenance outcomes"),
    "Ask AI": ("Ask AI", "Ask questions about the selected asset and maintenance workflow"),
}[workspace]
st.markdown(
    f"""
    <div class="lp-page-title">
      <h1>{_h(page_heading)}</h1>
      <p>{_h(page_subtitle)}</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if workspace == "Overview":
    with st.expander("Filters"):
        filter_status, filter_line, filter_judgement, filter_search = st.columns([1.15, 1.35, 1, 1.5])
        with filter_status:
            selected_statuses = st.multiselect(
                "Status",
                ["RED", "AMBER", "GREEN"],
                default=["RED", "AMBER", "GREEN"],
            )
        with filter_line:
            line_options = sorted({asset["line"] for asset in assets})
            selected_lines = st.multiselect("Production line", line_options)
        with filter_judgement:
            ambiguous_only = st.checkbox("Needs extra judgement", value=False)
        with filter_search:
            search = st.text_input("Find asset", placeholder="ID, name, or type")

    if os.getenv("LINEPULSE_ENABLE_ADMIN", "").strip().casefold() in {"1", "true", "yes"}:
        with st.expander("Administration"):
            if st.button("Clear review history"):
                _call(service.reset_demo)
                st.success("Review history cleared.")
                st.rerun()


search_term = search.strip().casefold()
filtered = [
    asset
    for asset in assets
    if asset["status"] in selected_statuses
    and (not selected_lines or asset["line"] in selected_lines)
    and (not ambiguous_only or asset["is_ambiguous"])
    and (
        not search_term
        or search_term in asset["asset_id"].casefold()
        or search_term in asset["name"].casefold()
        or search_term in asset["type"].casefold()
    )
]


if workspace == "Overview":
    counts = {status: sum(asset["status"] == status for asset in assets) for status in STATUS_COLORS}
    total_col, red_col, amber_col, green_col = st.columns([1.05, 1, 1, 1])
    with total_col:
        st.markdown(
            f"""
            <div class="lp-panel" style="min-height:7.1rem;border-top:5px solid #00677f;box-shadow:0 4px 14px rgba(16,24,40,.06)">
              <div class="lp-panel-label">Assets screened</div>
              <div style="font-size:2.2rem;line-height:1;font-weight:800;color:var(--lp-ink);margin:.62rem 0 .32rem">{len(assets)}</div>
              <div class="lp-panel-copy">Class A assets</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with red_col:
        _summary_card("RED", counts["RED"])
    with amber_col:
        _summary_card("AMBER", counts["AMBER"])
    with green_col:
        _summary_card("GREEN", counts["GREEN"])

    _section(
        "Highest priority",
        "",
        f"{min(3, len(filtered))} of {len(filtered)} shown",
    )
    top_assets = filtered[:3]
    if top_assets:
        row = st.columns(len(top_assets))
        for column, asset in zip(row, top_assets):
            rank = assets.index(asset) + 1
            with column:
                _asset_card(asset, rank)
                if st.button("Review asset", key=f"open_{asset['asset_id']}", use_container_width=True):
                    st.session_state.selected_asset = asset["asset_id"]
                    st.session_state._open_asset_next = True
                    st.rerun()
    else:
        st.info("No assets match the current filters.")

    chart_assets = filtered if filtered else assets
    frame = pd.DataFrame(chart_assets)
    with st.expander("Portfolio analytics"):
        chart_left, chart_right = st.columns([1.15, 1])
        with chart_left:
            matrix = px.scatter(
                frame,
                x="technical_risk",
                y="business_impact",
                color="status",
                symbol="status",
                size="attention_priority",
                hover_name="asset_id",
                hover_data={"name": True, "line": True, "days_remaining": True, "data_confidence": ":.0f"},
                color_discrete_map=STATUS_COLORS,
                category_orders={"status": ["RED", "AMBER", "GREEN"]},
                labels={"technical_risk": "Technical risk", "business_impact": "Production impact"},
                title="Technical risk and production impact",
                size_max=24,
            )
            matrix.add_vline(x=55, line_dash="dot", line_color="#98A2B3")
            matrix.add_hline(y=70, line_dash="dot", line_color="#98A2B3")
            matrix.update_xaxes(range=[0, 100])
            matrix.update_yaxes(range=[0, 100])
            st.plotly_chart(_plot_style(matrix, 380), use_container_width=True)
        with chart_right:
            priority = frame.nlargest(min(10, len(frame)), "attention_priority").sort_values("attention_priority")
            bars = px.bar(
                priority,
                x="attention_priority",
                y="asset_id",
                color="status",
                orientation="h",
                color_discrete_map=STATUS_COLORS,
                category_orders={"status": ["RED", "AMBER", "GREEN"]},
                hover_data={"failure_mode": True, "days_remaining": True},
                labels={"attention_priority": "Attention priority", "asset_id": "Asset"},
                title="Highest attention priorities",
            )
            bars.update_layout(showlegend=False)
            st.plotly_chart(_plot_style(bars, 380), use_container_width=True)
        st.caption("Priority combines technical risk and production impact.")

    _section("Asset portfolio", "", f"{len(filtered)} assets")
    display = pd.DataFrame(filtered)[
        [
            "status",
            "asset_id",
            "name",
            "line",
            "days_remaining",
            "attention_priority",
            "technical_risk",
            "business_impact",
            "data_confidence",
        ]
    ].copy() if filtered else pd.DataFrame(columns=["status", "asset_id", "name", "line", "days_remaining", "attention_priority", "technical_risk", "business_impact", "data_confidence"])
    display.columns = [
        "Status", "Asset ID", "Asset", "Line", "Days", "Priority", "Technical risk",
        "Production impact", "Confidence",
    ]
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Priority": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
            "Technical risk": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
            "Confidence": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
        },
    )

    overview_data = _to_dict(_get(overview, "data", "data_profile", "dataset", default={}))
    overview_flags = _flag_strings(
        _get(overview, "data_quality_flags", "quality_flags", "data_quality", default=overview_data.get("data_quality", []))
    )
    if overview_flags:
        with st.expander(f"Data-quality gate · {len(overview_flags)} finding(s)"):
            for flag in overview_flags:
                st.warning(flag)


elif workspace == "Asset review":
    asset_ids = [asset["asset_id"] for asset in assets]
    current_index = asset_ids.index(st.session_state.selected_asset)
    selected_id = st.selectbox(
        "Select a Class A asset",
        asset_ids,
        index=current_index,
        format_func=lambda asset_id: (
            f"{asset_id} · {asset_by_id[asset_id]['name']} · "
            f"{asset_by_id[asset_id]['status']} · priority {asset_by_id[asset_id]['attention_priority']:.0f}"
        ),
    )
    st.session_state.selected_asset = selected_id

    try:
        detail_raw = _call(service.asset_detail, selected_id)
        detail_envelope = _to_dict(detail_raw)
        detail_base = _to_dict(_get(detail_envelope, "asset", "assessment", "detail", default=detail_envelope))
        asset = _normalize_asset({**asset_by_id[selected_id], **detail_base})
    except Exception as exc:
        _user_error(f"Evidence for {selected_id} is temporarily unavailable. Please retry.", exc)
        st.stop()

    status = asset["status"]
    st.markdown(
        f"""
        <div class="lp-asset-hero" style="border-left:6px solid {STATUS_COLORS[status]}">
          <span class="lp-help" style="--status:{STATUS_COLORS[status]}" tabindex="0" aria-label="Why this status">?
            <span class="lp-tip">{_h(_status_tooltip(asset))}</span>
          </span>
          <div>
            <div class="lp-kicker">{_h(asset['line'])} · {_h(asset['type'])}</div>
            <h2>{_h(asset['asset_id'])} · {_h(asset['name'])}</h2>
            <p>{_h(asset['failure_mode'])}</p>
            <div style="margin-top:.65rem"><span class="lp-status-pill" style="background:{STATUS_COLORS[status]}"><span class="lp-dot"></span>{_h(status)} · {_h(STATUS_LABELS[status])}</span></div>
          </div>
          <div class="lp-horizon"><strong>{_h(_days_text(asset['days_remaining']))}</strong><span>planning horizon</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if asset["is_ambiguous"]:
        st.warning(f"Extra judgement required · {asset['ambiguity_reason']}")

    kpi_cols = st.columns(4)
    kpis = [
        ("Attention priority", f"{asset['attention_priority']:.0f}/100", "Where to review first"),
        ("Technical risk", f"{asset['technical_risk']:.0f}/100", "Condition and operating evidence"),
        ("Production impact", f"{asset['business_impact']:.0f}/100", "Consequence if availability is lost"),
        ("Data confidence", f"{asset['data_confidence']:.0f}/100", "Completeness and trust"),
    ]
    for column, (label, value, note) in zip(kpi_cols, kpis):
        with column:
            st.markdown(
                f"<div class='lp-kpi'><div class='lp-kpi-label'>{_h(label)}</div><div class='lp-kpi-value'>{_h(value)}</div><div class='lp-kpi-note'>{_h(note)}</div></div>",
                unsafe_allow_html=True,
            )

    _section(
        "Evidence",
        "Strongest signals behind the assessment.",
        "Official dataset",
    )
    evidence_value = _get(asset, "evidence_passport", "evidence", default=_get(detail_envelope, "evidence_passport", "evidence", default=[]))
    evidence = _to_records(evidence_value)
    if evidence:
        evidence_cols = st.columns(min(3, len(evidence)))
        for column, item in zip(evidence_cols, evidence[:3]):
            with column:
                _evidence_card(item)
        with st.expander(f"View all {len(evidence)} evidence records"):
            st.dataframe(pd.DataFrame(evidence), use_container_width=True, hide_index=True)
    else:
        st.info("No detailed evidence rows were returned for this asset.")

    asset_flags = _flag_strings(_get(asset, "data_quality_flags", "quality_flags", default=_get(detail_envelope, "data_quality_flags", default=[])))
    if asset_flags:
        st.warning("Data confidence is reduced because: " + " · ".join(asset_flags))

    action = _get(detail_envelope, "recommended_action", "action", default=asset["recommended_action"])
    cause = _get(detail_envelope, "failure_mode", "likely_failure_mode", default=asset["failure_mode"])
    maintenance_window = _get(detail_envelope, "maintenance_window", "recommended_window")
    if isinstance(maintenance_window, Mapping):
        window_label = str(_get(maintenance_window, "label", "window", default="Use the next safe production opportunity"))
    else:
        window_label = str(maintenance_window or asset.get("planning_window") or "Use the next safe production opportunity")

    st.markdown(
        f"""
        <div class="lp-action">
          <div class="lp-kicker">Recommended action</div>
          <h3>{_h(action)}</h3>
          <p><strong>Likely issue:</strong> {_h(cause)}</p>
          <p><strong>Recommended window:</strong> {_h(window_label)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    learning_value = _get(
        detail_envelope,
        "learning_summary",
        "decision_memory",
        "verified_outcome_memory",
        "similar_cases",
        default=asset.get("learning_summary"),
    )
    if learning_value:
        learning_map = _to_dict(learning_value)
        learning_records = _to_records(learning_value)
        learning_copy = _get(
            learning_map,
            "summary",
            "message",
            "recommendation_note",
            "note",
            default="No matching verified maintenance outcome is available yet.",
        )
        st.markdown("<div style='height:.75rem'></div>", unsafe_allow_html=True)
        with st.expander("Verified outcome memory · similar completed cases"):
            st.write(str(learning_copy))
            if learning_records and not (len(learning_records) == 1 and learning_records[0] == learning_map):
                st.dataframe(pd.DataFrame(learning_records), use_container_width=True, hide_index=True)
            else:
                st.json(learning_map or learning_value)
            st.caption("Only technician-verified outcomes update recommendation memory.")

    with st.expander("Planning simulation"):
        st.caption("Compare a lower-stress plan. Results are read-only and are not saved.")
        what_left, what_mid, what_right = st.columns([1, 1, 1.25])
        with what_left:
            duty_reduction = st.slider("Reduce duty cycle", 0, 40, 10, 5, format="%d%%")
        with what_mid:
            start_stop_reduction = st.slider("Reduce start/stop events", 0, 60, 15, 5, format="%d%%")
        with what_right:
            st.markdown("<div style='height:.45rem'></div>", unsafe_allow_html=True)
            simulate = st.button("Calculate", type="primary", use_container_width=True)
        if simulate:
            try:
                scenario_raw = _call(
                    service.what_if,
                    selected_id,
                    duty_reduction_pct=duty_reduction,
                    start_stop_reduction_pct=start_stop_reduction,
                )
                scenario = _to_dict(scenario_raw)
                original_values = _to_dict(_get(scenario, "original", default={}))
                projected_values = _to_dict(_get(scenario, "scenario", default={}))
                base_priority = _score(
                    _get(
                        original_values,
                        "attention_priority",
                        default=_get(scenario, "baseline_priority", "current_priority", default=asset["attention_priority"]),
                    )
                )
                new_priority = _score(
                    _get(
                        projected_values,
                        "attention_priority",
                        default=_get(scenario, "scenario_priority", "projected_priority", "attention_priority", default=base_priority),
                    )
                )
                base_days = _get(
                    original_values,
                    "days_remaining",
                    default=_get(scenario, "baseline_days", "current_days", default=asset["days_remaining"]),
                )
                new_days = _get(
                    projected_values,
                    "days_remaining",
                    default=_get(scenario, "scenario_days", "projected_days", "days_remaining", default=base_days),
                )
                w1, w2, w3 = st.columns(3)
                w1.metric("Projected priority", f"{new_priority:.0f}/100", f"{new_priority - base_priority:+.0f}")
                w2.metric("Projected horizon", _days_text(new_days), f"{_num(new_days) - _num(base_days):+.0f} days")
                w3.metric("Mode", "Read-only")
                note = _get(scenario, "explanation", "note", "message")
                if note:
                    st.info(str(note))
            except Exception as exc:
                _user_error("The planning scenario could not be calculated. Please retry.", exc)

    _section("Equipment Owner decision", "Human approval is required before maintenance proceeds.")
    with st.form("asset_decision_form", clear_on_submit=False):
        d1, d2 = st.columns([.75, 1.25])
        with d1:
            decision = st.radio("Equipment Owner decision", ["APPROVE", "MODIFY", "REJECT"], horizontal=True)
            owner = st.text_input("Decision owner", value="Equipment Owner")
        with d2:
            modified_action = st.text_area(
                "Approved or modified action",
                value=str(action),
                help="For MODIFY, replace this with the action the owner authorizes. For APPROVE, retain the recommendation.",
            )
            rationale = st.text_input("Decision rationale", placeholder="Why is this the safest practical choice?")
        submitted = st.form_submit_button("Record human decision", type="primary", use_container_width=True)
        if submitted:
            if not rationale.strip():
                st.error("Add a short rationale so the decision remains auditable.")
            elif decision == "MODIFY" and not modified_action.strip():
                st.error("Describe the modified action before recording the decision.")
            else:
                try:
                    result = _call(
                        service.record_decision,
                        selected_id,
                        decision=decision,
                        rationale=rationale.strip(),
                        owner=owner.strip() or "Equipment Owner",
                        modified_action=(modified_action.strip() if decision == "MODIFY" else None),
                    )
                    result_map = _to_dict(result)
                    result_case = _to_dict(result_map.get("case"))
                    case_id = _get(result_map, "case_id", "id", default=_get(result_case, "case_id", "id", default="recorded"))
                    st.success(f"Decision recorded as case {case_id}. No automatic equipment action was taken.")
                except Exception as exc:
                    _user_error("The decision could not be recorded. Your equipment was not affected.", exc)


elif workspace == "Work verification":
    _section("Verify completed work", "Record what the technician observed after maintenance. Only verified results update the operating view.")
    try:
        case_records = _to_records(_call(service.list_cases), ("cases", "items"))
    except Exception as exc:
        _user_error("Maintenance cases are temporarily unavailable. Please retry.", exc)
        case_records = []

    resolved_count = sum(str(_get(case, "outcome", default="PENDING")).upper() == "RESOLVED" for case in case_records)
    pending_cases = [
        case
        for case in case_records
        if str(_get(case, "outcome", "verified_outcome", default="PENDING")).upper() in {"", "PENDING", "NONE", "AWAITING_OUTCOME"}
        and str(_get(case, "decision", default="")).upper() != "REJECT"
    ]
    c1, c2, c3 = st.columns(3)
    c1.metric("Recorded decisions", len(case_records))
    c2.metric("Awaiting verified outcome", len(pending_cases))
    c3.metric("Verified resolved", resolved_count)

    if pending_cases:
        with st.form("outcome_form"):
            pending_lookup = {
                str(_get(case, "case_id", "id", default=index + 1)): case
                for index, case in enumerate(pending_cases)
            }
            selected_case = st.selectbox(
                "Completed maintenance case",
                list(pending_lookup),
                format_func=lambda key: (
                    f"Case {key} · {_get(pending_lookup[key], 'asset_id', 'AssetID', default='Unknown asset')} · "
                    f"{str(_get(pending_lookup[key], 'decision', default='')).title()}"
                ),
            )
            outcome = st.radio(
                "Technician-verified outcome",
                ["RESOLVED", "PARTIAL", "UNRESOLVED"],
                horizontal=True,
                format_func=lambda value: value.replace("_", " ").title(),
            )
            outcome_notes = st.text_area("Verification evidence", placeholder="What was inspected, changed, measured, and observed afterward?")
            outcome_submit = st.form_submit_button("Record verified outcome", type="primary", use_container_width=True)
            if outcome_submit:
                if not outcome_notes.strip():
                    st.error("Add verification evidence before closing the learning loop.")
                else:
                    try:
                        result = _call(
                            service.record_outcome,
                            selected_case,
                            outcome=outcome,
                            notes=outcome_notes.strip(),
                        )
                        result_map = _to_dict(result)
                        new_status = _get(result_map, "new_display_status", "new_status")
                        message = f"Case {selected_case} updated."
                        if new_status:
                            message += f" Operational status is now {new_status}."
                        message += " The original model assessment remains auditable."
                        st.success(message)
                        st.rerun()
                    except Exception as exc:
                        _user_error("The outcome could not be recorded. Please retry.", exc)
    else:
        st.info("No approved or modified case is waiting for a verified maintenance outcome.")

    if case_records:
        with st.expander(f"Decision audit trail · {len(case_records)} case(s)"):
            st.caption("Every recommendation, owner decision, rationale, and verified outcome stays linked to the asset.")
            cases_frame = pd.DataFrame(case_records)
            preferred = [
                key
                for key in ["case_id", "id", "created_at", "asset_id", "owner", "decision", "rationale", "modified_action", "outcome", "outcome_notes"]
                if key in cases_frame.columns
            ]
            remaining = [key for key in cases_frame.columns if key not in preferred]
            st.dataframe(cases_frame[preferred + remaining], use_container_width=True, hide_index=True)
    else:
        st.info("No human decision has been recorded yet. Open Asset review to begin.")


elif workspace == "Ask AI":
    selected_asset_for_chat = asset_by_id[st.session_state.selected_asset]
    chat_context = build_assistant_context(overview, selected_asset_for_chat)
    st.info(
        "This assistant explains the current LinePulse evidence. It uses synthetic demo data, "
        "does not control equipment, and does not replace a qualified maintenance decision."
    )
    st.caption(
        f"Context: {selected_asset_for_chat['asset_id']} · {selected_asset_for_chat['status']} · "
        f"{selected_asset_for_chat['failure_mode']}"
    )

    if not is_configured():
        st.warning(
            "The assistant is not configured. Add VW_LLM_CLIENT_ID, VW_LLM_CLIENT_SECRET, "
            "and VW_LLM_API_KEY to .env, then restart the dashboard."
        )
    else:
        st.caption("VW LLM model: " + os.getenv("OPENAI_MODEL", "gpt-4o"))

    if "linepulse_chat_messages" not in st.session_state:
        st.session_state.linepulse_chat_messages = []
    clear_col, _ = st.columns([1, 5])
    with clear_col:
        if st.button("Clear chat", use_container_width=True):
            st.session_state.linepulse_chat_messages = []
            st.rerun()

    for message in st.session_state.linepulse_chat_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    question = st.chat_input("Ask about the selected asset, its alert, or the maintenance workflow")
    if question:
        st.session_state.linepulse_chat_messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Reviewing the dashboard evidence…"):
                try:
                    answer = answer_question(st.session_state.linepulse_chat_messages, chat_context)
                    st.markdown(answer)
                    st.session_state.linepulse_chat_messages.append(
                        {"role": "assistant", "content": answer}
                    )
                except AssistantUnavailableError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    _user_error("The AI assistant could not answer the question.", exc)
