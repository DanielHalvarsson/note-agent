#!/usr/bin/env python3
"""
Compiler — the wiki compilation engine.
Takes raw sources and produces/updates wiki articles.

Called by intake.py --process or directly:
    python compile.py raw/clippings/2026-04-04-karpathy-wiki.md
    python compile.py --all  # process all pending sources
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

from registry import (
    get_article,
    get_registry_context,
    get_pending_sources,
    load_registry,
    mark_source_compiled,
    register_article,
)
from indexer import (
    find_related_articles,
    get_section_context,
    load_section_index,
    update_article_in_index,
)

AGENT_DIR = Path(__file__).parent


def _load_config() -> dict:
    config_path = AGENT_DIR / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def _get_vault(config: dict) -> Path:
    return Path(config["obsidian"]["vault_path"])


def call_claude(prompt: str, config: dict, model: str = None) -> str:
    """Wrapper around Claude CLI call.

    Uses config for claude_cli.bin path.
    Default model: compile_model from wiki config (sonnet).
    Handles timeouts and errors gracefully.
    """
    claude_bin = config.get("claude_cli", {}).get("bin", "claude")
    wiki_cfg = config.get("wiki", {})
    timeout = wiki_cfg.get("compile_timeout", 120)

    if model is None:
        model = wiki_cfg.get("compile_model", "sonnet")

    try:
        result = subprocess.run(
            [claude_bin, "--print", "--model", model, prompt],
            capture_output=True,
            text=True,
            cwd=str(AGENT_DIR),
            timeout=timeout,
            env={**os.environ, "LANG": "en_US.UTF-8"},
        )
        output = result.stdout.strip()
        if not output and result.stderr:
            raise RuntimeError(result.stderr.strip())
        return output
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Claude CLI timed out after {timeout}s")
    except FileNotFoundError:
        raise RuntimeError(f"Claude CLI not found at: {claude_bin}")


def _extract_json(text: str) -> dict:
    """Extract the last JSON object from a text block."""
    # Look for JSON after a --- separator first (compile prompts put it there)
    sep_idx = text.rfind("\n---")
    search_text = text[sep_idx:] if sep_idx >= 0 else text

    start = search_text.rfind("{")
    end = search_text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(search_text[start:end])
        except json.JSONDecodeError:
            pass

    # Fallback: search full text
    start = text.rfind("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    return {}


def _extract_article_content(text: str) -> str:
    """Extract markdown article content before the trailing --- JSON block."""
    sep_idx = text.rfind("\n---")
    if sep_idx >= 0:
        content = text[:sep_idx].strip()
    else:
        content = text.strip()

    # Strip markdown code fences if the LLM wrapped the article in ```markdown ... ```
    if content.startswith("```"):
        first_newline = content.find("\n")
        if first_newline >= 0:
            content = content[first_newline + 1:]
        if content.endswith("```"):
            content = content[:-3].strip()

    return content


def classify_and_route(registry_context: str, source_content: str, config: dict) -> dict:
    """LLM Call #1: Decide where this source belongs.

    Returns:
        {
            "section": "research",
            "action": "update" | "create",
            "target_slug": "existing-article-slug" or null,
            "suggested_slug": "new-article-slug",
            "suggested_title": "New Article Title",
            "reasoning": "Brief explanation of classification"
        }
    """
    wiki_cfg = config.get("wiki", {})
    classify_model = wiki_cfg.get("classify_model", "haiku")

    prompt = f"""You are a knowledge wiki compiler. Given the current wiki registry and a new source, decide where it belongs.

WIKI REGISTRY:
{registry_context}

NEW SOURCE (preview):
{source_content[:1500]}

Respond with ONLY a JSON object:
{{
    "section": "one of: research, ideas, references, personal",
    "action": "create or update",
    "target_slug": "slug of existing article to update, or null",
    "suggested_slug": "kebab-case-slug for new article",
    "suggested_title": "Title for new article",
    "reasoning": "One sentence explaining your decision"
}}

Rules:
- If the source clearly relates to an existing article, update it
- If it's a new topic not covered by any existing article, create
- Prefer updating over creating — don't fragment knowledge into tiny articles
- Section choice should match the content: research for empirical/academic, ideas for hypotheses/directions, references for external source summaries, personal for workflows/preferences"""

    output = call_claude(prompt, config, model=classify_model)
    result = _extract_json(output)

    # Validate required fields with sane defaults
    result.setdefault("section", "references")
    result.setdefault("action", "create")
    result.setdefault("target_slug", None)
    result.setdefault("suggested_slug", "untitled")
    result.setdefault("suggested_title", "Untitled")
    result.setdefault("reasoning", "")
    return result


def create_article(section_context: str, source_content: str, suggested_title: str,
                   config: dict) -> dict:
    """LLM Call #2b: Create a new article from source material.

    Returns:
        {
            "article_content": "full article markdown",
            "summary": "one-paragraph summary for index",
            "tags": ["tag", "list"],
            "related": ["other-article-slugs"]
        }
    """
    prompt = f"""You are a knowledge wiki compiler. Create a new wiki article from this source material.

SECTION CONTEXT (existing articles in this section):
{section_context}

SOURCE MATERIAL:
{source_content}

Write a wiki article in markdown. Requirements:
- Start with YAML frontmatter (title, section, slug, created, tags, related)
- Write in clear, information-dense prose — not a summary of the source, but a KNOWLEDGE ARTICLE that synthesizes the information
- Include sections for: key findings/concepts, evidence/details, open questions
- End with a Source Notes section attributing what came from this source
- Cross-reference related articles from the section context where relevant
- Tags should be lowercase, kebab-case, 3-8 tags

After the article, add a --- separator and then a JSON block:
{{
    "summary": "One-paragraph summary for the section index",
    "tags": ["tag", "list"],
    "related": ["slugs-of-related-articles"]
}}"""

    output = call_claude(prompt, config)
    article_content = _extract_article_content(output)
    meta = _extract_json(output)

    return {
        "article_content": article_content,
        "summary": meta.get("summary", suggested_title),
        "tags": meta.get("tags", []),
        "related": meta.get("related", []),
    }


def update_article(section_context: str, existing_article: str, source_content: str,
                   config: dict) -> dict:
    """LLM Call #2a: Update an existing article with new source material.

    Returns:
        {
            "article_content": "full updated markdown",
            "summary": "updated one-paragraph summary for index",
            "tags": ["updated", "tag", "list"],
            "related": ["other-article-slugs"]
        }
    """
    prompt = f"""You are a knowledge wiki compiler. Update an existing wiki article with new source material.

SECTION CONTEXT:
{section_context}

EXISTING ARTICLE:
{existing_article}

NEW SOURCE MATERIAL:
{source_content}

Update the article to integrate the new source. Requirements:
- Preserve existing content — add to it, don't replace it
- Update sections where the new source adds information
- Add the new source to the Source Notes section
- Update frontmatter: last_updated, sources list, tags if needed
- If the new source contradicts existing content, note both perspectives
- Keep the article focused — if the source is tangential, add only the relevant parts

Return the full updated article markdown, then a --- separator and JSON:
{{
    "summary": "Updated one-paragraph summary for the section index",
    "tags": ["updated", "tag", "list"],
    "related": ["slugs-of-related-articles"]
}}"""

    output = call_claude(prompt, config)
    article_content = _extract_article_content(output)
    meta = _extract_json(output)

    return {
        "article_content": article_content,
        "summary": meta.get("summary", ""),
        "tags": meta.get("tags", []),
        "related": meta.get("related", []),
    }


def compile_source(vault_path: Path, source_path: str, config: dict) -> dict:
    """Compile a single raw source into the wiki.

    Orchestrates the full compilation loop:
    1. Load registry (Tier 1)
    2. Read source content
    3. LLM Call #1: classify & route
    4. Load section index (Tier 2)
    5. LLM Call #2: create or update article
    6. Write article, update index and registry

    Returns:
        {
            "status": "compiled" | "failed",
            "action": "created" | "updated",
            "article": {"slug": "...", "section": "...", "title": "..."},
            "error": "..." (if failed)
        }
    """
    file_path = vault_path / source_path if not Path(source_path).is_absolute() else Path(source_path)

    if not file_path.exists():
        return {"status": "failed", "error": f"Source file not found: {file_path}"}

    try:
        source_content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"status": "failed", "error": f"Could not read source: {e}"}

    try:
        # Step 1: Load registry context
        registry_ctx = get_registry_context(vault_path)

        # Step 2: Classify and route
        print(f"  → Classifying {source_path}...", flush=True)
        routing = classify_and_route(registry_ctx, source_content, config)
        section = routing["section"]
        action = routing["action"]
        target_slug = routing.get("target_slug")
        suggested_slug = routing.get("suggested_slug") or "untitled"
        suggested_title = routing.get("suggested_title") or ""

        # For updates, fall back to existing article title from registry
        if not suggested_title and target_slug:
            existing = get_article(vault_path, target_slug)
            if existing:
                suggested_title = existing.get("title", target_slug)
        if not suggested_title:
            suggested_title = suggested_slug.replace("-", " ").title()

        print(f"  → {action.upper()} in [{section}]: {suggested_title} (reason: {routing.get('reasoning', '')})", flush=True)

        # Step 3: Load section context
        section_ctx = get_section_context(vault_path, section)

        # Step 4: Create or update article
        if action == "update" and target_slug:
            article_path = vault_path / "wiki" / section / f"{target_slug}.md"
            if article_path.exists():
                existing_article = article_path.read_text(encoding="utf-8")
                print(f"  → Updating existing article {target_slug}.md...", flush=True)
                result = update_article(section_ctx, existing_article, source_content, config)
                final_slug = target_slug
            else:
                # Target slug specified but file missing — create instead
                print(f"  → Target {target_slug}.md not found, creating instead...", flush=True)
                result = create_article(section_ctx, source_content, suggested_title, config)
                final_slug = suggested_slug
                action = "create"
        else:
            print(f"  → Creating new article {suggested_slug}.md...", flush=True)
            result = create_article(section_ctx, source_content, suggested_title, config)
            final_slug = suggested_slug

        # Step 5: Write article to disk
        article_dir = vault_path / "wiki" / section
        article_dir.mkdir(parents=True, exist_ok=True)
        article_path = article_dir / f"{final_slug}.md"

        # Inject source tracking into frontmatter if not already there
        article_content = _inject_source_into_frontmatter(
            result["article_content"], source_path, section, final_slug
        )
        article_path.write_text(article_content, encoding="utf-8")

        # Step 6: Update section index
        related = result.get("related", [])
        update_article_in_index(
            vault_path, section, final_slug,
            title=suggested_title,
            summary=result["summary"],
            tags=result.get("tags", []),
            related=related,
            source_count=_count_sources_in_article(article_content),
        )

        # Step 7: Update registry
        register_article(
            vault_path, final_slug,
            title=suggested_title,
            section=section,
            summary=result["summary"],
            tags=result.get("tags", []),
            source_count=_count_sources_in_article(article_content),
        )
        mark_source_compiled(vault_path, source_path)

        return {
            "status": "compiled",
            "action": "created" if action != "update" else "updated",
            "article": {
                "slug": final_slug,
                "section": section,
                "title": suggested_title,
                "path": str(article_path.relative_to(vault_path)),
            },
        }

    except Exception as e:
        return {"status": "failed", "error": str(e), "source": source_path}


def compile_all_pending(vault_path: Path, config: dict) -> list:
    """Process all pending sources. Returns list of compilation results."""
    pending = get_pending_sources(vault_path)
    if not pending:
        return []

    results = []
    for source in pending:
        source_path = source["path"]
        print(f"\nCompiling: {source_path}", flush=True)
        result = compile_source(vault_path, source_path, config)
        results.append(result)
        if result["status"] == "compiled":
            article = result["article"]
            print(f"  ✓ {result['action']}: wiki/{article['section']}/{article['slug']}.md")
        else:
            print(f"  ✗ Failed: {result.get('error', 'unknown error')}")

    return results


def _inject_source_into_frontmatter(content: str, source_path: str,
                                     section: str, slug: str) -> str:
    """Ensure the article frontmatter has section, slug, and sources fields."""
    if not content.startswith("---"):
        # No frontmatter — prepend minimal one
        now = datetime.now().isoformat(timespec="seconds")
        fm = f"---\nsection: {section}\nslug: {slug}\ncreated: {now}\nlast_updated: {now}\nsources:\n  - {source_path}\n---\n\n"
        return fm + content

    end = content.find("---", 3)
    if end == -1:
        return content

    fm_text = content[3:end]
    body = content[end + 3:]

    try:
        fm = yaml.safe_load(fm_text) or {}
    except Exception:
        return content

    fm.setdefault("section", section)
    fm.setdefault("slug", slug)
    fm.setdefault("created", datetime.now().isoformat(timespec="seconds"))
    fm["last_updated"] = datetime.now().isoformat(timespec="seconds")

    sources = fm.get("sources", [])
    if isinstance(sources, list):
        if source_path not in sources:
            sources.append(source_path)
    else:
        sources = [source_path]
    fm["sources"] = sources

    new_fm = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return f"---\n{new_fm}---{body}"


def _count_sources_in_article(content: str) -> int:
    """Count sources listed in the article frontmatter."""
    if not content.startswith("---"):
        return 0
    end = content.find("---", 3)
    if end == -1:
        return 0
    try:
        fm = yaml.safe_load(content[3:end]) or {}
        sources = fm.get("sources", [])
        return len(sources) if isinstance(sources, list) else 0
    except Exception:
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wiki compiler engine")
    parser.add_argument("source", nargs="?", help="Source file path (relative to vault or absolute)")
    parser.add_argument("--all", action="store_true", help="Compile all pending sources")
    args = parser.parse_args()

    config = _load_config()
    vault = _get_vault(config)

    if args.all:
        results = compile_all_pending(vault, config)
        if not results:
            print("No pending sources.")
        compiled = sum(1 for r in results if r["status"] == "compiled")
        failed = len(results) - compiled
        print(f"\nDone: {compiled} compiled, {failed} failed.")

    elif args.source:
        source_path = args.source
        # Normalise: if absolute path inside vault, make relative
        abs_path = Path(source_path).resolve()
        if abs_path.is_relative_to(vault):
            source_path = str(abs_path.relative_to(vault))

        # Auto-register if not already in registry
        from registry import load_registry
        registry = load_registry(vault)
        known = {s["path"] for s in registry.get("pending_sources", [])}
        if source_path not in known:
            from intake import register_source
            register_source(abs_path)

        result = compile_source(vault, source_path, config)
        if result["status"] == "compiled":
            a = result["article"]
            print(f"\n✓ {result['action'].upper()}: wiki/{a['section']}/{a['slug']}.md")
        else:
            print(f"\n✗ Failed: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    else:
        parser.print_help()
