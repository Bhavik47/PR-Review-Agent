import hmac
import hashlib
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Header, HTTPException
from app.config import settings
from app.db.session import init_db
from app.queue.redis_conn import (
    pr_queue,
    is_duplicate_webhook,
    cancel_active_job,
    set_active_job,
)
from app.queue.worker import process_pr_review_job

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Autonomous PR Reviewer Agent", lifespan=lifespan)

def verify_github_signature(payload_body: bytes, signature_header: str | None):
    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256")
    hash_object = hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    )
    expected_signature = "sha256=" + hash_object.hexdigest()
    if not hmac.compare_digest(expected_signature, signature_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

@app.post("/webhooks/github", status_code=202)
async def github_webhook(
    request: Request,
    x_github_event: str = Header(None),
    x_github_delivery: str = Header(None),
    x_hub_signature_256: str = Header(None),
):
    raw_body = await request.body()
    verify_github_signature(raw_body, x_hub_signature_256)

    if x_github_event != "pull_request":
        return {"status": "ignored", "reason": f"unhandled_event_{x_github_event}"}

    payload = await request.json()
    action = payload.get("action")
    if action not in ("opened", "synchronize", "reopened"):
        return {"status": "ignored", "reason": f"unhandled_action_{action}"}

    sender = payload.get("sender", {}).get("login", "")
    if sender == settings.GITHUB_BOT_USERNAME:
        return {"status": "ignored", "reason": "bot_sender"}

    if x_github_delivery and is_duplicate_webhook(x_github_delivery):
        return {"status": "ignored", "reason": "duplicate_delivery"}

    pr = payload["pull_request"]
    repo_full_name = payload["repository"]["full_name"]
    pr_number = pr["number"]

    # Rapid-push cancellation: cancel any pending or running job for this PR
    cancel_active_job(repo_full_name, pr_number)

    job = pr_queue.enqueue(
        process_pr_review_job,
        repo_full_name=repo_full_name,
        pr_number=pr_number,
        base_sha=pr["base"]["sha"],
        head_sha=pr["head"]["sha"],
        pr_title=pr["title"],
        pr_description=pr.get("body") or "",
    )

    set_active_job(repo_full_name, pr_number, job.id)

    return {"status": "queued", "job_id": job.id}