from __future__ import annotations

import math
import random
from dataclasses import dataclass

import pygame

from models import StadiumConfig, Vec2
from scenarios import ScenarioRuntime
from stadium import Stadium
from utils import cell_center, circle_intersects_rect, clamp, clamp_int


@dataclass
class Agent:
    position: Vec2
    velocity: Vec2
    radius: float
    speed: float
    color: pygame.Color
    target_direction: Vec2
    evacuated: bool = False
    evacuated_at: float | None = None
    panicked: bool = False
    hazard_exposure: float = 0.0
    fleeing_until: float = 0.0

    def update(
        self,
        dt: float,
        stadium: "Stadium",
        scenario: ScenarioRuntime,
        neighbors: list["Agent"],
        elapsed: float,
        rng: random.Random,
    ) -> None:
        if self.evacuated:
            return

        desired = Vec2(self.target_direction)
        if desired.length_squared() > 0:
            desired = desired.normalize() * self.speed * scenario.speed_multiplier(self)

        force = (desired - self.velocity) * 3.8
        force += self._agent_repulsion(neighbors, stadium.config, scenario.personal_space_multiplier(self), rng)
        force += scenario.emergency_force(self, elapsed)
        noise = scenario.motion_noise(self)
        if noise > 0:
            force += Vec2(1, 0).rotate(rng.uniform(0, 360)) * noise
        solid_rects = stadium.nearby_solid_rects(self.position, max(self.radius * 2.4, self.radius))
        force += self._wall_repulsion(solid_rects, stadium.config)

        self.velocity += force * dt
        max_speed = self.speed * scenario.speed_multiplier(self) * stadium.config.crowd_max_speed_multiplier
        if self.velocity.length() > max_speed:
            self.velocity.scale_to_length(max_speed)

        movement = self.velocity * dt
        self._move_axis(Vec2(movement.x, 0), solid_rects)
        self._move_axis(Vec2(0, movement.y), solid_rects)

        if scenario.in_hazard(self.position):
            self.hazard_exposure += dt

        if scenario.is_evacuation_reached(self.position, self.radius):
            self.evacuated = True
            self.evacuated_at = elapsed
            self.velocity = Vec2(0, 0)

    def _agent_repulsion(
        self,
        neighbors: list["Agent"],
        config: StadiumConfig,
        personal_space_multiplier: float,
        rng: random.Random,
    ) -> Vec2:
        force = Vec2(0, 0)
        personal_space = config.crowd_personal_space * personal_space_multiplier
        for other in neighbors:
            if other is self or other.evacuated:
                continue

            delta = self.position - other.position
            distance_sq = delta.length_squared()
            if distance_sq <= 0:
                delta = Vec2(1, 0).rotate(rng.uniform(0, 360))
                distance_sq = 1

            distance = math.sqrt(distance_sq)
            min_distance = self.radius + other.radius + personal_space
            if distance >= min_distance:
                continue

            overlap = (min_distance - distance) / min_distance
            force += delta.normalize() * overlap * config.crowd_repulsion_strength
        return force

    def _wall_repulsion(self, solid_rects: list[pygame.Rect], config: StadiumConfig) -> Vec2:
        force = Vec2(0, 0)
        sense_radius = self.radius * 2.4
        for rect in solid_rects:
            closest = Vec2(
                max(rect.left, min(self.position.x, rect.right)),
                max(rect.top, min(self.position.y, rect.bottom)),
            )
            delta = self.position - closest
            distance_sq = delta.length_squared()
            if distance_sq <= 0:
                continue
            distance = math.sqrt(distance_sq)
            if distance >= sense_radius:
                continue
            force += delta.normalize() * (sense_radius - distance) / sense_radius * config.crowd_wall_repulsion_strength
        return force

    def _move_axis(self, movement: Vec2, solid_rects: list[pygame.Rect]) -> None:
        self.position += movement
        if movement.x == 0 and movement.y == 0:
            return

        for rect in solid_rects:
            if not circle_intersects_rect(self.position, self.radius, rect):
                continue

            if movement.x > 0:
                self.position.x = rect.left - self.radius
            elif movement.x < 0:
                self.position.x = rect.right + self.radius
            elif movement.y > 0:
                self.position.y = rect.top - self.radius
            elif movement.y < 0:
                self.position.y = rect.bottom + self.radius
            self.velocity *= 0.35

    def draw(self, surface: pygame.Surface) -> None:
        if self.evacuated:
            return
        center = (round(self.position.x), round(self.position.y))
        pygame.draw.circle(surface, self.color, center, round(self.radius))
        outline = pygame.Color("#e63946") if self.panicked else pygame.Color("#1d1f24")
        pygame.draw.circle(surface, outline, center, round(self.radius), 2 if self.panicked else 1)




class CrowdSimulation:
    def __init__(self, stadium: Stadium, scenario: ScenarioRuntime | None = None):
        self.stadium = stadium
        self.scenario = scenario or ScenarioRuntime(stadium, None)
        self.elapsed = 0.0
        self.paused = False
        self.routing_rng = random.Random(stadium.config.crowd_seed + 991)
        self.motion_rng = random.Random(stadium.config.crowd_seed + 1991)
        self.agents = spawn_agents(stadium)
        self.repath_timer = 0.0
        self.max_cell_count = 0
        self._active_agents = [agent for agent in self.agents if not agent.evacuated]
        self._evacuated_count = len(self.agents) - len(self._active_agents)
        self._cell_counts: dict[tuple[int, int], int] = {}
        self._refresh_frame_stats(self._active_agents)

    @property
    def active_agents(self) -> list[Agent]:
        return self._active_agents

    @property
    def evacuated_count(self) -> int:
        return self._evacuated_count

    def update(self, dt: float) -> None:
        if self.paused:
            return

        self.elapsed += dt
        self.repath_timer -= dt
        active = self._active_agents
        self.scenario.update(self.elapsed, active)
        buckets = self._agent_buckets(active)
        if self.repath_timer <= 0:
            self.repath_timer = self.stadium.config.crowd_repath_interval
            planned_counts = {cell: len(agents) for cell, agents in buckets.items()}
            for agent in active:
                agent.target_direction, target_cell = self._congestion_aware_direction(agent, planned_counts)
                if target_cell is not None:
                    planned_counts[target_cell] = planned_counts.get(target_cell, 0) + 1

        for agent in active:
            neighbors = self._nearby_agents(agent, buckets)
            agent.update(dt, self.stadium, self.scenario, neighbors, self.elapsed, self.motion_rng)

        self._resolve_agent_collisions(active, buckets)
        self._active_agents = [agent for agent in self.agents if not agent.evacuated]
        self._evacuated_count = len(self.agents) - len(self._active_agents)
        self._refresh_frame_stats(self._active_agents)

    def cell_counts(self) -> dict[tuple[int, int], int]:
        return self._cell_counts

    def _refresh_frame_stats(self, active: list[Agent]) -> None:
        counts: dict[tuple[int, int], int] = {}
        for agent in active:
            cell = self.stadium.cell_at_pixel(agent.position)
            counts[cell] = counts.get(cell, 0) + 1
        self._cell_counts = counts
        self.max_cell_count = max(self.max_cell_count, max(counts.values(), default=0))

    def draw_density(self, surface: pygame.Surface) -> None:
        for (x, y), count in self._cell_counts.items():
            if not self.stadium.is_walkable_cell(x, y):
                continue
            intensity = min(180, 35 + count * 24)
            pygame.draw.rect(surface, (255, 86, 55, intensity), self.stadium.tile_rect(x, y))

    def draw_hazard(self, surface: pygame.Surface) -> None:
        scenario_type = self.scenario.config.type if self.scenario.config is not None else None
        fill = (255, 125, 35, 92) if scenario_type == "fire" else (230, 40, 45, 110)
        for cell in self.scenario.hazard_cells:
            pygame.draw.rect(surface, fill, self.stadium.tile_rect(*cell))
        if self.scenario.config is None or self.elapsed < float(self.scenario.config.parameters["starts_at"]):
            return
        marker = self.scenario.marker_cell()
        if marker is None:
            return
        rect = self.stadium.tile_rect(*marker)
        marker_color = pygame.Color("#ff8a00" if scenario_type == "fire" else "#e63946")
        pygame.draw.circle(surface, marker_color, rect.center, max(5, rect.width // 2), 2)

    def draw_agents(self, surface: pygame.Surface) -> None:
        for agent in self._active_agents:
            agent.draw(surface)

    def _congestion_aware_direction(
        self,
        agent: Agent,
        planned_counts: dict[tuple[int, int], int],
    ) -> tuple[Vec2, tuple[int, int] | None]:
        config = self.stadium.config
        x, y = self.stadium.cell_at_pixel(agent.position)
        if not self.stadium.is_walkable_cell(x, y):
            return Vec2(0, 0), None
        if config.layout[y][x] in config.exit_tiles:
            target = self.stadium.nearest_exit_center(agent.position)
            return direction_to(agent.position, target), (x, y)

        candidates: list[tuple[int, int]] = []
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if self.stadium.is_walkable_cell(nx, ny) and self.scenario.routing.distances[ny][nx] < math.inf:
                candidates.append((nx, ny))
        if not candidates:
            return Vec2(0, 0), None

        def candidate_score(cell: tuple[int, int]) -> tuple[float, int, int]:
            nx, ny = cell
            congestion = planned_counts.get(cell, 0)
            score = (
                self.scenario.routing.distances[ny][nx]
                + congestion * config.crowd_congestion_weight * self.scenario.congestion_multiplier(agent)
            )
            return score, ny, nx

        if self.scenario.random_route_chance(agent) > 0 and self.routing_rng.random() < self.scenario.random_route_chance(agent):
            target_cell = self.routing_rng.choice(candidates)
        else:
            target_cell = min(candidates, key=candidate_score)
        target = cell_center(
            target_cell,
            config.col_lefts,
            config.row_tops,
            config.col_widths,
            config.row_heights,
        )
        return direction_to(agent.position, target), target_cell

    def _agent_buckets(self, active: list[Agent]) -> dict[tuple[int, int], list[Agent]]:
        buckets: dict[tuple[int, int], list[Agent]] = {}
        for agent in active:
            cell = self.stadium.cell_at_pixel(agent.position)
            buckets.setdefault(cell, []).append(agent)
        return buckets

    def _nearby_agents(self, agent: Agent, buckets: dict[tuple[int, int], list[Agent]]) -> list[Agent]:
        x, y = self.stadium.cell_at_pixel(agent.position)
        neighbors: list[Agent] = []
        for ny in range(y - 1, y + 2):
            for nx in range(x - 1, x + 2):
                neighbors.extend(buckets.get((nx, ny), []))
        return neighbors

    def _resolve_agent_collisions(
        self,
        active: list[Agent],
        buckets: dict[tuple[int, int], list[Agent]],
    ) -> None:
        for iteration in range(self.stadium.config.crowd_collision_iterations):
            if iteration > 0:
                buckets = self._agent_buckets(active)
            for cell, agents in buckets.items():
                self._resolve_bucket_pairs(agents, agents, same_bucket=True)
                x, y = cell
                for neighbor_cell in (
                    (x + 1, y - 1),
                    (x + 1, y),
                    (x + 1, y + 1),
                    (x, y + 1),
                ):
                    neighbor_agents = buckets.get(neighbor_cell)
                    if neighbor_agents:
                        self._resolve_bucket_pairs(agents, neighbor_agents, same_bucket=False)
            for agent in active:
                keep_agent_out_of_walls(agent, self.stadium)

    def _resolve_bucket_pairs(
        self,
        first_bucket: list[Agent],
        second_bucket: list[Agent],
        same_bucket: bool,
    ) -> None:
        if same_bucket:
            for first_index, first in enumerate(first_bucket):
                if first.evacuated:
                    continue
                for second in second_bucket[first_index + 1:]:
                    if not second.evacuated:
                        separate_agents(first, second)
            return

        for first in first_bucket:
            if first.evacuated:
                continue
            for second in second_bucket:
                if not second.evacuated:
                    separate_agents(first, second)




def spawn_agents(stadium: Stadium) -> list[Agent]:
    config = stadium.config
    rng = random.Random(config.crowd_seed)
    candidates = spawn_candidate_cells(stadium)
    agents: list[Agent] = []

    for index in range(config.crowd_count):
        cell = candidates[index]
        center = cell_center(cell, config.col_lefts, config.row_tops, config.col_widths, config.row_heights)
        jitter = Vec2(
            rng.uniform(-config.crowd_spawn_jitter, config.crowd_spawn_jitter),
            rng.uniform(-config.crowd_spawn_jitter, config.crowd_spawn_jitter),
        )
        position = keep_inside_cell(center + jitter, cell, config, config.agent_radius)
        speed_variation = rng.uniform(0.82, 1.13)
        color_shift = rng.randint(-18, 18)
        color = pygame.Color(
            clamp_int(config.agent_color.r + color_shift, 0, 255),
            clamp_int(config.agent_color.g + color_shift, 0, 255),
            clamp_int(config.agent_color.b + color_shift, 0, 255),
        )
        agents.append(
            Agent(
                position=position,
                velocity=Vec2(0, 0),
                radius=config.agent_radius,
                speed=config.agent_speed * speed_variation,
                color=color,
                target_direction=stadium.desired_direction(position),
            )
        )

    return agents




def spawn_candidate_cells(stadium: Stadium) -> list[tuple[int, int]]:
    config = stadium.config
    cells: list[tuple[int, int]] = []
    for y, row in enumerate(config.layout):
        row_cells: list[tuple[int, int]] = []
        for x, tile in enumerate(row):
            if not stadium.is_walkable_cell(x, y):
                continue
            if config.col_widths[x] < config.agent_radius * 2 + 2:
                continue
            if config.row_heights[y] < config.agent_radius * 2 + 2:
                continue
            if tile in config.exit_tiles or tile in config.stairs_tiles:
                continue
            if tile != ".":
                continue
            if stadium.distance_to_exit[y][x] == math.inf:
                continue
            row_cells.append((x, y))

        if y % 2:
            row_cells.reverse()
        cells.extend(row_cells)

    if not cells:
        spawn_x, spawn_y = stadium.cell_at_pixel(config.spawn_position)
        return [(spawn_x, spawn_y) for _ in range(config.crowd_count)]

    return evenly_spaced_cells(cells, config.crowd_count)




def evenly_spaced_cells(cells: list[tuple[int, int]], count: int) -> list[tuple[int, int]]:
    if count <= len(cells):
        if count == 1:
            return [cells[len(cells) // 2]]
        step = (len(cells) - 1) / (count - 1)
        return [cells[round(index * step)] for index in range(count)]

    selected = list(cells)
    index = 0
    while len(selected) < count:
        selected.append(cells[index % len(cells)])
        index += 1
    return selected




def direction_to(position: Vec2, target: Vec2) -> Vec2:
    delta = target - position
    if delta.length_squared() == 0:
        return Vec2(0, 0)
    return delta.normalize()




def separate_agents(first: Agent, second: Agent) -> None:
    delta = first.position - second.position
    distance_sq = delta.length_squared()
    if distance_sq <= 0:
        delta = Vec2(1, 0).rotate((id(first) + id(second)) % 360)
        distance_sq = 1

    distance = math.sqrt(distance_sq)
    min_distance = first.radius + second.radius + 1.0
    if distance >= min_distance:
        return

    normal = delta / distance
    correction = (min_distance - distance) * 0.5
    first.position += normal * correction
    second.position -= normal * correction

    relative_speed = first.velocity - second.velocity
    separating_speed = relative_speed.dot(normal)
    if separating_speed < 0:
        impulse = normal * separating_speed * 0.5
        first.velocity -= impulse
        second.velocity += impulse




def keep_agent_out_of_walls(agent: Agent, stadium: Stadium) -> None:
    for rect in stadium.nearby_solid_rects(agent.position, agent.radius):
        if not circle_intersects_rect(agent.position, agent.radius, rect):
            continue

        closest = Vec2(
            max(rect.left, min(agent.position.x, rect.right)),
            max(rect.top, min(agent.position.y, rect.bottom)),
        )
        delta = agent.position - closest
        if delta.length_squared() > 0:
            distance = delta.length()
            agent.position += delta.normalize() * (agent.radius - distance + 0.5)
            agent.velocity *= 0.35
            continue

        left_push = abs(agent.position.x - rect.left)
        right_push = abs(rect.right - agent.position.x)
        top_push = abs(agent.position.y - rect.top)
        bottom_push = abs(rect.bottom - agent.position.y)
        push = min(
            (left_push, Vec2(-1, 0)),
            (right_push, Vec2(1, 0)),
            (top_push, Vec2(0, -1)),
            (bottom_push, Vec2(0, 1)),
            key=lambda item: item[0],
        )
        agent.position += push[1] * (agent.radius + push[0] + 0.5)
        agent.velocity *= 0.2




def keep_inside_cell(position: Vec2, cell: tuple[int, int], config: StadiumConfig, radius: float) -> Vec2:
    x, y = cell
    rect = pygame.Rect(config.col_lefts[x], config.row_tops[y], config.col_widths[x], config.row_heights[y])
    return Vec2(
        clamp(position.x, rect.left + radius, rect.right - radius),
        clamp(position.y, rect.top + radius, rect.bottom - radius),
    )
