"""Streamlit investigator review screen for the AML synthetic bank.

Owner: Antigravity · Build plan: item 9 · Design: Step 6
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# Ensure repository root is on sys.path when launched directly (e.g. streamlit run ui/app.py)
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import streamlit as st

from ui.data import (
    API_EQUIVALENT_LABEL,
    API_EQUIVALENT_RATES_PER_M,
    calculate_api_cost,
    ensure_decisions_table,
    list_decisions,
    load_case,
    load_queue,
    lookup_source,
    save_decision,
)

# Page Configuration
st.set_page_config(
    page_title="AML Investigator Review",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Sidebar configuration and paths
st.sidebar.title("AML Investigation System")
st.sidebar.markdown("**Synthetic Bank Proof of Concept**")

st.sidebar.header("Data Paths")
default_db_path = os.getenv("AML_BANK_DB", str(REPO_ROOT / "bank" / "bank.db"))
default_cases_dir = os.getenv("AML_CASES_DIR", str(REPO_ROOT / "cases"))
default_usage_path = os.getenv("AML_USAGE_LOG", str(REPO_ROOT / "usage" / "usage.jsonl"))

db_path = st.sidebar.text_input("Bank DB Path (AML_BANK_DB)", value=default_db_path)
cases_dir = st.sidebar.text_input("Cases Directory (AML_CASES_DIR)", value=default_cases_dir)
usage_path = st.sidebar.text_input("Usage Log Path (AML_USAGE_LOG)", value=default_usage_path)

st.sidebar.markdown("---")
st.sidebar.subheader("AI FinOps Model Rates")
st.sidebar.caption(API_EQUIVALENT_LABEL)
st.sidebar.markdown(
    f"""
    - **Input:** ${API_EQUIVALENT_RATES_PER_M['input']:.2f} / 1M tokens
    - **Output:** ${API_EQUIVALENT_RATES_PER_M['output']:.2f} / 1M tokens
    - **Cache Write:** ${API_EQUIVALENT_RATES_PER_M['cache_write']:.2f} / 1M tokens
    - **Cache Read:** ${API_EQUIVALENT_RATES_PER_M['cache_read']:.2f} / 1M tokens
    """
)

# Prominent Synthetic Data & Human Decision Banner
st.warning(
    "⚠️ **SYNTHETIC DATA & PROOF OF CONCEPT — HUMAN MAKES EVERY DECISION**\n\n"
    "All bank records, customer profiles, counterparties, and alerts in this system are entirely synthetic. "
    "The AI agent gathers evidence and suggests an action, but **a human investigator must make and record every final decision**."
)

st.title("AML Investigator Review Screen")
st.caption("Review queued AML alerts, inspect cited evidence records, and record human decisions.")

# Load Queue
try:
    queue = load_queue(db_path=db_path, cases_dir=cases_dir, usage_path=usage_path)
except Exception as e:
    st.error(f"Error loading investigation queue from database: {e}")
    queue = []

if not queue:
    st.info("No open alerts found in the database queue.")
    st.stop()

# Queue Table View
st.subheader("Investigation Queue")
st.markdown("Open alerts ranked by **Risk Rating** (High > Medium > Low > Not investigated), then **Rule Score** (descending), then **Case ID**.")

queue_display_data = []
for item in queue:
    typology_str = ", ".join(item["typologies"]) if item["typologies"] else "None"
    queue_display_data.append({
        "Case ID": item["case_id"],
        "Customer ID": item["customer_id"],
        "Risk Rating": item["risk_rating"],
        "Rule Score": f"{item['score']:.2f}",
        "Typologies": typology_str,
        "Total Tokens": f"{item['total_tokens']:,}" if item["total_tokens"] > 0 else "0",
        "API Cost ($)": f"${item['api_cost_usd']:.4f}" if item["api_cost_usd"] > 0 else "$0.0000",
        "Decision Status": item["decision_status"],
    })

st.dataframe(
    queue_display_data,
    width="stretch",
    hide_index=True,
)

st.markdown("---")

# Case Selection
case_ids = [item["case_id"] for item in queue]
selected_case_id = st.selectbox(
    "Select Case to Review:",
    options=case_ids,
    index=0,
    format_func=lambda cid: f"{cid} — {next((item['risk_rating'] for item in queue if item['case_id'] == cid), '')} (Customer: {next((item['customer_id'] for item in queue if item['case_id'] == cid), '')})",
)

# Retrieve selected case data from queue
selected_item = next((item for item in queue if item["case_id"] == selected_case_id), None)
if not selected_item:
    st.error(f"Case {selected_case_id} not found in queue.")
    st.stop()

case_file = load_case(cases_dir, selected_case_id)

# Case Header Information
col_hdr1, col_hdr2, col_hdr3, col_hdr4 = st.columns(4)
with col_hdr1:
    st.metric(label="Case ID", value=selected_case_id)
with col_hdr2:
    st.metric(label="Customer ID", value=selected_item["customer_id"])
with col_hdr3:
    st.metric(label="Risk Rating", value=selected_item["risk_rating"])
with col_hdr4:
    st.metric(label="Alert Rule Score", value=f"{selected_item['score']:.2f}")

col_fin1, col_fin2, col_fin3 = st.columns(3)
with col_fin1:
    st.write(f"**Typologies:** {', '.join(selected_item['typologies']) if selected_item['typologies'] else 'None'}")
with col_fin2:
    st.write(f"**Tokens Consumed:** {selected_item['total_tokens']:,}")
with col_fin3:
    st.write(f"**API-Equivalent Cost:** ${selected_item['api_cost_usd']:.4f} *(illustrative)*")

st.markdown("---")

# Case Details or Uninvestigated Alert Notice
if not case_file:
    st.info(
        f"ℹ️ **Case {selected_case_id} has not been investigated by the agent yet.**\n\n"
        f"Alert rule triggered on customer `{selected_item['customer_id']}` with score `{selected_item['score']:.2f}`. "
        "No case file draft is available on disk."
    )
    if selected_item.get("hits"):
        with st.expander("View Underlying Rule Hits"):
            st.json(selected_item["hits"])
else:
    # Summary Section
    st.subheader("Case Summary")
    st.info(case_file.get("summary", "No summary provided in case file."))

    # Cited Evidence Section with Clickable Source IDs
    st.subheader("Cited Evidence Claims")
    st.caption("Every claim is cited. Click any source ID button to inspect the underlying synthetic banking record.")

    # Container for showing inspected source record
    inspected_tuple = st.session_state.get("inspected_source")
    if inspected_tuple and inspected_tuple[0] == selected_case_id:
        active_source_id = inspected_tuple[1]
        rec_data = lookup_source(db_path, active_source_id)
        with st.container():
            st.markdown(f"#### 🔎 Inspected Record: `{active_source_id}` ({rec_data['kind'].upper()})")
            if rec_data["found"]:
                st.dataframe(rec_data["records"], width="stretch")
            else:
                st.warning(f"Record `{active_source_id}` not found in database.")
            if st.button("✕ Close Record View", key=f"close_{selected_case_id}_{active_source_id}"):
                st.session_state["inspected_source"] = None
                st.rerun()
            st.markdown("---")

    evidence_items = case_file.get("evidence", [])
    if not evidence_items:
        st.write("No evidence items listed.")
    else:
        for idx, ev in enumerate(evidence_items):
            st.markdown(f"**Claim {idx + 1}:** {ev.get('claim', '')}")
            sources = ev.get("source", [])
            if sources:
                btn_cols = st.columns(max(len(sources), 1))
                for col, src_id in zip(btn_cols, sources):
                    if col.button(f"📄 {src_id}", key=f"src_btn_{selected_case_id}_{idx}_{src_id}"):
                        st.session_state["inspected_source"] = (selected_case_id, src_id)
                        st.rerun()

                with st.expander(f"View all records cited in Claim {idx + 1} ({len(sources)} citations)"):
                    for src_id in sources:
                        res = lookup_source(db_path, src_id)
                        st.markdown(f"**Source: `{src_id}`** ({res['kind']})")
                        if res["found"]:
                            st.dataframe(res["records"], width="stretch")
                        else:
                            st.caption(f"Record {src_id} not found.")
            st.write("")

    # Innocent Explanations
    st.subheader("Innocent Explanations")
    innocent = case_file.get("innocent_explanations", [])
    if innocent:
        for item in innocent:
            st.markdown(f"- {item}")
    else:
        st.caption("None recorded.")

    # Information Gaps
    st.subheader("Information Gaps")
    gaps = case_file.get("gaps", [])
    if gaps:
        for item in gaps:
            st.markdown(f"- {item}")
    else:
        st.caption("None recorded.")

    # Suggested Action (Information Only)
    suggested_action = case_file.get("suggested_action", "None")
    st.subheader("Agent Suggested Action")
    st.info(
        f"🤖 **Agent Suggestion:** **{suggested_action}**\n\n"
        "*(This recommendation is generated by the AI agent for reference only. It is not preselected, and the investigator must make an independent decision.)*"
    )

st.markdown("---")

# Investigator Decision Form
st.subheader("Investigator Decision")
st.caption("Select a decision, provide mandatory rationale, and record your investigator identity.")

with st.container():
    # Radio with NO default selection (index=None)
    decision_selection = st.radio(
        "Decision (required):",
        options=["Escalate", "Request more information", "Dismiss"],
        index=None,
        key=f"decision_radio_{selected_case_id}",
        help="A decision must be explicitly selected. No action is preselected.",
    )

    reason_text = st.text_area(
        "Reason for Decision (required):",
        key=f"reason_text_{selected_case_id}",
        placeholder="Document the detailed investigative justification and rationale...",
        height=100,
    )

    investigator_name = st.text_input(
        "Investigator Name (required):",
        key=f"investigator_name_{selected_case_id}",
        placeholder="e.g., A. Smith (Senior AML Investigator)",
    )

    save_clicked = st.button("Save Decision", key=f"save_btn_{selected_case_id}", type="primary")

    if save_clicked:
        if decision_selection is None:
            st.error("⚠️ Please select a decision option (Escalate, Request more information, or Dismiss).")
        elif not reason_text or not reason_text.strip():
            st.error("⚠️ Please provide a non-empty reason for your decision.")
        elif not investigator_name or not investigator_name.strip():
            st.error("⚠️ Please provide your investigator name.")
        else:
            try:
                sugg_action = case_file.get("suggested_action") if case_file else None
                saved_record = save_decision(
                    db_path=db_path,
                    case_id=selected_case_id,
                    decision=decision_selection,
                    reason=reason_text.strip(),
                    investigator=investigator_name.strip(),
                    suggested_action=sugg_action,
                )
                new_id = saved_record["decision_id"]
                saved_time = saved_record["decided_at"]
                st.success(
                    f"✅ **Decision recorded successfully! (ID: {new_id})**\n\n"
                    f"- **Decision:** {decision_selection}\n"
                    f"- **Investigator:** {investigator_name.strip()}\n"
                    f"- **Timestamp:** {saved_time}"
                )
            except Exception as ex:
                st.error(f"Failed to record decision: {ex}")

# Decision History
st.markdown("---")
st.subheader("Decision History for Case")

prior_decisions = list_decisions(db_path, selected_case_id)
if prior_decisions:
    latest = prior_decisions[0]
    st.success(
        f"📌 **Current Status:** **{latest['decision']}** recorded by **{latest['investigator']}** on **{latest['decided_at']}**\n\n"
        f"**Reason:** {latest['reason']}"
    )

    history_table = []
    for d in prior_decisions:
        history_table.append({
            "Decision ID": d["decision_id"],
            "Decision": d["decision"],
            "Investigator": d["investigator"],
            "Decided At (UTC)": d["decided_at"],
            "Reason": d["reason"],
            "Suggested Action": d.get("suggested_action") or "N/A",
        })
    st.dataframe(history_table, width="stretch", hide_index=True)
else:
    st.caption("No prior decisions recorded for this case.")
