from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from models import ScenarioChoice, ScenarioConfig, StadiumConfig, Vec2
from stadium import Stadium, build_exit_route_maps
from utils import circle_intersects_rect


SCENARIO_TYPES = {"delayed_gates", "fire", "uneven_crowd", "panic"}


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
    if scenario.type == "delayed_gates":
        gates = parameters.get("gates")
        if not isinstance(gates, list) or not gates:
            raise ValueError("Scenariusz delayed_gates wymaga listy 'gates'.")
        for gate in gates:
            resolve_exit_reference(gate, config)
            require_non_negative(gate.get("opens_at"), "opens_at")
        return
    if scenario.type == "uneven_crowd":
        weights = parameters.get("sector_weights")
        if not isinstance(weights, dict) or not weights:
            raise ValueError("Scenariusz uneven_crowd wymaga obiektu 'sector_weights'.")
        for sector_id, weight in weights.items():
            require_sector(str(sector_id), config)
            require_non_negative(weight, f"waga sektora {sector_id}")
        effective_total = sum(
            float(weights.get(sector_id, 1.0))
            for sector_id in config.metadata.sector_cells
        )
        if effective_total <= 0:
            raise ValueError("Co najmniej jeden sektor musi miec dodatnia wage.")
        return

    location_key = "origin" if scenario.type == "fire" else "incident"
    resolve_local_cell(parameters.get(location_key), config, location_key)
    require_non_negative(parameters.get("starts_at"), "starts_at")
    if scenario.type == "fire":
        initial_radius = require_positive(parameters.get("initial_radius"), "initial_radius")
        require_non_negative(parameters.get("growth_per_second"), "growth_per_second")
        max_radius = require_positive(parameters.get("max_radius"), "max_radius")
        if max_radius < initial_radius:
            raise ValueError("Parametr 'max_radius' nie moze byc mniejszy od 'initial_radius'.")
        require_positive(parameters.get("routing_cost"), "routing_cost")
    else:
        require_positive(parameters.get("influence_radius"), "influence_radius")
        require_positive(parameters.get("speed_multiplier"), "speed_multiplier")
        require_positive(parameters.get("personal_space_multiplier"), "personal_space_multiplier")
        require_non_negative(parameters.get("congestion_weight_multiplier"), "congestion_weight_multiplier")


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
        self._opened_gates: set[tuple[str, str]] = set()
        all_exit_cells = {
            cell
            for exits in stadium.config.metadata.sector_exits.values()
            for exit_ref in exits
            for cell in exit_ref.cells
        }
        active_exit_cells = set(all_exit_cells)
        if scenario is not None and scenario.type == "delayed_gates":
            for gate in scenario.parameters["gates"]:
                active_exit_cells -= resolve_exit_reference(gate, stadium.config)
        self.routing = RoutingContext(active_exit_cells, {}, [], [])
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
        if self.config.type == "delayed_gates":
            self._update_delayed_gates(elapsed, agents)
        elif self.config.type == "fire":
            self._update_fire(elapsed)
        elif self.config.type == "panic":
            self._update_panic(elapsed, agents)

    def consume_events(self) -> list[dict[str, Any]]:
        events = self.events[self._event_cursor:]
        self._event_cursor = len(self.events)
        return events

    def sector_weights(self) -> dict[str, float] | None:
        if self.config is None or self.config.type != "uneven_crowd":
            return None
        supplied = self.config.parameters["sector_weights"]
        return {
            sector_id: float(supplied.get(sector_id, 1.0))
            for sector_id in self.stadium.config.metadata.sector_cells
        }

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

    def in_hazard(self, position: Vec2) -> bool:
        return self.stadium.cell_at_pixel(position) in self.hazard_cells

    def is_evacuation_reached(self, position: Vec2, radius: float) -> bool:
        for cell in self.routing.active_exit_cells:
            if circle_intersects_rect(position, radius, self.stadium.tile_rect(*cell)):
                return True
        return False

    def _update_delayed_gates(self, elapsed: float, agents: list[Any]) -> None:
        changed = False
        for gate in self.config.parameters["gates"]:
            key = (str(gate["sector_id"]), str(gate["exit_id"]))
            if key in self._opened_gates or elapsed < float(gate["opens_at"]):
                continue
            cells = resolve_exit_reference(gate, self.stadium.config)
            self.routing.active_exit_cells.update(cells)
            self._opened_gates.add(key)
            changed = True
            self.events.append(
                {
                    "time": round(elapsed, 4),
                    "type": "gate_opened",
                    "sector_id": key[0],
                    "exit_id": key[1],
                    "active_agents": len(agents),
                }
            )
        if changed:
            self._rebuild_routes()

    def _update_fire(self, elapsed: float) -> None:
        starts_at = float(self.config.parameters["starts_at"])
        if elapsed < starts_at:
            return
        if not self.hazard_started:
            self.hazard_started = True
            self.events.append({"time": round(elapsed, 4), "type": "fire_started"})
        radius = min(
            float(self.config.parameters["max_radius"]),
            float(self.config.parameters["initial_radius"])
            + (elapsed - starts_at) * float(self.config.parameters["growth_per_second"]),
        )
        center = resolve_local_cell(self.config.parameters["origin"], self.stadium.config, "origin")
        new_cells = {
            (x, y)
            for y, row in enumerate(self.stadium.config.layout)
            for x in range(len(row))
            if self.stadium.is_walkable_cell(x, y)
            and math.dist((x, y), center) <= radius
        }
        self.hazard_radius = radius
        if new_cells == self.hazard_cells:
            return
        self.hazard_cells = new_cells
        cost = float(self.config.parameters["routing_cost"])
        self.routing.additional_costs = {cell: cost for cell in new_cells}
        self.events.append(
            {
                "time": round(elapsed, 4),
                "type": "fire_expanded",
                "radius": round(radius, 4),
                "affected_cells": len(new_cells),
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
