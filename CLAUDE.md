# Project instructions for Claude Code

<!-- ai-frontend-guide-kit:start -->
## Frontend, UI and design: always this flow (ai-frontend-guide-kit)
**Mandatory.** Any request about frontend, UI, UX, design, a screen, page, component, style or polish, however small,
starts like this, before any file is read or edited:
1. Read `ai-frontend-guide-kit/INDEX.md`.
2. Run `node ai-frontend-guide-kit/tools/flow.mjs status`, declare the route with `flow.mjs start <route>` (a small change
   is route `iterate`), follow `flow.mjs next` and close each step with `flow.mjs done <step>`, which refuses a skipped step.
The flow is never skipped. Routes: `ai-frontend-guide-kit/guides/FLOWS.md`; full rules: `ai-frontend-guide-kit/AGENTS.md`.
Triggers: design, redesign, restyle, UI, UX, look and feel, theme, colors, typography, fonts, spacing, layout, screen, page,
landing, dashboard, component, form, animation, polish; diseño, rediseñar, estilo, aspecto, tema, colores, tipografía,
fuentes, espaciado, maquetación, pantalla, página, landing, componente, formulario, animación, pulir.
Reuse before building: `node ai-frontend-guide-kit/tools/pieces.mjs find "<need>"` before any component, and
`node ai-frontend-guide-kit/tools/ui-map.mjs impact <role|component>` / `ui-map.mjs have <name>` before changing UI
(read `ai-frontend-output/UI-MAP.md`, do not explore the repo). Record every decision with `tools/memory.mjs add`, and every
piece use, version and reaction with `tools/pieces.mjs`.
External design skills never start the work; each runs only at its step (`guides/00-START-HERE.md`): landing-page-design in phase 1
(landing pages), hallmark and design-taste-frontend only to build in phase 2, emilkowalski in phases 2-3, impeccable in phase 3
through `frontend-polish` (Playwright MCP). UX map: skill `ux-map`.
On "what is this", "qué puedo pedirle", "dame un resumen de esta herramienta": read `ai-frontend-guide-kit/HELP.md`
(Spanish: `HELP.es.md`) and answer from it; never explore the folders to explain the kit.
<!-- ai-frontend-guide-kit:end -->
