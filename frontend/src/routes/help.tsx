import { createFileRoute } from "@tanstack/react-router";

import { SiteHeader } from "@/components/pauseguard/site-header";
import { Help } from "@/pages/Help";
import "@/styles/pauseguard/base.css";
import "@/styles/pauseguard/app.css";

const TITLE = "PauseGuard — Help and fraud reporting";
const DESCRIPTION =
  "What to do about a suspicious UPI payment request: stop, verify independently, and report through the National Cybercrime Helpline 1930.";

export const Route = createFileRoute("/help")({
  head: () => ({
    meta: [
      { title: TITLE },
      { name: "description", content: DESCRIPTION },
      { name: "robots", content: "noindex, nofollow" },
      { property: "og:title", content: TITLE },
      { property: "og:description", content: DESCRIPTION },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: HelpPage,
});

function HelpPage() {
  return (
    <div className="relative min-h-screen overflow-x-clip">
      <SiteHeader />
      <div className="app public-help">
        <main id="main" className="frame" tabIndex={-1}>
          <Help />
        </main>
      </div>
    </div>
  );
}
