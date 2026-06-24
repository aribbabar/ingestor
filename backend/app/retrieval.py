from __future__ import annotations

from app.db import db
from app.models import SearchMode

DEFAULT_SEARCH_MODE_KEY = "default_search_mode"


def get_default_search_mode() -> SearchMode:
    value = db.get_app_setting(DEFAULT_SEARCH_MODE_KEY)
    if not value:
        return SearchMode.HYBRID
    try:
        return SearchMode(value)
    except ValueError:
        return SearchMode.HYBRID


def set_default_search_mode(mode: SearchMode) -> None:
    db.set_app_setting(DEFAULT_SEARCH_MODE_KEY, mode.value)


def reset_default_search_mode() -> None:
    db.delete_app_settings([DEFAULT_SEARCH_MODE_KEY])
