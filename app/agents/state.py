from typing import TypedDict, List, Optional
from pydantic import BaseModel, Field

class StaticFinding(BaseModel):
    file_path: str = Field(description="Relative file path from the diff")
    line_number: int = Field(description="Line number in the new version of the file (RIGHT side of diff)")
    severity: str = Field(description="CRITICAL or WARNING")
    category: str = Field(description="e.g., Debug Leftover, Commented-Out Guard, Hardcoded Secret, Logic Bug")
    explanation: str = Field(description="Concise explanation of why this is an issue")
    suggested_fix: Optional[str] = Field(default=None, description="Exact replacement line(s) if applicable")

class StaticReviewOutput(BaseModel):
    summary: str = Field(description="Brief 1-2 sentence overview of the PR hygiene and security")
    findings: List[StaticFinding] = Field(default_factory=list)

class AgentState(TypedDict):
    repo_full_name: str
    pr_number: int
    head_sha: str
    pr_title: str
    pr_description: str
    diff_text: str
    static_summary: str
    static_findings: List[dict]