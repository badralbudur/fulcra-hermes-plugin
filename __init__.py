"""Fulcra Context plugin for Hermes Agent."""

from pathlib import Path
from . import tools


def register(ctx):
    """Wire fixed CLI handlers to their typed schemas, then bundled resources."""
    for name, schema in tools.TOOL_SCHEMAS.items():
        ctx.register_tool(name=name, toolset="context", schema=schema, handler=getattr(tools, name))

    skills_dir = Path(__file__).parent / "skills"
    if skills_dir.exists():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                ctx.register_skill(child.name, skill_md)
