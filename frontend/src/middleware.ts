import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Public routes: homepage, about, share, login, API, static assets
  const publicPaths = ["/", "/about", "/share", "/login", "/api", "/_next", "/favicon.ico"];
  if (publicPaths.some((p) => pathname === p || pathname.startsWith(p + "/"))) {
    return NextResponse.next();
  }

  // Check for access token cookie
  const token = request.cookies.get("access_token")?.value;
  if (!token) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  // Admin routes require admin role (decode JWT payload without verification —
  // backend verifies the full token on every API call)
  if (pathname.startsWith("/admin")) {
    try {
      const payload = JSON.parse(atob(token.split(".")[1]));
      if (payload.role !== "admin") {
        return NextResponse.redirect(new URL("/chat", request.url));
      }
    } catch {
      // Malformed token — let backend reject it
      return NextResponse.next();
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
