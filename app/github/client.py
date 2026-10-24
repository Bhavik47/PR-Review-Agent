import ast
import httpx
from typing import List, Dict, Any
from app.config import settings

def is_valid_code_replacement(snippet: str) -> bool:
    """Checks if a suggested fix is syntactically valid code that can be applied in a GitHub suggestion block."""
    if not snippet or not snippet.strip():
        return False
    clean = snippet.strip()
    if clean.startswith("```") and clean.endswith("```"):
        lines = clean.splitlines()
        clean = "\n".join(lines[1:-1]).strip()
    try:
        ast.parse(clean)
        return True
    except SyntaxError:
        return False

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

    def get_compare_diff(self, repo_full_name: str, base_sha: str, head_sha: str) -> str:
        """Fetches the raw git diff between two commit SHAs using GitHub Compare API."""
        url = f"{self.base_url}/repos/{repo_full_name}/compare/{base_sha}...{head_sha}"
        headers = {**self.headers, "Accept": "application/vnd.github.v3.diff"}
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text

    def get_file_raw(self, repo_full_name: str, file_path: str, ref: str) -> str:
        """Fetches the entire raw file content from GitHub at commit `ref`."""
        url = f"{self.base_url}/repos/{repo_full_name}/contents/{file_path}?ref={ref}"
        headers = {**self.headers, "Accept": "application/vnd.github.v3.raw"}
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code == 200:
                return resp.text
            return ""

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
        inline_comments = []
        general_notes = []

        for f in findings:
            path = (f.get("file_path") or "").strip()
            line = f.get("line_number", 0)
            fix = f.get("suggested_fix")
            if fix:
                fix_clean = fix.strip()
                if fix_clean.startswith("```") and fix_clean.endswith("```"):
                    lines = fix_clean.splitlines()
                    fix_clean = "\n".join(lines[1:-1]).strip()

                if is_valid_code_replacement(fix_clean):
                    body += f"\n\n```suggestion\n{fix_clean}\n```"
                else:
                    body += f"\n\n**Suggested Approach:**\n{fix_clean}"

            # Only valid positive line numbers on a real path can be inline comments
            if line > 0 and path:
                inline_comments.append({
                    "path": path,
                    "line": line,
                    "side": "RIGHT",
                    "body": body,
                })
            else:
                general_notes.append(f"- **{path or 'PR General'}**: {body}")

        full_summary = summary
        if general_notes:
            full_summary += "\n\n### General Findings:\n" + "\n".join(general_notes)

        payload = {
            "commit_id": commit_sha,
            "body": full_summary,
            "event": "COMMENT",
            "comments": inline_comments,
        }

        with httpx.Client(timeout=20.0) as client:
            resp = client.post(url, headers=self.headers, json=payload)
            # Fallback: if GitHub rejects an inline comment line (422), post summary with all findings
            if resp.status_code == 422 and inline_comments:
                fallback_body = full_summary + "\n\n### Findings:\n" + "\n".join(
                    [f"- **{c['path']}** (Line {c['line']}): {c['body']}" for c in inline_comments]
                )
                fallback_resp = client.post(
                    url,
                    headers=self.headers,
                    json={"commit_id": commit_sha, "body": fallback_body, "event": "COMMENT"},
                )
                fallback_resp.raise_for_status()
            else:
                resp.raise_for_status()


github_client = GitHubClient()