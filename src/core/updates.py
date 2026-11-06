"""Checks GitHub Releases for a newer version (only when a repo is configured)."""
import json
import re
import urllib.request


def _parts(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3]) or (0,)


def check_for_update(repo: str, current: str) -> dict:
    repo = (repo or "").strip().strip("/")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        return {"available": False, "error": "No release page set. Add your GitHub repo (owner/name) in Settings › About."}
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WordPulse", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"available": False, "error": f"Couldn't reach GitHub ({e.__class__.__name__})."}
    latest = data.get("tag_name") or data.get("name") or ""
    return {"available": _parts(latest) > _parts(current), "latest": latest.lstrip("v"),
            "url": data.get("html_url", f"https://github.com/{repo}/releases")}
