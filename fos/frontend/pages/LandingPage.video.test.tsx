/**
 * This file tests the landing page preview media.
 * render_landing_page shows the page inside a router so links work in the test.
 * test_landing_page_shows_local_preview_video_when_external_video_is_not_configured checks that the page shows a built-in video player when no external video is set.
 * test_landing_page_waits_to_load_external_preview_until_people_ask_for_it checks that the external iframe stays deferred until someone clicks the preview button.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        "landing.hero.sub": "Run living worlds.",
        "landing.hero.tag1": "tag one",
        "landing.hero.tag2": "tag two",
        "landing.hero.tag3": "tag three",
        "landing.entry.dashboardTitle": "Dashboard",
        "landing.entry.dashboardSubtitle": "See everything",
        "landing.entry.interfaceTitle": "Interface",
        "landing.entry.interfaceSubtitle": "Build a sim",
        "landing.entry.savedTitle": "Saved",
        "landing.entry.savedSubtitle": "Open work",
        "landing.entry.settingsTitle": "Settings",
        "landing.entry.settingsSubtitle": "Tune tools",
        "landing.scenes.policyTitle": "Policy",
        "landing.scenes.policySubtitle": "Policy subtitle",
        "landing.scenes.policyBody": "Policy body",
        "landing.scenes.behaviorTitle": "Behavior",
        "landing.scenes.behaviorSubtitle": "Behavior subtitle",
        "landing.scenes.behaviorBody": "Behavior body",
        "landing.scenes.institutionTitle": "Institution",
        "landing.scenes.institutionSubtitle": "Institution subtitle",
        "landing.scenes.institutionBody": "Institution body",
        "landing.scenes.interventionTitle": "Intervention",
        "landing.scenes.interventionSubtitle": "Intervention subtitle",
        "landing.scenes.interventionBody": "Intervention body",
        "landing.finalCta.new": "New",
        "landing.finalCta.dashboard": "Dashboard",
        "landing.finalCta.saved": "Saved",
        "landing.hero.line1": "Future",
        "landing.hero.line2": "of Society",
        "landing.hero.accent": "Labs",
        "landing.hero.badge": "Badge",
        "landing.hero.primaryCta": "Start",
        "landing.hero.secondaryCta": "Docs",
        "landing.entry.primaryBadge": "Primary",
        "landing.entry.primaryTitle": "Launch",
        "landing.entry.primarySubtitle": "Launch subtitle",
        "landing.preview.title": "Simulation Interaction Preview",
        "landing.preview.accent": "Live platform view",
        "landing.preview.sub": "Immersive observation",
        "landing.preview.cta": "View live engine",
        "landing.preview.configureVideo": "Please configure the preview video",
        "landing.capabilities.title": "Capabilities",
        "landing.capabilities.designTitle": "Design",
        "landing.capabilities.designSubtitle": "Design subtitle",
        "landing.capabilities.designBody": "Design body",
        "landing.capabilities.observeTitle": "Observe",
        "landing.capabilities.observeSubtitle": "Observe subtitle",
        "landing.capabilities.branchTitle": "Branch",
        "landing.capabilities.branchSubtitle": "Branch subtitle",
        "landing.capabilities.controlTitle": "Control",
        "landing.capabilities.controlBody": "Control body",
        "landing.scenes.title": "Scenes",
        "landing.scenes.kicker": "Scene kicker",
        "landing.finalCta.title": "Ready",
        "landing.finalCta.sub": "Final subtitle",
      };
      return translations[key] ?? key;
    },
  }),
}));

vi.mock("../config/video", () => ({
  isBilibiliConfigured: () => false,
  getBilibiliEmbedUrl: () => "https://player.bilibili.com/player.html?bvid=demo",
}));

async function render_landing_page(): Promise<ReturnType<typeof render>> {
  const { LandingPage } = await import("./LandingPage");
  return render(
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>
  );
}

beforeAll(() => {
  class FakeIntersectionObserver implements IntersectionObserver {
    readonly root = null;
    readonly rootMargin = "";
    readonly thresholds = [];

    disconnect(): void {}

    observe(): void {}

    takeRecords(): IntersectionObserverEntry[] {
      return [];
    }

    unobserve(): void {}
  }

  vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
});

beforeEach(() => {
  vi.resetModules();
});

describe("LandingPage preview video", () => {
  it("test_landing_page_shows_local_preview_video_when_external_video_is_not_configured", async () => {
    const { container } = await render_landing_page();

    expect(screen.queryByText("Please configure the preview video")).not.toBeInTheDocument();

    const previewVideo = container.querySelector("video");
    expect(previewVideo).toBeInTheDocument();
    expect(previewVideo).toHaveAttribute("autoplay");
    expect(previewVideo).toHaveAttribute("loop");
    expect(previewVideo?.muted).toBe(true);
    expect(previewVideo?.playsInline).toBe(true);
  });

  it("test_landing_page_waits_to_load_external_preview_until_people_ask_for_it", async () => {
    vi.doMock("../config/video", () => ({
      isBilibiliConfigured: () => true,
      getBilibiliEmbedUrl: () => "https://player.bilibili.com/player.html?bvid=BV1demo",
    }));

    const { container } = await render_landing_page();
    const user = userEvent.setup();

    expect(container.querySelector("iframe")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "View live engine" }));

    const previewFrame = container.querySelector("iframe");
    expect(previewFrame).toBeInTheDocument();
    expect(previewFrame).toHaveAttribute("src", "https://player.bilibili.com/player.html?bvid=BV1demo");
  });
});
