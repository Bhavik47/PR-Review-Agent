import logging
from rq import get_current_job
from app.github.client import github_client
from app.agents.graph import pr_review_graph
from app.db.session import SessionLocal
from app.db.models import PRReview
from app.queue.redis_conn import is_job_superseded

logger = logging.getLogger(__name__)

def process_pr_review_job(
    repo_full_name: str,
    pr_number: int,
    base_sha: str,
    head_sha: str,
    pr_title: str,
    pr_description: str,
):
    current_job = get_current_job()
    current_job_id = current_job.id if current_job else None

    # Step 1: Early rapid-push cancellation check
    if current_job_id and is_job_superseded(repo_full_name, pr_number, current_job_id):
        logger.info(
            f"[{repo_full_name}#{pr_number}] Job {current_job_id} already superseded by a newer push. Exiting."
        )
        return

    db = SessionLocal()
    review_record = None
    try:
        review_record = (
            db.query(PRReview)
            .filter_by(repo_full_name=repo_full_name, pr_number=pr_number)
            .first()
        )

        last_completed = None
        if not review_record:
            review_record = PRReview(
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                base_sha=base_sha,
                last_completed_sha=None,
                status="RUNNING",
            )
            db.add(review_record)
            db.commit()
        else:
            # Check if this exact head commit was already reviewed
            if review_record.last_completed_sha == head_sha and review_record.status == "COMPLETED":
                logger.info(
                    f"[{repo_full_name}#{pr_number}] Head {head_sha[:7]} has already been reviewed. Skipping."
                )
                return

            last_completed = review_record.last_completed_sha
            review_record.status = "RUNNING"
            db.commit()

        # Step 2: Incremental Diff Calculation
        diff_text = ""
        if last_completed and last_completed != head_sha:
            try:
                diff_text = github_client.get_compare_diff(
                    repo_full_name=repo_full_name,
                    base_sha=last_completed,
                    head_sha=head_sha,
                )
                logger.info(
                    f"[{repo_full_name}#{pr_number}] Incremental diff calculated between {last_completed[:7]}...{head_sha[:7]} ({len(diff_text)} chars)"
                )
            except Exception as e:
                logger.warning(
                    f"[{repo_full_name}#{pr_number}] Compare diff failed ({e}). Falling back to full PR diff."
                )
                diff_text = ""

        # Fallback to full diff if no last_completed_sha or compare failed
        if not diff_text:
            diff_text = github_client.get_pr_diff(repo_full_name, pr_number)
            logger.info(
                f"[{repo_full_name}#{pr_number}] Full PR diff fetched ({len(diff_text)} chars)"
            )

        if not diff_text.strip():
            logger.info(f"[{repo_full_name}#{pr_number}] Diff is empty, nothing to review.")
            review_record.last_completed_sha = head_sha
            review_record.status = "COMPLETED"
            db.commit()
            return

        # Step 3: Mid-execution check before invoking expensive LLM
        if current_job_id and is_job_superseded(repo_full_name, pr_number, current_job_id):
            logger.info(
                f"[{repo_full_name}#{pr_number}] Job {current_job_id} superseded before LLM invocation. Aborting."
            )
            return

        # Step 4: Invoke review graph
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

        # Step 5: Final check before marking as COMPLETED
        if current_job_id and is_job_superseded(repo_full_name, pr_number, current_job_id):
            logger.info(
                f"[{repo_full_name}#{pr_number}] Job {current_job_id} superseded before DB update. Skipping state save."
            )
            return

        review_record.last_completed_sha = head_sha
        review_record.status = "COMPLETED"
        db.commit()
        logger.info(
            f"[{repo_full_name}#{pr_number}] Successfully completed review for head {head_sha[:7]}."
        )

    except Exception as e:
        if review_record is not None:
            review_record.status = "FAILED"
            try:
                db.commit()
            except Exception:
                pass
        raise e
    finally:
        db.close()