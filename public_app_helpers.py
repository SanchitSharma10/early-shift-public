from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import shutil
import tempfile

import pandas as pd

from check_my_game import get_game_ccu_status, search_youtube_for_game
from db_manager import get_db_connection


def _resolve_public_db_path() -> str:
    env_path = os.getenv("DB_PATH")
    if env_path:
        return env_path

    project_root = Path(__file__).parent
    demo_db = project_root / "early_shift_demo.db"
    if demo_db.exists():
        src = demo_db
    else:
        src = project_root / "early_shift.db"

    # Copy to a writable location so DuckDB can create lock/WAL files
    # (Streamlit Cloud mounts the repo read-only).
    tmp_dest = Path(tempfile.gettempdir()) / src.name
    if not tmp_dest.exists():
        shutil.copy2(src, tmp_dest)
    return str(tmp_dest)


DB_PATH = _resolve_public_db_path()


def _query_dataframe(query: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    with get_db_connection(DB_PATH, read_only=True) as db:
        result = db.execute(query, params)
        columns = [column[0] for column in result.description]
        rows = result.fetchall()
    return pd.DataFrame(rows, columns=columns)


def _table_exists(table_name: str) -> bool:
    query = """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name = ?
    """
    frame = _query_dataframe(query, (table_name,))
    return bool(frame.iloc[0, 0]) if not frame.empty else False


def clean_label(text: str | None) -> str:
    if not text:
        return "-"
    cleaned = re.sub(r"^\s*(\[[^\]]+\]\s*)+", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or text.strip()


def time_ago(value: datetime | None) -> str:
    if value is None:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - value
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def get_public_snapshot() -> dict[str, Any]:
    retention_count_expr = (
        "(SELECT COUNT(*) FROM game_retention_metrics) AS retention_profiles"
        if _table_exists("game_retention_metrics")
        else "0 AS retention_profiles"
    )
    query = f"""
        SELECT
            (SELECT COUNT(*) FROM games) AS ccu_rows,
            (SELECT COUNT(DISTINCT universe_id) FROM games) AS tracked_games,
            (SELECT COUNT(*) FROM youtube_videos) AS youtube_videos,
            (SELECT COUNT(DISTINCT channel_id) FROM youtube_videos WHERE channel_id IS NOT NULL) AS tracked_channels,
            (SELECT COUNT(*) FROM mechanic_spikes) AS creator_linked_spikes,
            {retention_count_expr},
            (SELECT MIN(timestamp) FROM games) AS first_ccu_at,
            (SELECT MAX(timestamp) FROM games) AS last_ccu_at,
            (SELECT MIN(detected_at) FROM mechanic_spikes) AS first_spike_at,
            (SELECT MAX(detected_at) FROM mechanic_spikes) AS last_spike_at
    """
    row = _query_dataframe(query).iloc[0].to_dict()
    return row


def load_public_creator_signals(limit: int = 10) -> pd.DataFrame:
    query = """
        WITH spike_videos AS (
            SELECT
                channel_title AS creator,
                COUNT(*) AS spike_detections,
                COUNT(DISTINCT video_url) AS spike_videos,
                COUNT(DISTINCT game_name) AS games_covered,
                ROUND(MEDIAN(growth_percent), 1) AS median_growth,
                ROUND(MEDIAN(EXTRACT(EPOCH FROM (detected_at - published_at)) / 3600.0), 1) AS median_lag_hours
            FROM mechanic_spikes
            GROUP BY channel_title
            HAVING COUNT(DISTINCT video_url) >= 2
        ),
        creator_totals AS (
            SELECT
                channel_title AS creator,
                COUNT(DISTINCT video_id) AS total_videos
            FROM youtube_videos
            GROUP BY channel_title
        )
        SELECT
            sv.creator,
            sv.spike_detections,
            sv.spike_videos,
            sv.games_covered,
            sv.median_growth,
            ROUND(sv.spike_videos * 100.0 / NULLIF(ct.total_videos, 0), 1) AS hit_rate_pct,
            sv.median_lag_hours
        FROM spike_videos sv
        LEFT JOIN creator_totals ct ON ct.creator = sv.creator
        ORDER BY sv.spike_videos DESC, sv.median_growth DESC, sv.games_covered DESC
        LIMIT ?
    """
    return _query_dataframe(query, (limit,))


def load_public_recent_detections(limit: int = 10) -> pd.DataFrame:
    retention_join = (
        "LEFT JOIN game_retention_metrics grm ON grm.universe_id = ms.universe_id"
        if _table_exists("game_retention_metrics")
        else ""
    )
    stickiness_select = (
        "ROUND(grm.stickiness_index * 100.0, 1) AS stickiness_pct,"
        if _table_exists("game_retention_metrics")
        else "NULL AS stickiness_pct,"
    )
    decay_select = (
        "ROUND(grm.decay_days, 1) AS decay_days,"
        if _table_exists("game_retention_metrics")
        else "NULL AS decay_days,"
    )
    query = f"""
        WITH ranked AS (
            SELECT
                ms.game_name,
                ms.channel_title,
                ROUND(ms.growth_percent, 1) AS growth_percent,
                ms.current_ccu,
                {stickiness_select}
                {decay_select}
                ROUND(EXTRACT(EPOCH FROM (ms.detected_at - ms.published_at)) / 3600.0, 1) AS lag_hours,
                ms.detected_at,
                ms.video_url,
                ROW_NUMBER() OVER (PARTITION BY ms.game_name ORDER BY ms.detected_at DESC, ms.growth_percent DESC) AS row_num
            FROM mechanic_spikes ms
            {retention_join}
        )
        SELECT
            game_name,
            channel_title,
            growth_percent,
            current_ccu,
            stickiness_pct,
            decay_days,
            lag_hours,
            detected_at,
            video_url
        FROM ranked
        WHERE row_num = 1
        ORDER BY detected_at DESC, growth_percent DESC
        LIMIT ?
    """
    frame = _query_dataframe(query, (limit,))
    if not frame.empty:
        frame["game_name"] = frame["game_name"].map(clean_label)
    return frame


def load_detection_timeline(days: int = 14) -> pd.DataFrame:
    days = max(int(days), 1)
    query = f"""
        WITH latest AS (
            SELECT MAX(detected_at) AS max_detected_at
            FROM mechanic_spikes
        )
        SELECT
            CAST(ms.detected_at AS DATE) AS detected_day,
            COUNT(*) AS detections,
            ROUND(MEDIAN(ms.growth_percent), 1) AS median_growth
        FROM mechanic_spikes ms, latest
        WHERE ms.detected_at >= latest.max_detected_at - INTERVAL {days} DAY
        GROUP BY CAST(ms.detected_at AS DATE)
        ORDER BY detected_day
    """
    return _query_dataframe(query)


def load_correlation_evidence(limit: int = 5, recent_days: int = 7, lead_days: int = 30) -> dict[str, Any]:
    recent_days = max(int(recent_days), 1)
    lead_days = max(int(lead_days), 1)

    top_spikes_query = f"""
        WITH latest AS (
            SELECT MAX(detected_at) AS max_detected_at
            FROM mechanic_spikes
        ),
        ranked AS (
            SELECT
                ms.universe_id,
                ms.game_name,
                ms.detected_at,
                ms.published_at,
                ms.growth_percent,
                ms.current_ccu,
                ms.video_count,
                ROW_NUMBER() OVER (
                    PARTITION BY ms.universe_id
                    ORDER BY ms.growth_percent DESC, ms.detected_at DESC
                ) AS row_num
            FROM mechanic_spikes ms, latest
            WHERE ms.detected_at >= latest.max_detected_at - INTERVAL {recent_days} DAY
        )
        SELECT
            universe_id,
            game_name,
            detected_at,
            published_at,
            ROUND(growth_percent, 1) AS growth_percent,
            current_ccu,
            COALESCE(video_count, 1.0) AS video_count
        FROM ranked
        WHERE row_num = 1
        ORDER BY growth_percent DESC, current_ccu DESC
        LIMIT ?
    """
    top_spikes = _query_dataframe(top_spikes_query, (limit,))
    if top_spikes.empty:
        return {
            "overlay": pd.DataFrame(),
            "lead_histogram": pd.DataFrame(),
            "top_spikes": pd.DataFrame(),
            "median_lead_hours": None,
            "lead_samples": 0,
        }

    top_spikes["game_name"] = top_spikes["game_name"].map(clean_label)
    top_spikes["detected_at"] = pd.to_datetime(top_spikes["detected_at"], utc=True)
    top_spikes["published_at"] = pd.to_datetime(top_spikes["published_at"], utc=True)

    universe_ids = ",".join(str(int(value)) for value in top_spikes["universe_id"].dropna().unique())
    min_published = top_spikes["published_at"].min()
    max_detected = top_spikes["detected_at"].max()
    snapshot_query = f"""
        SELECT universe_id, name, timestamp, ccu
        FROM games
        WHERE universe_id IN ({universe_ids})
          AND timestamp >= ?
          AND timestamp <= ?
        ORDER BY universe_id, timestamp
    """
    snapshots = _query_dataframe(
        snapshot_query,
        (
            min_published.to_pydatetime() - pd.Timedelta(hours=48),
            max_detected.to_pydatetime() + pd.Timedelta(hours=24),
        ),
    )
    if not snapshots.empty:
        snapshots["timestamp"] = pd.to_datetime(snapshots["timestamp"], utc=True)

    velocity_rows: list[dict[str, Any]] = []
    mention_rows: list[dict[str, Any]] = []
    for row in top_spikes.itertuples(index=False):
        spike_snapshots = snapshots.loc[snapshots["universe_id"] == row.universe_id].copy()
        if spike_snapshots.empty:
            continue
        spike_snapshots = spike_snapshots.loc[
            (spike_snapshots["timestamp"] >= row.detected_at - pd.Timedelta(hours=48))
            & (spike_snapshots["timestamp"] <= row.detected_at + pd.Timedelta(hours=24))
        ].sort_values("timestamp")
        if len(spike_snapshots) >= 2:
            previous_ccu = spike_snapshots["ccu"].shift(1)
            delta_hours = (
                spike_snapshots["timestamp"].diff().dt.total_seconds() / 3600.0
            )
            velocity_pct = (
                (spike_snapshots["ccu"] - previous_ccu)
                / previous_ccu.where(previous_ccu > 0)
                * 100.0
            ) / delta_hours.where(delta_hours > 0)
            spike_snapshots["relative_hour"] = (
                (spike_snapshots["timestamp"] - row.detected_at).dt.total_seconds() / 3600.0
            ).round().astype("Int64")
            spike_snapshots["velocity_pct"] = velocity_pct
            valid_points = spike_snapshots.dropna(subset=["relative_hour", "velocity_pct"])
            valid_points = valid_points.loc[
                (valid_points["relative_hour"] >= -48)
                & (valid_points["relative_hour"] <= 24)
            ]
            for point in valid_points.itertuples(index=False):
                velocity_rows.append(
                    {
                        "relative_hour": int(point.relative_hour),
                        "velocity_pct": max(float(point.velocity_pct), 0.0),
                    }
                )

        mention_hour = int(round((row.published_at - row.detected_at).total_seconds() / 3600.0))
        if -48 <= mention_hour <= 24:
            mention_rows.append(
                {
                    "relative_hour": mention_hour,
                    "mention_weight": float(row.video_count or 1.0),
                }
            )

    hour_index = pd.DataFrame({"relative_hour": list(range(-48, 25))})
    velocity_frame = pd.DataFrame(velocity_rows)
    mention_frame = pd.DataFrame(mention_rows)

    if velocity_frame.empty:
        velocity_summary = hour_index.assign(avg_velocity_pct=0.0)
    else:
        velocity_summary = (
            velocity_frame.groupby("relative_hour", as_index=False)["velocity_pct"]
            .mean()
            .rename(columns={"velocity_pct": "avg_velocity_pct"})
        )

    if mention_frame.empty:
        mention_summary = hour_index.assign(mention_weight=0.0)
    else:
        mention_summary = (
            mention_frame.groupby("relative_hour", as_index=False)["mention_weight"]
            .sum()
        )

    overlay = (
        hour_index.merge(velocity_summary, on="relative_hour", how="left")
        .merge(mention_summary, on="relative_hour", how="left")
        .fillna({"avg_velocity_pct": 0.0, "mention_weight": 0.0})
    )
    velocity_scale = float(overlay["avg_velocity_pct"].max() or 0.0)
    mention_scale = float(overlay["mention_weight"].max() or 0.0)
    overlay["CCU velocity index"] = (
        overlay["avg_velocity_pct"] / velocity_scale * 100.0 if velocity_scale > 0 else 0.0
    )
    overlay["Creator mention index"] = (
        overlay["mention_weight"] / mention_scale * 100.0 if mention_scale > 0 else 0.0
    )
    overlay["Hour vs detection"] = overlay["relative_hour"].astype(int)
    overlay = overlay[["Hour vs detection", "CCU velocity index", "Creator mention index"]]

    lead_query = f"""
        WITH latest AS (
            SELECT MAX(detected_at) AS max_detected_at
            FROM mechanic_spikes
        ),
        spikes AS (
            SELECT universe_id, detected_at, current_ccu
            FROM mechanic_spikes, latest
            WHERE detected_at >= latest.max_detected_at - INTERVAL {lead_days} DAY
        ),
        lead AS (
            SELECT
                s.universe_id,
                s.detected_at,
                s.current_ccu,
                ARG_MAX(g.timestamp, g.ccu) AS peak_time,
                MAX(g.ccu) AS peak_ccu
            FROM spikes s
            JOIN games g
              ON g.universe_id = s.universe_id
             AND g.timestamp >= s.detected_at
             AND g.timestamp <= s.detected_at + INTERVAL '7' DAY
            GROUP BY s.universe_id, s.detected_at, s.current_ccu
        )
        SELECT
            EXTRACT(EPOCH FROM (peak_time - detected_at)) / 3600.0 AS lead_hours
        FROM lead
        WHERE peak_time IS NOT NULL
    """
    lead_frame = _query_dataframe(lead_query)
    if lead_frame.empty:
        lead_histogram = pd.DataFrame(columns=["Lead window", "Spikes"])
        median_lead_hours = None
    else:
        lead_hours = pd.to_numeric(lead_frame["lead_hours"], errors="coerce").dropna()
        if lead_hours.empty:
            lead_histogram = pd.DataFrame(columns=["Lead window", "Spikes"])
            median_lead_hours = None
        else:
            bins = [-0.01, 6, 12, 24, 48, 72, float("inf")]
            labels = ["0-6h", "6-12h", "12-24h", "24-48h", "48-72h", "72h+"]
            histogram = pd.cut(lead_hours, bins=bins, labels=labels)
            lead_histogram = (
                histogram.value_counts(sort=False)
                .rename_axis("Lead window")
                .reset_index(name="Spikes")
            )
            median_lead_hours = float(lead_hours.median())

    return {
        "overlay": overlay,
        "lead_histogram": lead_histogram,
        "top_spikes": top_spikes,
        "median_lead_hours": median_lead_hours,
        "lead_samples": int(len(lead_frame)),
    }


def load_public_top_spikes(limit: int = 10, recent_days: int = 7) -> pd.DataFrame:
    recent_days = max(int(recent_days), 1)
    retention_join = (
        "LEFT JOIN game_retention_metrics grm ON grm.universe_id = ranked.universe_id"
        if _table_exists("game_retention_metrics")
        else ""
    )
    stickiness_select = (
        "ROUND(grm.stickiness_index * 100.0, 1) AS stickiness_pct,"
        if _table_exists("game_retention_metrics")
        else "NULL AS stickiness_pct,"
    )
    query = f"""
        WITH latest AS (
            SELECT MAX(detected_at) AS max_detected_at
            FROM mechanic_spikes
        ),
        ranked AS (
            SELECT
                ms.universe_id,
                ms.game_name,
                ms.channel_title,
                ROUND(ms.growth_percent, 1) AS growth_percent,
                ms.current_ccu,
                ROUND(EXTRACT(EPOCH FROM (ms.detected_at - ms.published_at)) / 3600.0, 1) AS lag_hours,
                ms.detected_at,
                ms.published_at,
                ROW_NUMBER() OVER (
                    PARTITION BY ms.universe_id
                    ORDER BY ms.growth_percent DESC, ms.detected_at DESC
                ) AS row_num
            FROM mechanic_spikes ms, latest
            WHERE ms.detected_at >= latest.max_detected_at - INTERVAL {recent_days} DAY
        )
        SELECT
            ranked.universe_id,
            ranked.game_name,
            ranked.channel_title,
            ranked.growth_percent,
            ranked.current_ccu,
            {stickiness_select}
            ranked.lag_hours,
            ranked.detected_at,
            ranked.published_at
        FROM ranked
        {retention_join}
        WHERE ranked.row_num = 1
        ORDER BY ranked.growth_percent DESC, ranked.current_ccu DESC
        LIMIT ?
    """
    frame = _query_dataframe(query, (limit,))
    if frame.empty:
        return frame

    frame["game_name"] = frame["game_name"].map(clean_label)
    frame["detected_at"] = pd.to_datetime(frame["detected_at"], utc=True)
    frame["published_at"] = pd.to_datetime(frame["published_at"], utc=True)

    universe_ids = ",".join(str(int(value)) for value in frame["universe_id"].dropna().unique())
    min_published = frame["published_at"].min()
    max_detected = frame["detected_at"].max()
    snapshots_query = f"""
        SELECT universe_id, timestamp, ccu
        FROM games
        WHERE universe_id IN ({universe_ids})
          AND timestamp >= ?
          AND timestamp <= ?
        ORDER BY universe_id, timestamp
    """
    snapshots = _query_dataframe(
        snapshots_query,
        (
            min_published.to_pydatetime() - pd.Timedelta(hours=1),
            max_detected.to_pydatetime() + pd.Timedelta(hours=1),
        ),
    )
    if not snapshots.empty:
        snapshots["timestamp"] = pd.to_datetime(snapshots["timestamp"], utc=True)

    overlap_values: list[float | None] = []
    for row in frame.itertuples(index=False):
        spike_snapshots = snapshots.loc[
            (snapshots["universe_id"] == row.universe_id)
            & (snapshots["timestamp"] >= row.published_at)
            & (snapshots["timestamp"] <= row.detected_at)
        ].copy()
        if len(spike_snapshots) < 2:
            overlap_values.append(None)
            continue
        spike_snapshots = spike_snapshots.sort_values("timestamp")
        previous_ccu = spike_snapshots["ccu"].shift(1)
        delta_ccu = spike_snapshots["ccu"] - previous_ccu
        valid = delta_ccu.dropna()
        if valid.empty:
            overlap_values.append(None)
        else:
            overlap_values.append(round(float((valid > 0).mean() * 100.0), 1))

    frame["flow_overlap_pct"] = overlap_values
    frame["detected_at"] = frame["detected_at"].apply(time_ago)
    return frame


def load_public_case_studies(limit: int = 3) -> pd.DataFrame:
    retention_join = (
        "LEFT JOIN game_retention_metrics grm ON grm.universe_id = grouped.universe_id"
        if _table_exists("game_retention_metrics")
        else ""
    )
    stickiness_select = (
        "ROUND(grm.stickiness_index * 100.0, 1) AS stickiness_pct,"
        if _table_exists("game_retention_metrics")
        else "NULL AS stickiness_pct,"
    )
    decay_select = (
        "ROUND(grm.decay_days, 1) AS decay_days,"
        if _table_exists("game_retention_metrics")
        else "NULL AS decay_days,"
    )
    query = f"""
        WITH latest AS (
            SELECT MAX(detected_at) AS max_detected_at
            FROM mechanic_spikes
        ),
        grouped AS (
            SELECT
                ms.universe_id,
                ms.game_name,
                COUNT(*) AS detections,
                COUNT(DISTINCT ms.channel_title) AS creators,
                COUNT(DISTINCT ms.video_url) AS creator_videos,
                ROUND(MEDIAN(ms.growth_percent), 1) AS median_growth,
                ROUND(MAX(ms.growth_percent), 1) AS max_growth,
                MAX(ms.current_ccu) AS current_ccu,
                ARG_MAX(ms.channel_title, ms.growth_percent) AS standout_creator,
                ARG_MAX(ms.mechanic, ms.growth_percent) AS standout_mechanic,
                MIN(ms.detected_at) AS first_detected_at,
                MAX(ms.detected_at) AS last_detected_at
            FROM mechanic_spikes ms, latest
            WHERE ms.detected_at >= latest.max_detected_at - INTERVAL 45 DAY
            GROUP BY ms.universe_id, ms.game_name
            HAVING COUNT(*) >= 2
        )
        SELECT
            grouped.game_name,
            grouped.detections,
            grouped.creators,
            grouped.creator_videos,
            grouped.median_growth,
            grouped.max_growth,
            grouped.current_ccu,
            grouped.standout_creator,
            grouped.standout_mechanic,
            {stickiness_select}
            {decay_select}
            grouped.first_detected_at,
            grouped.last_detected_at
        FROM grouped
        {retention_join}
        ORDER BY grouped.max_growth DESC, grouped.detections DESC, grouped.creators DESC
        LIMIT ?
    """
    frame = _query_dataframe(query, (limit,))
    if not frame.empty:
        frame["game_name"] = frame["game_name"].map(clean_label)
        frame["standout_mechanic"] = frame["standout_mechanic"].map(clean_label)
    return frame


def run_public_game_check(game_name: str = "", universe_id: str = "", max_results: int = 5) -> dict[str, Any]:
    normalized_name = game_name.strip()
    normalized_universe = universe_id.strip()
    if not normalized_name and not normalized_universe:
        return {
            "query": "",
            "ccu": {"found": False, "game_name": "", "current_ccu": None, "baseline_ccu": None, "growth_pct": None, "is_growing": False},
            "videos": [],
            "video_count": 0,
            "signal": "NONE",
            "signal_emoji": "*",
            "youtube_lookup_ok": False,
            "youtube_lookup_error": "missing_query",
            "recommendation": "Enter a Roblox game to inspect creator coverage and current momentum.",
        }

    ccu_status = get_game_ccu_status(normalized_name, universe_id=normalized_universe or None)
    loop = asyncio.new_event_loop()
    try:
        youtube_query = ccu_status.get("game_name") or normalized_name
        youtube_result = loop.run_until_complete(search_youtube_for_game(youtube_query, max_results=max_results))
    finally:
        loop.close()

    videos = youtube_result["videos"]
    video_count = len(videos)
    youtube_lookup_ok = bool(youtube_result.get("ok"))
    youtube_lookup_error = youtube_result.get("error")
    if not youtube_lookup_ok:
        signal, signal_emoji = "UNAVAILABLE", "?"
    elif video_count >= 8:
        signal, signal_emoji = "STRONG", "+++"
    elif video_count >= 3:
        signal, signal_emoji = "MEDIUM", "++"
    elif video_count >= 1:
        signal, signal_emoji = "WEAK", "+"
    else:
        signal, signal_emoji = "NONE", "-"

    if not youtube_lookup_ok:
        recommendation = "Creator coverage lookup is unavailable right now. Treat this as a CCU-only readout until YouTube search recovers."
    elif ccu_status.get("is_growing") and video_count >= 5:
        recommendation = "High momentum: creator coverage is active and CCU is already moving."
    elif ccu_status.get("is_growing") and video_count >= 1:
        recommendation = "Growing with coverage: worth checking for a partnership or timing window."
    elif ccu_status.get("is_growing"):
        recommendation = "Organic growth: CCU is moving without much creator support yet."
    elif video_count >= 5:
        recommendation = "Coverage is active but CCU is flat: watch for delayed lift or weak conversion."
    elif video_count >= 1:
        recommendation = "Some recent creator attention, but no strong momentum signal yet."
    else:
        recommendation = "Low activity right now: no meaningful creator signal in the last 72 hours."

    for video in videos:
        video["channel"] = clean_label(video.get("channel"))

    return {
        "query": normalized_name,
        "universe_query": normalized_universe,
        "ccu": ccu_status,
        "videos": videos,
        "video_count": video_count,
        "signal": signal,
        "signal_emoji": signal_emoji,
        "youtube_lookup_ok": youtube_lookup_ok,
        "youtube_lookup_error": youtube_lookup_error,
        "recommendation": recommendation,
    }
