import { describe, expect, it } from "vitest";

import { handleDemoApi } from "@/server/demoApi";

describe("In-app demo service adapter", () => {
  it("ignores non-demo addresses", async () => {
    expect(await handleDemoApi(new Request("http://localhost/payer"))).toBeUndefined();
  });

  it("rejects /api/v2 calls without a demo session", async () => {
    const response = await handleDemoApi(new Request("http://localhost/api/v2/profile"));
    expect(response?.status).toBe(401);
  });

  it("signs in the sample payer and returns a payer profile", async () => {
    const response = await handleDemoApi(
      new Request("http://localhost/__pauseguard/demo/session", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ role: "payer", sample: true }),
      }),
    );
    expect(response?.status).toBe(200);
    const body = (await response?.json()) as { token: string; profile: { role: string } };
    expect(body.profile.role).toBe("payer");
    const profile = await handleDemoApi(
      new Request("http://localhost/__pauseguard/demo/session", {
        headers: { authorization: `Bearer ${body.token}` },
      }),
    );
    expect(profile?.status).toBe(200);
  });
});
