from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from quality import check_quality, read_orders, run_etl, quality_trend, rule_distribution

ROOT = Path(__file__).parent
CSV_PATH = ROOT / "data" / "orders.csv"
DB_PATH = ROOT / "data" / "metrics.db"


def metric_value(value: object, prefix: str = "", decimals: int = 2) -> str:
    """Format nullable numeric values consistently in the dashboard."""
    if value is None or pd.isna(value):
        return "-"
    return f"{prefix}{float(value):,.{decimals}f}"


@st.cache_data
def load_data(db_path: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with sqlite3.connect(db_path) as connection:
        overview = pd.read_sql_query("""SELECT COUNT(*) order_count,
            ROUND(COALESCE(SUM(quantity * unit_price), 0), 2) gmv,
            ROUND(COALESCE(SUM(quantity * unit_price) / NULLIF(COUNT(*), 0), 0), 2) average_order_value,
            COUNT(DISTINCT customer_id) customer_count, COALESCE(SUM(quantity), 0) units
            FROM orders""", connection)
        daily = pd.read_sql_query("""SELECT order_date, COUNT(*) order_count,
            ROUND(SUM(quantity * unit_price), 2) gmv
            FROM orders GROUP BY order_date ORDER BY order_date""", connection)
        products = pd.read_sql_query("""SELECT product_id, COUNT(*) order_count,
            ROUND(SUM(quantity * unit_price), 2) gmv, SUM(quantity) units
            FROM orders GROUP BY product_id ORDER BY gmv DESC""", connection)
        quarantine = pd.read_sql_query("""SELECT source_row, rule, column_name, value, payload
            FROM quarantine ORDER BY source_row""", connection)
        history = pd.read_sql_query("""SELECT run_id, run_at, total_rows, valid_rows,
            issue_count, score, source FROM quality_runs ORDER BY run_at, run_id""", connection)
        distribution = pd.read_sql_query("""SELECT rule, SUM(issue_count) issue_count
            FROM quality_run_rules GROUP BY rule ORDER BY issue_count DESC, rule""", connection)
    return overview, daily, products, quarantine, history, distribution


st.set_page_config(page_title="DQ Observatory", page_icon="DQ", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
    :root { --ink:#17324d; --muted:#6b7d8f; --line:#dce6ec; --teal:#087f7b; --blue:#1976a8; --orange:#d97706; --surface:#ffffff; }
    .stApp { background:#f4f7f9; color:var(--ink); }
    [data-testid="stHeader"] { background:transparent; }
    .block-container { max-width:1360px; padding:2.2rem 3rem 3rem; }
    h1, h2, h3 { color:var(--ink); letter-spacing:0; }
    h1 { font-size:2rem !important; margin-bottom:.15rem; }
    h2 { font-size:1.18rem !important; margin-top:1.6rem; }
    .eyebrow { color:var(--teal); font-size:.76rem; font-weight:700; letter-spacing:.08em; text-transform:uppercase; margin-bottom:.35rem; }
    .subtitle { color:var(--muted); margin:0 0 1.15rem; }
    .statusbar { display:flex; align-items:center; justify-content:space-between; gap:1rem; background:var(--surface); border:1px solid var(--line); border-left:4px solid var(--teal); padding:.75rem 1rem; margin:.3rem 0 1.15rem; }
    .status-left { color:var(--ink); font-size:.88rem; }
    .status-dot { display:inline-block; width:8px; height:8px; background:#18a67a; border-radius:50%; margin-right:7px; }
    .status-meta { color:var(--muted); font-size:.8rem; }
    [data-testid="stMetric"] { background:var(--surface); border:1px solid var(--line); border-radius:6px; padding:1rem 1.05rem; box-shadow:0 2px 8px rgba(23,50,77,.04); }
    [data-testid="stMetricLabel"] { color:var(--muted); font-size:.78rem; }
    [data-testid="stMetricValue"] { color:var(--ink); font-size:1.55rem; }
    .score-card { background:var(--surface); border:1px solid var(--line); border-top:4px solid var(--teal); border-radius:6px; padding:1.2rem 1.35rem; min-height:132px; }
    .score-label { color:var(--muted); font-size:.82rem; }
    .score-value { color:var(--teal); font-size:2.65rem; font-weight:750; line-height:1.1; margin:.25rem 0; }
    .score-good { color:#16805d; font-size:.8rem; }
    .score-warn { color:var(--orange); font-size:.8rem; }
    .panel { background:var(--surface); border:1px solid var(--line); border-radius:6px; padding:1rem 1.1rem .8rem; min-height:260px; }
    .panel-title { color:var(--ink); font-size:1rem; font-weight:700; margin-bottom:.55rem; }
    .panel-note { color:var(--muted); font-size:.78rem; margin-bottom:.6rem; }
    [data-testid="stSidebar"] { background:#eef4f6; border-right:1px solid var(--line); }
    [data-testid="stDataFrame"] { border:1px solid var(--line); }
    .stDownloadButton button, .stButton button { border-radius:5px; }
    div[data-testid="stExpander"] { background:var(--surface); border:1px solid var(--line); }
</style>
""", unsafe_allow_html=True)

if not DB_PATH.exists():
    run_etl(CSV_PATH, DB_PATH)

overview, daily, products, quarantine, history, distribution = load_data(str(DB_PATH))
quality = check_quality(read_orders(CSV_PATH))

with st.sidebar:
    st.markdown("### Pipeline controls")
    if st.button("Refresh pipeline", type="primary", use_container_width=True):
        run_etl(CSV_PATH, DB_PATH)
        st.cache_data.clear()
        st.success("Pipeline refreshed")
        st.rerun()
    st.markdown("---")
    st.caption(f"Source file\n`{CSV_PATH.name}`")
    st.caption("Local-first monitoring · SQLite")

status_label = "Healthy source" if quality.total_issues == 0 else "Review required"
status_color = "#16805d" if quality.total_issues == 0 else "#d97706"
latest_date = daily["order_date"].max() if not daily.empty else "-"
st.markdown('<div class="eyebrow">Data operations / quality control</div>', unsafe_allow_html=True)
st.title("Data Quality Observatory")
st.markdown('<p class="subtitle">A compact command center for validating order data before it reaches reporting.</p>', unsafe_allow_html=True)
st.markdown(f'''<div class="statusbar"><div class="status-left"><span class="status-dot" style="background:{status_color}"></span><b>{status_label}</b>&nbsp; · &nbsp;validation pipeline is online</div><div class="status-meta">{len(read_orders(CSV_PATH)):,} source rows&nbsp; · &nbsp;latest {latest_date}</div></div>''', unsafe_allow_html=True)

score_state = "Within expected range" if quality.score >= 95 else "Investigate exceptions"
score_class = "score-good" if quality.score >= 95 else "score-warn"
score_col, kpi_col = st.columns([1, 3])
with score_col:
    st.markdown(f'''<div class="score-card"><div class="score-label">OVERALL QUALITY SCORE</div><div class="score-value">{quality.score:.1f}<span style="font-size:1.05rem;color:#6b7d8f"> / 100</span></div><div class="{score_class}">{score_state} · {quality.valid_rows:,} valid rows</div></div>''', unsafe_allow_html=True)
with kpi_col:
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("GMV", metric_value(overview.at[0, "gmv"], "¥"))
    k2.metric("Orders", f"{int(overview.at[0, 'order_count']):,}")
    k3.metric("Customers", f"{int(overview.at[0, 'customer_count']):,}")
    k4.metric("Units sold", f"{int(overview.at[0, 'units']):,}")

st.subheader("Quality checks")
q1, q2, q3, q4, q5 = st.columns(5)
q1.metric("Rows checked", quality.rows_checked)
q2.metric("Valid rows", quality.valid_rows)
q3.metric("Issues", quality.total_issues)
q4.metric("Missing", quality.missing_values)
q5.metric("Quarantined", len(quarantine))

if not daily.empty:
    min_date = pd.to_datetime(daily["order_date"]).min().date()
    max_date = pd.to_datetime(daily["order_date"]).max().date()
    selected = st.date_input("Reporting window", (min_date, max_date), min_value=min_date, max_value=max_date)
    if isinstance(selected, tuple) and len(selected) == 2:
        start, end = selected
        daily = daily[(pd.to_datetime(daily["order_date"]).dt.date >= start) & (pd.to_datetime(daily["order_date"]).dt.date <= end)]

st.subheader("Monitor")
trend_col, exception_col = st.columns([1.45, 1])
with trend_col:
    st.markdown('<div class="panel"><div class="panel-title">GMV trend</div><div class="panel-note">Daily gross merchandise value within the selected reporting window.</div>', unsafe_allow_html=True)
    if daily.empty:
        st.info("No data in this date range.")
    else:
        st.line_chart(daily.set_index("order_date")["gmv"], color="#087f7b", height=245)
    st.markdown('</div>', unsafe_allow_html=True)
with exception_col:
    st.markdown('<div class="panel"><div class="panel-title">Exception queue</div><div class="panel-note">Rows held back from the trusted orders table.</div>', unsafe_allow_html=True)
    if quarantine.empty:
        st.success("No exceptions found in the current source.")
    else:
        st.dataframe(quarantine[["source_row", "rule", "column_name", "value"]], use_container_width=True, hide_index=True, height=180)
        st.download_button("Download exceptions CSV", quarantine.to_csv(index=False), "quarantine.csv", "text/csv", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

st.subheader("Quality observability")
history_col, rules_col = st.columns([1.45, 1])
with history_col:
    st.markdown('<div class="panel"><div class="panel-title">Run history / quality trend</div><div class="panel-note">Every ETL execution is retained, including empty or invalid runs.</div>', unsafe_allow_html=True)
    if history.empty:
        st.info("No pipeline runs recorded yet.")
    else:
        trend = history.set_index("run_at")[["score", "total_rows", "valid_rows", "issue_count"]]
        st.line_chart(trend[["score"]], color="#087f7b", height=220)
        st.dataframe(history.sort_values(["run_at", "run_id"], ascending=False), use_container_width=True, hide_index=True, height=180)
    st.markdown('</div>', unsafe_allow_html=True)
with rules_col:
    st.markdown('<div class="panel"><div class="panel-title">Rule distribution</div><div class="panel-note">Cumulative exceptions by rule across retained pipeline runs.</div>', unsafe_allow_html=True)
    if distribution.empty:
        st.info("No rule exceptions recorded.")
    else:
        st.bar_chart(distribution.set_index("rule")["issue_count"], color="#d97706", height=220)
        st.dataframe(distribution, use_container_width=True, hide_index=True)
    st.markdown('</div>', unsafe_allow_html=True)

st.subheader("Product performance")
st.dataframe(products, use_container_width=True, hide_index=True)

with st.expander("Lineage and metric definitions"):
    st.markdown("**Lineage:** `data/orders.csv` → `check_quality` → `quarantine` / `orders` → SQL aggregates → this dashboard.")
    st.markdown("**GMV** = sum(quantity × unit_price); **AOV** = GMV ÷ valid order count; quality score deducts one point per issue per checked row, bounded to 0–100.")
