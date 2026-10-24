import redis
from rq import Queue
from app.config import settings

redis_client = redis.from_url(settings.REDIS_URL)
pr_queue = Queue("pr_reviews", connection=redis_client)

def is_duplicate_webhook(delivery_id: str) -> bool:
    """Returns True if we already processed this GitHub delivery UUID."""
    key = f"webhook_delivery:{delivery_id}"
    # NX = Only set if key does not exist; EX = expire after 1 hour
    was_set = redis_client.set(key, "1", nx=True, ex=3600)
    return not bool(was_set)

def set_active_job(repo_full_name: str, pr_number: int, job_id: str):
    """Tracks the active in-flight RQ job ID for a specific PR."""
    key = f"active_job:{repo_full_name}:{pr_number}"
    redis_client.set(key, job_id, ex=7200)

def get_active_job(repo_full_name: str, pr_number: int) -> str | None:
    """Returns the active job ID for a PR if one exists."""
    key = f"active_job:{repo_full_name}:{pr_number}"
    val = redis_client.get(key)
    return val.decode("utf-8") if val else None

def is_job_superseded(repo_full_name: str, pr_number: int, current_job_id: str) -> bool:
    """Checks if the currently executing job has been superseded by a newer push."""
    active_id = get_active_job(repo_full_name, pr_number)
    return bool(active_id and active_id != current_job_id)

def cancel_active_job(repo_full_name: str, pr_number: int) -> bool:
    """Cancels any in-flight or queued RQ job for this PR when a new commit is pushed."""
    active_id = get_active_job(repo_full_name, pr_number)
    if not active_id:
        return False
    try:
        from rq.job import Job
        from rq.command import send_stop_job_command
        job = Job.fetch(active_id, connection=redis_client)
        job.cancel()
        if job.worker_name:
            try:
                send_stop_job_command(redis_client, active_id)
            except Exception:
                pass
        return True
    except Exception:
        return False