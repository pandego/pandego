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

PR_URL_RE = re.compile(r"https://github\.com/([^\s/]+/[^\s/]+)/pull/(\d+)")

USERNAME = "pandego"
README_PATH = "README.md"
START = "<!-- OSS_START -->"
END = "<!-- OSS_END -->"
OWNED_REPO_OWNERS = {USERNAME}
BOT_LANDED_REPOS = {"pytorch/pytorch"}
BOT_LANDED_LABEL = "Merged"


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


def is_owned_repo(repo_full_name: str) -> bool:
    owner = repo_full_name.split("/", 1)[0].lower() if "/" in repo_full_name else repo_full_name.lower()
    return owner in {name.lower() for name in OWNED_REPO_OWNERS}


def pr_repo_name(pr: dict) -> str:
    repo_url = pr.get("repository_url", "")
    return repo_url.split("/repos/")[-1] if "/repos/" in repo_url else ""


def normalize_search_pr(pr: dict, acceptance: str = "merged") -> dict:
    repo = (pr.get("repository") or {}).get("nameWithOwner", "")
    return {
        "title": pr.get("title", ""),
        "html_url": pr.get("url", ""),
        "number": pr.get("number"),
        "repository_url": f"https://api.github.com/repos/{repo}" if repo else "",
        "sort_at": pr.get("closedAt") or pr.get("updatedAt") or "",
        "acceptance": acceptance,
    }


def dedupe_prs(prs: list[dict]) -> list[dict]:
    deduped: dict[tuple[str, object], dict] = {}
    for pr in prs:
        key = (pr_repo_name(pr), pr.get("number"))
        if key not in deduped or pr.get("sort_at", "") > deduped[key].get("sort_at", ""):
            deduped[key] = pr
    return sorted(deduped.values(), key=lambda pr: pr.get("sort_at", ""), reverse=True)


def fetch_merged_prs(token: str, limit: int = 1000) -> list[dict]:
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
            "repository,number,title,url,closedAt,updatedAt",
            "--",
            f"-user:{USERNAME}",
        ]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return [normalize_search_pr(pr) for pr in json.loads(result.stdout)]

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
        for pr in page_items:
            normalized = dict(pr)
            normalized["sort_at"] = pr.get("closed_at") or pr.get("updated_at") or ""
            normalized.setdefault("acceptance", "merged")
            items.append(normalized)
        if len(page_items) < per_page or len(items) >= limit:
            break
    return items[:limit]


def fetch_label_bot_landed_prs(token: str) -> list[dict]:
    """Find PRs that project merge bots close with an accepted/merged label.

    PyTorch can land a PR through pytorchmergebot, label it "Merged", reference
    the landing commit, and close it without GitHub setting merged=true.
    """
    if shutil.which("gh"):
        normalized = []
        for repo in sorted(BOT_LANDED_REPOS):
            cmd = [
                "gh",
                "search",
                "prs",
                "--repo",
                repo,
                "--author",
                USERNAME,
                "--state",
                "closed",
                "--label",
                BOT_LANDED_LABEL,
                "--sort",
                "updated",
                "--order",
                "desc",
                "--limit",
                "100",
                "--json",
                "repository,number,title,url,closedAt,updatedAt",
            ]
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            normalized.extend(normalize_search_pr(pr, acceptance="bot_landed") for pr in json.loads(result.stdout))
        return normalized

    items = []
    for repo in sorted(BOT_LANDED_REPOS):
        data = gh_get(
            "https://api.github.com/search/issues",
            token,
            params={
                "q": f"repo:{repo} is:pr author:{USERNAME} is:closed label:{BOT_LANDED_LABEL}",
                "sort": "updated",
                "order": "desc",
                "per_page": 100,
            },
        )
        for pr in data.get("items", []):
            normalized = dict(pr)
            normalized["repository_url"] = f"https://api.github.com/repos/{repo}"
            normalized["sort_at"] = pr.get("closed_at") or pr.get("updated_at") or ""
            normalized["acceptance"] = "bot_landed"
            items.append(normalized)
    return items


def fetch_commit_bot_landed_prs(limit: int = 100) -> list[dict]:
    """Find authored commits whose message links back to a resolved PR."""
    if not shutil.which("gh"):
        return []

    cmd = [
        "gh",
        "search",
        "commits",
        "--author",
        USERNAME,
        "--sort",
        "committer-date",
        "--order",
        "desc",
        "--limit",
        str(min(limit, 100)),
        "--json",
        "sha,url,commit,repository,author",
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        return []

    normalized = []
    for item in json.loads(result.stdout):
        if (item.get("author") or {}).get("login") != USERNAME:
            continue

        commit = item.get("commit") or {}
        message = commit.get("message", "")
        match = PR_URL_RE.search(message)
        if not match or "Pull Request resolved:" not in message:
            continue

        repo, number = match.groups()
        if is_owned_repo(repo):
            continue

        title = message.splitlines()[0].strip()
        title = re.sub(rf"\s*\(#{number}\)$", "", title)
        normalized.append(
            {
                "title": title,
                "html_url": f"https://github.com/{repo}/pull/{number}",
                "number": int(number),
                "repository_url": f"https://api.github.com/repos/{repo}",
                "sort_at": (commit.get("committer") or {}).get("date", ""),
                "acceptance": "bot_landed",
            }
        )

    return normalized


def fetch_contribution_prs(token: str, limit: int = 1000):
    prs = []
    prs.extend(fetch_label_bot_landed_prs(token))
    prs.extend(fetch_commit_bot_landed_prs())
    prs.extend(fetch_merged_prs(token, limit=limit))
    return enrich_repository_stars(dedupe_prs(prs), token)


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


def accepted_pr_filter_url(repo_full_name: str, bot_landed: bool = False) -> str:
    if bot_landed:
        query = urllib.parse.urlencode({"q": f"is:pr is:closed label:{BOT_LANDED_LABEL} author:{USERNAME}"})
    else:
        query = urllib.parse.urlencode({"q": f"is:pr is:merged author:{USERNAME}"})
    return f"https://github.com/{repo_full_name}/pulls?{query}"


def merged_pr_filter_url(repo_full_name: str) -> str:
    return accepted_pr_filter_url(repo_full_name)


def external_prs(prs: list[dict]) -> list[dict]:
    return [pr for pr in prs if pr_repo_name(pr) and not is_owned_repo(pr_repo_name(pr))]


def build_project_lines(prs: list[dict]) -> list[str]:
    projects: dict[str, dict[str, object]] = {}
    for position, pr in enumerate(prs):
        repo = pr_repo_name(pr)
        if not repo or is_owned_repo(repo):
            continue
        project = projects.setdefault(repo, {"count": 0, "first_seen": position, "stars": 0, "bot_landed": False})
        project["count"] = int(project["count"]) + 1
        project["stars"] = max(int(project["stars"]), pr_repository_stars(pr))
        project["bot_landed"] = bool(project["bot_landed"]) or pr.get("acceptance") == "bot_landed"

    sorted_projects = sorted(
        projects.items(),
        key=lambda item: (-int(item[1]["stars"]), -int(item[1]["count"]), int(item[1]["first_seen"]), item[0].lower()),
    )
    lines = []
    for repo, data in sorted_projects:
        stars = int(data["stars"])
        url = accepted_pr_filter_url(repo, bot_landed=bool(data["bot_landed"]))
        lines.append(f"- [{repo}]({url}) ({format_stars(stars)})")
    return lines


def build_recent_pr_lines(prs: list[dict], limit: int = 10) -> list[str]:
    lines = []
    for pr in external_prs(prs):
        title = pr.get("title", "")
        url = pr.get("html_url", "")
        number = pr.get("number")
        repo = pr_repo_name(pr)
        lines.append(f"- [{repo}#{number}]({url}) - {title}")
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
    prs = fetch_contribution_prs(token, limit=1000)
    section = build_section(prs)
    update_readme(section)
    print("README OSS section updated")
