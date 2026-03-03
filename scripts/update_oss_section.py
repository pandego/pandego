#!/usr/bin/env python3
import datetime as dt
import os
import re
import requests

USERNAME = "pandego"
README_PATH = "README.md"
START = "<!-- OSS_START -->"
END = "<!-- OSS_END -->"


def gh_get(url: str, token: str, params: dict | None = None):
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_merged_prs(token: str, limit: int = 20):
    q = f"is:pr author:{USERNAME} is:merged"
    data = gh_get(
        "https://api.github.com/search/issues",
        token,
        params={"q": q, "sort": "updated", "order": "desc", "per_page": min(limit, 100)},
    )
    return data.get("items", [])


def build_section(prs: list[dict]) -> str:
    repos = []
    lines = []
    for pr in prs[:8]:
        title = pr.get("title", "")
        url = pr.get("html_url", "")
        number = pr.get("number")
        repo_url = pr.get("repository_url", "")
        repo = repo_url.split("/repos/")[-1] if "/repos/" in repo_url else ""
        if repo and repo not in repos:
            repos.append(repo)
        lines.append(f"- [{repo}#{number}]({url}) — {title}")

    repos_md = ", ".join(f"`{r}`" for r in repos[:12]) if repos else "_Updating..._"
    prs_md = "\n".join(lines) if lines else "- _No merged PRs found yet._"
    updated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""{START}
## 🧩 OSS Contributor Activity (auto-updated)

**Active repos:** {repos_md}

**Recent merged PRs:**
{prs_md}

_Last updated: {updated}_
{END}"""


def update_readme(section: str):
    with open(README_PATH, "r", encoding="utf-8") as f:
        readme = f.read()

    pattern = re.compile(rf"{re.escape(START)}.*?{re.escape(END)}", re.S)
    if pattern.search(readme):
        readme = pattern.sub(section, readme)
    else:
        insert_after = "## 🛠️ Tech Stack"
        idx = readme.find(insert_after)
        if idx == -1:
            readme = readme + "\n\n" + section + "\n"
        else:
            readme = readme[:idx] + section + "\n\n" + readme[idx:]

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(readme)


if __name__ == "__main__":
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or ""
    prs = fetch_merged_prs(token, limit=30)
    section = build_section(prs)
    update_readme(section)
    print("README OSS section updated")
