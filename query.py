#!/usr/bin/env python3
"""
Note Agent - Query Interface

CLI interface for conversational note-taking with Obsidian vault.
Used by the personal-assistant router for conversational note management.

Usage:
    uv run python query.py "Note: had great idea about X"
    uv run python query.py "Add to today: met with Sarah"
    uv run python query.py "What did I note about Canadian?"
"""

import sys
import os
import subprocess
import json
from pathlib import Path
from datetime import datetime

import argparse
import re

AGENT_DIR = Path(__file__).parent
STATE_DIR = AGENT_DIR / "state"


def load_config():
    """Load configuration from config.yaml."""
    import yaml
    config_path = AGENT_DIR / "config.yaml"
    if not config_path.exists():
        print("ERROR: config.yaml not found", file=sys.stderr)
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def query_with_claude(user_request):
    """
    Process user's note request using Claude CLI with Haiku.

    Has access to:
    - note.py script for Obsidian vault operations
    - CLAUDE.md note-taking instructions
    - Conversation context from router

    Returns: Plain text response
    """
    config = load_config()
    claude_bin = config.get("claude_cli", {}).get("bin", "claude")
    model = config.get("claude_cli", {}).get("model", "haiku")

    # Read conversation context from environment
    conversation_context = ""
    if "CONVERSATION_CONTEXT" in os.environ:
        try:
            context_data = json.loads(os.environ["CONVERSATION_CONTEXT"])
            if context_data:
                conversation_context = "\n\nRecent conversation:\n"
                for msg in context_data:
                    role = "User" if msg["role"] == "user" else "Assistant"
                    conversation_context += f"{role}: {msg['content'][:150]}\n"
        except:
            pass

    prompt = f"""You are the note-taking specialist agent for Daniel's personal assistant.

Your role: Capture notes, thoughts, and information into Obsidian vault.
{conversation_context}
User request: "{user_request}"

CRITICAL - Using Conversation Context:
- If conversation context shows recently discussed topics, USE THEM for context
- When user says "note that", "capture it", "add that to today" - refer to what was just discussed
- Auto-tag with people/projects from conversation context
- Examples:
  * Context shows discussion about Dennis and Canadian contract + "Note that" = Create note with those details
  * Context shows calendar event + "Add to today's note" = Include event details
  * Context shows task completion + "Capture this" = Note the accomplishment

Instructions:
- CRITICAL: Always use 'uv run' when running scripts (e.g., uv run scripts/note.py create "Title" "Content")
- Use note.py for vault operations (create, append-daily, search, read, list)
- Be concise and format for Telegram using HTML: <b>bold</b> for emphasis, plain bullets (•) for lists
- Optional: Use emoji sparingly for clarity (📝 note, 🔍 search, ✓ saved)
- Auto-detect people, projects, and meaningful tags from content
- Default to Inbox/ for captures unless context suggests Projects/ or People/
- For "add to today" requests, use append-daily command
- For quick captures without specific structure, use create command
- After creating/appending notes, confirm what you did

Common patterns:
- "Note: X" → create note in Inbox with title extracted from X
- "Add to today: X" → append to daily note with timestamp
- "Capture: X" → quick capture to Inbox
- "What did I note about X?" → search for X
- "Show my notes from today" → list from Daily/
- "Save this narration: X" → uv run scripts/note.py save-narration "X"
- "What did I narrate this week?" → uv run scripts/note.py list-narrations --week current
- "What have I been working on?" → uv run scripts/note.py list-narrations --last 7
- "Narrations about X" → uv run scripts/note.py list-narrations --keyword "X"
- "Draft a post from this week's narrations" → list-narrations --week current, then synthesize and save-draft

For narration retrieval, format the output as a readable summary showing dates and content.
For draft generation: collect narrations, identify dominant thread, draft 300-500 words in first-person lab-notes style (building-in-public tone, 70% done for Daniel to finish), save with save-draft command, then show the draft content.

Use the tools available (Bash to run note.py, Read for CLAUDE.md) as needed.
Respond conversationally and directly to the user's request.
"""

    try:
        cmd = [
            claude_bin,
            "--print",
            prompt,
            "--allowedTools", "Bash,Read"
        ]

        if model:
            cmd.extend(["--model", model])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(AGENT_DIR),
            timeout=60,
            env={**os.environ, "LANG": "en_US.UTF-8"}
        )

        response = result.stdout.strip()

        if not response:
            return "I couldn't process that request. Try rephrasing?"

        return response

    except subprocess.TimeoutExpired:
        return "⚠️ Request timed out. Try a simpler request."
    except FileNotFoundError:
        return "⚠️ Claude CLI not found. Check configuration."
    except Exception as e:
        return f"⚠️ Error: {str(e)}"


def detect_citation_request(user_request):
    """Check if the user wants citations/papers for their notes."""
    patterns = [
        r"find\s+citations?\s+for",
        r"support\s+(?:this|that|these)\s+with\s+papers?",
        r"find\s+papers?\s+(?:for|about|on)\s+(?:my|this|the)\s+(?:draft|note|claim)",
        r"cite\s+(?:this|that|my)",
        r"back\s+(?:this|that)\s+up\s+with\s+(?:research|papers?|literature)",
        r"what\s+(?:research|papers?)\s+support",
    ]
    for pattern in patterns:
        if re.search(pattern, user_request.lower()):
            return True
    return False


def detect_narration_request(user_request):
    """Check if the user is saving or querying narrations / build-in-public content."""
    patterns = [
        r"save\s+(?:this\s+)?narration",
        r"narration\s*:",
        r"what\s+did\s+i\s+(build|narrate|work\s+on)",
        r"what\s+have\s+i\s+been\s+working\s+on",
        r"weekly\s+synthesis",
        r"draft\s+a\s+post",
        r"build.in.public",
        r"narrations?\s+(this|last)\s+week",
        r"show\s+(me\s+)?narrations?",
    ]
    for pattern in patterns:
        if re.search(pattern, user_request.lower()):
            return True
    return False


def extract_claims_with_claude(user_request):
    """Use Claude to extract claims from the user request / relevant note."""
    config = load_config()
    claude_bin = config.get("claude_cli", {}).get("bin", "claude")
    model = config.get("claude_cli", {}).get("model", "haiku")

    prompt = f"""Extract the key claims or topics that need academic citations from this request.
Return ONLY a JSON array of short claim strings, nothing else.

Request: "{user_request}"

Example output: ["firm productivity varies with management quality", "trade openness correlates with growth"]
"""
    try:
        cmd = [claude_bin, "--model", model, "--print", prompt]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            cwd=str(AGENT_DIR), env={**os.environ, "LANG": "en_US.UTF-8"}
        )
        output = result.stdout.strip()
        # Extract JSON array
        start = output.find("[")
        end = output.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(output[start:end])
    except Exception:
        pass
    return []


def handle_handshake(context_json):
    """Handle coordination handshake from another agent (e.g., research results back)."""
    context = json.loads(context_json)
    action = context.get("action")

    if action == "citation_results":
        # Research agent sent back papers — integrate into note
        papers = context.get("papers", [])
        note_path = context.get("note_path", "")
        response = query_with_claude(
            f"Add these citation results to the note at {note_path}: {json.dumps(papers[:5])}"
        )
        return json.dumps({
            "response": response,
            "status": "complete",
            "actions": [{"type": "citations_integrated", "count": len(papers)}]
        })

    if action == "save_narration":
        content = context.get("content", "")
        day_type = context.get("day_type", "")
        date_override = context.get("date", "")

        if not content:
            return json.dumps({"response": "No narration content provided.", "status": "blocked"})

        cmd = ["uv", "run", "scripts/note.py", "save-narration", content]
        if day_type:
            cmd.append(day_type)
        else:
            cmd.append("")  # placeholder so date lands in position 4
        if date_override:
            cmd.append(date_override)

        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(AGENT_DIR), timeout=30,
            env={**os.environ, "LANG": "en_US.UTF-8"}
        )

        if result.returncode != 0:
            return json.dumps({
                "response": f"⚠️ Failed to save narration: {result.stderr.strip()}",
                "status": "blocked"
            })

        try:
            saved = json.loads(result.stdout)
            path = saved.get("path", "narrations/")
        except Exception:
            path = "narrations/"

        date_label = date_override or datetime.now().strftime("%Y-%m-%d")
        dt_label = f" ({day_type})" if day_type else ""
        return json.dumps({
            "response": f"✓ Narration saved to {path}{dt_label}",
            "status": "complete",
            "actions": [{"type": "narration_saved", "path": path, "date": date_label}]
        })

    if action == "weekly_synthesis":
        week_start = context.get("week_start", "")
        week_end = context.get("week_end", "")

        # Build list-narrations command using week boundaries via keyword scan
        # We'll use --week flag for current/last, or fall back to listing all and filtering
        cmd = ["uv", "run", "scripts/note.py", "list-narrations"]

        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(AGENT_DIR), timeout=30,
            env={**os.environ, "LANG": "en_US.UTF-8"}
        )

        if result.returncode != 0:
            return json.dumps({
                "response": f"⚠️ Failed to list narrations: {result.stderr.strip()}",
                "status": "blocked"
            })

        try:
            narrations = json.loads(result.stdout)
        except Exception:
            narrations = []

        # Filter by date range if provided
        if week_start and week_end:
            from datetime import date as date_type
            try:
                ws = date_type.fromisoformat(week_start)
                we = date_type.fromisoformat(week_end)
                narrations = [n for n in narrations if ws <= date_type.fromisoformat(n["date"]) <= we]
            except Exception:
                pass

        if not narrations:
            return json.dumps({
                "response": "No narrations found for that period.",
                "status": "complete",
                "narration_count": 0,
                "threads": []
            })

        # Build synthesis prompt for Claude
        narration_text = "\n\n".join(
            f"--- {n['date']} ---\n{n['content']}" for n in narrations
        )

        config = load_config()
        claude_bin = config.get("claude_cli", {}).get("bin", "claude")
        model = config.get("claude_cli", {}).get("model", "haiku")

        synthesis_prompt = f"""Analyze these narrations from the week of {week_start} to {week_end} and identify recurring threads and people.

Narrations:
{narration_text}

Return ONLY a JSON object with this structure:
{{
  "response": "human-readable summary with threads and one-off mentions",
  "threads": [
    {{"topic": "...", "count": N, "dates": ["YYYY-MM-DD", ...]}}
  ],
  "one_off": ["topic1", "topic2"],
  "people_frequent": [
    {{"name": "...", "count": N, "context": "brief description of collaboration/topics discussed"}}
  ]
}}

Threads = topics appearing in 2+ narrations. One-off = mentioned only once.
people_frequent = real people (first/last names) mentioned 2+ times across narrations, with context summarising what was discussed.
Be concise. Response field should use bullet points."""

        try:
            synth_result = subprocess.run(
                [claude_bin, "--model", model, "--print", synthesis_prompt],
                capture_output=True, text=True, timeout=60,
                cwd=str(AGENT_DIR), env={**os.environ, "LANG": "en_US.UTF-8"}
            )
            output = synth_result.stdout.strip()
            start = output.find("{")
            end = output.rfind("}") + 1
            if start >= 0 and end > start:
                synthesis = json.loads(output[start:end])
            else:
                synthesis = {"response": output, "threads": [], "one_off": [], "people_frequent": []}
        except Exception as e:
            synthesis = {"response": f"Synthesis error: {e}", "threads": [], "one_off": [], "people_frequent": []}

        # Build coordination signals for frequent people
        # Path 5: signal email to draft outreach for people mentioned 3+ times
        # Path 6: signal network to update context for people mentioned 2+ times
        people_frequent = synthesis.get("people_frequent", [])
        coordination_needed = []
        handshake_contexts = []

        for person in people_frequent:
            person_name = person.get("name", "")
            person_count = person.get("count", 0)
            person_context = person.get("context", "")

            if not person_name:
                continue

            # Path 6: update network context for anyone mentioned 2+ times
            coordination_needed.append("network")
            handshake_contexts.append({
                "target": "network",
                "action": "update_person_context",
                "person_name": person_name,
                "update": f"Weekly synthesis ({week_start} to {week_end}): {person_context}",
                "source": "note agent weekly synthesis"
            })

            # Path 5: draft outreach email for people mentioned 3+ times
            if person_count >= 3:
                coordination_needed.append("email")
                handshake_contexts.append({
                    "target": "email",
                    "action": "draft_email",
                    "to": person_name,
                    "subject_hint": f"Catching up — {person_context[:40]}",
                    "task_context": f"You've been collaborating frequently with {person_name} this week ({person_context}). Suggested outreach.",
                    "tone": "collegial, informal, building-in-public spirit"
                })

        # Deduplicate coordination_needed list while preserving order
        seen = set()
        deduped_coordination = []
        for c in coordination_needed:
            if c not in seen:
                seen.add(c)
                deduped_coordination.append(c)

        result = {
            "response": synthesis.get("response", ""),
            "status": "complete",
            "narration_count": len(narrations),
            "threads": synthesis.get("threads", []),
            "one_off": synthesis.get("one_off", [])
        }

        if deduped_coordination:
            result["coordination_needed"] = deduped_coordination
            result["handshake_contexts"] = handshake_contexts

        return json.dumps(result)

    return json.dumps({
        "response": f"Unknown handshake action: {action}",
        "status": "blocked"
    })


def main():
    parser = argparse.ArgumentParser(description="Note Agent")
    parser.add_argument("query", nargs="*", help="User request")
    parser.add_argument("--handshake", help="Handshake context JSON")
    args = parser.parse_args()

    if args.handshake:
        print(handle_handshake(args.handshake))
        return

    if not args.query:
        print(__doc__)
        sys.exit(1)

    request = " ".join(args.query)

    # Check if user wants citations — signal coordination
    if detect_citation_request(request):
        claims = extract_claims_with_claude(request)
        if claims:
            print(json.dumps({
                "response": f"I'll find papers to support {len(claims)} claim(s). Searching...",
                "status": "complete",
                "coordination_needed": ["research"],
                "handshake_context": {
                    "action": "find_citations",
                    "claims": claims
                },
                "actions": [{"type": "citation_request", "claims": claims}]
            }, indent=2))
            return

    # Narration requests — route through Claude with narration-aware context
    if detect_narration_request(request):
        response = query_with_claude(request)
    else:
        # Normal query mode
        response = query_with_claude(request)

    # If response is already JSON (coordination), pass through
    # Otherwise wrap plain text with Markdown parse mode
    try:
        json.loads(response)
        print(response)
    except (json.JSONDecodeError, TypeError):
        result = {
            "response": response,
            "parse_mode": "HTML",
            "status": "complete"
        }
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
