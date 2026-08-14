from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

settings = get_settings()

# A single shared Limiter instance — imported both by main.py (to register it on the app
# and apply the global default) and by individual routers that need a stricter, endpoint
# specific limit (e.g. admin login, a brute-force target).
#
# Backed by Redis (storage_uri), not the slowapi default in-memory counter: an in-memory
# limiter counts hits per *process*, so with N backend replicas behind a load balancer an
# attacker gets N times the allowed rate, and every replica restart silently resets every
# counter. Redis makes the hit count a single shared value all replicas atomically
# increment (limits' RedisStorage does this via a Lua EVALSHA script, so concurrent
# increments from different replicas can't race each other), so the configured limit is
# actually enforced service-wide.
# If Redis is briefly unreachable (restart, network blip), requests must keep working —
# without a fallback, slowapi lets the storage backend's ConnectionError propagate up
# through the ASGI stack, so Redis being down would take down every single request through
# the API, not just rate limiting (confirmed empirically). Rate limiting is a
# defense-in-depth control; it must never be a single point of failure for the whole
# service.
#
# in_memory_fallback_enabled degrades to a real (per-process, not distributed) in-memory
# limiter — the pre-Fix-2 behavior — the moment the primary storage throws, and
# automatically switches back once Redis is reachable again (slowapi polls it in the
# background). swallow_errors=True is an additional last-resort backstop on top of that,
# for the case where even the in-memory fallback somehow fails: plain swallow_errors alone
# is NOT sufficient here — verified empirically that slowapi has a separate bug where
# swallowing the initial check still crashes the *response* path afterward (it tries to
# read request.state.view_rate_limit for header injection, which was never set because the
# check never completed) unless a fallback limiter actually runs and sets it.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.rate_limit_default],
    storage_uri=settings.redis_url,
    key_prefix="ratelimit",
    in_memory_fallback_enabled=True,
    in_memory_fallback=[settings.rate_limit_default],
    swallow_errors=True,
)
