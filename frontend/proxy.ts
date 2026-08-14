import { NextRequest, NextResponse } from "next/server";

// Next.js 16 renamed Middleware to Proxy (same runtime/conventions) — see
// node_modules/next/dist/docs/01-app/01-getting-started/16-proxy.md in this project.
//
// This is an *optimistic* check only: it looks for the presence of the admin_token cookie
// and redirects for UX purposes. It never decodes or verifies the token — the backend is
// the actual authorization boundary and independently validates signature/expiry/role on
// every request (see backend/app/core/deps.py::get_current_admin).

const COOKIE_NAME = "admin_token";
const PUBLIC_ROUTES = ["/login"];

export default function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasToken = Boolean(request.cookies.get(COOKIE_NAME)?.value);
  const isPublicRoute = PUBLIC_ROUTES.includes(pathname);

  if (!hasToken && !isPublicRoute) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  if (hasToken && isPublicRoute) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
