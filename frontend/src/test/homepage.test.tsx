import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { Route } from "@/routes/index";
import { THEME_STORAGE_KEY } from "@/lib/theme";

function renderHome() {
  const Component = Route.options.component as () => React.JSX.Element;
  return render(<Component />);
}

describe("PauseGuard homepage preview", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("keeps the existing headline", () => {
    renderHome();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "A pause can protect a payment.",
    );
  });

  it("links Get started to /payer/signup", () => {
    renderHome();
    const links = screen.getAllByRole("link", { name: /get started/i });
    expect(links.length).toBeGreaterThan(0);
    links.forEach((l) => expect(l.getAttribute("href")).toBe("/payer/signup"));
  });

  it("links Log in to /payer/login", () => {
    renderHome();
    expect(screen.getByRole("link", { name: "Log in" }).getAttribute("href")).toBe("/payer/login");
  });

  it("links Guardian portal to /guardian/login", () => {
    renderHome();
    screen
      .getAllByRole("link", { name: "Guardian portal" })
      .forEach((l) => expect(l.getAttribute("href")).toBe("/guardian/login"));
  });

  it("links How it works and Privacy to their homepage sections", () => {
    renderHome();
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getByRole("link", { name: "How it works" }).getAttribute("href")).toBe(
      "/#how-it-works",
    );
    expect(within(nav).getByRole("link", { name: "Privacy" }).getAttribute("href")).toBe(
      "/#privacy",
    );
    expect(document.getElementById("how-it-works")).not.toBeNull();
    expect(document.getElementById("privacy")).not.toBeNull();
  });

  it("links Help to /help and Admin & Razorpay sandbox to /admin/login", () => {
    renderHome();
    const footer = screen.getByRole("navigation", { name: "Footer navigation" });
    expect(within(footer).getByRole("link", { name: "Help" }).getAttribute("href")).toBe("/help");
    expect(
      within(footer).getByRole("link", { name: "Admin & Razorpay sandbox" }).getAttribute("href"),
    ).toBe("/admin/login");
  });

  it("states that no funds move in the preview and that a timed-out review stays on hold", () => {
    renderHome();
    expect(screen.getAllByText("Preview environment. No funds move.").length).toBeGreaterThan(0);
    expect(document.body.textContent).toContain(
      "If a guardian review times out, the payment stays on hold.",
    );
  });

  it("switches to the light theme and remembers it", () => {
    renderHome();
    fireEvent.click(screen.getAllByRole("button", { name: "Light theme" })[0]!);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });
});
