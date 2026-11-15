"""Pipeline orchestration and derived build state.

``plan_change`` compares source keys without generating artifacts. ``build_view``
resolves the current revision's keys through the verified artifact index.
``run`` enforces confirmation gates, publishes each successful artifact before
checkpointing it and reuses verified cache entries when an attempt is retried.
"""
