"""LLM synthesis with modular prompt loading."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Set

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_CITATION_RE = re.compile(r"\[Q(\d+)\]")


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    return path.read_text(encoding="utf-8").strip()


def get_system_prompt(include_stats: bool = False) -> str:
    prompt = load_prompt("system.txt")
    if not include_stats:
        prompt = prompt.split("## Using Statistics (MP or Ministry)", 1)[0].rstrip()
        prompt += "\n\nNo metadata statistics block is supplied. Do not invent ministry/MP question totals, rankings, or a statistics preface. Answer the user's topic directly."
    return prompt


def get_user_prompt(query: str, context: str) -> str:
    template = load_prompt("user.txt")
    return template.format(query=query, context=context)


def extract_citations(answer: str, max_n: int) -> List[int]:
    found: Set[int] = set()
    for m in _CITATION_RE.finditer(answer):
        idx = int(m.group(1))
        if 1 <= idx <= max_n:
            found.add(idx)
    return sorted(found)


def validate_citations(answer: str, evidence_count: int) -> List[str]:
    errors: List[str] = []
    for m in _CITATION_RE.finditer(answer):
        idx = int(m.group(1))
        if idx < 1 or idx > evidence_count:
            errors.append(f"Invalid citation [Q{idx}] (valid range: 1-{evidence_count})")
    return errors


class Synthesizer:
    def __init__(self):
        pass

    def generate(self, query: str, context: str) -> str:
        has_stats = context.lstrip().startswith(("=== MP STATISTICS (", "=== MINISTRY STATISTICS ("))
        system_prompt = get_system_prompt(include_stats=has_stats)
        user_prompt = get_user_prompt(query=query, context=context)

        from lok_sabha_rag.core.ai_provider import generate,normalize_citation_groups
        return normalize_citation_groups(generate(system_prompt,user_prompt,max_tokens=4096),'Q')

