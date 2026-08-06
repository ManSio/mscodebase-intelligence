"""Встроенные tree-sitter tags.scm query-файлы (vendored из upstream).

Каждая поддиректория (<lang>/tags.scm) — определения для одного языка,
загружаемые CodeParser._load_tags_query() для extract_definitions_scm().
Наличие __init__.py делает пакет discoverable для setuptools package-data,
иначе .scm файлы выпадают из wheel-сборки.
"""
