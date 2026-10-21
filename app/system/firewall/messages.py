"""Terminal messages, shared by Linux and Windows."""


def describe(port: int, word: str, rest: str = "") -> str:
    """Message for the terminal built from the helper's state."""
    if word == "OPEN":
        return f"Firewall: porta {port} aperta solo per la rete locale {rest}, finché il server è acceso."
    if word == "NOFIREWALL":
        return "Firewall: nessuna regola attiva ora; se il firewall si accende, la porta verrà aperta da sola."
    if word == "NONET":
        return "Firewall: nessuna rete locale trovata, porta chiusa (si apre da sola quando torna la rete)."
    if word == "ERROR":
        return f"ATTENZIONE, firewall: {rest}"
    if word == "CLOSED":
        return f"Firewall: porta {port} richiusa."
    return f"Firewall: {word} {rest}".rstrip()
