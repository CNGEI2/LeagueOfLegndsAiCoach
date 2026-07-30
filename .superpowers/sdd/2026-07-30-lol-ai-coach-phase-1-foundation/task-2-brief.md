### Task 2: Tested Bilingual Next.js Search Homepage

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/pnpm-lock.yaml`
- Create: `frontend/next.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/eslint.config.mjs`
- Create: `frontend/postcss.config.mjs`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/src/proxy.ts`
- Create: `frontend/src/app/globals.css`
- Delete after scaffolding: `frontend/src/app/layout.tsx`
- Delete after scaffolding: `frontend/src/app/page.tsx`
- Create: `frontend/src/app/[locale]/layout.tsx`
- Create: `frontend/src/app/[locale]/page.tsx`
- Create: `frontend/src/components/language-switcher.tsx`
- Create: `frontend/src/components/riot-search-form.tsx`
- Create: `frontend/src/i18n/locales.ts`
- Create: `frontend/src/i18n/messages.ts`
- Create: `frontend/src/i18n/en-US.ts`
- Create: `frontend/src/i18n/zh-CN.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/tests/i18n.test.ts`
- Create: `frontend/tests/riot-search-form.test.tsx`

**Interfaces:**
- Consumes: URL locale segment `zh-CN` or `en-US`; browser `Accept-Language` at `/`.
- Produces: `type Locale = "zh-CN" | "en-US"`, `resolveLocale(value: string | null) -> Locale`, `getMessages(locale: Locale) -> Messages`, `RiotSearchForm({messages}: Props)`, and localized routes `/zh-CN` and `/en-US`.
- Produces form fields named `gameName`, `tagLine`, and `platform`; Phase 1 submit prevents network access.

- [ ] **Step 1: Scaffold the frontend with current recommended defaults**

From the repository root, run:

```bash
pnpm create next-app@latest frontend --typescript --tailwind --eslint --app --src-dir --use-pnpm --import-alias '@/*' --yes
cd frontend
pnpm add -D vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

Retain the generated Next.js, React, TypeScript, Tailwind, ESLint, and PostCSS versions in `pnpm-lock.yaml`. Add these scripts to `frontend/package.json`:

```json
{
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "eslint .",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "test:watch": "vitest"
  }
}
```

- [ ] **Step 2: Configure Vitest and write failing locale tests**

Create `frontend/vitest.config.ts`:

```typescript
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    tsconfigPaths: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
```

Create `frontend/src/test/setup.ts`:

```typescript
import "@testing-library/jest-dom/vitest";
```

Create `frontend/tests/i18n.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { getMessages } from "@/i18n/messages";
import { resolveLocale } from "@/i18n/locales";

describe("locale resolution", () => {
  it("selects Simplified Chinese when it is preferred", () => {
    expect(resolveLocale("zh-CN,zh;q=0.9,en;q=0.8")).toBe("zh-CN");
  });

  it("falls back to English for unsupported languages", () => {
    expect(resolveLocale("fr-FR,fr;q=0.9")).toBe("en-US");
  });
});

describe("message catalogs", () => {
  it("contain exactly the same required keys", () => {
    expect(Object.keys(getMessages("zh-CN")).sort()).toEqual(
      Object.keys(getMessages("en-US")).sort(),
    );
  });
});
```

- [ ] **Step 3: Write the failing accessible form test**

Create `frontend/tests/riot-search-form.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { RiotSearchForm } from "@/components/riot-search-form";
import { getMessages } from "@/i18n/messages";

describe("RiotSearchForm", () => {
  it("renders the English fields and keeps Phase 1 submission local", async () => {
    const user = userEvent.setup();
    render(<RiotSearchForm messages={getMessages("en-US")} />);

    await user.type(screen.getByLabelText("Game Name"), "PlayerName");
    await user.type(screen.getByLabelText("Tag Line"), "NA1");
    expect(screen.getByLabelText("Region")).toHaveValue("NA1");

    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(screen.getByText("Riot API search will be added in Phase 2.")).toBeVisible();
  });

  it("renders Simplified Chinese labels", () => {
    render(<RiotSearchForm messages={getMessages("zh-CN")} />);

    expect(screen.getByLabelText("游戏名称")).toBeVisible();
    expect(screen.getByRole("button", { name: "查询" })).toBeVisible();
  });
});
```

- [ ] **Step 4: Run frontend tests and verify red state**

Run:

```bash
cd frontend
pnpm test
```

Expected: tests fail because the i18n modules and `RiotSearchForm` do not exist.

- [ ] **Step 5: Implement typed locale negotiation and message catalogs**

Create `frontend/src/i18n/locales.ts`:

```typescript
export const locales = ["zh-CN", "en-US"] as const;
export type Locale = (typeof locales)[number];

export function isLocale(value: string): value is Locale {
  return locales.includes(value as Locale);
}

export function resolveLocale(acceptLanguage: string | null): Locale {
  if (!acceptLanguage) return "en-US";
  const normalized = acceptLanguage.toLowerCase();
  return normalized.includes("zh-cn") || normalized.startsWith("zh")
    ? "zh-CN"
    : "en-US";
}
```

Create `frontend/src/i18n/en-US.ts`:

```typescript
export const enUS = {
  productName: "LoL AI Coach",
  headline: "Understand the match. Improve the next one.",
  description: "Enter a Riot ID to prepare a data-based post-game review.",
  gameName: "Game Name",
  tagLine: "Tag Line",
  region: "Region",
  northAmerica: "North America",
  search: "Search",
  example: "Example: PlayerName # NA1",
  phaseNotice: "Riot API search will be added in Phase 2.",
  language: "Language",
  disclaimer: "LoL AI Coach is not endorsed by Riot Games and does not reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks or registered trademarks of Riot Games, Inc.",
} as const;
```

Create `frontend/src/i18n/zh-CN.ts` with the same keys:

```typescript
import type { Messages } from "./messages";

export const zhCN: Messages = {
  productName: "LoL AI Coach",
  headline: "看懂这一局，打好下一局。",
  description: "输入 Riot ID，准备生成基于赛后数据的复盘。",
  gameName: "游戏名称",
  tagLine: "标签",
  region: "服务器",
  northAmerica: "北美",
  search: "查询",
  example: "示例：PlayerName # NA1",
  phaseNotice: "Riot API 查询将在第二阶段接入。",
  language: "语言",
  disclaimer: "LoL AI Coach 未获得 Riot Games 认可，也不代表 Riot Games 或任何正式参与 Riot Games 产品制作与管理人员的观点或意见。Riot Games 及其相关资产均为 Riot Games, Inc. 的商标或注册商标。",
};
```

Create `frontend/src/i18n/messages.ts`:

```typescript
import { enUS } from "./en-US";
import { zhCN } from "./zh-CN";
import type { Locale } from "./locales";

export type Messages = { [Key in keyof typeof enUS]: string };

export function getMessages(locale: Locale): Messages {
  return locale === "zh-CN" ? zhCN : enUS;
}
```

- [ ] **Step 6: Implement the localized form and language switch**

Create `frontend/src/components/riot-search-form.tsx`:

```tsx
"use client";

import { type FormEvent, useState } from "react";

import type { Messages } from "@/i18n/messages";

export function RiotSearchForm({ messages }: { messages: Messages }) {
  const [submitted, setSubmitted] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
  }

  return (
    <form onSubmit={handleSubmit} className="search-card">
      <label>
        <span>{messages.gameName}</span>
        <input name="gameName" autoComplete="off" required maxLength={16} />
      </label>
      <label>
        <span>{messages.tagLine}</span>
        <input name="tagLine" autoComplete="off" required maxLength={5} />
      </label>
      <label>
        <span>{messages.region}</span>
        <select name="platform" defaultValue="NA1">
          <option value="NA1">{messages.northAmerica}</option>
        </select>
      </label>
      <button type="submit">{messages.search}</button>
      <p className="example">{messages.example}</p>
      {submitted ? <p role="status">{messages.phaseNotice}</p> : null}
    </form>
  );
}
```

Create `frontend/src/components/language-switcher.tsx`:

```tsx
import Link from "next/link";

import type { Locale } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages";

export function LanguageSwitcher({ locale, messages }: { locale: Locale; messages: Messages }) {
  const target = locale === "zh-CN" ? "en-US" : "zh-CN";
  return (
    <nav aria-label={messages.language}>
      <Link href={`/${target}`} hrefLang={target}>
        {target === "zh-CN" ? "中文" : "English"}
      </Link>
    </nav>
  );
}
```

- [ ] **Step 7: Implement localized routes and the dark responsive shell**

Delete the generated `frontend/src/app/layout.tsx` and `frontend/src/app/page.tsx`. Create `frontend/src/proxy.ts` so `/` redirects before route resolution:

```tsx
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { resolveLocale } from "@/i18n/locales";

export function proxy(request: NextRequest) {
  const locale = resolveLocale(request.headers.get("accept-language"));
  return NextResponse.redirect(new URL(`/${locale}`, request.url));
}

export const config = { matcher: ["/"] };
```

Create `frontend/src/app/[locale]/layout.tsx`:

```tsx
import { notFound } from "next/navigation";

import "../globals.css";
import { isLocale, locales } from "@/i18n/locales";

export function generateStaticParams() {
  return locales.map((locale) => ({ locale }));
}

export default async function LocaleLayout({
  children,
  params,
}: Readonly<{ children: React.ReactNode; params: Promise<{ locale: string }> }>) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  return (
    <html lang={locale}>
      <body>{children}</body>
    </html>
  );
}
```

Create `frontend/src/app/[locale]/page.tsx`:

```tsx
import { notFound } from "next/navigation";

import { LanguageSwitcher } from "@/components/language-switcher";
import { RiotSearchForm } from "@/components/riot-search-form";
import { getMessages } from "@/i18n/messages";
import { isLocale } from "@/i18n/locales";

export default async function HomePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const messages = getMessages(locale);

  return (
    <main>
      <header>
        <span className="brand">{messages.productName}</span>
        <LanguageSwitcher locale={locale} messages={messages} />
      </header>
      <section className="hero">
        <p className="eyebrow">POST-GAME REVIEW</p>
        <h1>{messages.headline}</h1>
        <p>{messages.description}</p>
        <RiotSearchForm messages={messages} />
      </section>
      <footer>{messages.disclaimer}</footer>
    </main>
  );
}
```

Replace `frontend/src/app/globals.css` with:

```css
@import "tailwindcss";

:root {
  color-scheme: dark;
  --background: #070b14;
  --surface: #101827;
  --surface-raised: #172235;
  --border: #2a3850;
  --text: #f4f7fb;
  --muted: #9aa9bd;
  --accent: #56d68b;
  --accent-strong: #31b86c;
  --focus: #8ee8b1;
}

* {
  box-sizing: border-box;
}

body {
  min-height: 100vh;
  margin: 0;
  background:
    radial-gradient(circle at 15% 0%, rgb(42 72 94 / 35%), transparent 38%),
    var(--background);
  color: var(--text);
  font-family: Arial, Helvetica, sans-serif;
}

a {
  color: var(--accent);
  text-underline-offset: 0.25rem;
}

main {
  width: min(1120px, calc(100% - 2rem));
  min-height: 100vh;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.5rem 0;
}

.brand {
  font-weight: 800;
  letter-spacing: 0.04em;
}

.hero {
  flex: 1;
  display: grid;
  align-content: center;
  gap: 1rem;
  padding: 3rem 0;
}

.eyebrow {
  margin: 0;
  color: var(--accent);
  font-size: 0.78rem;
  font-weight: 800;
  letter-spacing: 0.18em;
}

h1 {
  max-width: 760px;
  margin: 0;
  font-size: clamp(2.5rem, 7vw, 5.4rem);
  line-height: 0.98;
  letter-spacing: -0.04em;
}

.hero > p:not(.eyebrow) {
  max-width: 640px;
  color: var(--muted);
  font-size: 1.08rem;
}

.search-card {
  display: grid;
  grid-template-columns: 1.4fr 0.8fr 1fr auto;
  gap: 0.9rem;
  margin-top: 1.5rem;
  padding: 1.2rem;
  border: 1px solid var(--border);
  border-radius: 1rem;
  background: rgb(16 24 39 / 88%);
  box-shadow: 0 1.5rem 4rem rgb(0 0 0 / 24%);
}

label {
  display: grid;
  gap: 0.45rem;
  color: var(--muted);
  font-size: 0.8rem;
  font-weight: 700;
}

input,
select,
button {
  min-height: 3rem;
  border-radius: 0.7rem;
  font: inherit;
}

input,
select {
  width: 100%;
  border: 1px solid var(--border);
  background: var(--surface-raised);
  color: var(--text);
  padding: 0 0.85rem;
}

input:focus-visible,
select:focus-visible,
button:focus-visible,
a:focus-visible {
  outline: 3px solid var(--focus);
  outline-offset: 2px;
}

button {
  align-self: end;
  border: 0;
  padding: 0 1.4rem;
  background: var(--accent);
  color: #041109;
  font-weight: 800;
  cursor: pointer;
  transition: background-color 140ms ease;
}

button:hover {
  background: var(--accent-strong);
}

.example,
[role="status"] {
  grid-column: 1 / -1;
  margin: 0;
  color: var(--muted);
  font-size: 0.85rem;
}

footer {
  padding: 1.5rem 0 2rem;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 0.75rem;
  line-height: 1.6;
}

@media (max-width: 720px) {
  .search-card {
    grid-template-columns: 1fr;
  }

  button {
    width: 100%;
  }
}
```

Set `output: "standalone"` in `frontend/next.config.ts`:

```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
};

export default nextConfig;
```

- [ ] **Step 8: Run the frontend quality gates**

Run:

```bash
cd frontend
pnpm test
pnpm lint
pnpm typecheck
pnpm build
```

Expected: locale/form tests pass, lint/typecheck exit 0, and Next.js builds `/`, `/zh-CN`, and `/en-US` successfully.

- [ ] **Step 9: Commit the bilingual frontend foundation**

```bash
git add frontend
git commit -m "feat: add bilingual Next.js search homepage"
```

---
