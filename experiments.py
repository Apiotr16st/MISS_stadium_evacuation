from __future__ import annotations

import json
import statistics
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from crowd import CrowdSimulation
from models import ScenarioConfig, SimulationSetup, StadiumConfig
from scenarios import ScenarioRuntime


class ExperimentRecorder:
    def __init__(
        self,
        config: StadiumConfig,
        setup: SimulationSetup,
        scenario: ScenarioConfig | None,
        runtime: ScenarioRuntime,
        output_directory: Path = Path("results"),
    ):
        self.config = config
        self.setup = setup
        self.scenario = scenario
        self.runtime = runtime
        self.started_at = datetime.now(timezone.utc)
        self.run_id = uuid4().hex
        output_directory.mkdir(parents=True, exist_ok=True)
        timestamp = self.started_at.strftime("%Y%m%dT%H%M%SZ")
        self.path = output_directory / f"{timestamp}_{runtime.scenario_id}_{setup.crowd_seed}.json"
        self.next_sample_at = 0.0
        self.finished = False
        self.heatmap: dict[str, dict[str, float | int]] = {}
        self.data: dict[str, Any] = {
            "schema_version": 1,
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": None,
            "status": "running",
            "configuration": serialize_configuration(config, setup),
            "scenario": serialize_scenario(scenario),
            "time_series": [],
            "heatmap": self.heatmap,
            "events": [],
            "summary": {},
        }
        self._write()

    def update(self, dt: float, crowd: CrowdSimulation) -> None:
        if self.finished:
            return
        self.data["events"].extend(self.runtime.consume_events())
        for cell, count in crowd.cell_counts().items():
            key = f"{cell[0]},{cell[1]}"
            entry = self.heatmap.setdefault(
                key,
                {
                    "occupancy_agent_seconds": 0.0,
                    "max_occupancy": 0,
                    "hazard_exposure_agent_seconds": 0.0,
                },
            )
            entry["occupancy_agent_seconds"] = round(float(entry["occupancy_agent_seconds"]) + count * dt, 5)
            entry["max_occupancy"] = max(int(entry["max_occupancy"]), count)
            if cell in self.runtime.hazard_cells:
                entry["hazard_exposure_agent_seconds"] = round(
                    float(entry["hazard_exposure_agent_seconds"]) + count * dt,
                    5,
                )

        if crowd.elapsed + 1e-9 < self.next_sample_at:
            return
        self.data["time_series"].append(self._sample(crowd))
        while self.next_sample_at <= crowd.elapsed + 1e-9:
            self.next_sample_at += self.setup.sample_interval
        self._write()

    def finalize(self, status: str, crowd: CrowdSimulation) -> Path:
        if self.finished:
            return self.path
        self.data["events"].extend(self.runtime.consume_events())
        self.data["events"].append({"time": round(crowd.elapsed, 4), "type": "run_finished", "status": status})
        self.data["finished_at"] = datetime.now(timezone.utc).isoformat()
        self.data["status"] = status
        self.data["summary"] = build_summary(crowd, self.runtime, self.heatmap)
        self.finished = True
        self._write()
        return self.path

    def _sample(self, crowd: CrowdSimulation) -> dict[str, Any]:
        active = crowd.active_agents
        current_max = max(crowd.cell_counts().values(), default=0)
        mean_speed = statistics.fmean(agent.velocity.length() for agent in active) if active else 0.0
        return {
            "time": round(crowd.elapsed, 4),
            "active_agents": len(active),
            "evacuated_agents": crowd.evacuated_count,
            "max_density": current_max,
            "mean_speed": round(mean_speed, 5),
            "panicked_agents": sum(1 for agent in active if agent.panicked),
            "agents_in_hazard": sum(1 for agent in active if self.runtime.in_hazard(agent.position)),
            "available_exits": self.runtime.available_exit_count,
            "hazard_radius": round(self.runtime.hazard_radius, 4),
        }

    def _write(self) -> None:
        temporary_path = self.path.with_suffix(".json.tmp")
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, ensure_ascii=True, indent=2)
        temporary_path.replace(self.path)


def serialize_configuration(config: StadiumConfig, setup: SimulationSetup) -> dict[str, Any]:
    values = asdict(setup)
    values.pop("scenario")
    values.update(
        {
            "config_file": config.config_path.name,
            "layout_width": config.width,
            "layout_height": config.height,
            "tile_size": config.tile_size,
            "sector_ids": sorted(config.metadata.sector_cells),
        }
    )
    return values


def serialize_scenario(scenario: ScenarioConfig | None) -> dict[str, Any] | None:
    if scenario is None:
        return None
    return {
        "id": scenario.id,
        "name": scenario.name,
        "type": scenario.type,
        "parameters": scenario.parameters,
        "source_file": scenario.source_path.name,
    }


def build_summary(
    crowd: CrowdSimulation,
    runtime: ScenarioRuntime,
    heatmap: dict[str, dict[str, float | int]],
) -> dict[str, Any]:
    evacuation_times = sorted(
        agent.evacuated_at
        for agent in crowd.agents
        if agent.evacuated_at is not None
    )
    top_cells = sorted(
        (
            {
                "cell": key,
                "occupancy_agent_seconds": value["occupancy_agent_seconds"],
                "max_occupancy": value["max_occupancy"],
            }
            for key, value in heatmap.items()
        ),
        key=lambda value: float(value["occupancy_agent_seconds"]),
        reverse=True,
    )[:10]
    total = len(crowd.agents)
    evacuated = crowd.evacuated_count
    summary: dict[str, Any] = {
        "total_agents": total,
        "evacuated_agents": evacuated,
        "evacuated_fraction": round(evacuated / total if total else 1.0, 5),
        "elapsed_time": round(crowd.elapsed, 4),
        "maximum_density": crowd.max_cell_count,
        "panicked_agents_total": runtime.panicked_total,
        "hazard_exposure_agent_seconds": round(sum(agent.hazard_exposure for agent in crowd.agents), 5),
        "evacuation_times": summarize_values(evacuation_times),
        "top_occupied_cells": top_cells,
    }
    return summary


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
