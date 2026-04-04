#!/usr/bin/env python3
"""
Registry — Tier 1 index for the wiki.
Always fits in context. One-line entry per article and per raw source.
"""

import os
import argparse
from pathlib import Path
from datetime import datetime

import yaml

REGISTRY_FILENAME = "_registry.yaml"

DEFAULT_REGISTRY = {
    "sections": {
        "research": {
            "description": "Academic research topics, empirical findings, methodological notes",
            "article_count": 0,
            "last_updated": None,
        },
        "ideas": {
            "description": "Working hypotheses, research directions, conceptual explorations",
            "article_count": 0,
            "last_updated": None,
        },
        "references": {
            "description": "Summaries of papers, articles, books, and external sources",
            "article_count": 0,
            "last_updated": None,
        },
        "personal": {
            "description": "Preferences, workflows, creative projects, personal knowledge",
            "article_count": 0,
            "last_updated": None,
        },
    },
    "articles": {},
    "pending_sources": [],
}


def _registry_path(vault_path: Path) -> Path:
    return vault_path / "wiki" / REGISTRY_FILENAME


def load_registry(vault_path: Path) -> dict:
    """Load _registry.yaml. Create with defaults if missing."""
    path = _registry_path(vault_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        save_registry(vault_path, DEFAULT_REGISTRY.copy())
        return DEFAULT_REGISTRY.copy()
    with open(path) as f:
        data = yaml.safe_load(f)
    # Ensure required keys exist for forward compatibility
    data.setdefault("sections", {})
    data.setdefault("articles", {})
    data.setdefault("pending_sources", [])
    if data["articles"] is None:
        data["articles"] = {}
    if data["pending_sources"] is None:
        data["pending_sources"] = []
    return data


def save_registry(vault_path: Path, registry: dict) -> None:
    """Write _registry.yaml atomically (write to tmp, then rename)."""
    path = _registry_path(vault_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".yaml.tmp")
    registry["_last_updated"] = datetime.now().isoformat(timespec="seconds")
    with open(tmp_path, "w") as f:
        yaml.dump(registry, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    os.rename(tmp_path, path)


def add_pending_source(vault_path: Path, source_path: str, source_type: str) -> None:
    """Register a new raw source as pending compilation."""
    registry = load_registry(vault_path)
    # Avoid duplicates
    existing_paths = {s["path"] for s in registry["pending_sources"]}
    if source_path in existing_paths:
        return
    registry["pending_sources"].append({
        "path": source_path,
        "type": source_type,
        "received": datetime.now().isoformat(timespec="seconds"),
        "status": "pending",
    })
    save_registry(vault_path, registry)


def mark_source_compiled(vault_path: Path, source_path: str) -> None:
    """Update a pending source status to 'compiled'."""
    registry = load_registry(vault_path)
    for source in registry["pending_sources"]:
        if source["path"] == source_path:
            source["status"] = "compiled"
            break
    save_registry(vault_path, registry)


def get_pending_sources(vault_path: Path) -> list:
    """Return all sources with status 'pending'."""
    registry = load_registry(vault_path)
    return [s for s in registry["pending_sources"] if s.get("status") == "pending"]


def register_article(vault_path: Path, slug: str, title: str, section: str,
                     summary: str, tags: list) -> None:
    """Add or update an article entry in the registry."""
    registry = load_registry(vault_path)
    now = datetime.now().isoformat(timespec="seconds")
    existing = registry["articles"].get(slug, {})
    registry["articles"][slug] = {
        "title": title,
        "section": section,
        "summary": summary,
        "last_updated": now,
        "source_count": existing.get("source_count", 0),
        "tags": tags,
    }
    # Update section article count
    if section in registry["sections"]:
        # Recount from articles dict
        registry["sections"][section]["article_count"] = sum(
            1 for a in registry["articles"].values() if a["section"] == section
        )
        registry["sections"][section]["last_updated"] = now
    save_registry(vault_path, registry)


def get_article(vault_path: Path, slug: str) -> dict | None:
    """Look up an article by slug."""
    registry = load_registry(vault_path)
    return registry["articles"].get(slug)


def list_articles(vault_path: Path, section: str = None, tag: str = None) -> list:
    """List articles, optionally filtered by section or tag."""
    registry = load_registry(vault_path)
    results = []
    for slug, data in registry["articles"].items():
        if section and data.get("section") != section:
            continue
        if tag and tag not in data.get("tags", []):
            continue
        results.append({"slug": slug, **data})
    return results


def get_registry_context(vault_path: Path) -> str:
    """Return the registry as a formatted string suitable for LLM context."""
    registry = load_registry(vault_path)
    sections = registry.get("sections", {})
    articles = registry.get("articles", {})
    pending = [s for s in registry.get("pending_sources", []) if s.get("status") == "pending"]

    total_articles = len(articles)
    section_counts = []
    for name, data in sections.items():
        count = sum(1 for a in articles.values() if a.get("section") == name)
        section_counts.append(f"{name} ({count} articles)")

    lines = [
        f"Wiki Registry ({len(sections)} sections, {total_articles} articles)",
        "",
        "Sections: " + ", ".join(section_counts),
    ]

    if articles:
        lines.append("")
        lines.append("Articles:")
        for slug, data in articles.items():
            tags_str = " ".join(f"#{t}" for t in data.get("tags", []))
            updated = (data.get("last_updated") or "")[:10]
            sources = data.get("source_count", 0)
            lines.append(
                f'- {slug} [{data.get("section", "?")}] "{data.get("title", slug)}"'
                f' (updated {updated}, {sources} sources) {tags_str}'
            )

    if pending:
        lines.append("")
        lines.append(f"Pending sources ({len(pending)}):")
        for s in pending:
            received = (s.get("received") or "")[:10]
            lines.append(f'- {s["path"]} ({s.get("type", "unknown")}, received {received})')

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    from pathlib import Path as _Path
    import yaml as _yaml

    def _get_vault() -> Path:
        agent_dir = _Path(__file__).parent
        config_path = agent_dir / "config.yaml"
        with open(config_path) as f:
            cfg = _yaml.safe_load(f)
        return _Path(cfg["obsidian"]["vault_path"])

    parser = argparse.ArgumentParser(description="Registry CLI")
    parser.add_argument("--context", action="store_true", help="Print registry context for LLM")
    parser.add_argument("--list", action="store_true", help="List all articles")
    parser.add_argument("--pending", action="store_true", help="List pending sources")
    args = parser.parse_args()

    vault = _get_vault()

    if args.context:
        print(get_registry_context(vault))
    elif args.list:
        articles = list_articles(vault)
        if not articles:
            print("No articles yet.")
        for a in articles:
            print(f"[{a['section']}] {a['slug']}: {a['title']}")
    elif args.pending:
        pending = get_pending_sources(vault)
        if not pending:
            print("No pending sources.")
        for s in pending:
            print(f"{s['path']} ({s['type']}) — {s['status']}")
    else:
        parser.print_help()
