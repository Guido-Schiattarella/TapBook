"""Update check: is there a newer TapBook Release on GitHub?

A single HTTPS request to GitHub's public API (latest Release of the
repository, drafts and pre-releases excluded). It sends no user data and
downloads or runs nothing: it only returns version, notes and Release page,
which the panel shows; the user installs the update with the installer and the
password. The answer is treated as untrusted: version name, link and text are
checked before being shown.
"""
import json
import re
import ssl
import urllib.error
import urllib.request

from .. import __repository__, __version__

API = "https://api.github.com"
TIMEOUT = 6
MAX_BYTES = 512 * 1024
MAX_NOTES = 600
REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")


def parse_version(text: str):
    """"v1.2.3" or "1.2" → (1, 2, 3) / (1, 2, 0); None if it is not a version."""
    m = VERSION_RE.match((text or "").strip())
    return tuple(int(g or 0) for g in m.groups()) if m else None


def repository(config) -> str:
    """Repository to check: the one in config.ini, otherwise the app's own."""
    repo = (config.update_repository or __repository__).strip()
    return repo if REPO_RE.match(repo) else ""


def check(config, api: str = API) -> dict | None:
    """Latest Release if newer than the installed version, otherwise None (also
    when the check is off, the repository is not set or the network does not
    answer: a failed check must never get in the way)."""
    repo = repository(config) if config.update_check else ""
    current = parse_version(__version__)
    if not repo or not current:
        return None
    request = urllib.request.Request(
        f"{api}/repos/{repo}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"TapBook/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=ssl.create_default_context()) as resp:
            data = json.loads(resp.read(MAX_BYTES).decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name") if isinstance(data.get("tag_name"), str) else ""
    latest = parse_version(tag)
    if not latest or latest <= current:
        return None
    # The button only ever opens the Release page of that repository on GitHub.
    url = data.get("html_url") if isinstance(data.get("html_url"), str) else ""
    if not url.startswith(f"https://github.com/{repo}/releases/"):
        url = f"https://github.com/{repo}/releases/latest"
    notes = data.get("body") if isinstance(data.get("body"), str) else ""
    notes = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", notes).strip()
    if len(notes) > MAX_NOTES:
        notes = notes[:MAX_NOTES].rsplit(" ", 1)[0] + "…"
    return {"version": ".".join(map(str, latest)), "url": url, "notes": notes, "current": __version__}
