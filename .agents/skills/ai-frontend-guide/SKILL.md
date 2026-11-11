---
name: ai-frontend-guide
description: Reuse-first UI workflow for frontend projects and the entry point for ANY design conversation in a project that contains the ai-frontend-guide-kit folder. Use whenever the user talks about design, redesign, restyle, UI, UX, look and feel, theme, colors, typography, fonts, spacing, layout, screens, pages, landing pages, dashboards, components, forms, animations or polish ("diseño", "rediseñar", "estilo", "aspecto", "tema", "colores", "tipografía", "fuentes", "espaciado", "maquetación", "pantalla", "página", "componente", "formulario", "animación", "pulir"), before other design skills (landing-page-design, hallmark, design-taste-frontend, emilkowalski and impeccable run only at the step guide 00 gives them, never as the entry point). Decide the experience direction first (adaptive questions guided by the local Laya engine), consult the local component catalog before writing custom code, follow the guided flow in three on-demand phases (experience + UX/theory, composition, total polish), and optionally rank candidates with Laya after asking the user once per session. Covers interactive reference discovery (example sites with the user, likes and screenshots, component combinations), catalog discovery, reuse/adapt/build decisions, installation, licensing, playbook for small changes/custom additions, the Excalidraw UX map and verification with Playwright MCP.
---

# AI Frontend Guide

Reusable-first UI workflow for AI agents. The point: **search what already exists before creating anything from scratch** — and **choose the experience direction before choosing visuals**.

## What you have

When this kit is installed, the project contains:

- `ai-frontend-guide-kit/INDEX.md` — the global index, read this first (when the flow applies, the first command, the routes, the tool for each job).
- `ai-frontend-guide-kit/AGENTS.md` — awareness layer.
- `ai-frontend-guide-kit/guides/00…10` — the guided workflow (router + direction + three phases + iteration).
- `ai-frontend-guide-kit/experience/` — direction knowledge: `EXPERIENCE-DIRECTION.md`, `QUESTION-BANK.md`, `SITE-ARCHETYPES.md`, `UX-PHILOSOPHIES.md`, `STYLE-DIRECTIONS.md`, `REFERENCE-PROTOCOL.md`, `DISCOVERY-LOOP.md`, `experience-manifest.json` and `references/` (saved idea cards).
- `ai-frontend-guide-kit/catalog/` — 4,287 reusable entries from 34 verified sources (licenses, install commands, links), plus a light index.
- `ai-frontend-guide-kit/tools/` — `flow.mjs` (the route and step of this project), `context.mjs` (stack, screens and UI libraries), `find.mjs`, `get.mjs`, `memory.mjs` (decisions and libraries), `ui-map.mjs`, `laya_select.py` and `excalidraw-mcp.mjs` (local, dependency-free Excalidraw MCP).
- Sibling skills (when installed): `frontend-polish` (total polish phase), `frontend-refactor` (FSD structure, only on explicit request), `ux-map` (visual screen map) and the external design skills, each at its step of the flow: `landing-page-design` (phase 1, landing pages only), `hallmark` and `design-taste-frontend` (build only in phase 2, for decision `build`, and `design-taste-frontend` also for an agreed visual redesign; raw material without building in phase 1; `hallmark` also gives a report-only audit in phase 3), `emilkowalski` (phases 2–3), `impeccable` (phase 3). Details in `guides/00-START-HERE.md`, "External design skills by step".

If the folder is missing, install it with:

```bash
npx github:urben88/ai-frontend-guide-kit
```

## Route first (intake)

Ask the user what they want before touching code and declare the route: new frontend (phases 1→2→3), direction only (`01-EXPERIENCE-DIRECTION.md`), small change or custom addition (`10-ITERATE.md`), polish only (phase 3), UX only (`02-UX-FLOWS.md`). The phases are entry points, not a fixed pipeline.

The route lives in the project, so everyone who talks about the design follows the same step:

```bash
node ai-frontend-guide-kit/tools/flow.mjs status          # kit installed? active route and step, what is recorded
node ai-frontend-guide-kit/tools/flow.mjs start <route>   # new | direction | ux | iterate | polish | redesign | visual-feedback | architecture
node ai-frontend-guide-kit/tools/flow.mjs next            # current step: guide, skill, tools, output
node ai-frontend-guide-kit/tools/flow.mjs done <step>     # refuses a skipped step or a missing artifact (--evidence for steps without a file)
```

When the user links a component site, run `node ai-frontend-guide-kit/tools/scout.mjs <url>` (add `--fetch` for an unknown site, `--record` to keep it) instead of reading the whole site; start from `ai-frontend-guide-kit/catalog/digest.md` for an overview of the catalog.

Never skip a step: when `done` refuses, produce the missing artifact first. Every route, step and skill is listed in `ai-frontend-guide-kit/guides/FLOWS.md`; when the user asks which flows exist, answer from it and recommend the route that fits.

## Start here

1. Read `ai-frontend-guide-kit/AGENTS.md`.
2. Follow the phase that matches the route — read **only the guide for the current phase/step**:

| Phase | Guide | Output |
|---|---|---|
| 0 · Intake | `00-START-HERE.md` | route declared + phase map |
| 1 · UX & theory | `01-EXPERIENCE-DIRECTION.md` | `EXPERIENCE-BRIEF.md` (archetype, philosophy, journey, IA, 3 directions, visual brief) |
| 1 · UX & theory | `02-UX-FLOWS.md`, `03-TOKENS.md` | context + `PRODUCT.md` + `UX-SPEC.md` + `flow-report.html` + `ux-map.excalidraw` + `DESIGN.md` |
| 2 · Composition | `04-INVENTORY.md` … `07-ADAPT.md` | inventory, shortlist, reuse/adapt/build + install, adapted components |
| 3 · Total polish | `frontend-polish` skill + `08-PHILOSOPHY.md`, `09-VERIFY.md` | audits + Playwright MCP loop + E2E/visual checks green |
| Iterate | `10-ITERATE.md` | small changes and custom additions |
| Visual feedback (optional, React) | `11-VISUAL-FEEDBACK.md` | the user clicks elements in the browser (Agentation MCP); the agent changes exactly those |

## Frontend map (always on)

The installer keeps `ai-frontend-output/UI-MAP.md` (plus `ui-map.json`, `ui-history.jsonl`) up to date. Read it instead of exploring the repo. Before changing UI run `node ai-frontend-guide-kit/tools/ui-map.mjs impact <role|component>`; before creating run `node ai-frontend-guide-kit/tools/ui-map.mjs have <name>`; to see what the profile treats as required run `node ai-frontend-guide-kit/tools/ui-map.mjs check --profile sprint|standard|long-term`. Existing violations are recorded, never changed unless the user asks (`guides/08-PHILOSOPHY.md`, Separation).

## Pieces (the project's own reusable components)

Pieces (`node tools/pieces.mjs`) are the project's own components, registered where its architecture already keeps them (for example `src/components/`); the kit never copies or stores component code, only metadata, history and an index. Before creating any component run `pieces find "<need>"`: your own piece, a new variant of a close piece, a piece of another registered project (`pieces adopt` copies its file into this project), the kit catalog, and only then a new piece (`add` refuses otherwise unless `--new --reason "..."`). A polish request ("más espaciado", "more image") means editing the component file and then `pieces version <name>`, or a new variant, never a new piece. Without waiting to be asked, record `pieces use` when a piece goes into the project, `version` after the user adjusts it, `like`/`dislike` when they react, and `note` for any remark. Say where a component came from: `node tools/get.mjs <id> --landed <path>` registers a catalog component that landed in the project (origin `catalog:<id>`); for one from the internet use `pieces add ... --origin internet:<url>`; set `--relation` to `chosen` (used as is), `modified` (adapted) or `copied` (traced from a reference). The project keeps only its personality and usage in `ai-frontend-output/pieces/` (`pieces personality set <key> <value>`).

## Architecture (FSD only on request)

The folder structure is a separate decision (`guides/12-ARCHITECTURE.md`): `map` is the default and only records folder roles in `ai-frontend-output/architecture.json`; `fsd-new` (a new project) and `fsd-refactor` (an existing one) run **only when the user asks**, through the sibling `frontend-refactor` skill, one approved slice at a time. Never apply FSD unasked, never silently, not even on a greenfield repo, and never rename FSD layers onto the kit's roles or component types.

## Experience direction first (guide 01)

For a new frontend or redesign, run the direction phase before any UI:

- Adaptive questions in rounds of 3–5 from `experience/QUESTION-BANK.md`; never ask what the repo/PRD already answers.
- Optional Laya ranking: `--dataset experience --kind question --task next-question` (which question next) and `--kind archetype|philosophy|style --task direction` (which direction fits).
- (Recommended) Run the discovery loop (`experience/DISCOVERY-LOOP.md`, phase A) before the three directions: idea deck of example sites with their structure, browsing round with the user, screenshots in `ai-frontend-output/ux/references/`, picks cited as `[ref: <slug>]` and recorded with `--ref "reference:<slug>"`.
- Write `ai-frontend-output/ux/EXPERIENCE-BRIEF.md` with three directions (safe/differentiated/experimental), the chosen one and the visual brief. **Gate:** no `02-UX-FLOWS` without it.
- Apply the anti-generic list and the purpose/convergence tests from `experience/STYLE-DIRECTIONS.md`.

## UX phase (proven flows)

Run `02-UX-FLOWS` with the bundled UX flow skills (`userflow` + 15 `flow-*`: auth, onboarding, checkout, paywall, settings, navigation, tables, forms, errors, empty states, AI chat…).

```bash
node ai-frontend-guide-kit/tools/context.mjs   # → ai-frontend-output/ux/REPO-CONTEXT.md (incl. ux_present)
```

Then follow `ai-frontend-guide-kit/guides/02-UX-FLOWS.md`:

- No UX in the repo → design from scratch with `userflow` (load 1–4 flow skills, never from memory) → `UX-SPEC.md` + `flow-report.html` + `ux-map.excalidraw`.
- UX exists → **ask the user once**: Summarize (as-is + audit, no changes) or Radical redesign (baseline → ideal UX → diff). Never redesign silently; redesign is UX-only (`PRODUCT.md` stays).
- Single surface → `/userflow audit …` (findings only).

The visual screen map is part of the phase: use the sibling `ux-map` skill with the local Excalidraw MCP (`tools/excalidraw-mcp.mjs`). The template comes from the brief's `navigation_model` (`one-page`, `flow`, `hub`, `catalog`, `console`, `tree`), areas/colors from the brief IA, and the legend includes the direction (+ `P(fit)` when Laya ranked). Redesign snapshots `ux-map-baseline.excalidraw` first; the map is maintained incrementally, never regenerated blind. If the MCP is unavailable, use the skill's manual fallback and say so.

**BMAD / spec-driven repos:** `context.mjs` detects them (`Framework:` in `REPO-CONTEXT.md`). Read `ai-frontend-guide-kit/guides/ADAPTERS.md`: with a BMAD PRD use it as the business anchor (no duplicate `PRODUCT.md`) and cite stories with `--ref "story:<id>"`; with OpenSpec, specs are the behavioral source of truth and decisions cite `--ref "spec:<capability>"`.

The UI inventory and memory `--screen/--block` names come from `UX-SPEC.md`.

## Total polish (phase 3)

Before closing a screen, run the sibling skill `frontend-polish` when installed: external audits (`impeccable`, `hallmark`, emilkowalski, plus the checks of `design-taste-frontend` when it built the screen) if available, the Playwright MCP loop (states, console, accessibility, keyboard, reduced motion, responsive) and the closing `@playwright/test` regression of `09-VERIFY`. Fallback without tools: the distilled checklist of `08-PHILOSOPHY`. In React projects, offer the optional human round (the user points at elements with Agentation; see `11-VISUAL-FEEDBACK.md`, which holds the install message) during composition for fine tweaks or at the end of polish.

## Query the catalog (do this before writing components)

```bash
node ai-frontend-guide-kit/tools/find.mjs --category hero --stack react --commercial
node ai-frontend-guide-kit/tools/find.mjs --text marquee --limit 8
node ai-frontend-guide-kit/tools/get.mjs <entry-id>   # license, deps, install command
```

Rules:

- **Reuse → adapt → build.** Create custom only when nothing fits or the license blocks you.
- Licenses are facts: check `license_type` / `commercial_use` in `get` before using anything.
  Never use `non-commercial` entries in commercial work; verify `unknown` ones on their page.
- Before closing a selection, present 2–3 **combinations** with rationale and `get` facts; web-discovered components stay `provisional` until their license is verified (`experience/DISCOVERY-LOOP.md`, phase B).
- Keep high-impact animations to 1–2 per view and respect the brief's anti-generic list.

## Selection memory (`ai-frontend-output/`)

Keep a reusable history of decisions and combinations (the folder survives kit refreshes):

```bash
node ai-frontend-guide-kit/tools/memory.mjs combo list     # check saved combinations BEFORE searching
node ai-frontend-guide-kit/tools/memory.mjs add --screen <screen> --block <block> --need "..." \
  --decision reuse|adapt|build --id <entry-id> [--style a,b] [--notes "..."]
node ai-frontend-guide-kit/tools/memory.mjs add --screen experience --block direction \
  --need "..." --decision adapt --ref "direction:<id>"
node ai-frontend-guide-kit/tools/memory.mjs combo save <name> --note "..."   # snapshot for reuse
node ai-frontend-guide-kit/tools/memory.mjs combo show <name>                # entries + install commands
node ai-frontend-guide-kit/tools/memory.mjs combo apply <name>               # reuse in this project
```

Rules: check combinations before searching; record **every** decision right after choosing (facts come from the catalog); `ai-frontend-output/SUMMARY.md` is the generated styles/components summary.

## Laya (optional local ranking — consent once per session)

`laya_select.py` ranks questions, experience directions and components with calibrated probabilities, running entirely on this PC. **It is opt-in:** ask the user once per session/project, record `laya_consent` in `EXPERIENCE-BRIEF.md`, then use `--confirmed` per call. For components, `--direction <id>` passes the chosen direction into the ranking state so the fit matches the UX direction.

```bash
python ai-frontend-guide-kit/tools/laya_select.py --check      # ready? (exit 0)
python ai-frontend-guide-kit/tools/laya_select.py --need "…" --dry-run   # preview, no model
# after consent, pick the command matching the task:
python ai-frontend-guide-kit/tools/laya_select.py --dataset experience --kind question \
  --task next-question --context-file ai-frontend-output/ux/EXPERIENCE-BRIEF.md --confirmed
python ai-frontend-guide-kit/tools/laya_select.py --dataset experience --kind archetype \
  --task direction --context-file ai-frontend-output/ux/EXPERIENCE-BRIEF.md --confirmed
python ai-frontend-guide-kit/tools/laya_select.py --need "…" --category <category> --commercial \
  --direction <experience-id> --context-file ai-frontend-output/ux/EXPERIENCE-BRIEF.md --confirmed
```

Without consent the script exits with code 3 and does not load the model. If Python/Laya is unavailable, continue with the question tree, the heuristic tables and `find`/`get` — the workflow never depends on Laya. Laya scores semantic fit only; licenses and install commands always come from the catalog.

## Do not

- Do not read the whole catalog or the whole `experience-manifest.json` into context: use `find`/`get`, the index cards and dry-runs.
- Do not copy third-party component source into the kit.
- Do not strip license notices from copied components.
