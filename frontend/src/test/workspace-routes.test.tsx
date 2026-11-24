import { QueryClient } from "@tanstack/react-query";
import { createRouter } from "@tanstack/react-router";
import { describe, expect, it } from "vitest";

import { routeTree } from "@/routeTree.gen";

function leaf(path: string) {
  const router = createRouter({ routeTree, context: { queryClient: new QueryClient() } });
  return router.matchRoutes(path).at(-1)?.routeId;
}

describe("Original PauseGuard addresses", () => {
  it.each([
    "/payer",
    "/payer/login",
    "/payer/signup",
    "/guardian/login",
    "/guardian/enrollment",
    "/admin/login",
    "/analyst",
    "/login",
  ])("%s reaches the workspace", (path) => {
    expect(leaf(path)).toBe("/$");
  });

  it("keeps the homepage and public help page as their own pages", () => {
    expect(leaf("/")).toBe("/");
    expect(leaf("/help")).toBe("/help");
  });
});
