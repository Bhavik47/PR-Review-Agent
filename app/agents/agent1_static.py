from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from app.config import settings
from app.github.client import github_client
from app.agents.state import AgentState, StaticReviewOutput

SYSTEM_PROMPT = """You are Agent 1: Static Hygiene, Security & Intent Reviewer.
Analyze the provided git diff and PR description. Look ONLY for high-signal, actionable issues:
1. Leftover debugging statements (print, console.log, debugger, breakpoint).
2. Dangerous commented-out code (e.g., commented-out auth checks, validation, or dead code blocks).
3. Hardcoded secrets, API keys, tokens, or hardcoded localhost URLs.
4. Obvious logic bugs that contradict the PR title/description or break existing behavior.

Strict Rules:
- `file_path`: MUST be the exact relative file path including extension as shown in the diff header (e.g. 'feature.py', NEVER omit the extension).
- `line_number`: MUST be the exact line number on the new/modified side of the diff (>= 1).
- ONLY report actionable problems or risks. Do NOT output positive compliments or 'no action needed' items.
- If a diff hunk is cut off and you need to see surrounding lines in the file before judging, call `get_file_content`.
- Do NOT nitpick formatting or style."""

def run_agent1_static(state: AgentState) -> dict:
    repo = state["repo_full_name"]
    head_sha = state["head_sha"]

    @tool
    def get_file_content(file_path: str, start_line: int, end_line: int) -> str:
        """Fetches lines from a file in the repository to inspect surrounding context."""
        return github_client.get_file_lines(repo, file_path, head_sha, start_line, end_line)

    llm = ChatOpenAI(
            model=settings.OPENROUTER_MODEL,
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_BASE_URL,
            temperature=0,
            default_headers={
                "HTTP-Referer": "https://github.com/your-username/pr-review-agent",
                "X-Title": "Autonomous PR Reviewer Agent",
            },
        )

    # Step 1: ReAct loop allowing Agent 1 to call `get_file_content` if needed
    react_agent = create_react_agent(llm, tools=[get_file_content])
    user_input = (
        f"PR Title: {state['pr_title']}\n"
        f"PR Description: {state['pr_description']}\n\n"
        f"Git Diff:\n{state['diff_text'][:15000]}"
    )
    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_input)]
    agent_response = react_agent.invoke({"messages": messages})
    final_analysis = agent_response["messages"][-1].content

    # Step 2: Enforce strict Pydantic schema for GitHub API publishing
    structured_llm = llm.with_structured_output(StaticReviewOutput)
    structured_result: StaticReviewOutput = structured_llm.invoke(
        f"Convert the following PR review analysis into the required structured format based on this diff:\n\n"
        f"Diff:\n{state['diff_text'][:10000]}\n\nAnalysis:\n{final_analysis}"
    )

    return {
        "static_summary": structured_result.summary,
        "static_findings": [f.model_dump() for f in structured_result.findings],
    }