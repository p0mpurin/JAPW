"""Pinterest integration: cookie session, direct resource-API client, and paginated feeds."""

from japw.pinterest.errors import PinterestAuthExpired, PinterestSessionError
from japw.pinterest.feeds import (
    board_pins,
    for_you,
    home,
    my_boards,
    prefetch_search,
    related,
    search,
    shutdown,
    suggestions,
    warm_up,
)
from japw.images import canonical_key, dedupe_pinimg_urls
from japw.pinterest.parse import set_content_filters
from japw.pinterest.session import (
    clear_session,
    get_last_login_error,
    get_storage_path,
    has_session,
    is_login_in_progress,
    run_cookie_sync_thread_entry,
    try_begin_sync,
)

__all__ = [
    "PinterestAuthExpired", "PinterestSessionError",
    "board_pins", "for_you", "home", "my_boards", "prefetch_search", "related", "search", "shutdown",
    "suggestions", "warm_up",
    "canonical_key", "dedupe_pinimg_urls", "set_content_filters",
    "clear_session", "get_last_login_error", "get_storage_path", "has_session",
    "is_login_in_progress", "run_cookie_sync_thread_entry", "try_begin_sync",
]
