---
name: frontend-polish
description: "Use when the user asks to polish, refine, QA or do a final visual review of frontend UI (\"pulir\", \"polish\", \"revisión final\", \"QA visual\", \"dejar impecable\", \"revisar el diseño\", \"dar el último pase\"). Runs the total polish loop: audits with the external design skills when installed (impeccable, hallmark, emilkowalski, plus the checks of design-taste-frontend on a screen it built), an interactive pass with Playwright MCP over states, console, accessibility, keyboard and reduced motion, exact fixes, a closing @playwright/test regression, and an optional human round where the user points at elements in the browser (Agentation MCP, React). Works with fallbacks when those tools are missing."
---

# Frontend Polish — total finish pass

Phase 3 of the `ai-frontend-guide-kit` workflow. Goal: a screen that survives scrutiny — correct business flow, deliberate craft, nothing generic, no console noise.

## When to use

- "Pulir", "polish", "revisión final", "QA visual", "dejar impecable", "last pass" on a screen or block.
- After composition (phase 2) or after any small change (see `10-ITERATE.md`).
- **NOT for**: changing flows or restructuring screens — that is the UX phase (`02-UX-FLOWS.md`); polish never redesigns silently.

## Step 0 — Scope and context (always)

1. Ask/confirm the scope: which screen, route or block; which states matter. One screen per pass.
2. Read the existing artifacts, do not re-explore the repo: `ai-frontend-output/ux/EXPERIENCE-BRIEF.md`, `ai-frontend-output/ux/UX-SPEC.md`, `DESIGN.md`, `PRODUCT.md`, and the `06-REUSE` decision log if present.
3. Look at what changed: `git status` + `git diff --stat` (polish what moved, not the whole app).
4. Declare the plan in one line: screen + states + tools available.

## Step 1 — External audits (only if installed)

Skills are opt-in by their own descriptions; load them when present, never assume slash commands:

- **`impeccable`** (if installed): the primary craft checklist. Run its `critique` workflow on the screen (scored UX review), then `audit` (accessibility, performance, theming, responsive), then `polish`. Also run `npx impeccable detect <dir-or-url>`: deterministic rules, no LLM.
- **`hallmark`** (if installed): second opinion, report only, for pages and sites. It audits only when named, so say "use hallmark to audit <path>", and run `node <skill-dir>/scripts/sloplint.mjs <path> --render`. Static checks run without a browser; browser checks need `puppeteer-core` and Chrome.
- **`design-taste-frontend`** (if installed): only when it built or redesigned this screen. Its lint and browser inspection must be green. It is a page builder, not a review pass: do not start it here on a screen it did not build.
- **emilkowalski** (if installed): `review-animations` (or `improve-animations`) when the screen has motion; `emil-design-eng` for interaction physics.
- If none are installed, use the distilled checklist in `guides/08-PHILOSOPHY.md` (anti-generic rules, springs, effect budget).

If a check of an installed skill cannot run (older Node, no browser, offline), say which one and continue with the others; never report it as passed. Taste's checks need Node 22+ and Chrome, Edge or Chromium.

Impeccable's `bolder` and `quieter` workflows change the design direction. If the critique says the screen is too safe or too loud, tell the user and run them only if the user agrees.

Merge duplicate findings across skills. Record every accepted finding with its fix; do not apply an external suggestion that contradicts `PRODUCT.md`, tokens or the license rules.

## Step 2 — Playwright MCP pass (the loop)

If Playwright MCP is configured, verify the browser once (`npx playwright install chromium`), start the dev server, then iterate:

1. **Navigate** to the screen and take an accessibility `snapshot` — it is the ground truth for roles, names and focus order.
2. **Console**: read console messages; any error/warning is a finding.
3. **States**: capture and review each state that carries intent — default, hover, focus-visible, active/pressed, loading, empty, error, disabled, success. Screenshot before/after every fix.
4. **Keyboard**: traverse the screen with Tab/Shift+Tab/Enter/Escape; focus must be visible, ordered and trapped only where it should be (modals).
5. **Reduced motion**: emulate `prefers-reduced-motion: reduce`; animations must degrade to no-motion or opacity-only.
6. **Responsive**: resize to the project's breakpoints (e.g. 375 / 768 / 1280 / 1536); check layout collapse, overflow and touch targets (≥ 44px).
7. **Content**: text hierarchy (max 3 sizes), contrast (body ≥ 4.5:1, large ≥ 3:1), spacing from the scale, no boxes-inside-boxes.
8. **Automated a11y and performance**: run the axe and Lighthouse checks from `guides/09-VERIFY.md` (sections 4–5) and the honesty audit (section 6) for conversion flows.
9. **Fix exactly what was reported**, then re-run the affected checks. No finding is closed without a re-check.

Report each iteration with evidence: state + screenshot + what changed. Keep a running findings list (optionally `ai-frontend-output/polish-report.md`).

## Step 3 — Regression gate

Close with `guides/09-VERIFY.md`:

- `npx playwright test` — critical funnel E2E + visual snapshots for the polished states.
- Red test = not done; fix the exact reported issue and re-run the full suite.

## Step 3b — Human round with Agentation (optional)

Offer it when the project is React and the user wants to point at specifics. If the `agentation` MCP tools are available, follow the agent loop of `guides/11-VISUAL-FEEDBACK.md` (watch → acknowledge → smallest change → re-check → resolve), then re-run the Step 3 gate. If they are not, give the user the install message from that guide (`npm install agentation -D`, `claude mcp add agentation -- npx -y agentation-mcp server`, `npx agentation-mcp doctor`, `<Agentation endpoint="http://localhost:4747" />` in dev only) and continue; never block the pass on it.

## Step 4 — Close

- Checklist from `09-VERIFY.md` (reduced motion, keyboard, console, licenses) is green.
- Effect budget respected: max 1–2 high-impact effects per view; effects do not compete.
- If the pass changed a component decision (replaced/adapted a catalog entry), record it: `node ai-frontend-guide-kit/tools/memory.mjs add --screen ... --block ... --need "..." --decision reuse|adapt|build [--id <entry-id>]`.
- Summarize: findings found, fixes applied, checks run, anything deliberately left open.

## Fallback without tools

- No Playwright MCP → use the `@playwright/test` suite from guide 09 plus the self-review checklist of `08-PHILOSOPHY.md`; state clearly which interactive checks could not be run.
- No external skills → apply the distilled rules of `08-PHILOSOPHY.md`.
- Never block the pass on missing tools; never claim a check that was not executed.

## Rules

- One screen per pass; keep reads token-thin (never load the whole catalog).
- Polish does not change UX flows, copy strategy or component choice beyond what the audit justifies.
- Licenses stay intact for reused components (no stripping notices).
- If a finding implies a UX change, stop and hand it to the UX phase with user consent.
