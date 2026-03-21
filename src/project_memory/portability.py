"""Export and import project memory to/from MEMORY.md."""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from . import __version__
from .db import ProjectMemoryDB

# Plan types that get their own top-level sections, in display order.
_PLAN_TYPE_SECTIONS = {
    "protocol": "Protocols",
    "design": "Designs",
    "checklist": "Checklists",
}

# Section heading → source_type mapping for parsing.
_SECTION_SOURCE_TYPE = {
    "Protocols": "plan",
    "Designs": "plan",
    "Checklists": "plan",
    "Plans": "plan",
    "Notes": "note",
    "Learnings": "learning",
    "Tasks": "task",
}


def export_memory(db: ProjectMemoryDB) -> str:
    """Export all active memory entries to a MEMORY.md-format string."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        "# Project Memory",
        "",
        f"> Exported from project-memory v{__version__} on {now}.",
        "> Import with: project-memory import",
    ]

    # Plans grouped by type: protocols, designs, checklists, then untyped
    plans = db.plan_list(status="active", limit=1000)
    typed_plans: dict[str, list[dict]] = {t: [] for t in _PLAN_TYPE_SECTIONS}
    untyped_plans: list[dict] = []
    for p in plans:
        ptype = p.get("type")
        if ptype in typed_plans:
            typed_plans[ptype].append(p)
        else:
            untyped_plans.append(p)

    for ptype, section_name in _PLAN_TYPE_SECTIONS.items():
        if typed_plans[ptype]:
            lines.append("")
            lines.append(f"## {section_name}")
            for p in typed_plans[ptype]:
                lines.extend(_format_entry(p, "plan"))

    if untyped_plans:
        lines.append("")
        lines.append("## Plans")
        for p in untyped_plans:
            lines.extend(_format_entry(p, "plan"))

    # Notes
    notes = db.recall(limit=1000)
    if notes:
        lines.append("")
        lines.append("## Notes")
        for n in notes:
            lines.extend(_format_entry(n, "note"))

    # Learnings
    learnings = db.recall_learnings(limit=1000)
    if learnings:
        lines.append("")
        lines.append("## Learnings")
        for l in learnings:
            lines.extend(_format_entry(l, "learning"))

    # Tasks
    tasks = db.task_list(limit=1000)
    if tasks:
        lines.append("")
        lines.append("## Tasks")
        for t in tasks:
            lines.extend(_format_entry(t, "task"))

    lines.append("")
    return "\n".join(lines)


def _format_entry(entry: dict, source_type: str) -> list[str]:
    """Format a single entry as markdown lines."""
    key = entry["path"].split(":", 1)[1]
    lines = ["", f"### {key}"]

    meta_parts = []
    if entry.get("type"):
        meta_parts.append(f"**Type:** {entry['type']}")
    if source_type in ("plan", "task") and entry.get("status"):
        meta_parts.append(f"**Status:** {entry['status']}")
    if entry.get("group"):
        meta_parts.append(f"**Group:** {entry['group']}")
    updated = entry.get("updated_at") or entry.get("indexed_at")
    if updated:
        meta_parts.append(f"**Updated:** {updated}")

    if meta_parts:
        lines.append(" | ".join(meta_parts))

    lines.append("")
    lines.append(entry["content"])

    return lines


def parse_memory_md(text: str) -> List[dict]:
    """Parse a MEMORY.md string into a list of entry dicts.

    Each dict has: key, content, source_type, type, status, group.
    """
    entries = []
    current_section = None
    current_entry = None

    for line in text.split("\n"):
        # Top-level section (## heading)
        m = re.match(r"^## (.+)$", line)
        if m:
            if current_entry:
                current_entry["content"] = current_entry["content"].strip()
                entries.append(current_entry)
                current_entry = None
            current_section = m.group(1).strip()
            continue

        # Entry heading (### key)
        m = re.match(r"^### (.+)$", line)
        if m:
            if current_entry:
                current_entry["content"] = current_entry["content"].strip()
                entries.append(current_entry)
            source_type = _SECTION_SOURCE_TYPE.get(current_section)
            if not source_type:
                current_entry = None
                continue
            current_entry = {
                "key": m.group(1).strip(),
                "source_type": source_type,
                "type": _infer_type_from_section(current_section),
                "status": None,
                "group": None,
                "content": "",
                "_meta_parsed": False,
            }
            continue

        if current_entry is None:
            continue

        # Metadata line (bold key-value pairs)
        if not current_entry["_meta_parsed"] and line.startswith("**"):
            _parse_meta_line(current_entry, line)
            current_entry["_meta_parsed"] = True
            continue

        # Content line
        current_entry["content"] += line + "\n"

    # Flush last entry
    if current_entry:
        current_entry["content"] = current_entry["content"].strip()
        entries.append(current_entry)

    # Clean up internal fields
    for e in entries:
        e.pop("_meta_parsed", None)

    return entries


def _infer_type_from_section(section: str) -> Optional[str]:
    """Infer the type from the section heading for plan types."""
    for ptype, heading in _PLAN_TYPE_SECTIONS.items():
        if section == heading:
            return ptype
    return None


def _parse_meta_line(entry: dict, line: str):
    """Parse a metadata line like '**Type:** convention | **Status:** active | ...'."""
    for part in line.split("|"):
        part = part.strip()
        m = re.match(r"\*\*(.+?):\*\*\s*(.+)", part)
        if m:
            key = m.group(1).strip().lower()
            value = m.group(2).strip()
            if key == "type":
                entry["type"] = value
            elif key == "status":
                entry["status"] = value
            elif key == "group":
                entry["group"] = value
            # updated_at is informational, not imported back


def import_memory(db: ProjectMemoryDB, path: Path) -> dict:
    """Import entries from a MEMORY.md file into the database.

    Idempotent — unchanged entries are skipped via content-hash logic.
    Returns {"imported": N, "skipped": N}.
    """
    text = path.read_text(encoding="utf-8")
    entries = parse_memory_md(text)

    imported = 0
    skipped = 0

    for entry in entries:
        written = _write_entry(db, entry)
        if written:
            imported += 1
        else:
            skipped += 1

    return {"imported": imported, "skipped": skipped}


def _write_entry(db: ProjectMemoryDB, entry: dict) -> bool:
    """Write a single parsed entry to the database. Returns True if written."""
    source_type = entry["source_type"]
    key = entry["key"]
    content = entry["content"]
    entry_type = entry.get("type")

    if source_type == "note":
        return db.remember(key, content, type=entry_type)
    elif source_type == "learning":
        return db.learn(key, content, type=entry_type)
    elif source_type == "task":
        return db.task_add(key, content, group=entry.get("group"), type=entry_type)
    elif source_type == "plan":
        return db.plan_create(key, content, type=entry_type)
    return False
