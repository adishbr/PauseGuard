<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.

## What Lovable manages

Rules outside this block are the project's own. Change the pieces below in
Lovable, not by hand. With the [Lovable MCP](https://mcp.lovable.dev)
connected, `send_message` asks Lovable to do it; otherwise ask the user to
use the editor.

- **Database.** Do not add or edit `supabase/migrations/` or `drizzle/`.
  Ask Lovable to change the schema.
- **Generated files.** Do not edit a file whose header says it is automatically
  generated.
- **AI gateway.** Keep model calls on Lovable's gateway, and keep
  `LOVABLE_API_KEY` out of browser code.
- **Connectors.** Lovable provides native connectors. `list_connectors` shows
  which are enabled; `add_connector` only returns the dashboard link. When a
  connector is enabled, calls go through the connector gateway and need
  `LOVABLE_API_KEY`. When Lovable does not provide one, users can bring their
  own key and store it in Secrets.
- **Secrets.** Lovable manages them. Do not put secret values in the repo.
<!-- LOVABLE:END -->

## Project rules

- The original PauseGuard workspace (`src/pages/Workspace.tsx`) is mounted by the client-only splat route `src/routes/$.tsx`, which applies the original aliases; `/` (cinematic homepage) and `/help` stay separate routes. Homepage links remain plain hrefs in `src/components/pauseguard/destinations.ts` so they match the original paths.
- The original mock API (`mocks/payment-api.ts`) is unchanged and served in memory by `src/server/demoApi.ts` through request middleware in `src/start.ts`, so `/api/v2` and the demo-account paths behave as in the original Vite plugin; real-backend env flags forward to the FastAPI backend instead.
- Workspace design tokens in `src/styles/pauseguard/base.css` are scoped to `.app`, so they never override the homepage's shadcn tokens.
- Theme state uses `data-theme` on `<html>` with the main app's storage key and change event (`src/lib/theme.ts`) plus a pre-paint head script, so saved preferences stay compatible and there is no flash.
- The hero artwork is pure SVG with geometry in `ribbon-geometry.ts`; it renders a deterministic static frame on SSR and only animates (rAF, ~30fps, paused off-screen) on large fine-pointer screens without reduced motion.
