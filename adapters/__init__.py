"""Adapter layer — platform/editor specifics isolated from the engine core.

Layout (ТЗ §1 three-axis split, Фаза 0):
    adapters/local_fs/windows.py  — Windows path primitives (transitional home,
                                     see module docstring; final home after
                                     Фаза 1 when WorkspaceSource owns them)
    adapters/zed/                 — Zed-specific configuration/install glue
                                    (zed_config.py; extension.toml moves here
                                    with the adapter-install split, Фаза 4)

Core must NOT depend on adapters except for the documented transitional
imports tracked by scripts/check_layer_boundaries.py.
"""
