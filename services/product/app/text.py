import unicodedata


def normalize(text: str) -> str:
    """Lowercase and strip Vietnamese diacritics so 'sac' matches 'Sạc'."""
    text = text.lower().replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
