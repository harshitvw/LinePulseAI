"""LinePulse AI maintenance operations dashboard."""

from __future__ import annotations

import html
import inspect
import json
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
    initial_sidebar_state="expanded",
)

st.html(
    """
    <script>
    (() => {
      const doc = window.parent.document;
      const key = "linepulseSidebarHidden";
      let button = doc.getElementById("linepulse-sidebar-toggle");
      if (!button) {
        button = doc.createElement("button");
        button.id = "linepulse-sidebar-toggle";
        button.type = "button";
        button.textContent = "☰";
        button.setAttribute("aria-label", "Toggle navigation");
        button.style.cssText = [
          "position:fixed", "top:2.5rem", "left:.75rem", "transform:translateY(-50%)",
          "z-index:2100", "width:2rem", "height:2rem", "display:grid", "place-items:center",
          "border-radius:.5rem", "border:2px solid #DCE8FA", "cursor:pointer",
          "background:var(--lp-blue,#0F52BA)", "color:#FFFFFF", "font:800 1rem/1 Segoe UI,Arial,sans-serif",
          "box-shadow:0 5px 14px rgba(10,22,42,.25)"
        ].join(";");
        doc.body.appendChild(button);
      }
      const apply = (hidden) => {
        doc.body.classList.toggle("lp-sidebar-hidden", hidden);
        button.setAttribute("aria-expanded", String(!hidden));
        button.title = hidden ? "Show navigation" : "Hide navigation";
        window.localStorage.setItem(key, String(hidden));
      };
      apply(window.localStorage.getItem(key) === "true");
      button.onclick = () => apply(!doc.body.classList.contains("lp-sidebar-hidden"));
    })();
    </script>
    """,
    unsafe_allow_javascript=True,
)

# Initialise UI state before calculating theme-dependent values.
st.session_state.setdefault("dark_mode", False)
st.session_state.setdefault("workspace", "Home")
st.session_state.setdefault("selected_asset", None)
st.session_state.setdefault("asset_review_view", "Assessment")

DARK_MODE = bool(st.session_state.dark_mode)

INK = "#F8FAFC" if DARK_MODE else "#0F172A"
TEXT_SECONDARY = "#CBD5E1" if DARK_MODE else "#475569"
MUTED = "#94A3B8" if DARK_MODE else "#64748B"
GRID = "#334155" if DARK_MODE else "#D7DFE8"

WORKSPACES = (
    "Dashboard",
    "Asset Review",
    "Work Verification",
    "Analytics",
    "AI Insights",
    "Settings",
)

WORKSPACE_LABELS = {
    "Dashboard": "Dashboard",
    "Asset Review": "Asset Review",
    "Work Verification": "Work Verification",
    "Analytics": "Analytics",
    "AI Insights": "AI Insights",
    "Settings": "Settings",
}

WORKSPACE_ICONS = {
    "Dashboard": "▦",
    "Asset Review": "◎",
    "Work Verification": "✓",
    "Analytics": "⌁",
    "AI Insights": "✦",
    "Settings": "⚙",
}


def _h(value: Any) -> str:
    """Escape every value originating in a workbook, database, or form."""

    return html.escape(str(value if value is not None else ""), quote=True)


def _user_error(message: str, exc: Exception) -> None:
    """Show a safe message in the UI and preserve diagnostics in server logs."""

    LOGGER.exception("%s", message, exc_info=exc)
    st.error(message)


def _scroll_to_top_on_change(namespace: str, value: str) -> None:
    storage_key = json.dumps(f"linepulse-view-{namespace}")
    view_value = json.dumps(value)
    st.html(
        f"""
        <script>
        (() => {{
          const key = {storage_key}, value = {view_value};
          if (window.sessionStorage.getItem(key) === value) return;
          window.sessionStorage.setItem(key, value);
          window.requestAnimationFrame(() => {{
            window.scrollTo({{top:0,left:0,behavior:"instant"}});
            document.documentElement.scrollTop = 0;
            document.body.scrollTop = 0;
            document.querySelector('[data-testid="stAppViewContainer"]')?.scrollTo(0,0);
            document.querySelector('[data-testid="stMain"]')?.scrollTo(0,0);
          }});
        }})();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


st.markdown(
    """
    <style>
    :root {
      --lp-bg: #F8F8FF;
      --lp-panel: #ffffff;
      --lp-panel-2: #F2F4FA;
      --lp-border: #B8C0CC;
      --lp-ink: #353839;
      --lp-muted: #646A70;
      --lp-text-2: #4B5053;
      --lp-blue: #0F52BA;
      --lp-red: #d92d20;
      --lp-amber: #dc6803;
      --lp-green: #1f7656;
      --lp-red-bg: #ffe9e7;
      --lp-amber-bg: #fff2cc;
      --lp-green-bg: #dcfae6;
      --lp-shadow-xs: 0 1px 2px rgba(16,24,40,.05);
      --lp-shadow-sm: 0 5px 16px rgba(16,24,40,.07);
      --lp-shadow-md: 0 14px 34px rgba(16,24,40,.12);
      --lp-radius: .9rem;
      --lp-nav-bg:#2A2C31;
      --lp-nav-border:#454952;
      --lp-nav-text:#F8F8FF;
      --lp-nav-muted:#C9CED8;
      --lp-header-height:5rem;
    }

    html, body, [class*="css"] {
      font-family: Inter, "Segoe UI", Arial, sans-serif;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }
    .stApp { background: var(--lp-bg); color: var(--lp-ink); }
    .block-container {
      max-width:none; padding:0 1.45rem 2.25rem !important;
    }
    [data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"] { display:none !important; }
    [data-testid="stAppViewContainer"] > .main { padding-top:0 !important; }
    [data-testid="stSidebar"] {
      display:block; width:16rem !important; min-width:16rem !important;
      background:#0d211b; border-right:1px solid #173b30;
    }
    [data-testid="stSidebar"] > div:first-child { width:16rem !important; }
    [data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding:0 !important; }
    [data-testid="stSidebarUserContent"] { padding-top:0 !important; }
    [data-testid="stSidebarContent"] > div:first-child { padding-top:0 !important; }
    [data-testid="stSidebar"] .block-container { padding:0 .8rem 1rem !important; }
    [data-testid="collapsedControl"] { display:flex; color:var(--lp-ink); }
    [data-testid="stAppViewContainer"] > .main > div { padding-top:0 !important; }
    .lp-side-brand { display:flex; align-items:center; gap:.7rem; padding:.35rem .35rem 1rem; border-bottom:1px solid #2d3d54; }
    .lp-side-logo {
      width:2.25rem; height:2.25rem; flex:0 0 2.25rem; display:grid; place-items:center;
      border-radius:.65rem; background:#087a96; color:#ffffff; font-weight:850;
    }
    .lp-side-name { color:#ffffff; font-size:.96rem; font-weight:780; line-height:1.15; }
    .lp-side-sub { color:#a8b5c7; font-size:.66rem; margin-top:.2rem; }
    .lp-side-label { color:#8291a6; font-size:.62rem; font-weight:800; letter-spacing:.12em; text-transform:uppercase; margin:.95rem .45rem .42rem; }
    [data-testid="stSidebar"] div[role="radiogroup"] { gap:.28rem; }
    [data-testid="stSidebar"] div[role="radiogroup"] label {
      min-height:2.65rem; padding:.58rem .72rem; border-radius:.55rem;
      color:#e7f0eb !important; transition:background .16s ease, color .16s ease, transform .16s ease;
    }
    [data-testid="stSidebar"] div[role="radiogroup"] label:hover { background:#173a30; transform:translateX(2px); }
    [data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
      background:#d1b36a; box-shadow:0 5px 16px rgba(17,55,43,.25); color:#13271f !important;
    }
    [data-testid="stSidebar"] div[role="radiogroup"] label p,
    [data-testid="stSidebar"] div[role="radiogroup"] label span,
    [data-testid="stSidebar"] div[role="radiogroup"] [data-testid="stMarkdownContainer"] { color:inherit !important; -webkit-text-fill-color:currentColor !important; font-weight:720; font-size:.8rem; }
    [data-testid="stSidebar"] div[role="radiogroup"] label input { opacity:0 !important; width:0 !important; margin:0 !important; }
    [data-testid="stSidebar"] div[role="radiogroup"] label > div:first-child { display:none; }
    [data-testid="stSidebar"] [data-testid="stToggle"] { margin:.1rem .42rem; }
    [data-testid="stSidebar"] [data-testid="stToggle"] label,
    [data-testid="stSidebar"] [data-testid="stToggle"] label p { color:#e7f0eb !important; -webkit-text-fill-color:#e7f0eb !important; }
    .lp-side-status {
      margin:1rem .35rem 0; padding:.72rem .75rem; border:1px solid #285144;
      border-radius:.65rem; background:#102b23;
    }
    .lp-side-status strong { display:block; color:#d1fadf; font-size:.72rem; }
    .lp-side-status span { display:block; color:#9eacc0; font-size:.64rem; line-height:1.38; margin-top:.22rem; }
    h1, h2, h3, h4, h5, h6 { color: var(--lp-ink); letter-spacing: -.025em; }
    p, label, li, .stMarkdown, [data-testid="stCaptionContainer"] { color: var(--lp-text-2); }
    hr { border-color: var(--lp-border) !important; }

    .lp-topbar {
      display:flex; align-items:center; justify-content:space-between; gap:1.5rem;
      background:var(--lp-panel); border:1px solid var(--lp-border); border-radius:1rem;
      min-height:4.25rem; padding:.8rem 1rem; margin-top:0; overflow:visible;
      box-sizing:border-box; box-shadow:var(--lp-shadow-sm);
    }
    .lp-appbar {
      display:flex; align-items:center; justify-content:space-between; gap:1.2rem;
      min-height:4.15rem; padding:.75rem .95rem; margin:0 0 .72rem;
      border:1px solid var(--lp-border); border-radius:.82rem; background:var(--lp-panel);
      box-shadow:var(--lp-shadow-xs); position:sticky; top:0; z-index:800;
      backdrop-filter:blur(14px);
    }
    .lp-appbar-title h1 { margin:0; color:var(--lp-ink); font-size:1.28rem; line-height:1.15; }
    .lp-appbar-title p { margin:.2rem 0 0; color:var(--lp-muted); font-size:.74rem; }
    .lp-appbar-meta { display:flex; align-items:center; justify-content:flex-end; gap:.65rem; }
    .lp-appbar-snapshot { color:var(--lp-muted); font-size:.66rem; text-align:right; }
    .lp-appbar-snapshot strong { display:block; color:var(--lp-ink); font-size:.74rem; margin-top:.12rem; }
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
    .lp-appbar-brand { display:flex; align-items:center; gap:.72rem; min-width:0; }
    .lp-appbar-logo { display:grid; place-items:center; width:2.25rem; height:2.25rem; flex:0 0 2.25rem; border-radius:.68rem; background:linear-gradient(135deg,#174b3d,#2b735d); color:#fff; font-size:.78rem; font-weight:850; letter-spacing:-.05em; box-shadow:0 5px 12px rgba(23,75,61,.22); }
    .lp-home-hero { padding:2.05rem 2.15rem; border-radius:1rem; background:linear-gradient(125deg,#0b2d24 0%,#174b3d 58%,#286a55 100%); color:#fff; box-shadow:0 16px 32px rgba(18,62,49,.2); margin:.35rem 0 1rem; }
    .lp-home-hero .eyebrow { color:#e0c98f; font-size:.68rem; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
    .lp-home-hero h2 { color:#fff; margin:.5rem 0 .35rem; font-size:1.75rem; letter-spacing:-.035em; }
    .lp-home-hero p { color:#e5eee9; max-width:44rem; margin:0; font-size:.9rem; line-height:1.5; }
    .lp-home-card { min-height:10rem; padding:1.15rem; border:1px solid var(--lp-border); background:var(--lp-panel); border-radius:.85rem; box-shadow:var(--lp-shadow-xs); }
    .lp-home-card .step { color:var(--lp-blue); font-size:.68rem; font-weight:800; letter-spacing:.1em; text-transform:uppercase; }
    .lp-home-card h3 { margin:.55rem 0 .35rem; font-size:1rem; }
    .lp-home-card p { color:var(--lp-muted); font-size:.78rem; line-height:1.45; min-height:2.3rem; }

    div[data-testid="stSegmentedControl"] { margin:.1rem 0 .72rem; }
    div[data-testid="stSegmentedControl"] button {
      min-height:2.35rem; font-weight:700; background:var(--lp-panel-2) !important;
      border-color:var(--lp-border) !important; transition:background-color .18s ease, color .18s ease;
    }
    div[data-testid="stSegmentedControl"] button[aria-pressed="true"] { background:var(--lp-blue) !important; border-color:var(--lp-blue) !important; }
    .lp-page-title { margin:.15rem 0 .6rem; }
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

    .lp-section-head { display:flex; align-items:flex-end; justify-content:space-between; gap:1rem; margin:.95rem 0 .55rem; }
    .lp-section-title { color:var(--lp-ink); font-size:1.12rem; font-weight:750; }
    .lp-section-copy { color:var(--lp-muted); font-size:.82rem; margin-top:.17rem; }

    .lp-summary {
      position:relative; overflow:visible; min-height:7.1rem; padding:1rem 1.05rem;
      border-radius:.9rem; color:var(--lp-ink); border:1px solid var(--lp-border);
      border-top:5px solid var(--status); box-shadow:var(--lp-shadow-sm);
    }
    .lp-summary.red { --status:#d92d20; background:var(--lp-red-bg); }
    .lp-summary.amber { --status:#dc6803; background:var(--lp-amber-bg); }
    .lp-summary.green { --status:#07883f; background:var(--lp-green-bg); }
    .lp-summary-label { font-size:.77rem; font-weight:780; letter-spacing:.05em; text-transform:uppercase; }
    .lp-summary-value { color:var(--status); font-size:2.2rem; line-height:1; font-weight:800; margin:.62rem 0 .32rem; }
    .lp-summary-copy { font-size:.78rem; color:var(--lp-muted); }
    .lp-summary-icon, .lp-kpi-icon {
      display:inline-grid; place-items:center; width:1.75rem; height:1.75rem;
      border-radius:.55rem; background:color-mix(in srgb, var(--status, var(--lp-blue)) 13%, transparent);
      color:var(--status, var(--lp-blue)); font-size:.92rem; font-weight:850; margin-bottom:.55rem;
    }
    .lp-warning-mark {
      position:absolute; top:.72rem; right:2.55rem; z-index:19;
      display:grid; place-items:center; width:1.35rem; height:1.35rem;
      border-radius:50%; color:#ffffff; background:#d92d20; border:1px solid #f97066;
      font-size:.86rem; font-weight:900; line-height:1;
      box-shadow:0 0 0 3px rgba(217,45,32,.16);
    }

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
      border-left:6px solid var(--status); box-shadow:var(--lp-shadow-sm); margin-bottom:.45rem;
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
      padding:1rem 1.08rem; margin-bottom:.75rem; box-shadow:var(--lp-shadow-xs);
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
    .lp-urgent {
      border-color:#f04438 !important;
      background:linear-gradient(105deg, var(--lp-panel) 0%, var(--lp-panel) 68%, var(--lp-red-bg) 100%);
      animation:lpUrgentPulse 1.45s ease-in-out infinite;
    }
    .lp-urgent-badge {
      display:inline-flex; align-items:center; gap:.4rem; color:#ffffff; background:#d92d20;
      border:1px solid #f04438; border-radius:999px; padding:.34rem .62rem;
      font-size:.69rem; font-weight:820; letter-spacing:.055em; text-transform:uppercase;
      margin-bottom:.52rem;
      animation:lpCriticalBadge 1.45s ease-in-out infinite;
    }
    .lp-urgent-badge::before {
      content:""; width:.48rem; height:.48rem; border-radius:50%; background:#ffffff;
      animation:lpUrgentDot 1s step-end infinite;
    }
    @keyframes lpUrgentPulse {
      0%, 100% { box-shadow:0 0 0 0 rgba(240,68,56,.05), var(--lp-shadow-xs); }
      50% { box-shadow:0 0 0 5px rgba(240,68,56,.18), 0 14px 34px rgba(217,45,32,.14); }
    }
    @keyframes lpUrgentDot { 0%, 48% { opacity:1; } 49%, 100% { opacity:.25; } }
    @keyframes lpCriticalBadge {
      0%, 100% { opacity:1; transform:scale(1); }
      50% { opacity:.72; transform:scale(1.025); }
    }

    .lp-kpi {
      min-height:7rem; padding:.95rem 1rem; border:1px solid var(--lp-border);
      background:var(--lp-panel); border-radius:.82rem; box-shadow:var(--lp-shadow-xs);
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
    .lp-workflow-card {
      min-height:10rem; padding:1.05rem 1.1rem; border-radius:var(--lp-radius);
      background:var(--lp-panel); border:1px solid var(--lp-border); box-shadow:var(--lp-shadow-xs);
    }
    .lp-workflow-card h3 { margin:.35rem 0 .35rem; font-size:1rem; }
    .lp-workflow-card p { color:var(--lp-muted); font-size:.78rem; line-height:1.45; margin:.25rem 0; }
    .lp-workflow-value { color:var(--lp-ink); font-size:1.7rem; font-weight:820; line-height:1; margin:.65rem 0 .3rem; }

    .lp-audit-card {
      background:var(--lp-panel); border:1px solid var(--lp-border); border-radius:var(--lp-radius);
      padding:1rem 1.05rem .9rem; margin:.65rem 0; box-shadow:var(--lp-shadow-xs);
    }
    .lp-audit-head { display:flex; flex-wrap:wrap; align-items:flex-start; justify-content:space-between; gap:.65rem 1rem; }
    .lp-audit-title { color:var(--lp-ink); font-size:1rem; font-weight:800; }
    .lp-audit-meta { color:var(--lp-muted); font-size:.72rem; margin-top:.22rem; }
    .lp-audit-badges { display:flex; flex-wrap:wrap; gap:.38rem; }
    .lp-audit-pill { display:inline-flex; padding:.28rem .55rem; border-radius:999px; font-size:.67rem; font-weight:780; letter-spacing:.035em; }
    .lp-audit-pill.approve, .lp-audit-pill.resolved { color:#05603a; background:#dcfae6; }
    .lp-audit-pill.modify, .lp-audit-pill.partial, .lp-audit-pill.pending { color:#93370d; background:#fff2cc; }
    .lp-audit-pill.reject, .lp-audit-pill.unresolved { color:#b42318; background:#ffe9e7; }
    .lp-audit-rationale { color:var(--lp-text-2); font-size:.79rem; line-height:1.5; margin-top:.8rem; padding-top:.72rem; border-top:1px solid var(--lp-border); }
    .lp-detail-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.7rem; }
    .lp-detail-item { background:var(--lp-panel-2); border:1px solid var(--lp-border); border-radius:.65rem; padding:.72rem .78rem; min-width:0; }
    .lp-detail-label { color:var(--lp-muted); font-size:.66rem; font-weight:750; letter-spacing:.055em; text-transform:uppercase; }
    .lp-detail-value { color:var(--lp-ink); font-size:.78rem; line-height:1.42; margin-top:.3rem; overflow-wrap:anywhere; }
    .lp-empty { text-align:center; padding:2.2rem 1rem; border:1px dashed var(--lp-border); border-radius:var(--lp-radius); background:var(--lp-panel); }
    .lp-empty strong { display:block; color:var(--lp-ink); margin-bottom:.3rem; }
    .lp-empty span { color:var(--lp-muted); font-size:.8rem; }

    .lp-summary, .lp-asset-card, .lp-kpi, .lp-evidence, .lp-action, .lp-workflow-card, .lp-audit-card {
      transition:transform .2s ease, box-shadow .2s ease, border-color .2s ease;
    }
    @media (hover:hover) {
      .lp-summary:hover, .lp-kpi:hover { transform:translateY(-3px) scale(1.02); box-shadow:var(--lp-shadow-md); }
      .lp-asset-card:hover, .lp-evidence:hover, .lp-action:hover, .lp-workflow-card:hover, .lp-audit-card:hover {
        transform:translateY(-2px); box-shadow:var(--lp-shadow-md); border-color:color-mix(in srgb, var(--lp-blue) 45%, var(--lp-border));
      }
    }
    :focus-visible { outline:3px solid color-mix(in srgb, var(--lp-blue) 55%, white); outline-offset:2px; }
    .stButton button, .stFormSubmitButton button { border-radius:.6rem; font-weight:700; transition:transform .16s ease, box-shadow .16s ease; }
    .stButton button:hover, .stFormSubmitButton button:hover { transform:translateY(-1px); box-shadow:var(--lp-shadow-sm); }
    .stButton button p, .stFormSubmitButton button p { color:inherit !important; }
    .stButton button[kind="secondary"] { background:var(--lp-panel); color:var(--lp-ink); border-color:var(--lp-border); }
    div[data-testid="stWidgetLabel"] p,
    div[data-testid="stRadio"] label p,
    div[data-testid="stCheckbox"] label p,
    div[data-testid="stToggle"] label p,
    [data-testid="stExpander"] summary,
    [data-testid="stExpander"] summary p { color:var(--lp-ink) !important; }
    div[data-testid="stSegmentedControl"] button[aria-pressed="false"],
    div[data-testid="stSegmentedControl"] button[aria-pressed="false"] p { color:var(--lp-text-2) !important; }
    div[data-testid="stSegmentedControl"] button[aria-pressed="true"],
    div[data-testid="stSegmentedControl"] button[aria-pressed="true"] p { color:#ffffff !important; }
    [data-testid="stTabs"] button[data-baseweb="tab"] { color:var(--lp-muted) !important; }
    [data-testid="stTabs"] button[data-baseweb="tab"] p { color:inherit !important; }
    [data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"] {
      color:var(--lp-ink) !important; border-bottom-color:var(--lp-blue) !important;
    }
    [data-testid="stTabs"] [data-baseweb="tab-highlight"] { background:var(--lp-blue) !important; }
    div[data-baseweb="select"] > div,
    div[data-baseweb="input"] > div,
    textarea { background:var(--lp-panel) !important; color:var(--lp-ink) !important; border-color:var(--lp-border) !important; }
    input, textarea, div[data-baseweb="select"] span { color:var(--lp-ink) !important; -webkit-text-fill-color:var(--lp-ink) !important; }
    input::placeholder, textarea::placeholder { color:var(--lp-muted) !important; opacity:1; }
    .stAlert { border-radius:.72rem; }
    [data-testid="stExpander"] { background:var(--lp-panel); border-color:var(--lp-border); }

    @media (max-width: 760px) {
      .block-container { padding:.75rem .75rem 1.5rem !important; }
      [data-testid="stSidebar"] { width:12rem !important; min-width:12rem !important; }
      [data-testid="stSidebar"] > div:first-child { width:12rem !important; }
      .lp-topbar { align-items:flex-start; }
      .lp-topmeta { align-items:flex-end; flex-direction:column; }
      .lp-snapshot { display:none; }
      .lp-asset-hero { grid-template-columns:1fr; }
      .lp-horizon { text-align:left; }
      .lp-detail-grid { grid-template-columns:1fr; }
      .lp-section-head { align-items:flex-start; flex-direction:column; gap:.2rem; }
      .lp-appbar { align-items:flex-start; }
      .lp-appbar-meta { align-items:flex-end; flex-direction:column; }
      .lp-appbar-snapshot { display:none; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { scroll-behavior:auto !important; transition:none !important; animation:none !important; }
      .lp-summary:hover, .lp-kpi:hover, .lp-asset-card:hover, .lp-evidence:hover, .lp-action:hover, .lp-workflow-card:hover, .lp-audit-card:hover { transform:none !important; }
      .lp-urgent { box-shadow:0 0 0 3px rgba(240,68,56,.18), var(--lp-shadow-xs) !important; animation:none !important; }
      .lp-urgent-badge::before { opacity:1 !important; }
      .lp-urgent-badge { animation:none !important; }
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
          --lp-bg:#2A2C31;
          --lp-panel:#34373D;
          --lp-panel-2:#3C4047;
          --lp-border:#59606B;
          --lp-ink:#F8F8FF;
          --lp-muted:#C9CED8;
          --lp-text-2:#E8EAF2;
          --lp-blue:#0F52BA;
          --lp-red-bg:#411d22;
          --lp-amber-bg:#422f13;
          --lp-green-bg:#101214;
          --lp-nav-bg:#24262B;
          --lp-nav-border:#4B5059;
          --lp-nav-text:#F8F8FF;
          --lp-nav-muted:#C9CED8;
        }
        .lp-kicker, .lp-panel-label, .lp-source { color:#8AB4F8; }
        .lp-appbar-logo { background:#0F52BA; }
        [data-testid="stSidebar"] { background:var(--lp-nav-bg); border-right-color:var(--lp-nav-border); }
        [data-testid="stSidebar"] div[role="radiogroup"] label { color:#F7FAFF !important; }
        [data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) { background:#0F52BA; color:#FFFFFF !important; }
        .lp-readonly { color:#a6f4c5; background:#123526; border-color:#087443; }
        .lp-audit-pill.approve, .lp-audit-pill.resolved { color:#d1fadf; background:#064e3b; }
        .lp-audit-pill.modify, .lp-audit-pill.partial, .lp-audit-pill.pending { color:#fef0c7; background:#713b12; }
        .lp-audit-pill.reject, .lp-audit-pill.unresolved { color:#fee4e2; background:#7a271a; }
        [data-testid="stAlert"] p, [data-testid="stAlert"] div { color:inherit !important; }
        [data-baseweb="popover"], [role="listbox"] { background:#172334 !important; color:#f2f4f7 !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

st.markdown(
    """
    <style>
    html { scroll-padding-top:5.75rem; }
    .stApp { background:var(--lp-bg) !important; color:var(--lp-ink); }
    .block-container { max-width:none; padding:calc(var(--lp-header-height) + .075rem) 1.45rem 2.25rem !important; }
    div[data-testid="stElementContainer"]:has(.lp-appbar) { display:contents !important; }
    div[data-testid="stElementContainer"]:has([data-testid="stHtml"]) { display:none !important; }
    [data-testid="stHeader"] { display:block !important; position:fixed !important; inset:0 0 auto 0 !important; height:2.75rem !important; background:transparent !important; z-index:1900 !important; pointer-events:none !important; }
    [data-testid="stToolbar"], [data-testid="stDecoration"] { display:none !important; }

    [data-testid="stSidebar"] { display:block; width:12.5rem !important; min-width:12.5rem !important; top:var(--lp-header-height) !important; height:calc(100vh - var(--lp-header-height)) !important; background:var(--lp-nav-bg) !important; border-right:1px solid var(--lp-nav-border) !important; }
    body:not(.lp-sidebar-hidden) [data-testid="stSidebar"] { display:block !important; visibility:visible !important; opacity:1 !important; transform:none !important; }
    body:not(.lp-sidebar-hidden) [data-testid="stMain"] { left:12.5rem !important; width:calc(100vw - 14.5rem) !important; }
    body.lp-sidebar-hidden [data-testid="stSidebar"] { display:none !important; }
    body.lp-sidebar-hidden [data-testid="stMain"] { left:0 !important; width:100vw !important; max-width:100vw !important; }
    [data-testid="stSidebar"] > div:first-child { width:12.5rem !important; }
    [data-testid="stSidebarHeader"] { display:none !important; height:0 !important; min-height:0 !important; padding:0 !important; margin:0 !important; }
    [data-testid="stSidebarContent"], [data-testid="stSidebarUserContent"] { padding-top:0 !important; }
    [data-testid="stSidebar"] .block-container { padding:0 .8rem 1rem !important; }
    [data-testid="collapsedControl"], [data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapseButton"] { visibility:hidden !important; opacity:0 !important; pointer-events:none !important; }
    .lp-side-brand { padding:.35rem .35rem 1rem; border-bottom-color:#2D3D54; }
    .lp-side-logo { background:#0F52BA; }
    .lp-side-name { color:#FFFFFF; }
    .lp-side-sub { color:#C3D0E2; }
    .lp-side-label { color:#B9C9DF; }
    [data-testid="stSidebar"] div[role="radiogroup"] label,
    [data-testid="stSidebar"] div[role="radiogroup"] label *,
    [data-testid="stSidebar"] div[role="radiogroup"] [data-testid="stMarkdownContainer"],
    [data-testid="stSidebar"] div[role="radiogroup"] [data-testid="stMarkdownContainer"] * {
      color:#F7FAFF !important; -webkit-text-fill-color:#F7FAFF !important; opacity:1 !important;
    }
    [data-testid="stSidebar"] div[role="radiogroup"] label:hover { background:#3A3D44 !important; transform:translateX(2px); }
    [data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) { background:#0F52BA !important; color:#FFFFFF !important; box-shadow:0 5px 16px rgba(15,82,186,.3); }
    [data-testid="stSidebar"] [data-testid="stToggle"] label,
    [data-testid="stSidebar"] [data-testid="stToggle"] label * { color:#F7FAFF !important; -webkit-text-fill-color:#F7FAFF !important; opacity:1 !important; }
    [data-testid="stSidebar"] [role="switch"] { border:2px solid #D8E5F5 !important; opacity:1 !important; }
    [data-testid="stSidebar"] [role="switch"][aria-checked="true"], [data-testid="stSidebar"] [role="switch"][aria-checked="false"] { background:#0F52BA !important; }
    .lp-side-status { background:#33363C; border-color:#555A64; }
    .lp-side-status strong { color:#F5F8FF; }
    .lp-side-status span { color:#C7D4E6; }

    .lp-appbar { position:fixed; inset:0 0 auto 0; z-index:1800; box-sizing:border-box; display:flex; align-items:center; justify-content:space-between; gap:1.2rem; height:var(--lp-header-height); min-height:var(--lp-header-height); padding:.8rem 1.45rem .8rem 4.25rem; margin:0; border:0; border-bottom:1px solid var(--lp-nav-border); border-radius:0; background:var(--lp-nav-bg); box-shadow:var(--lp-shadow-sm); }
    .lp-appbar-logo { width:2.25rem; height:2.25rem; flex-basis:2.25rem; background:#0F52BA; box-shadow:0 5px 12px rgba(15,82,186,.22); }
    .lp-appbar-title h1 { color:var(--lp-nav-text); font-size:1.28rem; }
    .lp-appbar-title p, .lp-appbar-snapshot { color:var(--lp-nav-muted); }
    .lp-appbar-snapshot strong { color:var(--lp-nav-text); }

    .lp-home-hero { padding:2.05rem 2.15rem; border-radius:1rem; background:linear-gradient(125deg,#2A2C31 0%,#353942 72%,#0F52BA 100%); color:#FFFFFF; box-shadow:0 16px 32px rgba(42,44,49,.18); margin:.35rem 0 1rem; }
    .lp-home-hero .eyebrow { color:#D7E5F5; }
    .lp-home-hero h2 { color:#FFFFFF; }
    .lp-home-hero p { color:#EDF3FA; }
    .lp-kicker, .lp-panel-label, .lp-source { color:var(--lp-blue); }
    .lp-summary.red, .lp-asset-card.red { --status:var(--lp-red); }
    .lp-summary.amber, .lp-asset-card.amber { --status:var(--lp-amber); }
    .lp-summary.green, .lp-asset-card.green { --status:var(--lp-green); }
    .lp-alert-icon { color:#D92D20 !important; background:#FEE4E2 !important; border:1px solid #FDA29B; }
    .lp-urgent { background:linear-gradient(105deg,var(--lp-panel) 0%,var(--lp-panel) 68%,var(--lp-red-bg) 100%); border-color:var(--lp-red) !important; }
    .lp-urgent-badge { border-radius:.35rem; background:var(--lp-red); border-color:var(--lp-red); }
    .blink { animation:lpBlink .75s linear infinite !important; will-change:opacity; }
    @keyframes lpBlink { 0%,50% { opacity:1; } 50.01%,100% { opacity:0; } }
    .lp-urgent, .lp-urgent-badge, .lp-urgent-badge::before { animation:none !important; }
    @media (hover:hover) { .lp-summary.red:hover, .lp-asset-card.red:hover, .lp-workflow-card.red:hover, .lp-urgent:hover { border-color:var(--lp-red) !important; border-left-color:var(--lp-red) !important; box-shadow:0 0 0 4px rgba(217,45,32,.28),0 14px 34px rgba(217,45,32,.22) !important; } }
    .stButton button[kind="primary"], .stFormSubmitButton button[kind="primary"] { background:#0F52BA !important; border-color:#0F52BA !important; color:#FFFFFF !important; }

    [data-testid="stExpander"] { background:var(--lp-panel) !important; border-color:var(--lp-border) !important; }
    [data-testid="stExpander"] details, [data-testid="stExpander"] summary, [data-testid="stExpander"] details[open] summary { background:var(--lp-panel-2) !important; color:var(--lp-ink) !important; border-color:var(--lp-border) !important; }
    [data-testid="stExpander"] summary *, [data-testid="stExpander"] summary svg { color:var(--lp-ink) !important; fill:var(--lp-ink) !important; -webkit-text-fill-color:var(--lp-ink) !important; opacity:1 !important; }
    [data-testid="InputInstructions"], [data-testid="InputInstructions"] * { color:var(--lp-muted) !important; -webkit-text-fill-color:var(--lp-muted) !important; opacity:1 !important; }
    [data-testid="stTooltipIcon"], [data-testid="stTooltipIcon"] *, [data-testid="stTooltipHoverTarget"] svg { color:var(--lp-ink) !important; fill:var(--lp-ink) !important; opacity:1 !important; }
    [data-testid="stTooltipContent"] { color:#FFFFFF !important; background:#17202D !important; border:1px solid #596579 !important; }
    [data-testid="stTooltipContent"] * { color:#FFFFFF !important; -webkit-text-fill-color:#FFFFFF !important; opacity:1 !important; }

    .stApp div[data-testid="stSelectbox"] div[role="group"], .stApp div[data-testid="stSelectbox"] div[data-baseweb="select"] > div { background:#FFFFFF !important; border-color:#8D97A5 !important; }
    .stApp div[data-testid="stSelectbox"] input[role="combobox"], .stApp div[data-testid="stSelectbox"] div[data-baseweb="select"] > div *, .stApp div[data-testid="stSelectbox"] div[data-baseweb="select"] [role="combobox"], .stApp div[data-testid="stSelectbox"] div[data-baseweb="select"] input { background:#FFFFFF !important; color:#353839 !important; -webkit-text-fill-color:#353839 !important; opacity:1 !important; }
    .stApp div[data-testid="stSelectbox"] button[aria-label="Open"], .stApp div[data-testid="stSelectbox"] button[aria-label="Open"] svg { color:#20252B !important; fill:#20252B !important; opacity:1 !important; }
    .stApp div[data-testid="stTextInput"] input { background:#FFFFFF !important; color:#353839 !important; -webkit-text-fill-color:#353839 !important; caret-color:#0F52BA !important; opacity:1 !important; }
    .stApp div[data-testid="stTextInput"] input::placeholder { color:#646A70 !important; -webkit-text-fill-color:#646A70 !important; opacity:1 !important; }
    .stApp div[data-testid="stTextArea"] textarea,
    .stApp div[data-testid="stNumberInput"] input,
    .stApp div[data-baseweb="input"] input {
      background:#FFFFFF !important; color:#353839 !important; -webkit-text-fill-color:#353839 !important;
      caret-color:#0F52BA !important; border-color:#8D97A5 !important; opacity:1 !important;
    }
    .stApp div[data-testid="stTextArea"] textarea::placeholder,
    .stApp div[data-testid="stNumberInput"] input::placeholder,
    .stApp div[data-baseweb="input"] input::placeholder { color:#646A70 !important; -webkit-text-fill-color:#646A70 !important; opacity:1 !important; }
    .stApp [data-testid="stWidgetLabel"], .stApp [data-testid="stWidgetLabel"] *,
    .stApp [data-testid="stRadio"] label, .stApp [data-testid="stRadio"] label *,
    .stApp [data-testid="stCheckbox"] label, .stApp [data-testid="stCheckbox"] label * {
      color:var(--lp-ink) !important; -webkit-text-fill-color:var(--lp-ink) !important; opacity:1 !important;
    }
    .stApp [data-testid="stSidebar"] [data-testid="stToggle"],
    .stApp [data-testid="stSidebar"] [data-testid="stToggle"] label,
    .stApp [data-testid="stSidebar"] [data-testid="stToggle"] label *,
    .stApp [data-testid="stSidebar"] [data-testid="stToggle"] [data-testid="stMarkdownContainer"],
    .stApp [data-testid="stSidebar"] [data-testid="stToggle"] [data-testid="stMarkdownContainer"] * {
      color:#F8F8FF !important; -webkit-text-fill-color:#F8F8FF !important; opacity:1 !important;
    }
    .stApp [data-testid="stSidebar"] [role="switch"][aria-checked="false"] {
      background:#46505E !important; border:2px solid #AFC8EC !important; box-shadow:inset 0 0 0 1px rgba(255,255,255,.14);
    }
    .stApp [data-testid="stSidebar"] [role="switch"][aria-checked="true"] {
      background:#0F52BA !important; border:2px solid #8AB4F8 !important;
    }
    [data-testid="stSidebarUserContent"], [data-testid="stSidebarUserContent"] > div { height:100% !important; }
    [data-testid="stSidebarUserContent"] { padding-bottom:7rem !important; }
    [data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"]:has(.st-key-appearance_panel) {
      min-height:calc(100vh - var(--lp-header-height) - 1rem) !important;
      display:flex !important; flex-direction:column !important;
    }
    .st-key-appearance_panel {
      position:fixed !important; left:.75rem !important; bottom:.75rem !important; z-index:1750 !important;
      width:11rem !important; box-sizing:border-box !important;
      margin:0 !important; padding:.8rem .75rem !important;
      border:1px solid #596579 !important; border-radius:.7rem !important;
      background:#20242B !important; box-shadow:0 8px 20px rgba(0,0,0,.18) !important;
    }
    [data-testid="stSidebarUserContent"] [data-testid="stElementContainer"]:has(.st-key-appearance_panel),
    [data-testid="stSidebarUserContent"] [data-testid="stVerticalBlockBorderWrapper"]:has(.st-key-appearance_panel) {
      margin-top:auto !important;
    }
    .st-key-appearance_panel .lp-side-label { margin:0 0 .55rem !important; color:#DCE9FA !important; }
    [data-testid="stSidebar"] [data-testid="stCheckbox"] label,
    [data-testid="stSidebar"] [data-testid="stCheckbox"] label *,
    [data-testid="stSidebar"] [data-testid="stCheckbox"] [data-testid="stWidgetLabel"],
    [data-testid="stSidebar"] [data-testid="stCheckbox"] [data-testid="stWidgetLabel"] * {
      color:#FFFFFF !important; -webkit-text-fill-color:#FFFFFF !important; opacity:1 !important;
      font-weight:700 !important;
    }
    [data-testid="stSidebar"] [data-testid="stCheckbox"] label > div:first-child,
    [data-testid="stSidebar"] [data-testid="stCheckbox"] label:has(input:not(:checked)) > div:first-child {
      background:#D68A00 !important; border:2px solid #FFD27A !important;
      box-shadow:0 0 0 2px rgba(255,210,122,.2) !important; opacity:1 !important;
    }
    [data-testid="stSidebar"] [data-testid="stCheckbox"] label:has(input:checked) > div:first-child {
      background:#0F52BA !important; border:2px solid #8AB4F8 !important;
      box-shadow:0 0 0 2px rgba(138,180,248,.22) !important; opacity:1 !important;
    }
    [data-testid="stSidebar"] [data-testid="stCheckbox"] label > div:first-child > div {
      background:#FFFFFF !important; opacity:1 !important;
    }
    [data-testid="stButtonGroup"] [data-variant="segmented_control"] {
      background:var(--lp-panel-2) !important; border-color:var(--lp-border) !important;
      color:var(--lp-ink) !important; -webkit-text-fill-color:var(--lp-ink) !important; opacity:1 !important;
    }
    [data-testid="stButtonGroup"] [data-variant="segmented_control"] * {
      color:inherit !important; -webkit-text-fill-color:currentColor !important; opacity:1 !important;
    }
    [data-testid="stButtonGroup"] [data-variant="segmented_control"][data-selected] {
      background:#0F52BA !important; border-color:#4D8FE8 !important;
      color:#FFFFFF !important; -webkit-text-fill-color:#FFFFFF !important;
    }
    @media (max-width:760px) { .st-key-appearance_panel { width:12.9rem !important; } }
    [data-baseweb="popover"] [role="option"], [data-baseweb="popover"] [role="option"] * {
      color:#F8F8FF !important; -webkit-text-fill-color:#F8F8FF !important; opacity:1 !important;
    }

    .lp-memory-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.7rem; margin:.85rem 0 .55rem; }
    .lp-memory-item { min-width:0; padding:1rem; border:1px solid var(--lp-border); border-radius:.68rem; background:var(--lp-panel-2); }
    .lp-memory-label { color:var(--lp-muted); font-size:.66rem; font-weight:760; letter-spacing:.055em; text-transform:uppercase; }
    .lp-memory-value { color:var(--lp-ink); font-size:.95rem; font-weight:780; line-height:1.35; margin-top:.32rem; overflow-wrap:anywhere; }

    @media (max-width:600px) { .block-container { padding:calc(var(--lp-header-height) + .06rem) .75rem 1.5rem !important; } [data-testid="stMain"] { left:0 !important; width:100vw !important; } .lp-appbar { padding:.7rem .75rem .7rem 4.15rem; } .lp-appbar-title h1 { font-size:1.08rem; } .lp-appbar-title p, .lp-appbar-meta, .lp-appbar-snapshot { display:none !important; } .lp-memory-grid { grid-template-columns:1fr; } }
    @media (prefers-reduced-motion:reduce) { .lp-urgent, .lp-urgent-badge, .lp-urgent-badge::before { animation:none !important; } }
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
          <div class="lp-summary-icon{' blink' if status == 'RED' else ''}" aria-hidden="true">{_h({'RED': '!', 'AMBER': '◒', 'GREEN': '✓'}[status])}</div>
          <div class="lp-summary-label">{_h(status)} · {_h(STATUS_LABELS[status])}</div>
          <div class="lp-summary-value">{int(count)}</div>
          <div class="lp-summary-copy">Class A assets</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _metric_card(label: str, value: Any, note: str, icon: str = "•", alert: bool = False) -> None:
    icon_class = "lp-kpi-icon lp-alert-icon blink" if alert else "lp-kpi-icon"
    st.markdown(
        f"""
        <div class="lp-kpi">
          <div class="{icon_class}" aria-hidden="true">{_h(icon)}</div>
          <div class="lp-kpi-label">{_h(label)}</div>
          <div class="lp-kpi-value">{_h(value)}</div>
          <div class="lp-kpi-note">{_h(note)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _empty_state(title: str, message: str) -> None:
    st.markdown(
        f"<div class='lp-empty'><strong>{_h(title)}</strong><span>{_h(message)}</span></div>",
        unsafe_allow_html=True,
    )


def _format_timestamp(value: Any) -> str:
    if value in (None, ""):
        return "Date unavailable"
    try:
        stamp = pd.to_datetime(value)
        return stamp.strftime("%d %b %Y · %H:%M")
    except (TypeError, ValueError):
        return str(value)


def _audit_record(case: Mapping[str, Any], position: int) -> None:
    case_id = _get(case, "case_id", "id", default=position)
    asset_id = _get(case, "asset_id", "AssetID", default="Unknown asset")
    owner = _get(case, "owner", "decision_owner", default="Equipment Owner")
    decision = str(_get(case, "decision", default="PENDING")).upper()
    outcome = str(_get(case, "outcome", "verified_outcome", default="PENDING") or "PENDING").upper()
    created_at = _format_timestamp(_get(case, "created_at", "decision_at", "timestamp"))
    rationale = _get(case, "rationale", "decision_rationale", default="No rationale recorded.")
    decision_class = decision.lower() if decision.lower() in {"approve", "modify", "reject"} else "pending"
    outcome_class = outcome.lower() if outcome.lower() in {"resolved", "partial", "unresolved"} else "pending"
    st.markdown(
        f"""
        <div class="lp-audit-card">
          <div class="lp-audit-head">
            <div><div class="lp-audit-title">{_h(asset_id)} <span style="color:var(--lp-muted);font-weight:650">· Case {_h(case_id)}</span></div>
            <div class="lp-audit-meta">{_h(owner)} · {_h(created_at)}</div></div>
            <div class="lp-audit-badges">
              <span class="lp-audit-pill {decision_class}">{_h(decision.title())}</span>
              <span class="lp-audit-pill {outcome_class}">{_h(outcome.replace('_', ' ').title())}</span>
            </div>
          </div>
          <div class="lp-audit-rationale"><strong>Rationale</strong><br>{_h(rationale)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander(f"View details · case {case_id}"):
        details = [
            ("Approved action", _get(case, "modified_action", "approved_action", "recommended_action", default="Original recommendation retained")),
            ("Outcome evidence", _get(case, "outcome_notes", "verification_notes", "notes", default="Awaiting technician verification")),
            ("Verified by", _get(case, "verified_by", "technician", "outcome_owner", default="Not yet verified")),
            ("Verified at", _format_timestamp(_get(case, "verified_at", "outcome_at", "updated_at"))),
            ("Original assessment", _get(case, "model_status", "original_status", "status", default="Preserved in asset record")),
            ("Equipment write", "None — decision support only"),
        ]
        content = "".join(
            f"<div class='lp-detail-item'><div class='lp-detail-label'>{_h(label)}</div><div class='lp-detail-value'>{_h(value)}</div></div>"
            for label, value in details
        )
        st.markdown(f"<div class='lp-detail-grid'>{content}</div>", unsafe_allow_html=True)


def _asset_card(asset: Mapping[str, Any], rank: int) -> None:
    status = asset["status"]
    model_note = ""
    if asset["model_status"] != status:
        model_note = f" · Model: {asset['model_status']}"
    ambiguity = " · HUMAN REVIEW" if asset.get("is_ambiguous") else ""
    warning_mark = '<span class="lp-warning-mark blink" aria-label="Critical warning">!</span>' if status == "RED" else ""
    st.markdown(
        f"""
        <div class="lp-asset-card {status.lower()}">
          {warning_mark}
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


def _render_asset_assessment(
    service: LinePulseService,
    selected_id: str,
    asset: Mapping[str, Any],
    action: Any,
    cause: Any,
    window_label: str,
) -> None:
    _section("Decision summary", "The information needed to choose the next safe action.")
    kpi_cols = st.columns(4)
    kpis = [
        ("Attention priority", f"{asset['attention_priority']:.0f}/100", "Where to review first", "↑"),
        ("Technical risk", f"{asset['technical_risk']:.0f}/100", "Condition and operating evidence", "◒"),
        ("Production impact", f"{asset['business_impact']:.0f}/100", "Consequence if availability is lost", "◆"),
        ("Data confidence", f"{asset['data_confidence']:.0f}/100", "Completeness and trust", "✓"),
    ]
    for column, (label, value, note, icon) in zip(kpi_cols, kpis):
        with column:
            _metric_card(label, value, note, icon)

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

    with st.expander("Planning simulation", expanded=False):
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
                base_priority = _score(_get(original_values, "attention_priority", default=_get(scenario, "baseline_priority", "current_priority", default=asset["attention_priority"])))
                new_priority = _score(_get(projected_values, "attention_priority", default=_get(scenario, "scenario_priority", "projected_priority", "attention_priority", default=base_priority)))
                base_days = _get(original_values, "days_remaining", default=_get(scenario, "baseline_days", "current_days", default=asset["days_remaining"]))
                new_days = _get(projected_values, "days_remaining", default=_get(scenario, "scenario_days", "projected_days", "days_remaining", default=base_days))
                w1, w2, w3 = st.columns(3)
                w1.metric("Projected priority", f"{new_priority:.0f}/100", f"{new_priority - base_priority:+.0f}")
                w2.metric("Projected horizon", _days_text(new_days), f"{_num(new_days) - _num(base_days):+.0f} days")
                w3.metric("Mode", "Read-only")
                note = _get(scenario, "explanation", "note", "message")
                if note:
                    st.info(str(note))
            except Exception as exc:
                _user_error("The planning scenario could not be calculated. Please retry.", exc)


def _render_asset_evidence(
    asset: Mapping[str, Any],
    detail_envelope: Mapping[str, Any],
) -> None:
    _section("Evidence passport", "Strongest signals behind the assessment.", "Official dataset")
    evidence_value = _get(asset, "evidence_passport", "evidence", default=_get(detail_envelope, "evidence_passport", "evidence", default=[]))
    evidence = _to_records(evidence_value)
    if evidence:
        evidence_cols = st.columns(min(3, len(evidence)))
        for column, item in zip(evidence_cols, evidence[:3]):
            with column:
                _evidence_card(item)
        with st.expander(f"View all {len(evidence)} evidence records", expanded=False):
            st.dataframe(pd.DataFrame(evidence), use_container_width=True, hide_index=True)
    else:
        _empty_state("No detailed evidence", "No evidence records were returned for this asset.")

    asset_flags = _flag_strings(_get(asset, "data_quality_flags", "quality_flags", default=_get(detail_envelope, "data_quality_flags", default=[])))
    if asset_flags:
        st.warning("Data confidence is reduced because: " + " · ".join(asset_flags))

    learning_value = _get(
        detail_envelope, "learning_summary", "decision_memory", "verified_outcome_memory", "similar_cases",
        default=asset.get("learning_summary"),
    )
    if learning_value:
        learning_map = _to_dict(learning_value)
        learning_records = _to_records(learning_value)
        learning_copy = _get(
            learning_map, "summary", "message", "recommendation_note", "note",
            default="No matching verified maintenance outcome is available yet.",
        )
        with st.expander("Verified outcome memory · similar completed cases", expanded=False):
            st.write(str(learning_copy))
            if learning_map:
                same_type_count = int(_num(_get(learning_map, "same_type_and_mode_resolved_cases", default=0)))
                same_mode_count = int(_num(_get(learning_map, "same_mode_resolved_cases", default=0)))
                learned_action = _get(learning_map, "learned_action_option", "learned_action", "recommended_action")
                learned_action_text = str(learned_action) if learned_action not in (None, "", "NULL") else "No learned action yet"
                source_text = str(_get(learning_map, "source", default="No verified match yet")).replace("_", " ").title()
                items = [
                    ("Same asset type and mode", f"{same_type_count} verified case{'s' if same_type_count != 1 else ''}"),
                    ("Same operating mode", f"{same_mode_count} verified case{'s' if same_mode_count != 1 else ''}"),
                    ("Learned action", learned_action_text),
                ]
                memory_html = "".join(
                    f"<div class='lp-memory-item'><div class='lp-memory-label'>{_h(label)}</div><div class='lp-memory-value'>{_h(value)}</div></div>"
                    for label, value in items
                )
                st.markdown(f"<div class='lp-memory-grid'>{memory_html}</div>", unsafe_allow_html=True)
                st.caption(f"Evidence source: {source_text}")
                examples = _to_records(_get(learning_map, "examples", "cases", default=[]))
                if examples:
                    st.dataframe(pd.DataFrame(examples).rename(columns=lambda column: str(column).replace("_", " ").title()), use_container_width=True, hide_index=True)
                else:
                    st.caption("No matching technician-verified examples are available yet.")
            elif learning_records:
                st.dataframe(pd.DataFrame(learning_records), use_container_width=True, hide_index=True)
            st.caption("Only technician-verified outcomes update recommendation memory.")


def _render_owner_decision(service: LinePulseService, selected_id: str, action: Any) -> None:
    _section("Owner decision", "AI recommends. The Equipment Owner decides and remains accountable.")
    st.markdown(
        "<div class='lp-panel'><div class='lp-panel-label'>Safety gate</div>"
        "<div class='lp-panel-value'>No automatic equipment action</div>"
        "<div class='lp-panel-copy'>Approve, modify, or reject the recommendation. A rationale is required for the audit trail.</div></div>",
        unsafe_allow_html=True,
    )
    with st.form("asset_decision_form", clear_on_submit=False):
        d1, d2 = st.columns([.75, 1.25])
        with d1:
            decision = st.radio("Decision", ["APPROVE", "MODIFY", "REJECT"], horizontal=True)
            owner = st.text_input("Decision owner", value="Equipment Owner")
        with d2:
            modified_action = st.text_area(
                "Approved or modified action", value=str(action),
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
                        service.record_decision, selected_id, decision=decision,
                        rationale=rationale.strip(), owner=owner.strip() or "Equipment Owner",
                        modified_action=(modified_action.strip() if decision == "MODIFY" else None),
                    )
                    result_map = _to_dict(result)
                    result_case = _to_dict(result_map.get("case"))
                    case_id = _get(result_map, "case_id", "id", default=_get(result_case, "case_id", "id", default="recorded"))
                    st.success(f"Decision recorded as case {case_id}. No automatic equipment action was taken.")
                except Exception as exc:
                    _user_error("The decision could not be recorded. Your equipment was not affected.", exc)


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
    "How it works": "Home",
    "Overview": "Priorities",
}
if st.session_state.get("workspace") in legacy_workspaces:
    st.session_state["workspace"] = legacy_workspaces[st.session_state["workspace"]]
requested_workspace = st.session_state.pop("_workspace_request", None)
if requested_workspace in {"Home", "Priorities", "Asset review", "Work verification"}:
    st.session_state["workspace"] = requested_workspace
if st.session_state.get("workspace") not in {"Home", "Priorities", "Asset review", "Work verification"}:
    st.session_state["workspace"] = "Home"
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

with st.sidebar:
    st.markdown(
        "<div class='lp-side-label'>Navigate</div>",
        unsafe_allow_html=True,
    )
    workspace = st.radio(
        "Workspace",
        ["Home", "Priorities", "Asset review", "Work verification"],
        key="workspace",
        format_func=lambda value: value,
        label_visibility="collapsed",
    )
    with st.container(key="appearance_panel"):
        st.markdown("<div class='lp-side-label lp-appearance-label'>Appearance</div>", unsafe_allow_html=True)
        st.toggle("Dark mode" if st.session_state.dark_mode else "Light mode", key="dark_mode")

_scroll_to_top_on_change("workspace", workspace)

st.markdown(
    f"""
    <div class="lp-appbar">
      <div class="lp-appbar-brand">
        <div class="lp-appbar-logo">LP</div>
        <div class="lp-appbar-title"><h1>LinePulse AI</h1></div>
      </div>
      <div class="lp-appbar-meta">
        <div class="lp-appbar-snapshot">Official data snapshot<strong>Week {_h(latest_source_week)} · {len(assets)} assets</strong></div>
        <div class="lp-readonly">● Human-controlled</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if workspace == "Home":
    red_count = sum(asset["status"] == "RED" for asset in assets)
    pending_count = 0
    try:
        home_cases = _to_records(_call(service.list_cases), ("cases", "items"))
        pending_count = sum(
            str(_get(case, "outcome", "verified_outcome", default="PENDING") or "PENDING").upper()
            in {"", "PENDING", "NONE", "AWAITING_OUTCOME"}
            and str(_get(case, "decision", default="")).upper() != "REJECT"
            for case in home_cases
        )
    except Exception:
        pass
    st.markdown(
        """<div class='lp-home-hero'>
          <div class='eyebrow'>Maintenance command center</div>
          <h2>Decide what needs attention.</h2>
          <p>Review priorities, inspect evidence, and close the loop on completed work.</p>
        </div>""",
        unsafe_allow_html=True,
    )
    _section("Today's snapshot", "A few signals to orient the next decision.")
    h1, h2, h3 = st.columns(3)
    with h1:
        _metric_card("Assets monitored", len(assets), "Class A equipment", "LP")
    with h2:
        _metric_card("Needs attention", red_count, "Red priority assets", "!", alert=True)
    with h3:
        _metric_card("Awaiting verification", pending_count, "Technician outcomes", "OK")
    _section("Choose your next step", "Each workspace keeps the decision small and clear.")
    home_cards = st.columns(3)
    cards = [
        ("01", "Review priorities", "Start with the assets carrying the highest operational consequence.", "Priorities", "Open priorities"),
        ("02", "Review an asset", "Read the recommendation, evidence, and owner decision in one place.", "Asset review", "Open asset review"),
        ("03", "Verify completed work", "Close the learning loop with technician-confirmed outcomes.", "Work verification", "Open verification"),
    ]
    for column, (step, title, copy, target, label) in zip(home_cards, cards):
        with column:
            st.markdown(f"<div class='lp-home-card'><div class='step'>{step}</div><h3>{title}</h3><p>{copy}</p></div>", unsafe_allow_html=True)
            if st.button(label, key=f"home_{target}", use_container_width=True):
                st.session_state["_workspace_request"] = target
                st.rerun()
    st.caption(f"Data snapshot: Week {latest_source_week} · {len(assets)} assets · Human approval required")

if workspace == "Priorities":
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


if workspace == "Priorities":
    counts = {status: sum(asset["status"] == status for asset in assets) for status in STATUS_COLORS}
    _section("Portfolio status", "Current Class A estate at a glance.", f"Week {latest_source_week}")
    total_col, red_col, amber_col, green_col = st.columns([1.05, 1, 1, 1])
    with total_col:
        _metric_card("Assets screened", len(assets), "Class A assets", "◇")
    with red_col:
        _summary_card("RED", counts["RED"])
    with amber_col:
        _summary_card("AMBER", counts["AMBER"])
    with green_col:
        _summary_card("GREEN", counts["GREEN"])

    _section(
        "Priority assets",
        "Highest urgency and production consequence. Open one to review its evidence.",
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
        _empty_state("No matching assets", "Adjust the collapsed filters to broaden the portfolio view.")

    chart_assets = filtered if filtered else assets
    frame = pd.DataFrame(chart_assets)
    _section("Asset analysis", "Explore portfolio patterns or open the asset register when needed.")
    overview_data = _to_dict(_get(overview, "data", "data_profile", "dataset", default={}))
    overview_flags = _flag_strings(
        _get(overview, "data_quality_flags", "quality_flags", "data_quality", default=overview_data.get("data_quality", []))
    )
    with st.expander(f"Open asset analysis · {len(filtered)} assets", expanded=False):
        analysis_tab, register_tab = st.tabs(["Risk & impact", "Asset register"])
        with analysis_tab:
            chart_left, chart_right = st.columns([1.15, 1])
            with chart_left:
                matrix = px.scatter(
                    frame, x="technical_risk", y="business_impact", color="status", symbol="status",
                    size="attention_priority", hover_name="asset_id",
                    hover_data={"name": True, "line": True, "days_remaining": True, "data_confidence": ":.0f"},
                    color_discrete_map=STATUS_COLORS, category_orders={"status": ["RED", "AMBER", "GREEN"]},
                    labels={"technical_risk": "Technical risk", "business_impact": "Production impact"},
                    title="Risk and production impact", size_max=24,
                )
                matrix.add_vline(x=55, line_dash="dot", line_color="#98A2B3")
                matrix.add_hline(y=70, line_dash="dot", line_color="#98A2B3")
                matrix.update_xaxes(range=[0, 100]); matrix.update_yaxes(range=[0, 100])
                st.plotly_chart(_plot_style(matrix, 360), use_container_width=True)
            with chart_right:
                priority = frame.nlargest(min(10, len(frame)), "attention_priority").sort_values("attention_priority")
                bars = px.bar(
                    priority, x="attention_priority", y="asset_id", color="status", orientation="h",
                    color_discrete_map=STATUS_COLORS, category_orders={"status": ["RED", "AMBER", "GREEN"]},
                    hover_data={"failure_mode": True, "days_remaining": True},
                    labels={"attention_priority": "Attention priority", "asset_id": "Asset"}, title="Highest priorities",
                )
                bars.update_layout(showlegend=False)
                st.plotly_chart(_plot_style(bars, 360), use_container_width=True)
            st.caption("Priority combines technical risk and production impact; RAG reflects condition and horizon.")
        with register_tab:
            columns = ["status", "asset_id", "name", "line", "days_remaining", "attention_priority", "data_confidence"]
            display = pd.DataFrame(filtered)[columns].copy() if filtered else pd.DataFrame(columns=columns)
            display.columns = ["Status", "Asset ID", "Asset", "Line", "Days", "Priority", "Confidence"]
            st.dataframe(
                display, use_container_width=True, hide_index=True,
                column_config={
                    "Priority": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
                    "Confidence": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
                },
            )
            if overview_flags:
                with st.expander(f"Data-quality gate · {len(overview_flags)} finding(s)"):
                    for flag in overview_flags:
                        st.warning(flag)

    try:
        overview_cases = _to_records(_call(service.list_cases), ("cases", "items"))
    except Exception:
        overview_cases = []
    pending_overview = [
        case for case in overview_cases
        if str(_get(case, "outcome", "verified_outcome", default="PENDING") or "PENDING").upper()
        in {"", "PENDING", "NONE", "AWAITING_OUTCOME"}
        and str(_get(case, "decision", default="")).upper() != "REJECT"
    ]
    _section("Decision support", "Move from evidence to a human-owned maintenance decision.")
    next_asset = filtered[0] if filtered else assets[0]
    decision_left, decision_right = st.columns(2)
    with decision_left:
        st.markdown(
            f"""<div class='lp-workflow-card'><div class='lp-kicker'>Next owner review</div>
            <div class='lp-workflow-value'>{_h(next_asset['asset_id'])}</div>
            <h3>{_h(next_asset['status'])} · priority {next_asset['attention_priority']:.0f}/100</h3>
            <p>{_h(next_asset['recommended_action'])}</p></div>""", unsafe_allow_html=True,
        )
        if st.button("Review recommendation", key="overview_review_next", type="primary", use_container_width=True):
            st.session_state.selected_asset = next_asset["asset_id"]
            st.session_state._open_asset_next = True
            st.rerun()
    with decision_right:
        st.markdown(
            f"""<div class='lp-workflow-card'><div class='lp-kicker'>Learning loop</div>
            <div class='lp-workflow-value'>{len(pending_overview)}</div>
            <h3>case{'s' if len(pending_overview) != 1 else ''} awaiting verification</h3>
            <p>Technician evidence closes the case and may update the operational colour. The original model assessment remains preserved.</p></div>""",
            unsafe_allow_html=True,
        )
        if st.button("Open work verification", key="overview_open_verification", type="primary", use_container_width=True):
            st.session_state["_workspace_request"] = "Work verification"
            st.rerun()

    _section("Historical activity", "Recent owner decisions and technician-verified outcomes.")
    with st.expander(f"Open decision history · {len(overview_cases)} case(s)", expanded=False):
        if overview_cases:
            for index, case in enumerate(reversed(overview_cases[-3:]), start=1):
                _audit_record(case, index)
        else:
            _empty_state("No decision history yet", "Review an asset and record the Equipment Owner's decision to begin the audit trail.")


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
    days_remaining = _num(asset["days_remaining"], default=999.0)
    is_urgent = status == "RED" and days_remaining <= 10
    urgency_badge = (
        f'<div class="lp-urgent-badge">Urgent review · {_h(_days_text(asset["days_remaining"]))} remaining</div>'
        if is_urgent else ""
    )
    hero_classes = f"lp-asset-hero {status.lower()}"
    if is_urgent:
        hero_classes += " lp-urgent"
    warning_mark = '<span class="lp-warning-mark blink" aria-label="Critical warning">!</span>' if status == "RED" else ""
    hero_html = (
        f'<div class="{hero_classes}" style="border-left:6px solid {STATUS_COLORS[status]}">'
        f'{warning_mark}'
        f'<span class="lp-help" style="--status:{STATUS_DARK[status]}" tabindex="0" aria-label="Why this status">?'
        f'<span class="lp-tip">{_h(_status_tooltip(asset))}</span></span>'
        '<div>'
        f'{urgency_badge}'
        f'<div class="lp-kicker">{_h(asset["line"])} · {_h(asset["type"])}</div>'
        f'<h2>{_h(asset["asset_id"])} · {_h(asset["name"])}</h2>'
        f'<p>{_h(asset["failure_mode"])}</p>'
        f'<div style="margin-top:.65rem"><span class="lp-status-pill" style="background:{STATUS_DARK[status]}">'
        f'<span class="lp-dot"></span><span class="lp-status-text{" blink" if status == "RED" else ""}">'
        f'{_h(status)} · {_h(STATUS_LABELS[status])}</span></span></div>'
        '</div>'
        f'<div class="lp-horizon"><strong>{_h(_days_text(asset["days_remaining"]))}</strong>'
        '<span>planning horizon</span></div></div>'
    )
    st.markdown(
        hero_html,
        unsafe_allow_html=True,
    )
    if asset["is_ambiguous"]:
        st.warning(f"Extra judgement required · {asset['ambiguity_reason']}")

    action = _get(detail_envelope, "recommended_action", "action", default=asset["recommended_action"])
    cause = _get(detail_envelope, "failure_mode", "likely_failure_mode", default=asset["failure_mode"])
    maintenance_window = _get(detail_envelope, "maintenance_window", "recommended_window")
    if isinstance(maintenance_window, Mapping):
        window_label = str(_get(maintenance_window, "label", "window", default="Use the next safe production opportunity"))
    else:
        window_label = str(maintenance_window or asset.get("planning_window") or "Use the next safe production opportunity")


    review_view = st.segmented_control(
        "Asset review section",
        ["Assessment", "Evidence", "Owner decision"],
        default="Assessment",
        key=f"asset_review_section_{selected_id}",
        label_visibility="collapsed",
    ) or "Assessment"

    _scroll_to_top_on_change("asset-review", f"{selected_id}:{review_view}")

    if review_view == "Assessment":
        _render_asset_assessment(service, selected_id, asset, action, cause, window_label)
    elif review_view == "Evidence":
        _render_asset_evidence(asset, detail_envelope)
    else:
        _render_owner_decision(service, selected_id, action)


elif workspace == "Work verification":
    _section("Work summary", "Human decisions and completed maintenance outcomes.")
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
    with c1:
        _metric_card("Recorded decisions", len(case_records), "Complete audit history", "◇")
    with c2:
        _metric_card("Awaiting outcome", len(pending_cases), "Technician evidence required", "…")
    with c3:
        _metric_card("Verified resolved", resolved_count, "Closed learning loops", "✓")

    _section("Verify completed work", "Record what the technician observed. Only verified results update the operating view.")
    if pending_cases:
        with st.expander(f"Record completed work · {len(pending_cases)} case(s) ready", expanded=False):
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
        _empty_state("No work awaiting verification", "Approved and modified cases appear here after maintenance is completed.")

    _section("Decision history", "A readable, immutable trail of recommendations, owner decisions, and verified outcomes.")
    if case_records:
        with st.expander(f"Browse audit trail · {len(case_records)} case(s)", expanded=False):
            for index, case in enumerate(reversed(case_records), start=1):
                _audit_record(case, index)
    else:
        _empty_state("No human decisions recorded", "Open Asset review to assess an asset and record the Equipment Owner's decision.")
