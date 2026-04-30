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


def fetch_merged_prs(token: str, limit: int = 1000):
    if shutil.which("gh"):
        cmd = [
            "gh",
            "search",
            "prs",
            "--author",
            USERNAME,
            "--merged",
            "--sort",
            "updated",
            "--order",
            "desc",
            "--limit",
            str(limit),
            "--json",
            "repository,number,title,url",
            "--",
            f"-user:{USERNAME}",
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
        return enrich_repository_stars(normalized, token)

    q = f"is:pr author:{USERNAME} is:merged -user:{USERNAME}"
    items = []
    per_page = 100
    for page in range(1, (limit + per_page - 1) // per_page + 1):
        data = gh_get(
            "https://api.github.com/search/issues",
            token,
            params={
                "q": q,
                "sort": "updated",
                "order": "desc",
                "per_page": min(per_page, limit - len(items)),
                "page": page,
            },
        )
        page_items = data.get("items", [])
        items.extend(page_items)
        if len(page_items) < per_page or len(items) >= limit:
            break
    return enrich_repository_stars(items[:limit], token)


def is_owned_repo(repo_full_name: str) -> bool:
    owner = repo_full_name.split("/", 1)[0].lower() if "/" in repo_full_name else repo_full_name.lower()
    return owner in {name.lower() for name in OWNED_REPO_OWNERS}


def pr_repo_name(pr: dict) -> str:
    repo_url = pr.get("repository_url", "")
    return repo_url.split("/repos/")[-1] if "/repos/" in repo_url else ""


def enrich_repository_stars(prs: list[dict], token: str) -> list[dict]:
    stars_by_repo: dict[str, int] = {}
    for pr in prs:
        repo = pr_repo_name(pr)
        if not repo or repo in stars_by_repo:
            continue
        try:
            repo_data = gh_get(f"https://api.github.com/repos/{repo}", token)
            stars_by_repo[repo] = int(repo_data.get("stargazers_count") or 0)
        except Exception:
            stars_by_repo[repo] = 0

    enriched = []
    for pr in prs:
        repo = pr_repo_name(pr)
        enriched_pr = dict(pr)
        enriched_pr.setdefault("repository_stars", stars_by_repo.get(repo, 0))
        enriched.append(enriched_pr)
    return enriched


def pr_repository_stars(pr: dict) -> int:
    return int(pr.get("repository_stars") or 0)


def format_stars(stars: int) -> str:
    if stars == 1:
        return "1 star"
    return f"{stars:,} stars"


def merged_pr_filter_url(repo_full_name: str) -> str:
    query = urllib.parse.urlencode({"q": f"is:pr is:merged author:{USERNAME}"})
    return f"https://github.com/{repo_full_name}/pulls?{query}"


def external_prs(prs: list[dict]) -> list[dict]:
    return [pr for pr in prs if pr_repo_name(pr) and not is_owned_repo(pr_repo_name(pr))]


def build_project_lines(prs: list[dict]) -> list[str]:
    projects: dict[str, dict[str, object]] = {}
    for position, pr in enumerate(prs):
        repo = pr_repo_name(pr)
        if not repo or is_owned_repo(repo):
            continue
        project = projects.setdefault(repo, {"count": 0, "first_seen": position, "stars": 0})
        project["count"] = int(project["count"]) + 1
        project["stars"] = max(int(project["stars"]), pr_repository_stars(pr))

    sorted_projects = sorted(
        projects.items(),
        key=lambda item: (-int(item[1]["stars"]), -int(item[1]["count"]), int(item[1]["first_seen"]), item[0].lower()),
    )
    lines = []
    for repo, data in sorted_projects:
        count = int(data["count"])
        stars = int(data["stars"])
        plural = "PR" if count == 1 else "PRs"
        lines.append(f"- [{repo}]({merged_pr_filter_url(repo)}) — {count} merged {plural}, {format_stars(stars)}")
    return lines


def build_recent_pr_lines(prs: list[dict], limit: int = 10) -> list[str]:
    lines = []
    for pr in external_prs(prs):
        title = pr.get("title", "")
        url = pr.get("html_url", "")
        number = pr.get("number")
        repo = pr_repo_name(pr)
        lines.append(f"- [{repo}#{number}]({url}) — {title}")
        if len(lines) >= limit:
            break
    return lines


def build_section(prs: list[dict], updated_at: Optional[str] = None) -> str:
    project_lines = build_project_lines(prs)
    projects_md = "\n".join(project_lines) if project_lines else "- _No external merged PR projects found yet._"

    recent_lines = build_recent_pr_lines(prs, limit=10)
    recent_md = "\n".join(recent_lines) if recent_lines else "- _No recent external merged PRs found yet._"

    updated = updated_at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""{START}
## 🧩 OSS Contributor Activity (auto-updated)

**Projects contributed to:**
{projects_md}

**Latest merged PRs:**
{recent_md}

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
    prs = fetch_merged_prs(token, limit=1000)
    section = build_section(prs)
    update_readme(section)
    print("README OSS section updated")
