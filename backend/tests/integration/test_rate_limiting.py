import pytest


@pytest.mark.asyncio
async def test_admin_login_is_rate_limited_after_repeated_attempts(client):
    """Admin login is a brute-force target — the 11th attempt within a minute from the
    same client must be rejected with 429, regardless of credentials."""
    payload = {"email": "nobody@example.com", "password": "wrong"}

    responses = [await client.post("/api/v1/auth/admin/login", json=payload) for _ in range(10)]
    assert all(r.status_code == 401 for r in responses)

    eleventh = await client.post("/api/v1/auth/admin/login", json=payload)
    assert eleventh.status_code == 429
