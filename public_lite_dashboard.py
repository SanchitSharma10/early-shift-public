from __future__ import annotations

import pandas as pd
import streamlit as st

from public_app_helpers import (
    clean_label,
    load_correlation_evidence,
    load_null_spike_baseline,
    get_public_snapshot,
    load_public_top_spikes,
    run_public_game_check,
)


@st.cache_data(ttl=300)
def snapshot_cached() -> dict:
    return get_public_snapshot()


@st.cache_data(ttl=300)
def correlation_evidence_cached(limit: int, recent_days: int, lead_days: int) -> dict:
    return load_correlation_evidence(limit=limit, recent_days=recent_days, lead_days=lead_days)


@st.cache_data(ttl=300)
def top_spikes_cached(limit: int, recent_days: int) -> pd.DataFrame:
    return load_public_top_spikes(limit=limit, recent_days=recent_days)


@st.cache_data(ttl=300)
def null_spike_baseline_cached(limit: int, recent_days: int, controls_per_spike: int) -> pd.DataFrame:
    return load_null_spike_baseline(
        limit=limit,
        recent_days=recent_days,
        controls_per_spike=controls_per_spike,
    )


@st.cache_data(ttl=120)
def game_check_cached(game_name: str, universe_id: str) -> dict:
    return run_public_game_check(game_name, universe_id=universe_id)


st.set_page_config(
    page_title="Early Shift Lite",
    page_icon="ES",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    .block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1200px;}
    .hero {
        padding: 1.4rem 1.5rem;
        border-radius: 20px;
        background: linear-gradient(135deg, #f4efe4 0%, #dce8e2 50%, #eef4fb 100%);
        border: 1px solid #d8d0c0;
        margin-bottom: 1rem;
    }
    .hero-kicker {
        font-size: 0.82rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #546b5e;
        margin-bottom: 0.35rem;
        font-weight: 700;
    }
    .hero-title {
        font-size: 2.2rem;
        line-height: 1.05;
        margin: 0;
        color: #1b2f27;
        font-weight: 800;
    }
    .hero-copy {
        margin-top: 0.8rem;
        color: #2d3e37;
        font-size: 1rem;
        max-width: 52rem;
    }
    .mini-card {
        padding: 1rem 1.1rem;
        border-radius: 16px;
        background: #fbfaf6;
        border: 1px solid #e5dcc9;
        height: 100%;
    }
    .mini-card h4 {
        margin: 0 0 0.45rem 0;
        font-size: 0.95rem;
        color: #2d3e37;
    }
    .mini-card p {
        margin: 0;
        color: #53635c;
        font-size: 0.92rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

snapshot = snapshot_cached()
evidence = correlation_evidence_cached(limit=5, recent_days=7, lead_days=30)
top_spikes_df = top_spikes_cached(limit=10, recent_days=7)
null_baseline_df = null_spike_baseline_cached(limit=3, recent_days=7, controls_per_spike=3)

st.markdown(
    f"""
    <div class="hero">
        <div class="hero-kicker">Public Signal Report</div>
        <h1 class="hero-title">Early Shift</h1>
        <div class="hero-copy">
            Track which creators are actually moving Roblox CCU, separate flash spikes from sticky growth,
            and give studios a fast read on whether a game has momentum or just noise.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

stats_col1, stats_col2, stats_col3, stats_col4 = st.columns(4)
with stats_col1:
    st.metric("Tracked games", f"{int(snapshot['tracked_games']):,}")
with stats_col2:
    st.metric("YouTube videos indexed", f"{int(snapshot['youtube_videos']):,}")
with stats_col3:
    st.metric("Creator-linked detections", f"{int(snapshot['creator_linked_spikes']):,}")
with stats_col4:
    sustained_rate = snapshot.get("sustained_rate_pct")
    sustained_known = int(snapshot.get("sustained_known") or 0)
    if sustained_rate is None:
        st.metric("Sustained 72h+", "N/A")
    else:
        st.metric("Sustained 72h+", f"{sustained_rate:.1f}%")

metrics_note_parts = []
if snapshot.get("median_lead_hours") is not None:
    metrics_note_parts.append(f"Median lead to peak: {float(snapshot['median_lead_hours']):.1f}h")
if sustained_known:
    metrics_note_parts.append(
        f"Sustained sample: {int(snapshot.get('sustained_true') or 0)}/{sustained_known}"
    )
if metrics_note_parts:
    st.caption(" | ".join(metrics_note_parts))

st.markdown("---")

st.subheader("Correlation evidence")
st.caption(
    "Public proof layer: recent top spikes aligned against creator upload timing and downstream lift. "
    "Hour 0 is the detected lift. Mention index is derived from creator publish timestamps inside detected spike events."
)

evidence_col1, evidence_col2 = st.columns(2, gap="large")

with evidence_col1:
    overlay_df = evidence["overlay"]
    if overlay_df.empty:
        st.info("Not enough recent spike evidence to build the overlay.")
    else:
        chart_df = overlay_df.set_index("Hour vs detection")
        st.line_chart(
            chart_df,
            color=["#1c5d4f", "#ff4d4f"],
            use_container_width=True,
            height=300,
        )
        top_spike_names = ", ".join(evidence["top_spikes"]["game_name"].head(5).tolist())
        st.caption(f"Top recent spikes in this evidence set: {top_spike_names}")

with evidence_col2:
    lead_hist_df = evidence["lead_histogram"]
    if lead_hist_df.empty:
        st.info("Lead-time histogram is unavailable for the current public sample.")
    else:
        st.bar_chart(
            lead_hist_df.set_index("Lead window")["Spikes"],
            color="#8fb8a7",
            use_container_width=True,
            height=300,
        )
        median_lead_hours = evidence.get("median_lead_hours")
        if median_lead_hours is not None:
            st.caption(
                f"Median lead time to local peak: {median_lead_hours:.1f}h "
                f"(n={evidence['lead_samples']})"
            )

st.subheader("Null-spike baseline")
st.caption(
    "Same-week spikes matched against non-spike games with similar baseline CCU at the same timestamp. "
    "This is a rough falsification layer: if the spike does not beat the matched control set, the lift is less convincing. "
    "Controls are matched by baseline CCU only in the public demo."
)
if null_baseline_df.empty:
    st.info("Not enough non-spike control data to build the baseline table.")
else:
    st.dataframe(
        null_baseline_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Baseline CCU": st.column_config.NumberColumn(format="%,d"),
            "Spike velocity 6h": st.column_config.NumberColumn(format="+%.1f%%"),
            "Control velocity 6h": st.column_config.NumberColumn(format="+%.1f%%"),
            "Spike peak 24h": st.column_config.NumberColumn(format="+%.1f%%"),
            "Control peak 24h": st.column_config.NumberColumn(format="+%.1f%%"),
            "Spike peak 72h": st.column_config.NumberColumn(format="+%.1f%%"),
            "Control peak 72h": st.column_config.NumberColumn(format="+%.1f%%"),
            "72h edge": st.column_config.NumberColumn(format="+%.1f%%"),
        },
    )

st.markdown("---")

panel_col1, panel_col2 = st.columns([1.1, 0.9], gap="large")

with panel_col1:
    st.subheader("Top this-week spikes")
    st.caption(
        "Best creator-linked lifts from the latest week in the dataset. "
        "CCU velocity 6h = forward CCU change in the first six hours after detection. "
        "Flow overlap % = share of snapshot intervals from creator upload to detected lift where CCU was still rising."
    )
    if top_spikes_df.empty:
        st.info("No recent creator-linked spikes available.")
    else:
        st.dataframe(
            top_spikes_df.rename(
                columns={
                    "game_name": "Game",
                    "channel_title": "Creator",
                    "growth_percent": "Growth",
                    "current_ccu": "CCU",
                    "ccu_velocity_6h_pct": "CCU velocity 6h",
                    "flow_overlap_pct": "Flow overlap %",
                    "sustained_72h_label": "Sustained 72h",
                    "stickiness_pct": "Stickiness",
                    "lag_hours": "Lag (h)",
                    "detected_at": "Detected",
                }
            ),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Growth": st.column_config.NumberColumn(format="+%.1f%%"),
                "CCU": st.column_config.NumberColumn(format="%,d"),
                "CCU velocity 6h": st.column_config.NumberColumn(format="+%.1f%%"),
                "Flow overlap %": st.column_config.NumberColumn(format="%.1f%%"),
                "Sustained 72h": st.column_config.TextColumn(),
                "Stickiness": st.column_config.NumberColumn(format="%.1f%%"),
                "Lag (h)": st.column_config.NumberColumn(format="%.1f"),
            },
        )

with panel_col2:
    st.subheader("Check a Roblox game")
    with st.form("game-check-form", clear_on_submit=False):
        game_name = st.text_input(
            "Game name",
            placeholder="Dress To Impress",
            help="Fuzzy-match a Roblox game name in the local CCU snapshot.",
        )
        universe_id = st.text_input(
            "Universe ID (optional)",
            placeholder="5203828273",
            help="Use this for an exact Roblox universe lookup.",
        )
        submitted = st.form_submit_button("Run check", use_container_width=True, type="primary")

    if submitted and (game_name.strip() or universe_id.strip()):
        result = game_check_cached(game_name.strip(), universe_id.strip())
        ccu = result["ccu"]

        metric_col1, metric_col2, metric_col3 = st.columns([2, 1, 2])
        with metric_col1:
            st.metric("YouTube signal", result["signal"])
        with metric_col2:
            st.metric("Videos (72h)", result["video_count"])
        with metric_col3:
            growth_value = ccu.get("growth_pct")
            if growth_value is None:
                st.metric("Growth", "N/A")
            else:
                st.metric("Growth", f"{growth_value:+.1f}%")
        st.caption("Based on recent matching creator coverage volume, not total CCU.")

        if ccu.get("found"):
            matched_universe_id = ccu.get("universe_id")
            st.caption(
                f"Matched game: {clean_label(ccu.get('game_name'))} | "
                f"Universe ID: {matched_universe_id if matched_universe_id is not None else 'N/A'} | "
                f"Current CCU: {int(ccu.get('current_ccu') or 0):,}"
            )
        else:
            st.caption("No close CCU match found in the local snapshot. Showing creator activity only.")

        st.info(result["recommendation"])

        if not result.get("youtube_lookup_ok"):
            lookup_error = result.get("youtube_lookup_error") or "lookup_failed"
            if lookup_error == "missing_api_key":
                st.warning("Live YouTube lookup is not configured in this deployment.")
            else:
                st.warning("Recent YouTube coverage could not be fetched right now. A 0-video reading may reflect lookup failure rather than true zero coverage.")
        elif result["videos"]:
            with st.expander("Recent creator coverage", expanded=True):
                for video in result["videos"][:5]:
                    st.markdown(f"**{video['title']}**")
                    st.caption(f"{video['channel']} | {video.get('published', '')[:19]}")
                    if video.get("url"):
                        st.markdown(f"[Watch on YouTube]({video['url']})")
        else:
            st.caption("No matching YouTube videos found in the last 72 hours.")
    else:
        st.caption("Enter either a game name or a universe ID to turn the analytics stack into a plain-English signal.")
