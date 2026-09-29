import { NextResponse, type NextRequest } from "next/server";

/**
 * Keep browsers on the public app origin.
 *
 * In the Docker stack every request should arrive through Caddy, which marks it
 * with `x-pf-proxied`. Port forwarders such as GitHub Codespaces also expose the
 * web server's own port; a page opened there works, but uploads (presigned for
 * the app origin) fail as cross-origin. Such requests are redirected to
 * PF_APP_ORIGIN. Without PF_APP_ORIGIN (plain `next dev` / `next start`) this
 * is a no-op.
 */
export function proxy(request: NextRequest) {
  const origin = process.env["PF_APP_ORIGIN"];
  if (!origin || request.headers.get("x-pf-proxied") === "1") {
    return NextResponse.next();
  }
  const { pathname, search } = request.nextUrl;
  return NextResponse.redirect(new URL(`${pathname}${search}`, origin), 307);
}
