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