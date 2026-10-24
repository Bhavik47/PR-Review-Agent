from langgraph.graph import StateGraph, START, END
from app.agents.state import AgentState
from app.agents.agent1_static import run_agent1_static
from app.github.client import github_client

def publish_review_node(state: AgentState) -> dict:
    summary = f"### 🤖 Automated PR Review\n{state['static_summary']}"
    github_client.post_pr_review(
        repo_full_name=state["repo_full_name"],
        pr_number=state["pr_number"],
        commit_sha=state["head_sha"],
        summary=summary,
        findings=state["static_findings"],
    )
    return {}

builder = StateGraph(AgentState)
builder.add_node("agent1_static", run_agent1_static)
builder.add_node("publish_review", publish_review_node)

builder.add_edge(START, "agent1_static")
builder.add_edge("agent1_static", "publish_review")
builder.add_edge("publish_review", END)

pr_review_graph = builder.compile()