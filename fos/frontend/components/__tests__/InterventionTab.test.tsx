/**
 * These tests make sure the intervention page keeps host control and
 * experiment design together in one place.
 *
 * Each test checks one visible tab change.
 */

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { InterventionTab } from "../InterventionTab";
import { useSimulationStore } from "../../store";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      (
        {
          "components.interventionTab.hostControl": "Host control",
          "simPage.designExperiment": "Design experiment",
        } as Record<string, string>
      )[key] ?? key,
  }),
}));

vi.mock("../HostPanel", () => ({
  HostPanel: () => <div>Host Control Panel</div>,
}));

vi.mock("../experiment/ExperimentDesignPanel", () => ({
  ExperimentDesignPanel: () => <div>Experiment Designer Panel</div>,
}));

describe("InterventionTab", () => {
  beforeEach(() => {
    useSimulationStore.setState({
      toggleExperimentDesigner: vi.fn(),
    } as never);
  });

  it("shows design experiment first", () => {
    render(<InterventionTab />);

    expect(screen.getByText("Host control")).toBeInTheDocument();
    expect(screen.getByText("Design experiment")).toBeInTheDocument();
    expect(screen.getByText("Experiment Designer Panel")).toBeInTheDocument();
  });

  it("switches to design experiment", () => {
    render(<InterventionTab />);

    fireEvent.click(screen.getByRole("button", { name: "Design experiment" }));

    expect(screen.getByText("Experiment Designer Panel")).toBeInTheDocument();
  });

  it("shows the design area without a second open button", () => {
    render(<InterventionTab />);

    fireEvent.click(screen.getByRole("button", { name: "Design experiment" }));

    expect(screen.getByText("Experiment Designer Panel")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Open experiment designer" })
    ).not.toBeInTheDocument();
  });
});
