---
name: frontend-refactor
description: "Use only on explicit request when the user asks to restructure an existing frontend into Feature-Sliced Design (FSD) layers, or to map a project's folders onto FSD roles without moving code. Triggers: \"refactor to FSD\", \"refactoriza a FSD\", \"aplica FSD\", \"migrate to Feature-Sliced\", \"reestructura el frontend\", \"map the folders to FSD layers\". Never restructures a project that did not ask. Runs one slice at a time, follows the official FSD migration guide, and verifies each slice with `ui-map build` and `ui-map check`."
---

# Frontend Refactor — FSD only on request

Restructures an existing frontend so it follows Feature-Sliced Design, **only when the user asks for it in this conversation**. The philosophy of `08-PHILOSOPHY.md` (one responsibility, one owner per visual role, UI apart from logic, reuse before creating) already applies to new code without this skill; FSD is one way to enforce it, never a requirement and never a silent default.

**This skill never restructures a project that did not ask.** A request to review, document or map the architecture is not a request to move files: answer it with `mode: "map"` (the `architecture.json` below) and change nothing.

## Gate — before any edit

1. The user asked for the refactor explicitly, in this conversation. "We will need it eventually" does not count.
2. Read `ai-frontend-guide-kit/guides/12-ARCHITECTURE.md` (modes, layers, framework adapters).
3. Read `ai-frontend-guide-kit/guides/08-PHILOSOPHY.md`, section `Separation`, and `ai-frontend-output/UI-MAP.md` — the map is the inventory you will keep true.
4. Confirm the scope: which folders, which layers, and whether the framework's routing moves at all. If the answer is not in the request, ask once and stop.

If any of those is missing, do not edit anything.

## Step 1 — Write the map first

Write `ai-frontend-output/architecture.json` with `"mode": "fsd-refactor"` before touching a single file, using the schema in guide 12:

```json
{
  "version": 1,
  "mode": "fsd-refactor",
  "framework": "<detected stack>",
  "layers": { "<layer>": ["<existing folder>"] },
  "unmapped": ["<folder that does not fit>"],
  "notes": "<what is planned and what stays>"
}
```

- It maps existing folders to FSD roles. It **never renames or moves anything by itself**.
- Folders that have no honest home go in `unmapped`: record them instead of inventing a layer.
- Only the layers the project needs. A small app may be `shared` + `pages`; a marketing site may have no FSD structure at all.

## Step 2 — Follow the official migration guide, one slice at a time

Use the official guide: https://feature-sliced.design/docs/guides/migration/from-custom

1. Pick the **first slice** with the user: one layer or one slice, not the repository.
2. Move or rewrite only that slice; the framework adapter of guide 12 decides what stays put. Keep the project's routing where the official guide keeps it (Next.js `app/` and `pages/`, Nuxt `dir.pages`, SvelteKit `routes` at the root) — routing is the framework's, not FSD's.
3. Do not rename FSD layers onto the kit's vocabulary. Layers keep their FSD names; the kit's visual roles and component types describe what a component does *inside* a layer and never replace its name.
4. Run the checks for this slice (step 3), report, then wait for the user before the next one.

## Step 3 — Verify each slice

```bash
node ai-frontend-guide-kit/tools/ui-map.mjs build
node ai-frontend-guide-kit/tools/ui-map.mjs check
```

- Both are mandatory after every slice, and their output is part of the migration: a new **stray**, **duplicate component type**, **ownerless visual role** or **unresolved import** is a defect this refactor introduced, not noise to ignore.
- Compare against the previous run: the slice must not add findings. `ui-map impact <role|component>` locates every owner and user of what moved.
- Behaviour is not negotiable: no test may change its expectations because a folder moved. If a change would alter behaviour, that is a separate request.

## Step 4 — Stop and report between slices

After each slice, report and stop:

- what moved (folders, files), and what `architecture.json` now says;
- the `build` and `check` output, with the findings that remain and why;
- what is left, and which slice you propose next.

Never chain slices on your own. Never run a big-bang restructure in one turn.

## Hard rules

| Never | Instead |
|---|---|
| Restructure a project that did not ask | Answer with `mode: "map"` and change nothing |
| Apply FSD to a new project silently | `fsd-new`, only after the request of guide 12 |
| Rename a layer to a kit role or component type | Keep `app`, `pages`, `widgets`, `features`, `entities`, `shared` |
| Move the framework's routing folders | Keep them where the framework (and its official FSD guide) expects them |
| Ignore a stray, duplicate type, ownerless role or unresolved import | Treat it as part of the migration and fix or report it |
| Move everything, then verify | Verify and report after each slice |

## Limits

- Steiger (`npx steiger <src>`) is the official FSD linter and is in beta: it is a second opinion, never the gate.
- `architecture.json` is a folder map, not proof that a boundary holds.
- Stacks without an official FSD guide (React Router, Vite, Angular) are a kit proposal: say so when you map them.

## Done when

- `ai-frontend-output/architecture.json` matches the folders on disk and states `fsd-refactor`.
- `ui-map build` and `ui-map check` run clean of new findings, slice by slice, with the output shown.
- `ARCHITECTURE.md` and the route/map documents describe the same structure (`guides/13-CONTEXT-DOCS.md`).
- The user knows what is done, what is left and what it cost — no hidden restructuring.
