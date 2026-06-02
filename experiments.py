from __future__ import annotations

import csv
import statistics
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from crowd import CrowdSimulation
from models import ScenarioConfig, SimulationSetup, StadiumConfig
from scenarios import ScenarioRuntime


CSV_FIELDS = [
    "run_id",
    "started_at",
    "finished_at",
    "status",
    "scenario_id",
    "scenario_name",
    "scenario_type",
    "scenario_start_time",
    "config_file",
    "crowd_count",
    "agent_radius",
    "agent_speed",
    "personal_space",
    "congestion_weight",
    "seed",
    "max_duration",
    "sample_time",
    "active_agents",
    "evacuated_agents",
    "max_density",
    "mean_speed",
    "panicked_agents",
    "agents_in_hazard",
    "available_exits",
    "final_elapsed_time",
    "final_evacuated_agents",
    "final_evacuated_fraction",
    "final_maximum_density",
    "final_panicked_agents_total",
    "final_hazard_exposure_agent_seconds",
    "evacuation_time_min",
    "evacuation_time_mean",
    "evacuation_time_median",
    "evacuation_time_p90",
    "evacuation_time_p95",
    "evacuation_time_max",
]


class ExperimentRecorder:
    def __init__(
        self,
        config: StadiumConfig,
        setup: SimulationSetup,
        scenario: ScenarioConfig | None,
        runtime: ScenarioRuntime,
        output_directory: Path = Path("results"),
    ):
        self.setup = setup
        self.scenario = scenario
        self.runtime = runtime
        self.started_at = datetime.now(timezone.utc)
        self.run_id = uuid4().hex
        output_directory.mkdir(parents=True, exist_ok=True)
        timestamp = self.started_at.strftime("%Y%m%dT%H%M%SZ")
        self.path = output_directory / f"{timestamp}_{runtime.scenario_id}_{setup.crowd_seed}.csv"
        self.next_sample_at = 0.0
        self.finished = False
        self.finished_at = ""
        self.status = "running"
        self.summary: dict[str, float | int | None] = {}
        self.samples: list[dict[str, float | int]] = []
        self.metadata = build_metadata(
            config,
            setup,
            scenario,
            runtime,
            self.run_id,
            self.started_at.isoformat(),
        )
        self._write()

    def update(self, _dt: float, crowd: CrowdSimulation) -> None:
        if self.finished:
            return
        self.runtime.consume_events()
        if crowd.elapsed + 1e-9 < self.next_sample_at:
            return
        self.samples.append(self._sample(crowd))
        while self.next_sample_at <= crowd.elapsed + 1e-9:
            self.next_sample_at += self.setup.sample_interval
        self._write()

    def finalize(self, status: str, crowd: CrowdSimulation) -> Path:
        if self.finished:
            return self.path
        self.runtime.consume_events()
        if not self.samples or self.samples[-1]["sample_time"] != round(crowd.elapsed, 4):
            self.samples.append(self._sample(crowd))
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.status = status
        self.summary = build_summary(crowd, self.runtime)
        self.finished = True
        self._write()
        return self.path

    def _sample(self, crowd: CrowdSimulation) -> dict[str, float | int]:
        active = crowd.active_agents
        current_max = max(crowd.cell_counts().values(), default=0)
        mean_speed = statistics.fmean(agent.velocity.length() for agent in active) if active else 0.0
        return {
            "sample_time": round(crowd.elapsed, 4),
            "active_agents": len(active),
            "evacuated_agents": crowd.evacuated_count,
            "max_density": current_max,
            "mean_speed": round(mean_speed, 5),
            "panicked_agents": sum(1 for agent in active if agent.panicked),
            "agents_in_hazard": sum(1 for agent in active if self.runtime.in_hazard(agent.position)),
            "available_exits": self.runtime.available_exit_count,
        }

    def _write(self) -> None:
        temporary_path = self.path.with_suffix(".csv.tmp")
        with temporary_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, delimiter=";")
            writer.writeheader()
            for sample in self.samples:
                writer.writerow(
                    {
                        **self.metadata,
                        **sample,
                        **self.summary,
                        "finished_at": self.finished_at,
                        "status": self.status,
                    }
                )
        temporary_path.replace(self.path)


def build_metadata(
    config: StadiumConfig,
    setup: SimulationSetup,
    scenario: ScenarioConfig | None,
    runtime: ScenarioRuntime,
    run_id: str,
    started_at: str,
) -> dict[str, str | float | int]:
    return {
        "run_id": run_id,
        "started_at": started_at,
        "scenario_id": runtime.scenario_id,
        "scenario_name": scenario.name if scenario is not None else "Brak scenariusza",
        "scenario_type": scenario.type if scenario is not None else "baseline",
        "scenario_start_time": round(runtime.start_time, 5),
        "config_file": config.config_path.name,
        "crowd_count": setup.crowd_count,
        "agent_radius": setup.agent_radius,
        "agent_speed": setup.agent_speed,
        "personal_space": setup.crowd_personal_space,
        "congestion_weight": setup.crowd_congestion_weight,
        "seed": setup.crowd_seed,
        "max_duration": setup.max_duration,
    }


def build_summary(crowd: CrowdSimulation, runtime: ScenarioRuntime) -> dict[str, float | int | None]:
    evacuation_times = sorted(
        agent.evacuated_at
        for agent in crowd.agents
        if agent.evacuated_at is not None
    )
    total = len(crowd.agents)
    evacuated = crowd.evacuated_count
    times = summarize_values(evacuation_times)
    return {
        "final_elapsed_time": round(crowd.elapsed, 4),
        "final_evacuated_agents": evacuated,
        "final_evacuated_fraction": round(evacuated / total if total else 1.0, 5),
        "final_maximum_density": crowd.max_cell_count,
        "final_panicked_agents_total": runtime.panicked_total,
        "final_hazard_exposure_agent_seconds": round(sum(agent.hazard_exposure for agent in crowd.agents), 5),
        "evacuation_time_min": times["min"],
        "evacuation_time_mean": times["mean"],
        "evacuation_time_median": times["median"],
        "evacuation_time_p90": times["p90"],
        "evacuation_time_p95": times["p95"],
        "evacuation_time_max": times["max"],
    }


def summarize_values(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "mean": None, "median": None, "p90": None, "p95": None, "max": None}
    return {
        "min": round(values[0], 5),
        "mean": round(statistics.fmean(values), 5),
        "median": round(statistics.median(values), 5),
        "p90": round(percentile(values, 0.9), 5),
        "p95": round(percentile(values, 0.95), 5),
        "max": round(values[-1], 5),
    }


def percentile(values: list[float], fraction: float) -> float:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight
