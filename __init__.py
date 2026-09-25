"""Fulcra Context plugin for Hermes Agent."""

from pathlib import Path
from . import mesh, mesh_updates, plugin_setup, tools, updates, workspace


def register(ctx):
    """Wire fixed CLI handlers to their typed schemas, then bundled resources."""
    for name, schema in tools.TOOL_SCHEMAS.items():
        ctx.register_tool(name=name, toolset="context", schema=schema, handler=getattr(tools, name))

    plugin_setup.register(ctx)
    mesh_updates.register(ctx)
    workspace.register(ctx)
    updates.register(ctx)
    ctx.register_tool(name="fulcra_mesh", toolset="context", schema=mesh.SCHEMA,
                      handler=mesh.make_handler(ctx.state))

    skills_dir = Path(__file__).parent / "skills"
    if skills_dir.exists():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                ctx.register_skill(child.name, skill_md)
