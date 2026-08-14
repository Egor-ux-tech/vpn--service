"use client";

/**
 * Token storage for the admin panel.
 *
 * The access token is kept in a *non-httpOnly* cookie (not localStorage-only) so that
 * `proxy.ts` can perform an optimistic existence check server-side before rendering a
 * protected route (see Next.js's documented "Optimistic checks with Proxy" pattern).
 * The real authorization boundary is the backend: every API call still sends the token as
 * a Bearer header and the FastAPI backend independently validates signature, expiry, and
 * role on every request — a forged or missing cookie only ever affects the redirect UX,
 * never actual access to data.
 *
 * Trade-off: keeping the cookie readable by client JS (not httpOnly) is what lets us avoid
 * a token-relay endpoint, at the cost of the token being exposed to any successful XSS. For
 * an internal admin tool behind short-lived (30 min) JWTs this is an accepted trade-off —
 * see docs/security.md for the full reasoning and mitigations (CSP headers, short expiry).
 */

const COOKIE_NAME = "admin_token";
const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 8; // 8h ceiling; the JWT itself expires sooner

export function setToken(token: string): void {
  const secure = typeof window !== "undefined" && window.location.protocol === "https:";
  document.cookie = [
    `${COOKIE_NAME}=${encodeURIComponent(token)}`,
    "path=/",
    `max-age=${COOKIE_MAX_AGE_SECONDS}`,
    "samesite=lax",
    secure ? "secure" : "",
  ]
    .filter(Boolean)
    .join("; ");
}

export function getToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${COOKIE_NAME}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : null;
}

export function clearToken(): void {
  document.cookie = `${COOKIE_NAME}=; path=/; max-age=0`;
}

export { COOKIE_NAME };
