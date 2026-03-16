# frontend/

Next.js 16 App Router frontend for Usami — multi-agent orchestration UI.

## Tech stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Framework | Next.js (App Router, `output: "standalone"`) | 16.1.6 |
| React | React 19 | 19.2.3 |
| State | Zustand | 5.x |
| Server state | TanStack Query | 5.x |
| UI | shadcn/ui **base-nova** style (`@base-ui/react`, NOT Radix) | 4.x |
| Styling | Tailwind CSS v4 (PostCSS plugin, no `tailwind.config.js`) | 4.x |
| Icons | Lucide React | 0.577.x |
| Markdown | streamdown + `@streamdown/code` + `@streamdown/cjk` | 2.4.x |
| DAG | `@xyflow/react` + `@dagrejs/dagre` | 12.x |
| i18n | next-intl (cookie-based, no URL prefix) | 4.x |
| Theme | next-themes (`attribute="class"`, system/light/dark) | — |
| Package manager | pnpm | — |

## Commands

```bash
pnpm dev          # Dev server (Turbopack)
pnpm build        # Production build (standalone)
pnpm lint         # ESLint
```

Docker: `docker compose up frontend` (builds with `BACKEND_INTERNAL_URL=http://backend:8000`).

## Directory structure

```
src/
├── app/
│   ├── globals.css              # Tailwind v4 + shadcn CSS variables (OKLCH)
│   ├── layout.tsx               # Root layout: Geist fonts + <Providers> + suppressHydrationWarning
│   ├── page.tsx                 # Landing page
│   ├── login/page.tsx           # Public: login form
│   ├── about/page.tsx           # Public: about
│   ├── share/[threadId]/page.tsx # Public: shared thread view
│   ├── (main)/                  # C端 authenticated route group
│   │   ├── layout.tsx           # C端 layout: AppSidebar + Header
│   │   ├── chat/page.tsx        # Main chat UI
│   │   ├── tasks/[threadId]/page.tsx # Task detail + DAG
│   │   └── settings/page.tsx    # User preferences (theme, language, notifications)
│   └── (admin)/                 # Admin route group (requires admin role)
│       ├── layout.tsx           # Admin layout: AdminSidebar + AdminHeader
│       ├── dashboard/page.tsx   # Admin overview
│       ├── users/page.tsx       # User management
│       ├── health/page.tsx
│       ├── personas/page.tsx
│       ├── scheduler/page.tsx
│       └── tools/page.tsx
├── components/
│   ├── ui/                      # shadcn/ui primitives (15 components)
│   ├── layout/                  # App shell: sidebar, admin-sidebar, header, admin-header, providers, theme-toggle, notification-center
│   ├── chat/                    # Chat: input, message bubble, thread list
│   ├── task/                    # DAG: plan card, task node, task DAG
│   ├── hitl/                    # HiTL dialog
│   └── admin/                   # Admin panels: persona-card, tool-table, job-table, health-panel, user-table
├── hooks/                       # TanStack Query hooks + derived state
├── lib/                         # API clients, WebSocket, constants, utils, push
├── stores/                      # Zustand stores (4 stores)
├── types/                       # TypeScript types (mirrors backend Pydantic)
├── i18n/                        # next-intl config and request handler
│   ├── config.ts                # Locale list + default
│   └── request.ts               # Server-side locale resolution from cookie
├── middleware.ts                 # Auth cookie + admin role check
messages/
├── zh.json                      # Chinese translations
└── en.json                      # English translations
public/
└── sw.js                        # Service Worker for push notifications
```

## Architecture patterns (7 patterns to internalize)

### 1. Event-driven state (WS → Zustand → React)

```
Backend WS event → UsamiWebSocket → ws-store → thread-store.appendEvent() → Re-render
```

- All WS events flow into `thread-store` as an **append-only event log**.
- `EVENT_TO_PHASE` mapping automatically transitions thread phase.
- `appendEvent()` extracts `result` from `task.completed` events and `pendingHitl` from `hitl.request` events.
- `useDerivedMessages()` hook transforms raw events → chat UI messages (pure derived state).
- Never manually manage message arrays — messages are always derived from events.

### 2. Dual API layer (client vs server)

| File | Context | Routing |
|------|---------|---------|
| `lib/api-client.ts` | Client Components (browser) | Via Next.js rewrite `/api/*` → backend |
| `lib/api-server.ts` | Server Components / SSR | Direct to `BACKEND_INTERNAL_URL` |

- Client-side API auto-redirects to `/login` on 401.
- Server-side API uses `fetch()` with `next.revalidate` for caching.
- Both return typed responses from `types/api.ts`.

### 3. WS-first architecture (no polling)

- **Primary**: WebSocket delivers all state updates in real-time, including `result` in `task.completed`.
- **Reconnect recovery**: On WS reconnect, `WsConnector` invalidates active thread query to catch missed events.
- **No periodic polling** — REST only fetches on mount and reconnect.

### 4. Global HiTL watcher

`<HiTLWatcher />` in `<Providers />` watches **all threads** for `pendingHitl.length > 0`. Auto-opens `<HiTLDialog />` when detected. Guarantees HiTL is never missed regardless of which thread is active.

### 5. Cookie-based auth with middleware

- `middleware.ts` checks `access_token` cookie on every request to authenticated routes.
- Missing cookie → redirect to `/login`.
- Admin routes (`/admin/*`) additionally decode JWT payload to check `role === "admin"`.
- Non-admin user accessing `/admin` → redirect to `/chat`.
- Login page stores token via `useAuthStore.setAuth(user, accessToken)`.
- WS appends token as `?token=` query param.

### 6. Separated route groups

- `(main)/` — C端 (consumer) routes: chat, task detail, settings. Uses `AppSidebar` + `Header`.
- `(admin)/` — Admin routes: dashboard, users, personas, tools, scheduler, health. Uses `AdminSidebar` + `AdminHeader`.
- Each group has its own layout, sidebar, and header. Completely independent sub-applications.

### 7. Notification system

- **In-app**: `NotificationWatcher` in providers listens to WS events → creates notifications in `notification-store`. `NotificationCenter` dropdown in headers shows unread count + notification list.
- **Push**: Service Worker (`public/sw.js`) + Web Push API. Backend sends via `pywebpush`. Managed in settings page.

## Four Zustand stores

| Store | File | Purpose |
|-------|------|---------|
| `useAuthStore` | `stores/auth-store.ts` | `user`, `accessToken`, `isAuthenticated`, `logout()` |
| `useWsStore` | `stores/ws-store.ts` | WS connection lifecycle, bridges WS events → `thread-store` |
| `useThreadStore` | `stores/thread-store.ts` | Thread map, event log, phase tracking, HiTL state, result |
| `useNotificationStore` | `stores/notification-store.ts` | In-app notifications, unread count, mark read/clear |

Cross-store access pattern: `useAuthStore.getState().accessToken` (no hook, for non-React code).

## TanStack Query hooks

| Hook | File | Purpose |
|------|------|---------|
| `useTaskDetail` | `hooks/use-task-detail.ts` | Task query (no polling — WS-first) |
| `useCreateTask` | `hooks/use-create-task.ts` | Create task mutation, auto-creates thread |
| `useResolveHitl` | `hooks/use-resolve-hitl.ts` | Resolve HiTL mutation |
| `useHealth` | `hooks/use-health.ts` | Health check query |
| `useDerivedMessages` | `hooks/use-derived-messages.ts` | Derived chat messages from thread events |
| `useAdminUsers` | `hooks/use-admin-users.ts` | Admin user CRUD (list, create, update) |

Default query config: `staleTime: 30_000`, `retry: 1`.

## Internationalization (i18n)

- **Library**: `next-intl` with cookie-based locale (no URL prefix).
- **Locale cookie**: `NEXT_LOCALE` (set in settings page, read in `i18n/request.ts`).
- **Messages**: `messages/zh.json` and `messages/en.json`.
- **Usage in client components**: `const t = useTranslations("namespace")` then `t("key")`.
- **Usage in server components**: `import { getTranslations } from "next-intl/server"`.
- **Config**: `next.config.ts` wraps with `createNextIntlPlugin`.

## Code style

### Language rules (same as backend)

- **English**: TypeScript code, comments, variable names, component names
- **Chinese**: User-facing UI text via i18n message files

### Naming conventions

| Item | Convention | Example |
|------|-----------|---------|
| Files | `kebab-case.tsx` | `use-task-detail.ts`, `message-bubble.tsx` |
| Components | `PascalCase` | `MessageBubble`, `TaskDag` |
| Hooks | `use` prefix | `useTaskDetail`, `useCreateTask` |
| Stores | `use*Store` | `useThreadStore`, `useWsStore` |
| Types/Interfaces | `PascalCase` | `TaskPlan`, `HiTLRequest` |
| Constants | `SCREAMING_SNAKE_CASE` | `API_BASE_URL` |

### Import order

```typescript
// 1. External libraries
import { create } from "zustand";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

// 2. Type imports (use 'import type')
import type { WsServerEvent } from "@/types/ws";

// 3. Internal modules (use @/ alias, never relative beyond ../)
import { api } from "@/lib/api-client";
import { useThreadStore } from "@/stores/thread-store";
```

### Component pattern

```typescript
"use client";  // Required for any component using hooks, state, browser APIs

import { useTranslations } from "next-intl";
import { ... } from "@/components/ui/button";
import type { ... } from "@/types/api";

export function MyComponent({ prop }: { prop: Type }) {
  const t = useTranslations("namespace");
  // hooks first, then handlers, then render
}
```

- All interactive components must have `"use client"` at top.
- Server Components (default): pages in `(admin)/*` (except users), layouts.
- Prefer `export function` over `export default function` for non-page components.

## shadcn/ui conventions

- Style: **base-nova** (uses `@base-ui/react`, NOT Radix).
- Composition uses **`render` prop**, NOT `asChild`:

```tsx
// CORRECT (base-nova)
<Button render={<Link href="/chat" />}>Go to chat</Button>

// WRONG (Radix-based shadcn)
<Button asChild><Link href="/chat">Go to chat</Link></Button>
```

- Add components via `npx shadcn@latest add <component>`.
- Icons: `lucide-react` only. Import individual icons.
- 15 UI components in `components/ui/`: avatar, badge, button, card, dialog, dropdown-menu, input, scroll-area, separator, sheet, sidebar, skeleton, sonner, textarea, tooltip.

## Styling

- **Tailwind CSS v4**: Via PostCSS plugin. No `tailwind.config.js`.
- **CSS variables**: OKLCH color space, defined in `globals.css` `:root` and `.dark`.
- **Fonts**: Geist Sans + Geist Mono (loaded via `next/font/google`).
- **Dark mode**: `next-themes` with `attribute="class"`. `ThemeProvider` wraps app in `providers.tsx`.
- **Markdown rendering**: `streamdown` library with `code` and `cjk` plugins.
- **Animations**: `tw-animate-css`.

## Types (mirrors backend)

`types/api.ts` mirrors backend `core/state.py` + `api/routes.py`:

| Frontend type | Backend model |
|---------------|--------------|
| `TaskPlan` | `state.TaskPlan` |
| `HiTLRequest` | `state.HiTLRequest` |
| `TaskResponse` | `routes.TaskResponse` |
| `PersonaInfo` | `persona_factory` output |

`types/ws.ts` defines discriminated unions for WS events:

```typescript
export type WsServerEvent =
  | { type: "task.created"; thread_id: string; intent: string }
  | { type: "task.completed"; thread_id: string; result?: string }
  | ...
```

When backend Pydantic models change, update `types/api.ts` and `types/ws.ts` accordingly.

## WebSocket

`lib/ws.ts` — `UsamiWebSocket` class:

- Client ID persisted in `sessionStorage` (`usami_client_id`).
- Auto-reconnect with exponential backoff: 1s → 2s → 4s → ... → 30s max.
- Token auth via `?token=<accessToken>` query param.
- URL auto-detected from `window.location` at runtime (no build-time env var needed).

## Routing

- **Route groups**: `(main)/` for C端, `(admin)/` for admin. Completely separate layouts.
- **Dynamic routes**: `[threadId]` for task detail and shared views.
- **Next.js rewrites**: `/api/*` → backend, `/health` → backend health. Configured in `next.config.ts`.
- **Async params**: Use React 19 `use()` to unwrap `params` promise in dynamic route pages:

```typescript
import { use } from "react";
export default function Page({ params }: { params: Promise<{ threadId: string }> }) {
  const { threadId } = use(params);
}
```

## Environment variables

| Variable | Context | Default | Purpose |
|----------|---------|---------|---------|
| `NEXT_PUBLIC_API_URL` | Client | `""` (empty) | API base URL, empty = use rewrite |
| `NEXT_PUBLIC_WS_URL` | Client | auto-detect | WS URL, auto-derived from `window.location` |
| `BACKEND_INTERNAL_URL` | Server | `http://localhost:8000` | Direct backend for SSR/rewrite |

## Do NOT

- Put Zustand stores or hooks in `components/ui/` — those are shadcn primitives only.
- Use `asChild` prop — use `render` prop (base-nova style).
- Import `api-server.ts` in Client Components — it's Server Component only.
- Import `api-client.ts` in Server Components — it uses `window` for 401 redirect.
- Add `"use client"` to layout files unless they need client-side state.
- Use relative imports beyond `../` — always use `@/` alias.
- Manually manage message arrays — derive them from thread events via `useDerivedMessages`.
- Create new Zustand stores without documenting them here.
- Hardcode Chinese strings in components — use `useTranslations()` from next-intl.
- Mix C端 and admin routes in the same route group — they are separate sub-applications.
