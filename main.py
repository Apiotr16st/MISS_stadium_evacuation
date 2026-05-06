from __future__ import annotations

import argparse
import heapq
import json
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pygame


Vec2 = pygame.math.Vector2


@dataclass(frozen=True)
class TileStyle:
    name: str
    color: pygame.Color
    solid: bool
    edges: tuple[str, ...]
    visual_width_ratio: float
    visual_height_ratio: float
    visual_align_x: str
    visual_align_y: str
    collision_width_ratio: float
    collision_height_ratio: float
    collision_align_x: str
    collision_align_y: str


@dataclass(frozen=True)
class StadiumConfig:
    title: str
    fps: int
    ui_width: int
    tile_size: int
    layout: list[str]
    tile_styles: dict[str, TileStyle]
    solid_tiles: set[str]
    stairs_tiles: set[str]
    exit_tiles: set[str]
    spawn_position: Vec2
    agent_radius: float
    agent_speed: float
    agent_color: pygame.Color
    crowd_count: int
    crowd_seed: int
    crowd_spawn_jitter: float
    crowd_repath_interval: float
    crowd_personal_space: float
    crowd_repulsion_strength: float
    crowd_wall_repulsion_strength: float
    crowd_max_speed_multiplier: float
    config_path: Path
    col_widths: list[int]
    row_heights: list[int]
    col_lefts: list[int]
    row_tops: list[int]

    @property
    def width(self) -> int:
        return len(self.layout[0])

    @property
    def height(self) -> int:
        return len(self.layout)

    @property
    def world_size(self) -> tuple[int, int]:
        return sum(self.col_widths), sum(self.row_heights)


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

    def update(
        self,
        dt: float,
        stadium: "Stadium",
        neighbors: list["Agent"],
        elapsed: float,
    ) -> None:
        if self.evacuated:
            return

        desired = Vec2(self.target_direction)
        if desired.length_squared() > 0:
            desired = desired.normalize() * self.speed

        force = (desired - self.velocity) * 3.8
        force += self._agent_repulsion(neighbors, stadium.config)
        force += self._wall_repulsion(stadium)

        self.velocity += force * dt
        max_speed = self.speed * stadium.config.crowd_max_speed_multiplier
        if self.velocity.length() > max_speed:
            self.velocity.scale_to_length(max_speed)

        movement = self.velocity * dt
        self._move_axis(Vec2(movement.x, 0), stadium)
        self._move_axis(Vec2(0, movement.y), stadium)

        if stadium.is_evacuation_reached(self.position, self.radius):
            self.evacuated = True
            self.evacuated_at = elapsed
            self.velocity = Vec2(0, 0)

    def _agent_repulsion(self, neighbors: list["Agent"], config: StadiumConfig) -> Vec2:
        force = Vec2(0, 0)
        personal_space = config.crowd_personal_space
        for other in neighbors:
            if other is self or other.evacuated:
                continue

            delta = self.position - other.position
            distance_sq = delta.length_squared()
            if distance_sq <= 0:
                delta = Vec2(1, 0).rotate(random.uniform(0, 360))
                distance_sq = 1

            distance = math.sqrt(distance_sq)
            min_distance = self.radius + other.radius + personal_space
            if distance >= min_distance:
                continue

            overlap = (min_distance - distance) / min_distance
            force += delta.normalize() * overlap * config.crowd_repulsion_strength
        return force

    def _wall_repulsion(self, stadium: "Stadium") -> Vec2:
        force = Vec2(0, 0)
        sense_radius = self.radius * 2.4
        for rect in stadium.nearby_solid_rects(self.position, sense_radius):
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
            force += delta.normalize() * (sense_radius - distance) / sense_radius * stadium.config.crowd_wall_repulsion_strength
        return force

    def _move_axis(self, movement: Vec2, stadium: "Stadium") -> None:
        self.position += movement
        if movement.x == 0 and movement.y == 0:
            return

        for rect in stadium.nearby_solid_rects(self.position, self.radius):
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
        pygame.draw.circle(surface, pygame.Color("#1d1f24"), center, round(self.radius), 1)


class Stadium:
    def __init__(self, config: StadiumConfig):
        self.config = config
        self.tile_size = config.tile_size
        self.distance_to_exit, self.next_cell_to_exit = build_exit_route_maps(config)
        self.exit_rects = self._build_exit_rects()
        self.exit_centers = [
            Vec2(rect.centerx, rect.centery)
            for rect in self.exit_rects
        ]
        self.solid_rects: list[tuple[str, pygame.Rect]] = []
        for y, row in enumerate(config.layout):
            for x, tile in enumerate(row):
                if tile in config.solid_tiles:
                    for rect in self.tile_collision_rects(x, y, tile):
                        self.solid_rects.append((tile, rect))

    def tile_at_pixel(self, position: Vec2) -> str:
        cell = self.cell_at_pixel(position)
        x, y = cell
        if x < 0 or y < 0 or y >= self.config.height or x >= self.config.width:
            return "#"
        return self.config.layout[y][x]

    def cell_at_pixel(self, position: Vec2) -> tuple[int, int]:
        return (
            index_at_position(position.x, self.config.col_lefts, self.config.col_widths),
            index_at_position(position.y, self.config.row_tops, self.config.row_heights),
        )

    def is_walkable_cell(self, x: int, y: int) -> bool:
        if x < 0 or y < 0 or y >= self.config.height or x >= self.config.width:
            return False
        tile = self.config.layout[y][x]
        return tile not in self.config.solid_tiles

    def desired_direction(self, position: Vec2) -> Vec2:
        x, y = self.cell_at_pixel(position)
        if not self.is_walkable_cell(x, y):
            return Vec2(0, 0)

        if self.config.layout[y][x] in self.config.exit_tiles:
            target = self.nearest_exit_center(position)
            return normalized_or_zero(target - position)

        next_cell = self.next_cell_to_exit[y][x]
        if next_cell is None:
            target = self.nearest_exit_center(position)
            return normalized_or_zero(target - position)

        target = cell_center(
            next_cell,
            self.config.col_lefts,
            self.config.row_tops,
            self.config.col_widths,
            self.config.row_heights,
        )
        return normalized_or_zero(target - position)

    def is_evacuation_reached(self, position: Vec2, radius: float) -> bool:
        for rect in self.exit_rects:
            if circle_intersects_rect(position, radius, rect):
                return True
        return False

    def nearest_exit_center(self, position: Vec2) -> Vec2:
        if not self.exit_centers:
            return Vec2(position)
        return min(self.exit_centers, key=lambda center: (center - position).length_squared())

    def _build_exit_rects(self) -> list[pygame.Rect]:
        rects: list[pygame.Rect] = []
        for y, row in enumerate(self.config.layout):
            for x, tile in enumerate(row):
                if tile in self.config.exit_tiles:
                    rects.append(self.tile_rect(x, y))
        return rects

    def nearby_solid_rects(self, position: Vec2, radius: float) -> list[pygame.Rect]:
        min_x = max(0, index_at_position(position.x - radius, self.config.col_lefts, self.config.col_widths) - 1)
        max_x = min(
            self.config.width - 1,
            index_at_position(position.x + radius, self.config.col_lefts, self.config.col_widths) + 1,
        )
        min_y = max(0, index_at_position(position.y - radius, self.config.row_tops, self.config.row_heights) - 1)
        max_y = min(
            self.config.height - 1,
            index_at_position(position.y + radius, self.config.row_tops, self.config.row_heights) + 1,
        )

        rects: list[pygame.Rect] = []
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                tile = self.config.layout[y][x]
                if tile in self.config.solid_tiles:
                    rects.extend(self.tile_collision_rects(x, y, tile))
        return rects

    def tile_collision_rects(self, x: int, y: int, tile: str) -> list[pygame.Rect]:
        style = self.config.tile_styles[tile]
        tile_rect = self.tile_rect(x, y)
        if style.edges:
            return [edge_rect(tile_rect, style, edge, visual=False) for edge in style.edges]

        return [
            aligned_size_rect(
                tile_rect,
                style.collision_width_ratio,
                style.collision_height_ratio,
                style.collision_align_x,
                style.collision_align_y,
            )
        ]

    def tile_rect(self, x: int, y: int) -> pygame.Rect:
        return pygame.Rect(
            self.config.col_lefts[x],
            self.config.row_tops[y],
            self.config.col_widths[x],
            self.config.row_heights[y],
        )

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(pygame.Color("#151a1f"))
        for y, row in enumerate(self.config.layout):
            for x, tile in enumerate(row):
                style = self.config.tile_styles[tile]
                draw_tile(surface, self.tile_rect(x, y), tile, style)


class CrowdSimulation:
    def __init__(self, stadium: Stadium):
        self.stadium = stadium
        self.elapsed = 0.0
        self.paused = False
        self.agents = spawn_agents(stadium)
        self.repath_timer = 0.0
        self.max_cell_count = 0

    @property
    def active_agents(self) -> list[Agent]:
        return [agent for agent in self.agents if not agent.evacuated]

    @property
    def evacuated_count(self) -> int:
        return len(self.agents) - len(self.active_agents)

    def update(self, dt: float) -> None:
        if self.paused:
            return

        self.elapsed += dt
        self.repath_timer -= dt
        if self.repath_timer <= 0:
            self.repath_timer = self.stadium.config.crowd_repath_interval
            for agent in self.active_agents:
                agent.target_direction = self.stadium.desired_direction(agent.position)

        buckets = self._agent_buckets()
        for agent in self.active_agents:
            neighbors = self._nearby_agents(agent, buckets)
            agent.update(dt, self.stadium, neighbors, self.elapsed)

        self._resolve_agent_collisions()
        self.max_cell_count = max(self.max_cell_count, max(self.cell_counts().values(), default=0))

    def cell_counts(self) -> dict[tuple[int, int], int]:
        counts: dict[tuple[int, int], int] = {}
        for agent in self.active_agents:
            cell = self.stadium.cell_at_pixel(agent.position)
            counts[cell] = counts.get(cell, 0) + 1
        return counts

    def draw_density(self, surface: pygame.Surface) -> None:
        for (x, y), count in self.cell_counts().items():
            if not self.stadium.is_walkable_cell(x, y):
                continue
            intensity = min(180, 35 + count * 24)
            overlay = pygame.Surface((self.stadium.config.col_widths[x], self.stadium.config.row_heights[y]), pygame.SRCALPHA)
            overlay.fill((255, 86, 55, intensity))
            surface.blit(overlay, self.stadium.tile_rect(x, y).topleft)

    def draw_agents(self, surface: pygame.Surface) -> None:
        for agent in self.active_agents:
            agent.draw(surface)

    def _agent_buckets(self) -> dict[tuple[int, int], list[Agent]]:
        buckets: dict[tuple[int, int], list[Agent]] = {}
        for agent in self.active_agents:
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

    def _resolve_agent_collisions(self) -> None:
        active = self.active_agents
        for _ in range(3):
            buckets = self._agent_buckets()
            handled: set[tuple[int, int]] = set()
            for first in active:
                if first.evacuated:
                    continue
                for second in self._nearby_agents(first, buckets):
                    if second is first or second.evacuated:
                        continue
                    pair = tuple(sorted((id(first), id(second))))
                    if pair in handled:
                        continue
                    handled.add(pair)
                    separate_agents(first, second)
            for agent in active:
                keep_agent_out_of_walls(agent, self.stadium)


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


def build_exit_route_maps(
    config: StadiumConfig,
) -> tuple[list[list[float]], list[list[tuple[int, int] | None]]]:
    distances = [[math.inf for _ in range(config.width)] for _ in range(config.height)]
    next_cells: list[list[tuple[int, int] | None]] = [[None for _ in range(config.width)] for _ in range(config.height)]
    queue: list[tuple[float, int, int]] = []

    for y, row in enumerate(config.layout):
        for x, tile in enumerate(row):
            if tile in config.exit_tiles:
                distances[y][x] = 0
                heapq.heappush(queue, (0, x, y))

    while queue:
        current_cost, x, y = heapq.heappop(queue)
        if current_cost > distances[y][x]:
            continue
        for nx, ny in walkable_neighbors(x, y, config):
            step_cost = movement_cost(config.layout[ny][nx], config)
            new_cost = distances[y][x] + step_cost
            if new_cost < distances[ny][nx]:
                distances[ny][nx] = new_cost
                next_cells[ny][nx] = (x, y)
                heapq.heappush(queue, (new_cost, nx, ny))

    return distances, next_cells


def walkable_neighbors(x: int, y: int, config: StadiumConfig) -> list[tuple[int, int]]:
    neighbors: list[tuple[int, int]] = []
    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
        if nx < 0 or ny < 0 or ny >= config.height or nx >= config.width:
            continue
        if config.layout[ny][nx] in config.solid_tiles:
            continue
        neighbors.append((nx, ny))
    return neighbors


def movement_cost(tile: str, config: StadiumConfig) -> float:
    if tile in config.stairs_tiles:
        return 1.35
    if tile in config.exit_tiles:
        return 0.65
    return 1.0


def normalized_or_zero(vector: Vec2) -> Vec2:
    if vector.length_squared() == 0:
        return Vec2(0, 0)
    return vector.normalize()


def circle_intersects_rect(center: Vec2, radius: float, rect: pygame.Rect) -> bool:
    closest_x = max(rect.left, min(center.x, rect.right))
    closest_y = max(rect.top, min(center.y, rect.bottom))
    dx = center.x - closest_x
    dy = center.y - closest_y
    return dx * dx + dy * dy < radius * radius


def draw_tile(surface: pygame.Surface, rect: pygame.Rect, tile: str, style: TileStyle) -> None:
    pygame.draw.rect(surface, style.color, rect)

    if tile == "#":
        pygame.draw.rect(surface, pygame.Color("#2e3740"), rect, 1)
        pygame.draw.line(surface, pygame.Color("#59656f"), rect.topleft, rect.topright)
        return

    if style.edges:
        pygame.draw.rect(surface, pygame.Color("#2b333b"), rect)
        for edge in style.edges:
            draw_edge(surface, edge_rect(rect, style, edge, visual=True), edge)
        return

    if tile == "S":
        pygame.draw.rect(surface, pygame.Color("#737d86"), rect.inflate(-3, -1), border_radius=2)
        step_gap = max(5, rect.height // 4)
        for y in range(rect.top + 4, rect.bottom, step_gap):
            pygame.draw.line(surface, pygame.Color("#d0d5d8"), (rect.left + 4, y), (rect.right - 4, y), 1)
        pygame.draw.line(surface, pygame.Color("#4b565f"), rect.topleft, rect.bottomleft, 2)
        pygame.draw.line(surface, pygame.Color("#4b565f"), rect.topright, rect.bottomright, 2)
        return

    if tile == "E":
        pygame.draw.rect(surface, pygame.Color("#1f7a4d"), rect.inflate(-2, -2), border_radius=2)
        arrow = [
            (rect.centerx, rect.top + rect.height * 0.25),
            (rect.right - rect.width * 0.2, rect.centery),
            (rect.centerx, rect.bottom - rect.height * 0.25),
            (rect.centerx, rect.centery + rect.height * 0.12),
            (rect.left + rect.width * 0.2, rect.centery + rect.height * 0.12),
            (rect.left + rect.width * 0.2, rect.centery - rect.height * 0.12),
            (rect.centerx, rect.centery - rect.height * 0.12),
        ]
        pygame.draw.polygon(surface, pygame.Color("#d8ffe6"), arrow)
        return

    if tile == "T":
        pygame.draw.rect(surface, pygame.Color("#0a0c10"), rect)
        pygame.draw.rect(surface, pygame.Color("#255b3b"), rect, 2)
        return

    pygame.draw.rect(surface, pygame.Color("#252c33"), rect, 1)


def draw_ui(
    surface: pygame.Surface,
    font: pygame.font.Font,
    small_font: pygame.font.Font,
    config: StadiumConfig,
    crowd: CrowdSimulation,
) -> None:
    world_w, world_h = config.world_size
    panel = pygame.Rect(world_w, 0, config.ui_width, world_h)
    pygame.draw.rect(surface, pygame.Color("#101418"), panel)
    pygame.draw.line(surface, pygame.Color("#37424d"), (world_w, 0), (world_w, world_h), 2)

    x = world_w + 18
    y = 20
    y = draw_text(surface, font, "Model trybuny", x, y, pygame.Color("#f4f7f8"))
    y = draw_text(surface, small_font, "Space: pauza / wznowienie", x, y + 12, pygame.Color("#b8c1c9"))
    y = draw_text(surface, small_font, "Esc: zamknij symulacje", x, y + 5, pygame.Color("#b8c1c9"))
    y = draw_text(surface, small_font, f"Config: {config.config_path.name}", x, y + 5, pygame.Color("#b8c1c9"))

    y += 20
    y = draw_text(surface, font, "Status", x, y, pygame.Color("#f4f7f8"))
    y = draw_text(surface, small_font, f"Czas: {crowd.elapsed:5.1f} s", x, y + 8, pygame.Color("#b8c1c9"))
    y = draw_text(surface, small_font, f"Na trybunie: {len(crowd.active_agents)}", x, y + 5, pygame.Color("#b8c1c9"))
    y = draw_text(surface, small_font, f"Ewakuowani: {crowd.evacuated_count}/{len(crowd.agents)}", x, y + 5, pygame.Color("#b8c1c9"))
    y = draw_text(surface, small_font, f"Max gestosc/kafelek: {crowd.max_cell_count}", x, y + 5, pygame.Color("#b8c1c9"))
    if crowd.paused:
        y = draw_text(surface, font, "Pauza", x, y + 18, pygame.Color("#ffd166"))
    elif crowd.evacuated_count == len(crowd.agents):
        y = draw_text(surface, font, "Ewakuacja zakonczona", x, y + 18, pygame.Color("#9ef0b5"))


def draw_text(
    surface: pygame.Surface,
    font: pygame.font.Font,
    text: str,
    x: int,
    y: int,
    color: pygame.Color,
) -> int:
    rendered = font.render(text, True, color)
    surface.blit(rendered, (x, y))
    return y + rendered.get_height()


def draw_edge(surface: pygame.Surface, rect: pygame.Rect, edge: str) -> None:
    shadow = edge_shadow_rect(rect, edge)
    pygame.draw.rect(surface, pygame.Color("#1b2026"), shadow, border_radius=2)
    pygame.draw.rect(surface, pygame.Color("#4f2229"), rect, border_radius=3)
    if edge == "D":
        pygame.draw.line(surface, pygame.Color("#8c3b45"), rect.midtop, rect.midbottom, 1)
        pygame.draw.line(surface, pygame.Color("#2a1116"), rect.bottomleft, rect.bottomright, 2)
        return

    pygame.draw.line(surface, pygame.Color("#8c3b45"), rect.midleft, rect.midright, 1)
    pygame.draw.line(surface, pygame.Color("#2a1116"), rect.topright, rect.bottomright, 2)


def edge_shadow_rect(rect: pygame.Rect, edge: str) -> pygame.Rect:
    if edge == "D":
        shadow = rect.copy()
        shadow.height = max(3, rect.height // 2)
        shadow.top = rect.bottom - 1
        return shadow

    shadow = rect.copy()
    shadow.width = max(3, rect.width // 2)
    shadow.left = rect.right - 1
    return shadow


def edge_rect(rect: pygame.Rect, style: TileStyle, edge: str, visual: bool) -> pygame.Rect:
    width_ratio = 1.0 if visual else style.collision_width_ratio
    height_ratio = 1.0 if visual else style.collision_height_ratio
    align_x = style.visual_align_x if visual else style.collision_align_x
    align_y = style.visual_align_y if visual else style.collision_align_y
    if edge == "P":
        return aligned_size_rect(rect, width_ratio, 1.0, align_x, "center")
    if edge == "D":
        return aligned_size_rect(rect, 1.0, height_ratio, "center", align_y)
    raise ValueError(f"Nieznana sciana: {edge}")


def aligned_size_rect(
    rect: pygame.Rect,
    width_ratio: float,
    height_ratio: float,
    align_x: str,
    align_y: str,
) -> pygame.Rect:
    width_ratio = clamp(width_ratio, 0.05, 1.0)
    height_ratio = clamp(height_ratio, 0.05, 1.0)
    width = max(2, round(rect.width * width_ratio))
    height = max(2, round(rect.height * height_ratio))
    left = aligned_offset(rect.left, rect.width, width, align_x)
    top = aligned_offset(rect.top, rect.height, height, align_y)
    return pygame.Rect(left, top, width, height)


def aligned_offset(start: int, full_size: int, part_size: int, align: str) -> int:
    if align in {"start", "left", "top"}:
        return start
    if align in {"end", "right", "bottom"}:
        return start + full_size - part_size
    return start + (full_size - part_size) // 2


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def index_at_position(value: float, starts: list[int], sizes: list[int]) -> int:
    if not starts:
        return -1
    for index, start in enumerate(starts):
        if start <= value < start + sizes[index]:
            return index
    if value < starts[0]:
        return -1
    return len(starts)


def build_offsets(sizes: list[int]) -> list[int]:
    offsets: list[int] = []
    current = 0
    for size in sizes:
        offsets.append(current)
        current += size
    return offsets


def cell_center(
    cell: tuple[int, int],
    col_lefts: list[int],
    row_tops: list[int],
    col_widths: list[int],
    row_heights: list[int],
) -> Vec2:
    x, y = cell
    return Vec2(col_lefts[x] + col_widths[x] / 2, row_tops[y] + row_heights[y] / 2)


def build_compacted_dimensions(
    layout: list[str],
    tile_styles: dict[str, TileStyle],
    tile_size: int,
) -> tuple[list[int], list[int]]:
    width = len(layout[0])
    col_widths = [tile_size for _ in range(width)]
    row_heights = [tile_size for _ in layout]

    for y, row in enumerate(layout):
        ratios = [
            tile_styles[tile].visual_height_ratio
            for tile in row
            if has_horizontal_edge(tile_styles[tile])
        ]
        if ratios:
            row_heights[y] = max(2, round(tile_size * max(ratios)))

    for x in range(width):
        ratios = [
            tile_styles[layout[y][x]].visual_width_ratio
            for y in range(len(layout))
            if has_vertical_edge(tile_styles[layout[y][x]])
        ]
        if ratios:
            col_widths[x] = max(2, round(tile_size * max(ratios)))

    return col_widths, row_heights


def has_horizontal_edge(style: TileStyle) -> bool:
    return "D" in style.edges


def has_vertical_edge(style: TileStyle) -> bool:
    return "P" in style.edges


def load_config(config_path: Path) -> StadiumConfig:
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    tile_size = int(raw.get("tile_size", 26))
    if tile_size < 12:
        raise ValueError("tile_size musi miec co najmniej 12 pikseli.")

    window = raw.get("window", {})
    title = str(window.get("title", "MISS - model trybuny stadionu"))
    fps = int(window.get("fps", 60))
    ui_width = int(window.get("ui_width", 310))

    tile_styles = parse_tile_styles(raw.get("tiles", {}))
    layout_block = raw.get("layout", {})
    layout = load_layout(layout_block, raw, config_path.parent)

    spawn_tile = str(layout_block.get("spawn_tile", "A"))
    floor_tile = str(layout_block.get("floor_tile", "."))
    spawn_cell, layout = extract_spawn_cell(layout, spawn_tile, floor_tile, raw.get("agent", {}))

    known_tiles = set(tile_styles)
    unknown_tiles = sorted({tile for row in layout for tile in row if tile not in known_tiles})
    if unknown_tiles:
        raise ValueError(f"Nieznane kafelki w mapie: {', '.join(unknown_tiles)}")

    validate_layout(layout)

    col_widths, row_heights = build_compacted_dimensions(layout, tile_styles, tile_size)
    col_lefts = build_offsets(col_widths)
    row_tops = build_offsets(row_heights)
    spawn_position = cell_center(spawn_cell, col_lefts, row_tops, col_widths, row_heights)

    solid_tiles = {
        tile
        for tile, style in tile_styles.items()
        if style.solid
    }
    solid_tiles.update(layout_block.get("solid_tiles", []))
    stairs_tiles = set(layout_block.get("stairs_tiles", ["S"]))
    exit_tiles = set(layout_block.get("exit_tiles", ["E", "T"]))

    agent = raw.get("agent", {})
    radius = float(agent.get("radius", max(5, tile_size * 0.34)))
    speed = float(agent.get("speed", tile_size * 5.7))
    color = pygame.Color(str(agent.get("color", "#ffd166")))
    crowd = raw.get("crowd", {})
    crowd_count = int(crowd.get("count", 70))
    crowd_seed = int(crowd.get("seed", 7))
    crowd_spawn_jitter = float(crowd.get("spawn_jitter", radius * 0.9))
    crowd_repath_interval = float(crowd.get("repath_interval", 0.35))
    crowd_personal_space = float(crowd.get("personal_space", radius * 0.85))
    crowd_repulsion_strength = float(crowd.get("repulsion_strength", speed * 6.0))
    crowd_wall_repulsion_strength = float(crowd.get("wall_repulsion_strength", speed * 4.5))
    crowd_max_speed_multiplier = float(crowd.get("max_speed_multiplier", 1.45))

    return StadiumConfig(
        title=title,
        fps=fps,
        ui_width=ui_width,
        tile_size=tile_size,
        layout=layout,
        tile_styles=tile_styles,
        solid_tiles=set(solid_tiles),
        stairs_tiles=stairs_tiles,
        exit_tiles=exit_tiles,
        spawn_position=spawn_position,
        agent_radius=radius,
        agent_speed=speed,
        agent_color=color,
        crowd_count=crowd_count,
        crowd_seed=crowd_seed,
        crowd_spawn_jitter=crowd_spawn_jitter,
        crowd_repath_interval=crowd_repath_interval,
        crowd_personal_space=crowd_personal_space,
        crowd_repulsion_strength=crowd_repulsion_strength,
        crowd_wall_repulsion_strength=crowd_wall_repulsion_strength,
        crowd_max_speed_multiplier=crowd_max_speed_multiplier,
        config_path=config_path,
        col_widths=col_widths,
        row_heights=row_heights,
        col_lefts=col_lefts,
        row_tops=row_tops,
    )


def parse_tile_styles(raw_tiles: dict[str, Any]) -> dict[str, TileStyle]:
    if not raw_tiles:
        raise ValueError("Config musi zawierac sekcje 'tiles'.")

    styles: dict[str, TileStyle] = {}
    for symbol, raw_style in raw_tiles.items():
        if len(symbol) != 1:
            raise ValueError(f"Symbol kafelka musi miec jeden znak: {symbol!r}")
        edges = tuple(raw_style.get("edges", []))
        bad_edges = sorted(set(edges) - {"P", "D"})
        if bad_edges:
            raise ValueError(f"Kafelek {symbol!r} ma nieznane sciany: {', '.join(bad_edges)}")
        color = pygame.Color(str(raw_style.get("color", "#ff00ff")))
        styles[symbol] = TileStyle(
            name=str(raw_style.get("name", symbol)),
            color=color,
            solid=bool(raw_style.get("solid", False)),
            edges=edges,
            visual_width_ratio=float(raw_style.get("visual_width_ratio", 1.0)),
            visual_height_ratio=float(raw_style.get("visual_height_ratio", 1.0)),
            visual_align_x=str(raw_style.get("visual_align_x", "center")),
            visual_align_y=str(raw_style.get("visual_align_y", "center")),
            collision_width_ratio=float(raw_style.get("collision_width_ratio", 1.0)),
            collision_height_ratio=float(raw_style.get("collision_height_ratio", 1.0)),
            collision_align_x=str(raw_style.get("collision_align_x", raw_style.get("visual_align_x", "center"))),
            collision_align_y=str(raw_style.get("collision_align_y", raw_style.get("visual_align_y", "center"))),
        )
    return styles


def load_layout(layout_block: dict[str, Any], raw: dict[str, Any], base_path: Path) -> list[str]:
    layout_type = str(layout_block.get("type", "text"))
    if layout_type == "image":
        image_path = base_path / str(layout_block.get("image_map", ""))
        palette = raw.get("image_palette", {})
        return load_layout_from_image(image_path, palette)

    layout = layout_block.get("map")
    if not isinstance(layout, list) or not all(isinstance(row, str) for row in layout):
        raise ValueError("layout.map musi byc lista napisow.")
    return layout


def load_layout_from_image(image_path: Path, palette: dict[str, str]) -> list[str]:
    if not image_path.exists():
        raise ValueError(f"Nie znaleziono pliku mapy obrazkowej: {image_path}")
    if not palette:
        raise ValueError("Mapa obrazkowa wymaga sekcji image_palette.")

    normalized_palette = {normalize_hex(color): str(tile) for color, tile in palette.items()}
    image = pygame.image.load(str(image_path))
    layout: list[str] = []
    for y in range(image.get_height()):
        row = []
        for x in range(image.get_width()):
            color = normalize_hex(image.get_at((x, y)))
            if color not in normalized_palette:
                raise ValueError(f"Kolor {color} z mapy obrazkowej nie istnieje w image_palette.")
            row.append(normalized_palette[color])
        layout.append("".join(row))
    return layout


def normalize_hex(color: Any) -> str:
    if isinstance(color, pygame.Color):
        return f"#{color.r:02X}{color.g:02X}{color.b:02X}"
    text = str(color).strip().upper()
    if not text.startswith("#"):
        text = "#" + text
    if len(text) != 7:
        raise ValueError(f"Niepoprawny kolor HEX: {color!r}")
    return text


def extract_spawn_cell(
    layout: list[str],
    spawn_tile: str,
    floor_tile: str,
    agent_config: dict[str, Any],
) -> tuple[tuple[int, int], list[str]]:
    spawn_cells: list[tuple[int, int]] = []
    cleaned: list[str] = []
    for y, row in enumerate(layout):
        if spawn_tile in row:
            for x, tile in enumerate(row):
                if tile == spawn_tile:
                    spawn_cells.append((x, y))
            cleaned.append(row.replace(spawn_tile, floor_tile))
        else:
            cleaned.append(row)

    if spawn_cells:
        return spawn_cells[0], cleaned

    start_tile = agent_config.get("start_tile")
    if isinstance(start_tile, list) and len(start_tile) == 2:
        spawn_x, spawn_y = int(start_tile[0]), int(start_tile[1])
        return (spawn_x, spawn_y), cleaned

    raise ValueError("Mapa musi zawierac kafelek startowy 'A' albo agent.start_tile.")


def validate_layout(layout: list[str]) -> None:
    if not layout:
        raise ValueError("Mapa nie moze byc pusta.")
    width = len(layout[0])
    if width == 0:
        raise ValueError("Mapa nie moze miec pustych wierszy.")
    for index, row in enumerate(layout):
        if len(row) != width:
            raise ValueError(f"Wiersz mapy {index} ma dlugosc {len(row)}, oczekiwano {width}.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pygame: model pojedynczej trybuny stadionu.")
    parser.add_argument(
        "--config",
        default="stadium_config.json",
        help="Sciezka do pliku konfiguracyjnego JSON.",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Wczytaj i sprawdz config bez otwierania okna.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pygame.init()

    try:
        config = load_config(Path(args.config))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Blad configu: {exc}", file=sys.stderr)
        pygame.quit()
        return 1

    if args.check_config:
        print(
            "Config OK: "
            f"{config.width}x{config.height} kafelkow, "
            f"tile_size={config.tile_size}, "
            f"solid={''.join(sorted(config.solid_tiles))}"
        )
        pygame.quit()
        return 0

    stadium = Stadium(config)
    crowd = CrowdSimulation(stadium)

    world_w, world_h = config.world_size
    screen = pygame.display.set_mode((world_w + config.ui_width, world_h))
    pygame.display.set_caption(config.title)

    clock = pygame.time.Clock()
    font = pygame.font.SysFont("segoeui", 22, bold=True)
    small_font = pygame.font.SysFont("segoeui", 16)
    running = True

    while running:
        dt = clock.tick(config.fps) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                crowd.paused = not crowd.paused

        crowd.update(dt)

        stadium.draw(screen)
        crowd.draw_density(screen)
        crowd.draw_agents(screen)
        draw_ui(screen, font, small_font, config, crowd)
        pygame.display.flip()

    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
