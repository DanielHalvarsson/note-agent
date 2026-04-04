#!/usr/bin/env python3
"""
Note Agent Monitor — runs once daily via cron.

Conditions checked:
  1. Pending source alert — sources pending compilation for >48 hours
  2. Stale section alert  — section with pending sources not updated in 2+ weeks
  3. Wiki review prompt   — Sundays, if ≥1 article exists in any section
"""

import sys
import json
import logging
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/home/server_lama/server-projects/personal-assistant")
sys.path.insert(0, "/home/server_lama/server-projects/shared")
from telegram_utils import send_telegram_message

AGENT_DIR = Path(__file__).parent
LOG_FILE = AGENT_DIR / "logs" / "monitor.log"
ALERT_STATE = AGENT_DIR / "state" / "monitor_alerts.json"
MAX_ALERTS_PER_SCAN = 3


def setup_logging():
    LOG_FILE.parent.mkdir(exist_ok=True)
    ALERT_STATE.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
    )


def load_alert_state():
    if ALERT_STATE.exists():
        try:
            return json.loads(ALERT_STATE.read_text())
        except Exception:
            pass
    return {"alerts": []}


def save_alert_state(state):
    ALERT_STATE.parent.mkdir(exist_ok=True)
    ALERT_STATE.write_text(json.dumps(state, indent=2))


def already_alerted(state, key, cooldown_hours=12):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)
    for alert in state["alerts"]:
        if alert["key"] == key:
            alerted_at = datetime.fromisoformat(alert["timestamp"])
            if alerted_at.tzinfo is None:
                alerted_at = alerted_at.replace(tzinfo=timezone.utc)
            if alerted_at > cutoff:
                return True
    return False


def record_alert(state, key):
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    state["alerts"] = [
        a for a in state["alerts"]
        if datetime.fromisoformat(a["timestamp"]).replace(tzinfo=timezone.utc) > cutoff
    ]
    state["alerts"].append({"key": key, "timestamp": datetime.now(timezone.utc).isoformat()})


def _get_vault_path() -> Path:
    import yaml
    config_path = AGENT_DIR / "config.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return Path(cfg["obsidian"]["vault_path"])


def check_pending_sources():
    """Alert if sources have been pending compilation for >48 hours."""
    alerts = []
    try:
        vault = _get_vault_path()
        sys.path.insert(0, str(AGENT_DIR))
        from registry import get_pending_sources

        pending = get_pending_sources(vault)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)

        stale = []
        for s in pending:
            received_str = s.get("received", "")
            if not received_str:
                continue
            received = datetime.fromisoformat(received_str)
            if received.tzinfo is None:
                received = received.replace(tzinfo=timezone.utc)
            if received < cutoff:
                stale.append(s)

        if stale:
            now = datetime.now(timezone.utc)
            week_key = now.strftime('%Y-W%W')
            key = f"pending_sources_stale:{week_key}"
            msg = (
                f"📚 {len(stale)} source(s) waiting to be compiled into the wiki "
                f"(oldest: {stale[0]['path'].split('/')[-1]}).\n"
                f"Run: <code>uv run python compile.py --all</code>"
            )
            alerts.append((key, msg, 48))

    except Exception as e:
        logging.warning(f"check_pending_sources error: {e}")

    return alerts


def check_stale_sections():
    """Alert if a section hasn't been updated in 2+ weeks but has pending sources."""
    alerts = []
    try:
        vault = _get_vault_path()
        sys.path.insert(0, str(AGENT_DIR))
        from registry import load_registry, get_pending_sources
        from indexer import SECTIONS

        registry = load_registry(vault)
        pending = get_pending_sources(vault)
        if not pending:
            return alerts

        # Group pending by suggested section (infer from path)
        pending_sections = set()
        for s in pending:
            path = s.get("path", "")
            if "papers" in path:
                pending_sections.add("references")
            elif "clippings" in path:
                pending_sections.add("references")
            elif "fragments" in path:
                pending_sections.add("ideas")
            else:
                pending_sections.add("research")

        two_weeks_ago = datetime.now(timezone.utc) - timedelta(weeks=2)
        stale_sections = []

        for section in pending_sections:
            section_data = registry.get("sections", {}).get(section, {})
            last_updated = section_data.get("last_updated")
            if last_updated is None:
                stale_sections.append(section)
            else:
                lu = datetime.fromisoformat(last_updated)
                if lu.tzinfo is None:
                    lu = lu.replace(tzinfo=timezone.utc)
                if lu < two_weeks_ago:
                    stale_sections.append(section)

        if stale_sections:
            now = datetime.now(timezone.utc)
            week_key = now.strftime('%Y-W%W')
            key = f"stale_sections:{week_key}"
            sections_str = ", ".join(stale_sections)
            msg = (
                f"📖 Wiki sections with pending sources haven't been updated in 2+ weeks: "
                f"<b>{sections_str}</b>.\n"
                f"Compile to keep the wiki current."
            )
            alerts.append((key, msg, 7 * 24))

    except Exception as e:
        logging.warning(f"check_stale_sections error: {e}")

    return alerts


def check_wiki_review():
    """On Sundays, prompt for wiki review if ≥1 article exists."""
    alerts = []
    now = datetime.now(timezone.utc)
    if now.weekday() != 6:  # 6 = Sunday
        return alerts

    try:
        vault = _get_vault_path()
        sys.path.insert(0, str(AGENT_DIR))
        from registry import list_articles

        articles = list_articles(vault)
        if not articles:
            return alerts

        week_key = now.strftime('%Y-W%W')
        key = f"wiki_review:{week_key}"
        msg = (
            f"📚 Wiki has {len(articles)} article(s) across sections.\n"
            f"Ask me: <i>\"What does the wiki know about X?\"</i> or "
            f"<i>\"Wiki status\"</i> to see what's been compiled."
        )
        alerts.append((key, msg, 7 * 24))

    except Exception as e:
        logging.warning(f"check_wiki_review error: {e}")

    return alerts


def main():
    setup_logging()
    state = load_alert_state()
    alerts_sent = 0

    conditions = [
        (check_pending_sources, 48),
        (check_stale_sections, 7 * 24),
        (check_wiki_review, 7 * 24),
    ]

    for fn, cooldown in conditions:
        if alerts_sent >= MAX_ALERTS_PER_SCAN:
            break
        try:
            for key, msg, *rest in fn():
                if alerts_sent >= MAX_ALERTS_PER_SCAN:
                    break
                cd = rest[0] if rest else cooldown
                if not already_alerted(state, key, cooldown_hours=cd):
                    send_telegram_message(msg, context_agent="monitor:note", parse_mode="HTML")
                    record_alert(state, key)
                    alerts_sent += 1
                    logging.info(f"Alert sent: {key}")
                else:
                    logging.info(f"Skipped (already alerted): {key}")
        except Exception as e:
            logging.error(f"{fn.__name__}: {e}")

    save_alert_state(state)
    logging.info(f"Scan done. {alerts_sent} alert(s) sent.")


if __name__ == "__main__":
    main()
