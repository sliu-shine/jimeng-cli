"""Viral agent package.

Submodules are intentionally not imported here, so lightweight imports such as
``viral_agent.ai_providers`` do not pull in API clients and create circular
imports.
"""

__all__ = ["knowledge_base", "analyzer", "agent", "pipeline", "ai_providers"]
