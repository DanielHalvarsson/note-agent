#!/usr/bin/env python3
"""
Intake — entry point for new raw sources.
Classifies incoming files and registers them for compilation.

Usage:
    # Register a single file
    python intake.py /path/to/source.md

    # Register a file with explicit type
    python intake.py /path/to/source.md --type clipping

    # Scan raw/ directories for unregistered files
    python intake.py --scan

    # Process all pending sources (triggers compilation)
    python intake.py --process
"""

import argparse
import sys
from pathlib import Path

import yaml

from registry import load_registry, add_pending_source, get_pending_sources

# Map raw/ subdirectory names to source types
RAW_TYPE_MAP = {
    "fragments": "fragment",
    "clippings": "clipping",
    "papers": "paper",
    "notes": "note",
}

# Keyword → section heuristics
SECTION_KEYWORDS = {
    "research": [
        "empirical", "regression", "data", "evidence", "findings", "methodology",
        "paper", "study", "analysis", "productivity", "labor", "firm", "economics",
        "survey", "experiment", "causal", "identification",
    ],
    "ideas": [
        "hypothesis", "idea", "direction", "explore", "conjecture", "speculation",
        "what if", "maybe", "question", "think", "consider", "propose",
    ],
    "references": [
        "summary of", "review of", "according to", "karpathy", "acemoglu",
        "abstract", "published", "journal", "arxiv", "doi", "isbn",
        "author", "source_url",
    ],
    "personal": [
        "workflow", "preference", "habit", "personal", "my setup", "i use",
        "i prefer", "creative", "project", "tool", "config",
    ],
}


def _load_config() -> dict:
    agent_dir = Path(__file__).parent
    config_path = agent_dir / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def _get_vault() -> Path:
    return Path(_load_config()["obsidian"]["vault_path"])


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split markdown into (frontmatter dict, body string)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    fm_text = text[3:end].strip()
    body = text[end + 3:].strip()
    try:
        fm = yaml.safe_load(fm_text) or {}
    except Exception:
        fm = {}
    return fm, body


def _infer_type_from_path(file_path: Path) -> str:
    """Infer source type from directory location."""
    for part in file_path.parts:
        if part in RAW_TYPE_MAP:
            return RAW_TYPE_MAP[part]
    return "note"


def _infer_section(fm: dict, body: str, source_type: str) -> str:
    """Keyword-match content against section descriptions. No LLM."""
    text = (body + " " + " ".join(str(v) for v in fm.values())).lower()

    # Explicit frontmatter section wins
    if "section" in fm:
        s = str(fm["section"]).lower()
        if s in SECTION_KEYWORDS:
            return s

    # Papers and clippings lean toward references unless strong research signal
    if source_type == "paper":
        return "references"

    scores = {section: 0 for section in SECTION_KEYWORDS}
    for section, keywords in SECTION_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[section] += 1

    best = max(scores, key=lambda s: scores[s])
    return best if scores[best] > 0 else "references"


def classify_source(file_path: Path) -> dict:
    """Classify a raw source file by reading its content and metadata.

    Classification logic (NO LLM — pure heuristics):
    - Files in raw/fragments/  → type: fragment
    - Files in raw/clippings/  → type: clipping
    - Files in raw/papers/     → type: paper
    - Files in raw/notes/      → type: note
    - Title: from frontmatter 'title' field, or first # heading, or filename
    - Topics: from frontmatter 'tags' field if present
    - Section: keyword matching against section descriptions
    """
    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return {
            "type": _infer_type_from_path(file_path),
            "title": file_path.stem,
            "detected_topics": [],
            "suggested_section": "references",
            "error": str(e),
        }

    fm, body = _parse_frontmatter(text)
    source_type = _infer_type_from_path(file_path)

    # Title: frontmatter > first # heading > filename
    title = fm.get("title") or fm.get("Title") or ""
    if not title:
        for line in body.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
    if not title:
        title = file_path.stem.replace("-", " ").replace("_", " ").title()

    # Topics from frontmatter tags
    raw_tags = fm.get("tags", [])
    if isinstance(raw_tags, str):
        raw_tags = [t.strip() for t in raw_tags.split(",")]
    detected_topics = [str(t).lower() for t in raw_tags if t]

    suggested_section = _infer_section(fm, body, source_type)

    return {
        "type": source_type,
        "title": str(title),
        "detected_topics": detected_topics,
        "suggested_section": suggested_section,
    }


def register_source(file_path: Path, source_type: str = None) -> dict:
    """Classify a file and register it as pending in the registry.

    Returns the classification result plus registration status.
    """
    classification = classify_source(file_path)
    if source_type:
        classification["type"] = source_type

    vault = _get_vault()
    # Store path relative to vault for portability
    try:
        rel_path = str(file_path.relative_to(vault))
    except ValueError:
        rel_path = str(file_path)

    add_pending_source(vault, rel_path, classification["type"])
    classification["registered_path"] = rel_path
    classification["status"] = "registered"
    return classification


def scan_raw_directories(vault_path: Path) -> list:
    """Walk raw/ subdirectories, find files not yet in registry, register them.

    Returns list of newly registered sources.
    """
    registry = load_registry(vault_path)
    known_paths = {s["path"] for s in registry.get("pending_sources", [])}

    raw_dir = vault_path / "raw"
    if not raw_dir.exists():
        return []

    newly_registered = []
    for md_file in sorted(raw_dir.rglob("*.md")):
        try:
            rel_path = str(md_file.relative_to(vault_path))
        except ValueError:
            rel_path = str(md_file)

        if rel_path in known_paths:
            continue

        classification = classify_source(md_file)
        add_pending_source(vault_path, rel_path, classification["type"])
        newly_registered.append({
            "path": rel_path,
            **classification,
        })

    return newly_registered


def get_pending_for_processing(vault_path: Path) -> list:
    """Return pending sources with classification and content preview.

    Returns:
        [
            {
                "source": {path, type, received, ...},
                "classification": {title, detected_topics, suggested_section},
                "content_preview": "first 500 chars of the file"
            }
        ]
    """
    pending = get_pending_sources(vault_path)
    results = []
    for source in pending:
        file_path = vault_path / source["path"]
        classification = classify_source(file_path) if file_path.exists() else {
            "type": source["type"],
            "title": file_path.stem,
            "detected_topics": [],
            "suggested_section": "references",
        }
        try:
            content_preview = file_path.read_text(encoding="utf-8")[:500]
        except Exception:
            content_preview = ""

        results.append({
            "source": source,
            "classification": classification,
            "content_preview": content_preview,
        })
    return results


def process_pending(vault_path: Path, config: dict) -> list:
    """Process all pending sources through the compiler."""
    from compile import compile_all_pending
    return compile_all_pending(vault_path, config)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Intake — register and process raw sources")
    parser.add_argument("file", nargs="?", help="File to register")
    parser.add_argument("--type", help="Override source type")
    parser.add_argument("--scan", action="store_true", help="Scan raw/ for unregistered files")
    parser.add_argument("--process", action="store_true", help="Process all pending sources")
    args = parser.parse_args()

    vault = _get_vault()

    if args.scan:
        found = scan_raw_directories(vault)
        if not found:
            print("No new files found.")
        else:
            print(f"Registered {len(found)} new file(s):")
            for f in found:
                print(f"  [{f['type']}] {f['path']} → {f['suggested_section']}")

    elif args.process:
        config = _load_config()
        results = process_pending(vault, config)
        if not results:
            print("No pending sources to process.")
        else:
            for r in results:
                status = r.get("status", "?")
                article = r.get("article", {})
                print(f"  [{status}] {article.get('section', '?')}/{article.get('slug', '?')}")

    elif args.file:
        file_path = Path(args.file).resolve()
        if not file_path.exists():
            print(f"File not found: {file_path}", file=sys.stderr)
            sys.exit(1)
        result = register_source(file_path, args.type)
        print(f"Registered: [{result['type']}] {result['title']}")
        print(f"  Path: {result['registered_path']}")
        print(f"  Suggested section: {result['suggested_section']}")
        if result.get("detected_topics"):
            print(f"  Topics: {', '.join(result['detected_topics'])}")

    else:
        parser.print_help()
