import { createFileRoute, notFound, redirect } from "@tanstack/react-router";

import { Workspace } from "@/pages/Workspace";
import { savedSession } from "@/services/accountApi";

// Original App.tsx aliases: these canonicalise to the payer workspace.
const PAYER_ALIASES = ["/login", "/signup", "/profile", "/enrollment"];
const WORKSPACE_PREFIXES = ["/payer", "/guardian", "/admin"];

function normalize(pathname: string) {
  return pathname.replace(/\/$/, "") || "/";
}

const TITLE = "PauseGuard — Payer, guardian and admin workspace";
const DESCRIPTION =
  "Sign in to check a UPI payment, review a request as an enrolled guardian, or test merchant checkout in the PauseGuard preview.";

export const Route = createFileRoute("/$")({
  // The original workspace reads browser storage on first render, so it renders client-side only.
  ssr: false,
  beforeLoad: ({ location }) => {
    const path = normalize(location.pathname);
    if (PAYER_ALIASES.includes(path)) {
      throw redirect({ href: "/payer" + path + location.searchStr, replace: true });
    }
    if (path === "/admin" && !savedSession("admin")) {
      throw redirect({ href: "/admin/login", replace: true });
    }
    const known =
      path === "/analyst" || WORKSPACE_PREFIXES.some((p) => path === p || path.startsWith(p + "/"));
    if (!known) throw notFound();
  },
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
  component: Workspace,
});
