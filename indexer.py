#!/usr/bin/env python3
"""
Indexer — Tier 2 section indexes for the wiki.
Each section has an _index.md with article summaries and cross-references.
Loaded on demand when the compiler works within a section.
"""

import argparse
from pathlib import Path
from datetime import datetime

import yaml

SECTIONS = ["research", "ideas", "references", "personal"]

SECTION_DESCRIPTIONS = {
    "research": "Academic research topics, empirical findings, methodological notes",
    "ideas": "Working hypotheses, research directions, conceptual explorations",
    "references": "Summaries of papers, articles, books, and external sources",
    "personal": "Preferences, workflows, creative projects, personal knowledge",
}


def _index_path(vault_path: Path, section: str) -> Path:
    return vault_path / "wiki" / section / "_index.md"


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


def _render_index(section: str, index_data: dict) -> str:
    """Render index_data back to markdown."""
    articles = index_data.get("articles", {})
    now = datetime.now().isoformat(timespec="seconds")
    fm = {
        "section": section,
        "description": SECTION_DESCRIPTIONS.get(section, ""),
        "article_count": len(articles),
        "last_updated": now,
    }
    lines = ["---"]
    lines.append(yaml.dump(fm, default_flow_style=False, allow_unicode=True).strip())
    lines.append("---")
    lines.append("")
    lines.append(f"# {section.capitalize()}")
    lines.append("")

    if articles:
        lines.append("## Articles")
        lines.append("")
        for slug, data in articles.items():
            lines.append(f"### {slug}")
            lines.append(f"**{data.get('title', slug)}**")
            lines.append(data.get("summary", ""))
            tags = data.get("tags", [])
            if tags:
                lines.append(f"Tags: {', '.join(tags)}")
            sources = data.get("source_count", 0)
            updated = (data.get("last_updated") or "")[:10]
            related = data.get("related", [])
            related_str = ", ".join(f"[{r}]" for r in related) if related else ""
            meta = f"Sources: {sources} | Updated: {updated}"
            if related_str:
                meta += f"\nRelated: {related_str}"
            lines.append(meta)
            lines.append("")

    cross_refs = index_data.get("cross_references", [])
    if cross_refs:
        lines.append("## Cross-references")
        for ref in cross_refs:
            lines.append(f"- {ref}")
        lines.append("")

    return "\n".join(lines)


def load_section_index(vault_path: Path, section: str) -> dict:
    """Load and parse a section's _index.md. Create if missing."""
    path = _index_path(vault_path, section)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        empty = {"articles": {}, "cross_references": []}
        save_section_index(vault_path, section, empty)
        return empty

    text = path.read_text()
    fm, body = _parse_frontmatter(text)

    # Parse article blocks from body
    articles = {}
    cross_references = []
    current_slug = None
    current_lines = []

    in_cross_refs = False

    for line in body.splitlines():
        if line.startswith("## Cross-references"):
            in_cross_refs = True
            if current_slug:
                articles[current_slug] = _parse_article_block(current_lines)
                current_slug = None
                current_lines = []
            continue
        if in_cross_refs:
            if line.startswith("- "):
                cross_references.append(line[2:])
            continue
        if line.startswith("### "):
            if current_slug:
                articles[current_slug] = _parse_article_block(current_lines)
            current_slug = line[4:].strip()
            current_lines = []
        elif current_slug is not None:
            current_lines.append(line)

    if current_slug:
        articles[current_slug] = _parse_article_block(current_lines)

    return {"articles": articles, "cross_references": cross_references}


def _parse_article_block(lines: list) -> dict:
    """Parse lines of an article block into a dict."""
    data = {"title": "", "summary": "", "tags": [], "source_count": 0,
            "last_updated": "", "related": []}
    for line in lines:
        line = line.strip()
        if line.startswith("**") and line.endswith("**"):
            data["title"] = line[2:-2]
        elif line.startswith("Tags: "):
            data["tags"] = [t.strip() for t in line[6:].split(",") if t.strip()]
        elif line.startswith("Sources: "):
            parts = line.split("|")
            for part in parts:
                part = part.strip()
                if part.startswith("Sources: "):
                    try:
                        data["source_count"] = int(part[9:].strip())
                    except ValueError:
                        pass
                elif part.startswith("Updated: "):
                    data["last_updated"] = part[9:].strip()
        elif line.startswith("Related: "):
            refs = line[9:].strip()
            data["related"] = [r.strip("[] ") for r in refs.split(",") if r.strip()]
        elif line and not line.startswith("#"):
            if not data["summary"]:
                data["summary"] = line
    return data


def save_section_index(vault_path: Path, section: str, index_data: dict) -> None:
    """Write section _index.md."""
    path = _index_path(vault_path, section)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_index(section, index_data))


def get_article_summary(vault_path: Path, section: str, slug: str) -> str | None:
    """Get the summary block for a specific article from its section index."""
    index_data = load_section_index(vault_path, section)
    article = index_data.get("articles", {}).get(slug)
    if not article:
        return None
    return article.get("summary", "")


def update_article_in_index(vault_path: Path, section: str, slug: str, title: str,
                             summary: str, tags: list, related: list,
                             source_count: int) -> None:
    """Add or update an article entry in the section index."""
    index_data = load_section_index(vault_path, section)
    index_data["articles"][slug] = {
        "title": title,
        "summary": summary,
        "tags": tags,
        "related": related,
        "source_count": source_count,
        "last_updated": datetime.now().isoformat(timespec="seconds"),
    }
    save_section_index(vault_path, section, index_data)


def get_section_context(vault_path: Path, section: str) -> str:
    """Return the section index as a string for LLM context."""
    index_data = load_section_index(vault_path, section)
    articles = index_data.get("articles", {})
    lines = [
        f"Section: {section.capitalize()} — {SECTION_DESCRIPTIONS.get(section, '')}",
        f"Articles: {len(articles)}",
        "",
    ]
    for slug, data in articles.items():
        tags_str = ", ".join(data.get("tags", []))
        lines.append(f"[{slug}] {data.get('title', slug)}")
        lines.append(f"  {data.get('summary', '')}")
        if tags_str:
            lines.append(f"  Tags: {tags_str}")
        related = data.get("related", [])
        if related:
            lines.append(f"  Related: {', '.join(related)}")
        lines.append("")
    return "\n".join(lines)


def find_related_articles(vault_path: Path, tags: list) -> list:
    """Search across all section indexes for articles with overlapping tags.

    Returns list of (section, slug, title, overlap_tags).
    """
    results = []
    tag_set = set(t.lower() for t in tags)
    for section in SECTIONS:
        index_path = _index_path(vault_path, section)
        if not index_path.exists():
            continue
        index_data = load_section_index(vault_path, section)
        for slug, data in index_data.get("articles", {}).items():
            article_tags = set(t.lower() for t in data.get("tags", []))
            overlap = tag_set & article_tags
            if overlap:
                results.append((section, slug, data.get("title", slug), sorted(overlap)))
    return results


if __name__ == "__main__":
    import yaml as _yaml
    from pathlib import Path as _Path

    def _get_vault() -> Path:
        agent_dir = _Path(__file__).parent
        config_path = agent_dir / "config.yaml"
        with open(config_path) as f:
            cfg = _yaml.safe_load(f)
        return _Path(cfg["obsidian"]["vault_path"])

    parser = argparse.ArgumentParser(description="Indexer CLI")
    parser.add_argument("--section", choices=SECTIONS, help="Print section context")
    parser.add_argument("--all", action="store_true", help="Print all section contexts")
    args = parser.parse_args()

    vault = _get_vault()

    if args.section:
        print(get_section_context(vault, args.section))
    elif args.all:
        for s in SECTIONS:
            print(get_section_context(vault, s))
            print("---")
    else:
        parser.print_help()
