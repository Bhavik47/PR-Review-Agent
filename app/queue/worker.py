from app.github.client import github_client
from app.agents.graph import pr_review_graph
from app.db.session import SessionLocal
from app.db.models import PRReview

def process_pr_review_job(
    repo_full_name: str,
    pr_number: int,
    base_sha: str,
    head_sha: str,
    pr_title: str,
    pr_description: str,
):
    db = SessionLocal()
    review_record = None  # Guard: initialise before try so except block is always safe
    try:
        review_record = (
            db.query(PRReview)
            .filter_by(repo_full_name=repo_full_name, pr_number=pr_number)
            .first()
        )
        if not review_record:
            review_record = PRReview(
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                base_sha=base_sha,
                status="RUNNING",
            )
            db.add(review_record)
        else:
            review_record.status = "RUNNING"
        db.commit()

        # Fetch diff & invoke LangGraph
        diff_text = github_client.get_pr_diff(repo_full_name, pr_number)
        pr_review_graph.invoke({
            "repo_full_name": repo_full_name,
            "pr_number": pr_number,
            "head_sha": head_sha,
            "pr_title": pr_title,
            "pr_description": pr_description or "",
            "diff_text": diff_text,
            "static_summary": "",
            "static_findings": [],
        })

        review_record.last_completed_sha = head_sha
        review_record.status = "COMPLETED"
        db.commit()
    except Exception as e:
        if review_record is not None:
            review_record.status = "FAILED"
            db.commit()
        raise e
    finally:
        db.close()