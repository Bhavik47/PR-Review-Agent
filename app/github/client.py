import httpx
from typing import List, Dict, Any
from app.config import settings

class GitHubClient:
    def __init__(self):
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def get_pr_diff(self, repo_full_name: str, pr_number: int) -> str:
        """Fetches the raw unified git diff for the Pull Request."""
        url = f"{self.base_url}/repos/{repo_full_name}/pulls/{pr_number}"
        headers = {**self.headers, "Accept": "application/vnd.github.v3.diff"}
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text

    def get_file_lines(self, repo_full_name: str, file_path: str, ref: str, start_line: int, end_line: int) -> str:
        """Fetches specific line ranges of a file at commit `ref` for Agent 1 context."""
        url = f"{self.base_url}/repos/{repo_full_name}/contents/{file_path}?ref={ref}"
        headers = {**self.headers, "Accept": "application/vnd.github.v3.raw"}
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code != 200:
                return f"Could not fetch {file_path} (HTTP {resp.status_code})"
            lines = resp.text.splitlines()
            start = max(1, start_line) - 1
            end = min(len(lines), end_line)
            numbered = [f"{i+1}: {lines[i]}" for i in range(start, end)]
            return "\n".join(numbered)

    def post_pr_review(
        self,
        repo_full_name: str,
        pr_number: int,
        commit_sha: str,
        summary: str,
        findings: List[Dict[str, Any]],
    ):
        """Posts a unified Pull Request Review with inline comments."""
        url = f"{self.base_url}/repos/{repo_full_name}/pulls/{pr_number}/reviews"
        comments = []
        for f in findings:
            body = f"**[{f['severity']}] {f['category']}**\n\n{f['explanation']}"
            if f.get("suggested_fix"):
                body += f"\n\n```suggestion\n{f['suggested_fix']}\n```"
            comments.append({
                "path": f["file_path"],
                "line": f["line_number"],
                "side": "RIGHT",
                "body": body,
            })

        payload = {
            "commit_id": commit_sha,
            "body": summary,
            "event": "COMMENT",
            "comments": comments,
        }

        with httpx.Client(timeout=20.0) as client:
            resp = client.post(url, headers=self.headers, json=payload)
            # Fallback: if an inline line number is outside the diff hunk, post summary comment only
            if resp.status_code == 422 and comments:
                fallback_body = summary + "\n\n### Findings:\n" + "\n".join(
                    [f"- **{c['path']}** (Line {c['line']}): {c['body']}" for c in comments]
                )
                client.post(
                    url,
                    headers=self.headers,
                    json={"commit_id": commit_sha, "body": fallback_body, "event": "COMMENT"},
                )
            else:
                resp.raise_for_status()

github_client = GitHubClient()