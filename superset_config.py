"""Superset configuration overrides for the Prometheus demo image."""

import os

# Required: Superset refuses to start with the default insecure key.
SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY") or "dev-insecure-key-change-me"

# The Prometheus server lives on a private IP and speaks plain HTTP.
# Superset's SSRF protection would block it otherwise.
PREVENT_UNSAFE_DB_CONNECTIONS = False
PREVENT_UNSAFE_DEFAULT_URLS_ON_DATASET = False

# Lab image: keep it light.
SUPERSET_LOAD_EXAMPLES = False

# Rolling relative time windows ("Last hour" etc. end at now, not midnight).
DEFAULT_RELATIVE_START_TIME = "now"
DEFAULT_RELATIVE_END_TIME = "now"

# 中文界面（2026-08-20 用户要求）
BABEL_DEFAULT_LOCALE = "zh"
LANGUAGES = {
    "en": {"flag": "us", "name": "English"},
    "zh": {"flag": "cn", "name": "简体中文"},
}
