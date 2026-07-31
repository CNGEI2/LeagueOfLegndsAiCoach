from unicodedata import normalize


def lookup_key(value: str) -> str:
    """Return the stable cache key for a user-facing Riot identifier."""
    return normalize("NFKC", value.strip()).casefold()
