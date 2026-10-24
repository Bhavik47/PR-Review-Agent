from typing import TypedDict, List, Optional
from pydantic import BaseModel, Field

# --- Agent 1: Static Review Models ---

class StaticFinding(BaseModel):
    file_path: str = Field(description="Exact relative file path with extension from the diff, e.g. 'feature.py'")
    line_number: int = Field(description="Line number in the new version of the file (RIGHT side of diff, >= 1). Use 0 ONLY for general comments.")
    severity: str = Field(description="CRITICAL, WARNING, or LOW")
    category: str = Field(description="e.g., Debug Leftover, Commented-Out Guard, Hardcoded Secret, Logic Bug")
    suggested_fix: Optional[str] = Field(
        default=None,
        description=(
            "Exact, syntactically valid code line(s) to directly replace the line in GitHub's suggestion box. "
            "MUST BE PURE CODE ONLY (e.g. 'return total / len(discounts) if discounts else 0.0'). "
            "NEVER write English prose, explanations, or instructions like 'Restore the logic' or 'Return 0.0 or raise error'. "
            "If a clean 1-to-1 code replacement is not possible, set to null."
        ),
    )

class StaticReviewOutput(BaseModel):
    summary: str = Field(description="Brief 1-2 sentence overview of the PR static hygiene and security")
    findings: List[StaticFinding] = Field(default_factory=list)


# --- Agent 2: Dynamic Sandbox Bug Proof Models ---

class SandboxBugProof(BaseModel):
    file_path: str = Field(description="Relative path of the file containing the bug, e.g. 'feature.py'")
    function_name: str = Field(description="Name of the function that failed or crashed")
    failing_input: str = Field(description="Exact arguments or input values that triggered the failure")
    error_type: str = Field(description="Type of exception or error, e.g. ZeroDivisionError, TypeError, KeyError, AssertionError")
    stack_trace: str = Field(description="Short, relevant snippet of the traceback or failure output from the sandbox")
    suggested_fix: str = Field(description="Proposed code patch to safely handle this edge case")
    test_code: str = Field(description="The pytest test function code that successfully reproduced the crash")

class SandboxReviewOutput(BaseModel):
    summary: str = Field(description="Overview of sandbox test execution and verification results")
    bugs_found: List[SandboxBugProof] = Field(default_factory=list)


# --- Global LangGraph State ---

class AgentState(TypedDict):
    repo_full_name: str
    pr_number: int
    head_sha: str
    pr_title: str
    pr_description: str
    diff_text: str
    
    # Agent 1 (Static) outputs
    static_summary: str
    static_findings: List[dict]
    
    # Agent 2 (Sandbox) outputs
    sandbox_summary: str
    sandbox_bugs: List[dict]
    
    # Aggregator outputs (merged review)
    final_summary: str
    final_findings: List[dict]