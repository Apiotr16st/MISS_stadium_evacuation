from __future__ import annotations

import json
import math
import random
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
    validate_trigger(parameters)
    if scenario.type == "fire":
        require_non_negative(parameters.get("initial_radius"), "initial_radius")
        require_positive(parameters.get("growth_per_second"), "growth_per_second")
        max_radius = require_positive(parameters.get("max_radius"), "max_radius")
        if max_radius < float(parameters["initial_radius"]):
            raise ValueError("Parametr 'max_radius' nie moze byc mniejszy niz 'initial_radius'.")
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
    if "avoidance_radius" in parameters:
        avoidance_radius = require_positive(parameters.get("avoidance_radius"), "avoidance_radius")
        if avoidance_radius < float(parameters["blast_radius"]):
            raise ValueError("Parametr 'avoidance_radius' nie moze byc mniejszy niz 'blast_radius'.")
    require_positive(parameters.get("flee_duration"), "flee_duration")
    require_positive(parameters.get("flee_force"), "flee_force")
    if "avoidance_force" in parameters:
        require_non_negative(parameters.get("avoidance_force"), "avoidance_force")
    require_positive(parameters.get("routing_cost"), "routing_cost")


class ScenarioRuntime:
    def __init__(
        self,
        stadium: Stadium,
        scenario: ScenarioConfig | None,
        start_time_override: float | None = None,
    ):
        self.stadium = stadium
        self.config = scenario
        self.start_time = resolve_start_time(scenario, stadium.config.crowd_seed, start_time_override)
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
        force = Vec2(0, 0)
        center = self.stadium.tile_rect(*self.incident_center).center
        delta = agent.position - Vec2(center)
        if delta.length_squared() == 0:
            delta = Vec2(1, 0)
        if elapsed >= getattr(agent, "fleeing_until", 0.0):
            avoidance_radius = float(self.config.parameters.get("avoidance_radius", self.config.parameters["blast_radius"]))
            distance = math.dist(self.stadium.cell_at_pixel(agent.position), self.incident_center)
            if distance >= avoidance_radius:
                return force
            strength = float(self.config.parameters.get("avoidance_force", 0.0))
            falloff = (avoidance_radius - distance) / avoidance_radius
            return delta.normalize() * strength * falloff
        return delta.normalize() * float(self.config.parameters["flee_force"])

    def in_hazard(self, position: Vec2) -> bool:
        return self.stadium.cell_at_pixel(position) in self.hazard_cells

    def is_evacuation_reached(self, position: Vec2, radius: float) -> bool:
        x, y = self.stadium.cell_at_pixel(position)
        margin = max(1, math.ceil(radius / self.stadium.minimum_cell_extent))
        config = self.stadium.config
        for ny in range(max(0, y - margin), min(config.height, y + margin + 1)):
            for nx in range(max(0, x - margin), min(config.width, x + margin + 1)):
                if (nx, ny) not in self.routing.active_exit_cells:
                    continue
                if circle_intersects_rect(position, radius, self.stadium.tile_rect(nx, ny)):
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
        if elapsed < self.start_time:
            lines.append(f"Start za: {self.start_time - elapsed:.1f} s")
            return lines
        if self.config.type == "fire":
            lines.append(f"Promien: {self.hazard_radius:.1f} kaf.")
            lines.append(f"Komorki zagrozenia: {len(self.hazard_cells)}")
        elif self.config.type == "panic":
            lines.append(f"Spanikowani: {self.panicked_total}")
            lines.append(f"Losowe trasy: {float(self.config.parameters['random_route_chance']) * 100:.0f}%")
        elif self.config.type == "bombing":
            lines.append(f"Wylaczony sektor: {self.disabled_sector}")
            lines.append(f"Uciekajacy: {self.panicked_total}")
        lines.append(f"Dostepne wyjscia: {self.available_exit_count}")
        return lines

    def _update_fire(self, elapsed: float) -> None:
        if elapsed < self.start_time:
            return
        sector_id = str(self.config.parameters["origin"]["sector_id"])
        if self.incident_center is None:
            self.incident_center = resolve_local_cell(self.config.parameters["origin"], self.stadium.config, "origin")
        old_cells = self.hazard_cells
        previous_radius = self.hazard_radius
        active_time = max(0.0, elapsed - self.start_time)
        initial_radius = float(self.config.parameters["initial_radius"])
        growth = float(self.config.parameters["growth_per_second"])
        max_radius = float(self.config.parameters["max_radius"])
        self.hazard_radius = min(max_radius, initial_radius + active_time * growth)
        new_cells = {
            cell for cell in self.stadium.config.metadata.sector_cells[sector_id]
            if self.stadium.is_walkable_cell(*cell)
            and math.dist(cell, self.incident_center) <= self.hazard_radius
        }
        if new_cells == old_cells:
            return
        self.hazard_cells = new_cells
        cost = float(self.config.parameters["routing_cost"])
        self.routing.additional_costs = {cell: cost for cell in self.hazard_cells}
        if not self.hazard_started:
            self.hazard_started = True
            self.events.append(
                {
                    "time": round(elapsed, 4),
                    "type": "fire_started",
                    "sector": sector_id,
                    "radius": round(self.hazard_radius, 4),
                    "affected_cells": len(self.hazard_cells),
                }
            )
        elif math.floor(previous_radius) != math.floor(self.hazard_radius):
            self.events.append(
                {
                    "time": round(elapsed, 4),
                    "type": "fire_grew",
                    "radius": round(self.hazard_radius, 4),
                    "affected_cells": len(self.hazard_cells),
                }
            )
        self._rebuild_routes()

    def _update_panic(self, elapsed: float, agents: list[Any]) -> None:
        if elapsed < self.start_time:
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
        if elapsed < self.start_time or self.hazard_started:
            return
        self.hazard_started = True
        sector_id = str(self.config.parameters["incident"]["sector_id"])
        self.disabled_sector = sector_id
        self.incident_center = resolve_local_cell(self.config.parameters["incident"], self.stadium.config, "incident")
        blast_radius = float(self.config.parameters["blast_radius"])
        avoidance_radius = float(self.config.parameters.get("avoidance_radius", blast_radius))
        self.hazard_radius = blast_radius
        self.hazard_cells = {
            cell for cell in self.stadium.config.metadata.sector_cells[sector_id]
            if self.stadium.is_walkable_cell(*cell)
            and math.dist(cell, self.incident_center) <= blast_radius
        }
        self._disable_sector_exits(sector_id)
        cost = float(self.config.parameters["routing_cost"])
        self.routing.additional_costs = {
            cell: cost * (1.0 + 1.5 * (avoidance_radius - math.dist(cell, self.incident_center)) / avoidance_radius)
            for cell in self.stadium.config.metadata.sector_cells[sector_id]
            if math.dist(cell, self.incident_center) <= avoidance_radius
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


def validate_trigger(parameters: dict[str, Any]) -> None:
    has_fixed = "starts_at" in parameters
    has_range = "starts_after_range" in parameters
    if has_fixed and has_range:
        raise ValueError("Uzyj tylko jednego z pol: 'starts_at' albo 'starts_after_range'.")
    if has_range:
        value = parameters["starts_after_range"]
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError("Parametr 'starts_after_range' musi zawierac [min, max].")
        lower = require_non_negative(value[0], "starts_after_range[0]")
        upper = require_non_negative(value[1], "starts_after_range[1]")
        if upper < lower:
            raise ValueError("Parametr 'starts_after_range' musi miec max >= min.")
        return
    require_non_negative(parameters.get("starts_at"), "starts_at")


def resolve_start_time(
    scenario: ScenarioConfig | None,
    seed: int,
    override: float | None = None,
) -> float:
    if scenario is None:
        return 0.0
    if override is not None:
        return override
    parameters = scenario.parameters
    if "starts_after_range" not in parameters:
        return float(parameters["starts_at"])
    lower, upper = parameters["starts_after_range"]
    rng = random.Random(f"{seed}:{scenario.id}:start")
    return rng.uniform(float(lower), float(upper))


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
