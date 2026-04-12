#!/usr/bin/env python3
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from typing import Optional

USERNAME = "pandego"
README_PATH = "README.md"
START = "<!-- OSS_START -->"
END = "<!-- OSS_END -->"
OWNED_REPO_OWNERS = {USERNAME}


def gh_get(url: str, token: str, params: Optional[dict] = None):
    if shutil.which("gh"):
        gh_target = url.replace("https://api.github.com/", "")
        cmd = ["gh", "api", gh_target]
        if params:
            for key, value in params.items():
                cmd.extend(["-f", f"{key}={value}"])
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    query = f"?{urllib.parse.urlencode(params or {})}" if params else ""
    req = urllib.request.Request(f"{url}{query}", headers={"Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_merged_prs(token: str, limit: int = 20):
    if shutil.which("gh"):
        cmd = [
            "gh",
            "search",
            "prs",
            "--author",
            USERNAME,
            "--merged",
            "--limit",
            str(min(limit, 100)),
            "--json",
            "repository,number,title,url",
        ]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        items = json.loads(result.stdout)
        normalized = []
        for pr in items:
            repo = (pr.get("repository") or {}).get("nameWithOwner", "")
            normalized.append(
                {
                    "title": pr.get("title", ""),
                    "html_url": pr.get("url", ""),
                    "number": pr.get("number"),
                    "repository_url": f"https://api.github.com/repos/{repo}" if repo else "",
                }
            )
        return normalized

    q = f"is:pr author:{USERNAME} is:merged"
    data = gh_get(
        "https://api.github.com/search/issues",
        token,
        params={"q": q, "sort": "updated", "order": "desc", "per_page": min(limit, 100)},
    )
    return data.get("items", [])


def is_owned_repo(repo_full_name: str) -> bool:
    owner = repo_full_name.split("/", 1)[0].lower() if "/" in repo_full_name else repo_full_name.lower()
    return owner in {name.lower() for name in OWNED_REPO_OWNERS}



def build_section(prs: list[dict]) -> str:
    lines = []
    for pr in prs:
        title = pr.get("title", "")
        url = pr.get("html_url", "")
        number = pr.get("number")
        repo_url = pr.get("repository_url", "")
        repo = repo_url.split("/repos/")[-1] if "/repos/" in repo_url else ""
        if not repo or is_owned_repo(repo):
            continue
        lines.append(f"- [{repo}#{number}]({url}) — {title}")
        if len(lines) >= 10:
            break

    prs_md = "\n".join(lines) if lines else "- _No external merged PRs found yet._"
    updated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""{START}
## 🧩 OSS Contributor Activity (auto-updated)

**Recent merged PRs:**
{prs_md}

_Last updated: {updated}_
{END}"""


def update_readme(section: str):
    with open(README_PATH, "r", encoding="utf-8") as f:
        readme = f.read()

    pattern = re.compile(rf"\n?{re.escape(START)}.*?{re.escape(END)}\n?", re.S)
    readme = pattern.sub("\n", readme)

    insert_before = "## 🔐 About Private Work"
    idx = readme.find(insert_before)
    if idx == -1:
        readme = readme + "\n\n" + section + "\n"
    else:
        readme = readme[:idx].rstrip() + "\n\n" + section + "\n\n" + readme[idx:]

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(readme)


if __name__ == "__main__":
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or ""
    prs = fetch_merged_prs(token, limit=30)
    section = build_section(prs)
    update_readme(section)
    print("README OSS section updated")
