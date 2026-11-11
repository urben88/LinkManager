---
name: ux-map
description: "Use when generating or maintaining the visual screen map of an app in Excalidraw: pages as rectangles, labeled buttons/actions as arrows, drawn as a connected navigation network. Triggers: \"mapa visual\", \"mapa de pantallas\", \"wireframe de navegación\", \"diagrama de flujos\", \"boceto de las páginas\", \"excalidraw\", \"actualizar el mapa\", and the end of the UX phase in `02-UX-FLOWS.md`. Maintains `ai-frontend-output/ux/ux-map.excalidraw` incrementally through the local Excalidraw MCP, with a manual fallback when the MCP is unavailable."
---

# UX Map — visual screen map (Excalidraw)

Living map of how the app's screens are structured and communicate: one node per screen or section, one labeled arrow per navigating action, laid out by the direction chosen in `EXPERIENCE-BRIEF.md`. Output of the UX phase, updated (never regenerated) as the UX evolves.

## Artifact

`ai-frontend-output/ux/ux-map.excalidraw` — single source of truth (do NOT keep a parallel JSON). Open it with Excalidraw (excalidraw.com or the VS Code extension). The installer creates the empty scaffold; the local MCP creates it too if missing.

## Template selection (direction-aware)

Read `ai-frontend-output/ux/EXPERIENCE-BRIEF.md` first and take its `navigation_model`:

| navigation_model | Template | Layout | Node meaning | Typical areas (from the brief IA) |
|---|---|---|---|---|
| `single-page-anchors` | `one-page` | single vertical spine; anchors as edges; final CTA at the bottom | section of the page | journey stages |
| `linear-wizard` | `flow` | steps left→right in rows; diamond for branches; dashed for optional/skip | step/screen | step groups |
| `hub` | `hub` | start node + clusters by area (columns) | screen/panel | IA areas |
| `catalog` | `catalog` | discovery → decision → transaction areas with return loops | listing/detail/action | discovery/decision/transaction/account |
| `console` | `console` | modules/panels by area; persistent nav | module/screen | modules/alerts/states |
| `tree` | `tree` | home → sections by depth | page/section | site sections |

- **Areas and colors come from the brief**, not from a fixed set: assign a color preset per area in IA order (`light-purple`, `light-blue`, `light-green`, `light-yellow`, `light-orange`, `light-red`), plus `yellow` for the start ellipse.
- Rows follow the journey stages when the brief defines them; otherwise flow order (landing row 0, onboarding row 1, app rows 2+).
- Coordinates: `x = column * 400`, `y = row * 240`; `width = 280`, height auto. Start node at `y = -240`. Leave one empty cell between clusters.

## Node label — stable and exact

```
{Nombre exacto de pantalla de UX-SPEC.md}
CTA: {acción primaria}
Bloques: {bloque1} · {bloque2} · {bloque3}
```

- For `one-page`, the name is `{Página} ▸ {Sección}` and each section is a node (anchors = edges).
- The name MUST equal the name in `UX-SPEC.md`: it is the key used by `createEdge`/`deleteElement` (by label) and keeps map and spec coherent.
- 2–4 key blocks max; no prose, no every-field detail.
- Optional `link` on the node to the real route/component when the screen already exists in the repo.

## Legend (required)

Add a start-area text node or first node with:

```
Dirección: {arquetipo elegido} · {filosofía}
Navegación: {navigation_model}
P(fit Laya): {probabilidad o "no ranking"}
```

Only include `P(fit Laya)` when Laya scored the direction; otherwise write `no ranking`.

## Edges — one per action

- `createEdge(from=<screen label>, to=<screen label>, label=<texto real del botón o enlace>)`.
- Label = the real action text that navigates ("Iniciar sesión", "Ir al dashboard"), not an abstraction.
- `style: "dashed"` for secondary or optional flows (forgot password, legal, "skip", optional wizard branches).
- Two actions to the same screen = two arrows with distinct labels. Never invent transitions: they come from the flows of `UX-SPEC.md`.

## MCP tools (server `excalidraw`, local `ai-frontend-guide-kit/tools/excalidraw-mcp.mjs`)

The kit ships a **local, dependency-free MCP server** (`node ai-frontend-guide-kit/tools/excalidraw-mcp.mjs --diagram ai-frontend-output/ux/ux-map.excalidraw`): offline, no `npx`, no install. It creates the file if missing and never fails on a missing scaffold.

| Tool | Use |
|---|---|
| `getFullDiagramState` | Read the current map (nodes, edges, labels) before touching anything |
| `createNode` | Add a screen/section/start/legend node (`label`, `shape`, `color`, `x`, `y`, `width`, optional `link`) |
| `createEdge` | Add a labeled arrow between nodes, referenced by label text or id |
| `deleteElement` | Remove a node or edge by label text or id (its labels and attached arrows go with it) |

## First build

1. Read `EXPERIENCE-BRIEF.md` (direction, navigation model, areas, journey) and `UX-SPEC.md` (screens, flows, states) — never explore the repo for this.
2. Pick the template from `navigation_model`; assign areas/colors from the brief IA.
3. Group nodes by area and order them by journey/flow to get each `(column, row)`.
4. `createNode` the INICIO ellipse, the legend and every screen/section with explicit `x`/`y` and the area color.
5. `createEdge` every transition from the flows, with the action text as label.
6. Verify with `getFullDiagramState`: every UX-SPEC screen has a node, every flow step has an arrow, no orphan nodes.

## Maintenance — incremental, never blind

1. `getFullDiagramState` first (always).
2. **New screen** → `createNode` in its area/row (shift later rows if needed; keep one-cell gaps).
3. **New transition** → `createEdge` by label.
4. **Removed screen** → `deleteElement(<label>)`.
5. **Renamed screen** → `deleteElement` + `createNode` with the new name + recreate its arrows.
6. **Changed action** → delete the old edge by label and `createEdge` with the new text.
7. Re-run `getFullDiagramState` to confirm. Manual styling tweaks made in Excalidraw survive as long as you only add/delete what changed.

Update the map in the same pass as the UX change (guide 02, redesign, or `10-ITERATE.md` when screens/navigation move).

## Redesign (UX path C)

Before touching the map, copy the file: `ux-map.excalidraw` → `ux-map-baseline.excalidraw` (plain JSON copy), in parallel with `UX-BASELINE.md`. Then apply the maintenance steps to reach the ideal UX; `UX-DIFF.md` describes added/removed/restructured screens and transitions.

## Fallback without MCP

If the `excalidraw` server is unavailable (harness without MCP, error):

- Create/patch the JSON directly; keep it valid. Minimal empty scaffold:

```json
{ "type": "excalidraw", "version": 2, "source": "https://excalidraw.com", "elements": [], "appState": { "gridSize": null, "viewBackgroundColor": "#ffffff" }, "files": {} }
```

- Manual node = rectangle element + text element. Copy the shape of existing elements when present; for a new file use this pattern (repeat per screen with its `x`, `y` and color; arrow elements may omit bindings):

```json
{ "id": "screen-1", "type": "rectangle", "x": 0, "y": 0, "width": 280, "height": 120, "angle": 0, "strokeColor": "#6c8ebf", "backgroundColor": "#dae8fc", "fillStyle": "solid", "strokeWidth": 1.4, "strokeStyle": "solid", "roughness": 1, "opacity": 100, "groupIds": [], "frameId": null, "roundness": { "type": 3 }, "seed": 1, "version": 1, "versionNonce": 1, "isDeleted": false, "updated": 1, "link": null, "locked": false }
{ "id": "screen-1-text", "type": "text", "x": 20, "y": 40, "width": 240, "height": 40, "angle": 0, "strokeColor": "#1e1e1e", "backgroundColor": "transparent", "fillStyle": "solid", "strokeWidth": 1.4, "strokeStyle": "solid", "roughness": 1, "opacity": 100, "groupIds": [], "frameId": null, "roundness": null, "seed": 2, "version": 1, "versionNonce": 2, "isDeleted": false, "updated": 1, "link": null, "locked": false, "text": "Landing\nCTA: Empezar\nBloques: hero · prueba social", "fontSize": 16, "fontFamily": 1, "textAlign": "center", "verticalAlign": "middle", "containerId": "screen-1", "originalText": "Landing\nCTA: Empezar\nBloques: hero · prueba social", "lineHeight": 1.25, "autoResize": true }
```

- Tell the user the MCP was unavailable and that arrows may need manual re-binding. Never block the UX phase on the map; never claim it was generated visually if it was patched by hand.

## Anti-Patterns

| Mistake | Fix |
|---|---|
| Regenerating the whole file on every update | Read state and patch incrementally |
| Free-form labels that drift from `UX-SPEC.md` | Exact screen names — they are the key for edges and deletes |
| Using the fixed SaaS grid when the brief says `one-page` or `flow` | Pick the template from `navigation_model` |
| Ignoring the brief's areas/colors | Derive areas from the IA; rotate the preset palette |
| Drawing every UI element | Screens/sections + key blocks + actions only |
| One arrow per screen pair | One arrow per action, labeled with its button text |
| No legend | Always include direction, navigation model and P(fit) when ranked |
| Leaving the map stale after a UX change | Same-pass update (guide 02 / redesign / guide 10) |
