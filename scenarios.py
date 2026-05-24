from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from models import ScenarioChoice, ScenarioConfig, StadiumConfig, Vec2
from stadium import Stadium, build_exit_route_maps
from utils import circle_intersects_rect


SCENARIO_TYPES = {"fire", "panic", "bombing"}


@dataclass
class RoutingContext:
    active_exit_cells: set[tuple[int, int]]
    additional_costs: dict[tuple[int, int], float]
    distances: list[list[float]]
    next_cells: list[list[tuple[int, int] | None]]


def load_scenario_catalog(directory: Path, config: StadiumConfig) -> tuple[list[ScenarioChoice], list[str]]:
    choices = [ScenarioChoice(label="Brak scenariusza", config=None)]
    errors: list[str] = []
    if not directory.exists():
        return choices, errors
    for path in sorted(directory.glob("*.json")):
        try:
            scenario = load_scenario(path, config)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        choices.append(ScenarioChoice(label=scenario.name, config=scenario))
    return choices, errors


def load_scenario(path: Path, config: StadiumConfig) -> ScenarioConfig:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    scenario_id = str(raw.get("id", "")).strip()
    name = str(raw.get("name", "")).strip()
    scenario_type = str(raw.get("type", "")).strip()
    parameters = raw.get("parameters", {})
    if not scenario_id or not name:
        raise ValueError("Scenariusz wymaga niepustych pol 'id' i 'name'.")
    if scenario_type not in SCENARIO_TYPES:
        raise ValueError(f"Nieznany typ scenariusza: {scenario_type!r}.")
    if not isinstance(parameters, dict):
        raise ValueError("Pole 'parameters' musi byc obiektem.")
    scenario = ScenarioConfig(scenario_id, name, scenario_type, parameters, path)
    validate_scenario(scenario, config)
    return scenario


def validate_scenario(scenario: ScenarioConfig, config: StadiumConfig) -> None:
    parameters = scenario.parameters
    location_key = "origin" if scenario.type == "fire" else "incident"
    resolve_local_cell(parameters.get(location_key), config, location_key)
    require_non_negative(parameters.get("starts_at"), "starts_at")
    if scenario.type == "fire":
        require_positive(parameters.get("routing_cost"), "routing_cost")
        return
    if scenario.type == "panic":
        require_positive(parameters.get("influence_radius"), "influence_radius")
        require_positive(parameters.get("speed_multiplier"), "speed_multiplier")
        require_positive(parameters.get("personal_space_multiplier"), "personal_space_multiplier")
        require_non_negative(parameters.get("congestion_weight_multiplier"), "congestion_weight_multiplier")
        require_non_negative(parameters.get("random_route_chance"), "random_route_chance")
        require_non_negative(parameters.get("motion_noise"), "motion_noise")
        return
    require_positive(parameters.get("blast_radius"), "blast_radius")
    require_positive(parameters.get("flee_duration"), "flee_duration")
    require_positive(parameters.get("flee_force"), "flee_force")
    require_positive(parameters.get("routing_cost"), "routing_cost")


class ScenarioRuntime:
    def __init__(self, stadium: Stadium, scenario: ScenarioConfig | None):
        self.stadium = stadium
        self.config = scenario
        self.events: list[dict[str, Any]] = []
        self._event_cursor = 0
        self.hazard_cells: set[tuple[int, int]] = set()
        self.hazard_radius = 0.0
        self.hazard_started = False
        self.panicked_total = 0
        self.incident_center: tuple[int, int] | None = None
        self.disabled_sector: str | None = None
        all_exit_cells = {
            cell
            for exits in stadium.config.metadata.sector_exits.values()
            for exit_ref in exits
            for cell in exit_ref.cells
        }
        self.routing = RoutingContext(set(all_exit_cells), {}, [], [])
        self._rebuild_routes()

    @property
    def scenario_id(self) -> str:
        return self.config.id if self.config is not None else "baseline"

    @property
    def available_exit_count(self) -> int:
        return sum(
            1
            for exits in self.stadium.config.metadata.sector_exits.values()
            for exit_ref in exits
            if any(cell in self.routing.active_exit_cells for cell in exit_ref.cells)
        )

    def update(self, elapsed: float, agents: list[Any]) -> None:
        if self.config is None:
            return
        if self.config.type == "fire":
            self._update_fire(elapsed)
        elif self.config.type == "panic":
            self._update_panic(elapsed, agents)
        elif self.config.type == "bombing":
            self._update_bombing(elapsed, agents)

    def consume_events(self) -> list[dict[str, Any]]:
        events = self.events[self._event_cursor:]
        self._event_cursor = len(self.events)
        return events

    def congestion_multiplier(self, agent: Any) -> float:
        if not getattr(agent, "panicked", False) or self.config is None or self.config.type != "panic":
            return 1.0
        return float(self.config.parameters["congestion_weight_multiplier"])

    def speed_multiplier(self, agent: Any) -> float:
        if not getattr(agent, "panicked", False) or self.config is None or self.config.type != "panic":
            return 1.0
        return float(self.config.parameters["speed_multiplier"])

    def personal_space_multiplier(self, agent: Any) -> float:
        if not getattr(agent, "panicked", False) or self.config is None or self.config.type != "panic":
            return 1.0
        return float(self.config.parameters["personal_space_multiplier"])

    def random_route_chance(self, agent: Any) -> float:
        if not getattr(agent, "panicked", False) or self.config is None or self.config.type != "panic":
            return 0.0
        return min(1.0, float(self.config.parameters["random_route_chance"]))

    def motion_noise(self, agent: Any) -> float:
        if not getattr(agent, "panicked", False) or self.config is None or self.config.type != "panic":
            return 0.0
        return float(self.config.parameters["motion_noise"])

    def emergency_force(self, agent: Any, elapsed: float) -> Vec2:
        if self.config is None or self.config.type != "bombing" or self.incident_center is None:
            return Vec2(0, 0)
        if elapsed >= getattr(agent, "fleeing_until", 0.0):
            return Vec2(0, 0)
        center = self.stadium.tile_rect(*self.incident_center).center
        delta = agent.position - Vec2(center)
        if delta.length_squared() == 0:
            return Vec2(1, 0) * float(self.config.parameters["flee_force"])
        return delta.normalize() * float(self.config.parameters["flee_force"])

    def in_hazard(self, position: Vec2) -> bool:
        return self.stadium.cell_at_pixel(position) in self.hazard_cells

    def is_evacuation_reached(self, position: Vec2, radius: float) -> bool:
        for cell in self.routing.active_exit_cells:
            if circle_intersects_rect(position, radius, self.stadium.tile_rect(*cell)):
                return True
        return False

    def marker_cell(self) -> tuple[int, int] | None:
        if self.config is None:
            return None
        key = "origin" if self.config.type == "fire" else "incident"
        return resolve_local_cell(self.config.parameters[key], self.stadium.config, key)

    def status_lines(self, elapsed: float) -> list[str]:
        if self.config is None:
            return ["Brak"]
        lines = [self.config.name]
        starts_at = float(self.config.parameters["starts_at"])
        if elapsed < starts_at:
            lines.append(f"Start za: {starts_at - elapsed:.1f} s")
            return lines
        if self.config.type == "fire":
            lines.append(f"Wylaczony sektor: {self.disabled_sector}")
        elif self.config.type == "panic":
            lines.append(f"Spanikowani: {self.panicked_total}")
            lines.append(f"Losowe trasy: {float(self.config.parameters['random_route_chance']) * 100:.0f}%")
        elif self.config.type == "bombing":
            lines.append(f"Wylaczony sektor: {self.disabled_sector}")
            lines.append(f"Uciekajacy: {self.panicked_total}")
        lines.append(f"Dostepne wyjscia: {self.available_exit_count}")
        return lines

    def _update_fire(self, elapsed: float) -> None:
        starts_at = float(self.config.parameters["starts_at"])
        if elapsed < starts_at or self.hazard_started:
            return
        self.hazard_started = True
        sector_id = str(self.config.parameters["origin"]["sector_id"])
        self.disabled_sector = sector_id
        self.incident_center = resolve_local_cell(self.config.parameters["origin"], self.stadium.config, "origin")
        self.hazard_cells = {
            cell for cell in self.stadium.config.metadata.sector_cells[sector_id]
            if self.stadium.is_walkable_cell(*cell)
        }
        self._disable_sector_exits(sector_id)
        cost = float(self.config.parameters["routing_cost"])
        self.routing.additional_costs = {cell: cost for cell in self.hazard_cells}
        self.events.append(
            {
                "time": round(elapsed, 4),
                "type": "fire_started",
                "disabled_sector": sector_id,
                "affected_cells": len(self.hazard_cells),
            }
        )
        self._rebuild_routes()

    def _update_panic(self, elapsed: float, agents: list[Any]) -> None:
        if elapsed < float(self.config.parameters["starts_at"]):
            return
        center = resolve_local_cell(self.config.parameters["incident"], self.stadium.config, "incident")
        radius = float(self.config.parameters["influence_radius"])
        new_count = 0
        for agent in agents:
            if agent.evacuated or agent.panicked:
                continue
            if math.dist(self.stadium.cell_at_pixel(agent.position), center) <= radius:
                agent.panicked = True
                new_count += 1
        if new_count:
            self.panicked_total += new_count
            self.events.append(
                {
                    "time": round(elapsed, 4),
                    "type": "agents_panicked",
                    "new_count": new_count,
                    "total_count": self.panicked_total,
                }
            )

    def _update_bombing(self, elapsed: float, agents: list[Any]) -> None:
        if elapsed < float(self.config.parameters["starts_at"]) or self.hazard_started:
            return
        self.hazard_started = True
        sector_id = str(self.config.parameters["incident"]["sector_id"])
        self.disabled_sector = sector_id
        self.incident_center = resolve_local_cell(self.config.parameters["incident"], self.stadium.config, "incident")
        blast_radius = float(self.config.parameters["blast_radius"])
        self.hazard_radius = blast_radius
        self.hazard_cells = {
            cell for cell in self.stadium.config.metadata.sector_cells[sector_id]
            if self.stadium.is_walkable_cell(*cell)
            and math.dist(cell, self.incident_center) <= blast_radius
        }
        self._disable_sector_exits(sector_id)
        cost = float(self.config.parameters["routing_cost"])
        self.routing.additional_costs = {
            cell: cost for cell in self.stadium.config.metadata.sector_cells[sector_id]
        }
        affected = 0
        for agent in agents:
            if agent.evacuated:
                continue
            if math.dist(self.stadium.cell_at_pixel(agent.position), self.incident_center) <= blast_radius:
                agent.fleeing_until = elapsed + float(self.config.parameters["flee_duration"])
                agent.panicked = True
                affected += 1
        self.panicked_total += affected
        self.events.append(
            {
                "time": round(elapsed, 4),
                "type": "bombing_started",
                "disabled_sector": sector_id,
                "fleeing_agents": affected,
            }
        )
        self._rebuild_routes()

    def _disable_sector_exits(self, sector_id: str) -> None:
        for exit_ref in self.stadium.config.metadata.sector_exits.get(sector_id, ()):
            self.routing.active_exit_cells.difference_update(exit_ref.cells)

    def _rebuild_routes(self) -> None:
        distances, next_cells = build_exit_route_maps(
            self.stadium.config,
            self.routing.active_exit_cells,
            self.routing.additional_costs,
        )
        self.routing.distances = distances
        self.routing.next_cells = next_cells


def resolve_exit_reference(reference: Any, config: StadiumConfig) -> set[tuple[int, int]]:
    if not isinstance(reference, dict):
        raise ValueError("Odwolanie do wyjscia musi byc obiektem.")
    sector_id = str(reference.get("sector_id", ""))
    exit_id = str(reference.get("exit_id", ""))
    require_sector(sector_id, config)
    for exit_ref in config.metadata.sector_exits.get(sector_id, ()):
        if exit_ref.id == exit_id:
            return set(exit_ref.cells)
    raise ValueError(f"Sektor {sector_id!r} nie ma wyjscia {exit_id!r}.")


def resolve_local_cell(reference: Any, config: StadiumConfig, name: str) -> tuple[int, int]:
    if not isinstance(reference, dict):
        raise ValueError(f"Pole {name!r} musi byc obiektem.")
    sector_id = str(reference.get("sector_id", ""))
    require_sector(sector_id, config)
    local_cell = reference.get("local_cell")
    if not isinstance(local_cell, list) or len(local_cell) != 2:
        raise ValueError(f"Pole {name}.local_cell musi zawierac [x, y].")
    bounds = config.metadata.sector_bounds[sector_id]
    x = bounds.left + int(local_cell[0])
    y = bounds.top + int(local_cell[1])
    if (x, y) not in config.metadata.sector_cells[sector_id]:
        raise ValueError(f"Pole {name}.local_cell lezy poza sektorem {sector_id!r}.")
    return x, y


def require_sector(sector_id: str, config: StadiumConfig) -> None:
    if sector_id not in config.metadata.sector_cells:
        raise ValueError(f"Nieznany sektor: {sector_id!r}.")


def require_non_negative(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Parametr {name!r} musi byc liczba.") from exc
    if number < 0:
        raise ValueError(f"Parametr {name!r} nie moze byc ujemny.")
    return number


def require_positive(value: Any, name: str) -> float:
    number = require_non_negative(value, name)
    if number <= 0:
        raise ValueError(f"Parametr {name!r} musi byc dodatni.")
    return number
