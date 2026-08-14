"""Proves the rate limiter is actually backed by Redis (not slowapi's default in-process
memory counter) and that the counter is shared across independent process instances —
the property that matters once the backend runs as multiple replicas behind a load
balancer. tests/conftest.py replaces redis.from_url with a shared fakeredis instance
process-wide, so these tests exercise the real limits.storage.redis code path (including
its Lua EVALSHA increment script) against a fake server instead of skipping it.
"""

import redis as redis_module
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.core.errors import register_exception_handlers
from app.core.rate_limit import limiter as app_limiter


def _limit_item(limiter_instance: Limiter, limit_string: str):
    group = limiter_instance._default_limits[0]
    return next(iter(group)).limit


def test_limiter_is_backed_by_redis_storage_not_in_memory() -> None:
    storage_type = type(app_limiter._storage).__name__
    assert storage_type == "RedisStorage", (
        f"expected the shared app limiter to use Redis storage, got {storage_type} — "
        "an in-memory limiter only counts hits for a single process, so with multiple "
        "backend replicas each one gets its own separate quota."
    )


def test_two_independent_limiter_instances_share_state_via_redis() -> None:
    """Simulates two backend replicas: two completely separate Limiter objects, each with
    its own in-process state, pointed at the same Redis (storage_uri defaults to redis://,
    matching production config — see app.core.rate_limit). If the limit is enforced
    correctly across replicas, hits recorded by instance A must count against instance B's
    view of the same key — proving the counter lives in Redis, not in either process."""
    replica_a = Limiter(
        key_func=get_remote_address, default_limits=["3/minute"], storage_uri="redis://"
    )
    replica_b = Limiter(
        key_func=get_remote_address, default_limits=["3/minute"], storage_uri="redis://"
    )
    assert type(replica_a._storage).__name__ == "RedisStorage"

    limit_item_a = _limit_item(replica_a, "3/minute")
    limit_item_b = _limit_item(replica_b, "3/minute")

    key = "multi-replica-test-client"

    assert replica_a.limiter.hit(limit_item_a, key) is True
    assert replica_a.limiter.hit(limit_item_a, key) is True
    # Third hit comes from the *other* replica — if state weren't shared via Redis, replica
    # B would see zero prior hits for this key and wrongly allow it.
    assert replica_b.limiter.hit(limit_item_b, key) is True
    assert replica_b.limiter.hit(limit_item_b, key) is False, (
        "replica B allowed a 4th hit on a 3/minute limit — the counter is not actually "
        "shared across instances, so each backend replica would enforce its own separate "
        "quota instead of one service-wide limit"
    )


def test_requests_still_succeed_when_redis_is_genuinely_unreachable(monkeypatch) -> None:
    """A real regression, caught by the cross-service E2E suite (tests/test_full_stack_e2e.py)
    while verifying this fix: pointing the Limiter at Redis with no fallback configured
    means *every* request 500s the moment Redis is unreachable — swapping the rate limiter
    to Redis must not turn a cache-tier hiccup into a full API outage. Confirmed two
    distinct slowapi bugs empirically before landing on this config: (1) swallow_errors
    alone still crashes later when injecting rate-limit response headers, because the
    request never got as far as recording what to inject, and (2) that crash reproduces
    with a real TCP-refused connection, not just fakeredis, which is why this test
    deliberately restores the *real* redis.from_url (undoing tests/conftest.py's process
    wide fakeredis patch) and points at a port nothing listens on, instead of using the
    shared fake Redis like every other test in this module.
    """
    monkeypatch.setattr(redis_module, "from_url", redis_module.Redis.from_url)

    unreachable_limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["100/minute"],
        storage_uri="redis://localhost:1/0",  # port 1: nothing listens here
        in_memory_fallback_enabled=True,
        in_memory_fallback=["100/minute"],
        swallow_errors=True,
    )

    app = FastAPI()
    app.state.limiter = unreachable_limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    register_exception_handlers(app)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/ping")

    assert resp.status_code == 200, (
        f"request failed with Redis unreachable and no fallback protection: "
        f"{resp.status_code} {resp.text}"
    )
    assert resp.json() == {"ok": True}
