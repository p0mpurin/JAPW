class PinterestSessionError(Exception):
    """No saved session, a cookie import failure, or a Pinterest API error."""


class PinterestAuthExpired(PinterestSessionError):
    """Pinterest rejected the saved cookies — the user must sync again."""

    def __init__(self, msg: str = "Your Pinterest session has expired. Sync from your browser again.") -> None:
        super().__init__(msg)
