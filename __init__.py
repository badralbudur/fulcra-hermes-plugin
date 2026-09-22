"""Fulcra Context plugin for Hermes Agent."""

from pathlib import Path
from . import schemas
from . import tools

def register(ctx):
    """Wire schemas to handlers and register skills."""
    
    # Register Authentication Tools
    ctx.register_tool(
        name="get_auth_url",
        toolset="context",
        schema=schemas.AUTH_GET_URL,
        handler=tools.fulcra_get_auth_url,
    )

    ctx.register_tool(
        name="submit_device_code",
        toolset="context",
        schema=schemas.AUTH_SUBMIT_CODE,
        handler=tools.fulcra_submit_device_code,
    )

    # Register Catalog Tool
    ctx.register_tool(
        name="get_data_catalog",
        toolset="context",
        schema=schemas.GET_CATALOG,
        handler=tools.fulcra_get_data_catalog,
    )

    # Register bundled skills
    skills_dir = Path(__file__).parent / "skills"
    if skills_dir.exists():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                ctx.register_skill(child.name, skill_md)
