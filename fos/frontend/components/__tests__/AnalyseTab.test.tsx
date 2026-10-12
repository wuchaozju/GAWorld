/**
 * These tests make sure the analysis page keeps overview and compare
 * diff together under the analysis area.
 *
 * Each test checks one visible tab switch.
 */

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AnalyseTab } from "../AnalyseTab";
import { useSimulationStore } from "../../store";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      ({
        "components.analyseTab.results": "Results",
        "components.analyseTab.compareDiff": "Compare diff",
        "simPage.analytics": "Analytics",
        "simPage.report": "Report",
      } as Record<string, string>)[key] ?? key,
    i18n: { language: "en", changeLanguage: vi.fn() },
  }),
}));

vi.mock("../results/MetricComparisonView", () => ({
  MetricComparisonView: () => <div>Compare Diff Panel</div>,
}));

describe("AnalyseTab", () => {
  beforeEach(() => {
    useSimulationStore.setState({
      agents: [],
      logs: [],
      resultsSummary: null,
      isGeneratingResultsSummary: false,
      resultsSummaryError: null,
      toggleAnalytics: vi.fn(),
      toggleReportModal: vi.fn(),
    } as never);
  });

  it("shows the results tab first", () => {
    render(<AnalyseTab />);

    expect(screen.getByText("Results")).toBeInTheDocument();
    expect(screen.getByText("Compare diff")).toBeInTheDocument();
  });

  it("switches to compare diff", () => {
    render(<AnalyseTab />);

    fireEvent.click(screen.getByRole("button", { name: "Compare diff" }));

    expect(screen.getByText("Compare Diff Panel")).toBeInTheDocument();
  });
});
