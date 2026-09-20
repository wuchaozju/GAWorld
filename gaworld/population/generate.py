"""One-call orchestration of the population pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gaworld.population.network import (
    HouseholdRecord,
    WorkplaceRecord,
    build_households,
    build_social_graph,
    build_workplaces,
)
from gaworld.population.report import Finding, build_report, has_errors, validate_population
from gaworld.population.schema import Issue, PopulationSpec, check_feasibility
from gaworld.population.synth import Person, synthesize_people
from gaworld.population.writer import write_population


@dataclass
class GeneratedPopulation:
    spec: PopulationSpec
    people: list[Person]
    households: list[HouseholdRecord]
    workplaces: list[WorkplaceRecord]
    neighbours: dict[int, list[int]]
    report: dict[str, Any]
    findings: list[Finding] = field(default_factory=list)
    feasibility: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not has_errors(self.findings)

    def write(self, output_dir: Path | str) -> dict[str, Path]:
        return write_population(
            output_dir,
            self.spec,
            self.people,
            self.households,
            self.workplaces,
            self.report,
            self.findings,
        )


def generate_population(spec: PopulationSpec) -> GeneratedPopulation:
    """Run the full pipeline: sample → structure → validate → report.

    Feasibility issues are attached rather than raised. The caller decides
    whether an infeasible-but-clamped spec is acceptable; the panel, for
    instance, wants to render the conflict alongside a preview.
    """
    feasibility = check_feasibility(spec)
    people, fit_report = synthesize_people(spec)
    households = build_households(spec, people)
    workplaces = build_workplaces(spec, people)
    neighbours = build_social_graph(spec, people, households, workplaces)
    report = build_report(spec, people, households, workplaces, neighbours, fit_report)
    findings = validate_population(spec, people, households, neighbours)
    return GeneratedPopulation(
        spec=spec,
        people=people,
        households=households,
        workplaces=workplaces,
        neighbours=neighbours,
        report=report,
        findings=findings,
        feasibility=feasibility,
    )


__all__ = ["GeneratedPopulation", "generate_population"]
