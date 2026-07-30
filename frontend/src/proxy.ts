import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { resolveLocale } from "@/i18n/locales";

export function proxy(request: NextRequest) {
  const locale = resolveLocale(request.headers.get("accept-language"));
  return NextResponse.redirect(new URL(`/${locale}`, request.url));
}

export const config = { matcher: ["/"] };
