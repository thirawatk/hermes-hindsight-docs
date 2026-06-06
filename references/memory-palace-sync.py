#!/usr/bin/env python3
"""
Memory Palace Sync — Bidirectional sync of shared memory across all Hermes profiles.

Strategy:
1. Each profile has ANY section matching '## Shared Infrastructure' (may be multiple)
2. Extract ALL shared blocks from all profiles
3. Merge them (union of all facts, deduplicated by header)
   - Same header → keep the longer/more complete version
4. Remove ALL old shared sections from each profile
5. Write ONE clean merged shared section back to ALL profiles

Usage:
  python3 memory-palace-sync.py          # sync all profiles
  python3 memory-palace-sync.py --check  # dry run
  python3 memory-palace-sync.py --force  # overwrite even if unchanged
"""

import os
import re
import sys
from datetime import datetime, timezone

PROFILES = {
    "default": "/root/.hermes/memories/MEMORY.md",
    "buddy": "/root/.hermes/profiles/buddy/memories/MEMORY.md",
    "financialanalyst": "/root/.hermes/profiles/financialanalyst/memories/MEMORY.md",
    "investor": "/root/.hermes/profiles/investor/memories/MEMORY.md",
    "monitor": "/root/.hermes/profiles/monitor/memories/MEMORY.md",
    "trader": "/root/.hermes/profiles/trader/memories/MEMORY.md",
    "astrology": "/root/.hermes/profiles/astrology/memories/MEMORY.md",
}

SHARED_HEADER_RE = re.compile(r'^## Shared Infrastructure.*$', re.MULTILINE)
SUB_HEADER_RE = re.compile(r'^### .+$', re.MULTILINE)


def read_file(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def extract_profile_specific(content):
    """Remove ALL Shared Infrastructure sections. Returns content before first one."""
    match = SHARED_HEADER_RE.search(content)
    if not match:
        return content.rstrip()
    return content[:match.start()].rstrip()


def extract_all_shared_blocks(content):
    """Extract all ### blocks from all Shared Infrastructure sections."""
    blocks = []
    for match in SHARED_HEADER_RE.finditer(content):
        section_start = match.end()
        next_section = SHARED_HEADER_RE.search(content, section_start + 1)
        section_end = next_section.start() if next_section else len(content)
        section = content[section_start:section_end]

        sub_headers = list(SUB_HEADER_RE.finditer(section))
        for i, header_match in enumerate(sub_headers):
            header = header_match.group(0).replace("### ", "").strip()
            body_start = header_match.end()
            body_end = sub_headers[i + 1].start() if i + 1 < len(sub_headers) else len(section)
            body = section[body_start:body_end].strip()
            blocks.append((header, body))
    return blocks


def merge_facts(all_blocks):
    """
    Merge blocks from all profiles. Deduplicate by header name.
    Same header → keep the longer (more complete) version.
    """
    merged = {}  # header -> body

    for profile, blocks in all_blocks.items():
        for header, body in blocks:
            if header not in merged or len(body) > len(merged[header]):
                merged[header] = body

    # Sort by header name
    return [(h, merged[h]) for h in sorted(merged.keys())]


def build_shared_section(facts):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"## Shared Infrastructure (updated {now})", ""]

    for header, body in facts:
        lines.append(f"### {header}")
        lines.append("")
        for line in body.split('\n'):
            lines.append(line)
        lines.append("")

    return '\n'.join(lines).rstrip() + '\n'


def sync_profiles(dry_run=False, force=False):
    profiles_data = {}
    for name, path in PROFILES.items():
        content = read_file(path)
        if content:
            profiles_data[name] = content
        else:
            print(f"  ⚠️  {name}: file not found")

    if not profiles_data:
        print("❌ No profile memory files found!")
        return

    all_blocks = {}
    profile_specifics = {}

    for name, content in profiles_data.items():
        specific = extract_profile_specific(content)
        blocks = extract_all_shared_blocks(content)
        profile_specifics[name] = specific
        if blocks:
            all_blocks[name] = blocks
            print(f"  📖 {name}: {len(blocks)} shared fact blocks")
        else:
            print(f"  📖 {name}: no shared section found")

    if not all_blocks:
        print("⚠️  No shared sections found. Nothing to sync.")
        return

    merged_facts = merge_facts(all_blocks)
    merged_section = build_shared_section(merged_facts)
    print(f"\n🔀 Merged: {len(merged_facts)} unique fact blocks")

    changes = 0
    for name, path in PROFILES.items():
        if name not in profile_specifics:
            continue

        specific = profile_specifics[name]
        new_content = specific + "\n\n" + merged_section

        old_content = profiles_data.get(name, "")

        if old_content.strip() == new_content.strip() and not force:
            print(f"  ✅ {name}: unchanged")
            continue

        if dry_run:
            print(f"  🔄 {name}: would update")
        else:
            write_file(path, new_content)
            print(f"  ✏️  {name}: updated")
            changes += 1

    if dry_run:
        print(f"\n📋 Dry run complete.")
    else:
        print(f"\n✅ Sync complete. {changes} profiles updated.")


if __name__ == "__main__":
    dry_run = "--check" in sys.argv
    force = "--force" in sys.argv
    print("🔍 Memory Palace Sync — DRY RUN\n" if dry_run else "🔄 Memory Palace Sync\n")
    sync_profiles(dry_run=dry_run, force=force)
