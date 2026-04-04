#!/usr/bin/env python3
"""
Note Agent Monitor — runs once daily at 21:00 weekdays + Sunday via cron.

Conditions checked:
  1. Narration gap (≥3 working days without narration)
  2. Weekly synthesis ready (Sundays, ≥3 narrations this week)
"""

import sys
import json
import logging
import subprocess
from datetime import datetime, timedelta, timezone, date
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


def count_working_days_without_narration(narrations, days_back=7):
    """Count consecutive working days from today backwards without a narration."""
    narration_dates = set()
    for n in narrations:
        d = n.get("date") or n.get("created_at", "")[:10]
        if d:
            narration_dates.add(d)

    count = 0
    today = date.today()
    for i in range(1, days_back + 1):
        day = today - timedelta(days=i)
        if day.weekday() >= 5:  # weekend
            continue
        if day.isoformat() not in narration_dates:
            count += 1
        else:
            break  # consecutive count stops at first narration

    return count


def check_narration_gap():
    """Alert if ≥3 working days without narration."""
    alerts = []
    try:
        result = subprocess.run(
            ["uv", "run", "scripts/note.py", "list-narrations", "--last", "7"],
            capture_output=True, text=True,
            cwd=str(AGENT_DIR),
            timeout=30
        )
        if result.returncode != 0:
            logging.warning(f"list-narrations failed: {result.stderr.strip()}")
            return alerts

        narrations = json.loads(result.stdout) if result.stdout.strip() else []
        if isinstance(narrations, dict):
            narrations = narrations.get("narrations", narrations.get("items", []))

    except Exception as e:
        logging.warning(f"check_narration_gap error: {e}")
        return alerts

    working_days_without = count_working_days_without_narration(narrations, days_back=7)
    if working_days_without >= 3:
        now = datetime.now(timezone.utc)
        week_key = now.strftime('%Y-W%W')
        key = f"narration_gap:{week_key}"
        msg = (
            f"📝 No narration in {working_days_without} working days.\n"
            f"Even 2 sentences helps — what's been happening?"
        )
        alerts.append((key, msg, 24))

    return alerts


def check_weekly_synthesis():
    """On Sundays, prompt for weekly synthesis if ≥3 narrations this week."""
    alerts = []
    now = datetime.now(timezone.utc)
    if now.weekday() != 6:  # 6 = Sunday
        return alerts

    try:
        result = subprocess.run(
            ["uv", "run", "scripts/note.py", "list-narrations", "--week", "current"],
            capture_output=True, text=True,
            cwd=str(AGENT_DIR),
            timeout=30
        )
        if result.returncode != 0:
            logging.warning(f"list-narrations week failed: {result.stderr.strip()}")
            return alerts

        narrations = json.loads(result.stdout) if result.stdout.strip() else []
        if isinstance(narrations, dict):
            narrations = narrations.get("narrations", narrations.get("items", []))

    except Exception as e:
        logging.warning(f"check_weekly_synthesis error: {e}")
        return alerts

    if len(narrations) >= 3:
        week_key = now.strftime('%Y-W%W')
        key = f"weekly_synthesis_ready:{week_key}"
        msg = (
            f"📝 {len(narrations)} narrations this week.\n"
            f"Want me to run the weekly synthesis and find threads?"
        )
        alerts.append((key, msg, 7 * 24))

    return alerts


def main():
    setup_logging()
    state = load_alert_state()
    alerts_sent = 0

    conditions = [
        (check_narration_gap, 24),
        (check_weekly_synthesis, 7 * 24),
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
                    send_telegram_message(msg, context_agent="monitor:note")
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
