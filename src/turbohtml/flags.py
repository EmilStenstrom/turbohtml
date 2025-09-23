"""Feature flags for incremental parser refactors.

Centralized so tests can toggle behavior deterministically without
sprinkling ad-hoc environment variable reads in hot code paths.

Flags are simple module-level booleans (no dynamic mutation during a
single parse run to preserve determinism). Unit tests that need both
paths should spawn fresh parser instances after flipping flags.
"""

# Enable rewritten adoption agency implementation (phase 1: <a><b><i> only)
NEW_ADOPTION = True  # re-enabled to test updated adoption simple-case parent reset

