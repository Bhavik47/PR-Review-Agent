import logging
from langgraph.graph import StateGraph, START, END
from app.agents.state import AgentState
from app.agents.agent1_static import run_agent1_static
from app.agents.agent2_sandbox import run_agent2_sandbox
from app.github.client import github_client

logger = logging.getLogger(__name__)

def aggregate_reviews_node(state: AgentState) -> dict:
    """Aggregates static findings from Agent 1 and empirical sandbox proofs from Agent 2."""
    static_summary = state.get("static_summary") or "No static issues found."
    static_findings = state.get("static_findings") or []
    sandbox_summary = state.get("sandbox_summary") or ""
    sandbox_bugs = state.get("sandbox_bugs") or []

    summary_parts = ["### 🤖 Autonomous PR Review & Sandbox Verification\n"]

    summary_parts.append(f"**Static Review Summary:**\n{static_summary}\n")

    if sandbox_bugs:
        summary_parts.append("### 🧪 ⚠️ Verified Runtime Bugs (Sandbox Proved)\n")
        summary_parts.append(
            "> **The following issues are NOT hallucinations.** They were proven by executing real `pytest` tests inside an isolated Docker sandbox container.\n"
        )
        for idx, bug in enumerate(sandbox_bugs, 1):
            func = bug.get("function_name", "function")
            file_p = bug.get("file_path", "")
            err = bug.get("error_type", "Error")
            inp = bug.get("failing_input", "")
            trace = bug.get("stack_trace", "")
            fix = bug.get("suggested_fix", "")
            test = bug.get("test_code", "")

            summary_parts.append(
                f"#### Bug #{idx}: `{func}` crashed in `{file_p}`\n"
                f"- **Error Type:** `{err}`\n"
                f"- **Failing Input:** `{inp}`\n\n"
                f"**Reproducing Test:**\n```python\n{test}\n```\n\n"
                f"**Stack Trace:**\n```text\n{trace}\n```\n\n"
                f"**Suggested Fix:**\n```python\n{fix}\n```\n"
            )
    elif sandbox_summary:
        summary_parts.append(f"**Sandbox Verification:**\n{sandbox_summary}\n")

    final_summary = "\n".join(summary_parts)

    return {
        "final_summary": final_summary,
        "final_findings": static_findings,
    }

def publish_review_node(state: AgentState) -> dict:
    """Posts the final aggregated review to GitHub."""
    summary = state.get("final_summary") or "Automated review completed."
    findings = state.get("final_findings") or []

    logger.info(
        f"Publishing review to {state['repo_full_name']} PR #{state['pr_number']} "
        f"({len(findings)} inline findings)"
    )

    github_client.post_pr_review(
        repo_full_name=state["repo_full_name"],
        pr_number=state["pr_number"],
        commit_sha=state["head_sha"],
        summary=summary,
        findings=findings,
    )
    return {}

# Build the parallel LangGraph workflow
builder = StateGraph(AgentState)

# Add nodes
builder.add_node("agent1_static", run_agent1_static)
builder.add_node("agent2_sandbox", run_agent2_sandbox)
builder.add_node("aggregator", aggregate_reviews_node)
builder.add_node("publish_review", publish_review_node)

# Parallel Fan-Out from START to both Agent 1 and Agent 2
builder.add_edge(START, "agent1_static")
builder.add_edge(START, "agent2_sandbox")

# Fan-In from both agents into the Aggregator node
builder.add_edge("agent1_static", "aggregator")
builder.add_edge("agent2_sandbox", "aggregator")

# Final publishing step
builder.add_edge("aggregator", "publish_review")
builder.add_edge("publish_review", END)

pr_review_graph = builder.compile()