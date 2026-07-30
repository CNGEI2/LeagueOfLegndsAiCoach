# Task 2 Report: Tested Bilingual Next.js Search Homepage

## Scope

Implemented the frontend-only Phase 1 search homepage in `frontend/`. It provides
localized `/zh-CN` and `/en-US` routes, redirects `/` using `Accept-Language`,
and deliberately keeps form submission local: the submit handler calls
`preventDefault()` and shows the Phase 2 notice. No backend file was modified and
no Riot or OpenAI request is made.

## Scaffolding and dependencies

Executed from the repository root:

```bash
pnpm create next-app@latest frontend --typescript --tailwind --eslint --app --src-dir --use-pnpm --import-alias '@/*' --yes
```

The initial sandboxed download failed with
`[WARN] GET https://registry.npmjs.org/create-next-app error (ENOTFOUND)`; the
same command was rerun with permitted network access. `create-next-app` generated
Next.js 16.2.12, React 19.2.4, TypeScript 5.9.3, Tailwind 4.3.3, ESLint 9.39.5,
and the corresponding generated `pnpm-lock.yaml`.

Executed from `frontend/`:

```bash
pnpm add -D vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event vite-tsconfig-paths
pnpm approve-builds --all
```

The second command approved the downloaded `sharp` and `unrs-resolver` build
scripts that pnpm required before it would run project scripts.

## TDD evidence

### RED

After only adding Vitest configuration, test setup, and the prescribed tests,
before creating the i18n or form production modules, `pnpm test` exited 1 with:

```text
FAIL  tests/i18n.test.ts
Error: Failed to resolve import "@/i18n/messages" from "tests/i18n.test.ts". Does the file exist?

FAIL  tests/riot-search-form.test.tsx
Error: Failed to resolve import "@/components/riot-search-form" from "tests/riot-search-form.test.tsx". Does the file exist?

Test Files  2 failed (2)
Tests  no tests
```

### GREEN

After implementing typed locale negotiation, matching catalogs, and the local
form behavior, `pnpm test` exited 0:

```text
Test Files  2 passed (2)
Tests  5 passed (5)
```

## Quality gates

All requested checks completed successfully:

```text
pnpm test       2 files passed, 5 tests passed
pnpm lint       exit 0
pnpm typecheck  exit 0
pnpm build      exit 0
```

The first sandboxed `pnpm build` attempt failed because Turbopack could not bind a
local port (`Operation not permitted (os error 1)`). Rerunning the exact command
with permitted local process access compiled successfully and generated static
`/zh-CN` and `/en-US` routes plus the root proxy. A runtime HTTP check also
confirmed `Accept-Language: zh-CN,zh;q=0.9,en;q=0.8` receives
`HTTP/1.1 307 Temporary Redirect` with `location: /zh-CN`; both localized pages
returned their expected heading and form labels.

## Files changed

- Generated/configured: `frontend/package.json`, `frontend/pnpm-lock.yaml`,
  `frontend/next.config.ts`, `frontend/tsconfig.json`,
  `frontend/eslint.config.mjs`, `frontend/postcss.config.mjs`,
  `frontend/pnpm-workspace.yaml`, and the generated supporting scaffold files.
- Added application code: `frontend/src/proxy.ts`, localized route layout/page,
  `language-switcher.tsx`, `riot-search-form.tsx`, and all four i18n modules.
- Added test configuration and behavior tests: `frontend/vitest.config.ts`,
  `frontend/src/test/setup.ts`, `frontend/tests/i18n.test.ts`, and
  `frontend/tests/riot-search-form.test.tsx`.
- Replaced the generated global styles and removed the generated root
  `src/app/layout.tsx` and `src/app/page.tsx` so locale routing owns the document.

## Visual and design decisions

The frontend-design guidance informed a restrained dark game aesthetic rather
than a generic dashboard: deep navy surfaces (`#070b14`, `#101827`) suggest a
post-match analysis room, while emerald (`#56d68b`) is intentionally spent only
on the review eyebrow, link, button, and focus system. The oversized compressed
headline is the visual thesis; it names the single job (learn from the last
match) before the form. The horizontal desktop input row resembles a compact
match lookup console and becomes a one-column sequence below 720px. Quiet
metadata, a clear legal footer, visible keyboard focus, and no decorative motion
keep the page precise and accessible. The page's one signature is the
"POST-GAME REVIEW" green marker framing the large reflective headline; no
additional ornamental effects compete with it.

## Self-review and concerns

Reviewed the changed source for exact requested field names (`gameName`,
`tagLine`, `platform`), the local-only `preventDefault()` submission path,
catalog key parity, unsupported-language English fallback, generated static
locale params, and preserved root `.gitignore` content. There are no functional
concerns. Vitest prints an informational Vite notice that
`vite-tsconfig-paths` is now redundant, but it remains because the brief
explicitly requires that plugin and configuration.
