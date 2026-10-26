import os
import sys
import logging
from datetime import datetime
import kopf

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.github.client import github_client
from app.agents.graph import pr_review_graph

logger = logging.getLogger("pr-review-operator")

@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **kwargs):
    """Configures operator settings upon initialization."""
    settings.posting.level = logging.INFO
    logger.info("Initializing Autonomous PR Review Kubernetes Operator (platform.atlassian.dev/v1alpha1)...")

@kopf.on.create("platform.atlassian.dev", "v1alpha1", "prreviewjobs")
def reconcile_pr_review_create(spec, patch, name, namespace, **kwargs):
    """
    Reconciliation loop triggered upon creation of a PRReviewJob Custom Resource.
    
    1. Sets status.phase = 'Running'
    2. Fetches PR diff from GitHub
    3. Runs parallel LangGraph multi-agent analysis (Static + K8s Sandbox)
    4. Reconciles observed state and updates status (phase, bug counts, summary)
    """
    repo = spec.get("repo")
    pr_number = spec.get("prNumber")
    enable_sandbox = spec.get("enableSandbox", True)
    cell_id = spec.get("cellId", "default-cell")

    logger.info(
        f"Reconciling PRReviewJob '{name}' in namespace '{namespace}' "
        f"[Repo: {repo}, PR #{pr_number}, Cell: {cell_id}, Sandbox: {enable_sandbox}]"
    )

    patch.status["phase"] = "Running"
    patch.status["startedAt"] = datetime.utcnow().isoformat()
    patch.status["cellId"] = cell_id

    try:
        # Fetch PR diff
        diff_text = github_client.get_pr_diff(repo, pr_number)
        if not diff_text.strip():
            patch.status["phase"] = "Completed"
            patch.status["staticIssuesCount"] = 0
            patch.status["sandboxBugsCount"] = 0
            patch.status["summary"] = "PR diff is empty; no review required."
            patch.status["completedAt"] = datetime.utcnow().isoformat()
            patch.status["message"] = "Empty diff reconciled successfully."
            return

        # Execute autonomous agent review graph
        state = {
            "repo_full_name": repo,
            "pr_number": pr_number,
            "head_sha": "HEAD",
            "pr_title": f"Kubernetes PRReviewJob {name}",
            "pr_description": f"Triggered via K8s Operator CRD ({namespace}/{name})",
            "diff_text": diff_text,
            "static_summary": "",
            "static_findings": [],
            "sandbox_summary": "",
            "sandbox_bugs": [],
            "final_summary": "",
            "final_findings": [],
        }

        result = pr_review_graph.invoke(state)

        static_count = len(result.get("final_findings", []))
        sandbox_bugs = result.get("sandbox_bugs", [])
        sandbox_count = len(sandbox_bugs)
        final_summary = result.get("final_summary", "Review completed.")

        # Reconcile status
        patch.status["phase"] = "Completed"
        patch.status["staticIssuesCount"] = static_count
        patch.status["sandboxBugsCount"] = sandbox_count
        # Truncate summary to preserve etcd capacity
        patch.status["summary"] = final_summary[:1000]
        patch.status["completedAt"] = datetime.utcnow().isoformat()
        patch.status["message"] = (
            f"Successfully reconciled review: {static_count} static findings, "
            f"{sandbox_count} runtime bugs proven in sandbox."
        )

        logger.info(f"PRReviewJob '{name}' successfully reconciled to phase 'Completed'.")

    except Exception as e:
        logger.error(f"Error during reconciliation of PRReviewJob '{name}': {e}", exc_info=True)
        patch.status["phase"] = "Failed"
        patch.status["message"] = f"Reconciliation error: {str(e)}"
        patch.status["completedAt"] = datetime.utcnow().isoformat()

@kopf.on.delete("platform.atlassian.dev", "v1alpha1", "prreviewjobs")
def reconcile_pr_review_delete(spec, name, namespace, **kwargs):
    """Handles teardown and cleanup when a PRReviewJob resource is deleted."""
    logger.info(f"PRReviewJob '{name}' in namespace '{namespace}' marked for deletion. Reconciling cleanup.")

if __name__ == "__main__":
    kopf.run()
