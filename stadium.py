from __future__ import annotations

import heapq
import math

import pygame

from drawing import aligned_size_rect, draw_field_markings, draw_tile, edge_rect
from models import StadiumConfig, Vec2
from utils import cell_center, circle_intersects_rect, clamp_int, index_at_position, normalized_or_zero


class Stadium:
    def __init__(self, config: StadiumConfig):
        self.config = config
        self.tile_size = config.tile_size
        self.minimum_cell_extent = max(1, min(config.col_widths + config.row_heights))
        self.neighborhood_cell_size = max(1, config.tile_size)
        self.distance_to_exit, self.next_cell_to_exit = build_exit_route_maps(config)
        self.exit_rects = self._build_exit_rects()
        self.exit_centers = [
            Vec2(rect.centerx, rect.centery)
            for rect in self.exit_rects
        ]
        self.solid_rects: list[tuple[str, pygame.Rect]] = []
        self.collision_rects_by_cell: list[list[list[pygame.Rect]]] = [
            [[] for _ in range(config.width)]
            for _ in range(config.height)
        ]
        self.exit_rects_by_cell: list[list[list[pygame.Rect]]] = [
            [[] for _ in range(config.width)]
            for _ in range(config.height)
        ]
        self._solid_neighborhood_cache: dict[tuple[int, int, int], list[pygame.Rect]] = {}
        self._exit_neighborhood_cache: dict[tuple[int, int, int], list[pygame.Rect]] = {}
        for y, row in enumerate(config.layout):
            for x, tile in enumerate(row):
                if tile in config.solid_tiles and config.tile_styles[tile].collision:
                    rects = self.tile_collision_rects(x, y, tile)
                    self.collision_rects_by_cell[y][x] = rects
                    for rect in rects:
                        self.solid_rects.append((tile, rect))
                if tile in config.exit_tiles:
                    self.exit_rects_by_cell[y][x] = [self.tile_rect(x, y)]
        self.field_rect = self._build_tile_bounds("F")

    def tile_at_pixel(self, position: Vec2) -> str:
        cell = self.cell_at_pixel(position)
        x, y = cell
        if x < 0 or y < 0 or y >= self.config.height or x >= self.config.width:
            return "#"
        return self.config.layout[y][x]

    def cell_at_pixel(self, position: Vec2) -> tuple[int, int]:
        return (
            index_at_position(position.x, self.config.col_lefts, self.config.col_rights),
            index_at_position(position.y, self.config.row_tops, self.config.row_bottoms),
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
        for rect in self.nearby_exit_rects(position, radius):
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

    def _build_tile_bounds(self, target_tile: str) -> pygame.Rect | None:
        bounds: pygame.Rect | None = None
        for y, row in enumerate(self.config.layout):
            for x, tile in enumerate(row):
                if tile != target_tile:
                    continue
                rect = self.tile_rect(x, y)
                bounds = rect.copy() if bounds is None else bounds.union(rect)
        return bounds

    def nearby_solid_rects(self, position: Vec2, radius: float) -> list[pygame.Rect]:
        x, y = self.cell_at_pixel(position)
        key = (x, y, self._cell_margin(radius))
        cached = self._solid_neighborhood_cache.get(key)
        if cached is not None:
            return cached

        rects: list[pygame.Rect] = []
        min_x, max_x, min_y, max_y = self._cell_range_from_key(key)
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                rects.extend(self.collision_rects_by_cell[y][x])
        self._solid_neighborhood_cache[key] = rects
        return rects

    def nearby_exit_rects(self, position: Vec2, radius: float) -> list[pygame.Rect]:
        x, y = self.cell_at_pixel(position)
        key = (x, y, self._cell_margin(radius))
        cached = self._exit_neighborhood_cache.get(key)
        if cached is not None:
            return cached

        rects: list[pygame.Rect] = []
        min_x, max_x, min_y, max_y = self._cell_range_from_key(key)
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                rects.extend(self.exit_rects_by_cell[y][x])
        self._exit_neighborhood_cache[key] = rects
        return rects

    def _cell_margin(self, radius: float) -> int:
        return max(1, math.ceil(radius / self.neighborhood_cell_size))

    def _cell_range_from_key(self, key: tuple[int, int, int]) -> tuple[int, int, int, int]:
        x, y, margin = key
        x = clamp_int(x, 0, self.config.width - 1)
        y = clamp_int(y, 0, self.config.height - 1)
        return (
            max(0, x - margin),
            min(self.config.width - 1, x + margin),
            max(0, y - margin),
            min(self.config.height - 1, y + margin),
        )

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
        if self.field_rect is not None:
            draw_field_markings(surface, self.field_rect)




def build_exit_route_maps(
    config: StadiumConfig,
    active_exit_cells: set[tuple[int, int]] | None = None,
    additional_costs: dict[tuple[int, int], float] | None = None,
) -> tuple[list[list[float]], list[list[tuple[int, int] | None]]]:
    distances = [[math.inf for _ in range(config.width)] for _ in range(config.height)]
    next_cells: list[list[tuple[int, int] | None]] = [[None for _ in range(config.width)] for _ in range(config.height)]
    queue: list[tuple[float, int, int]] = []
    additional_costs = additional_costs or {}

    for y, row in enumerate(config.layout):
        for x, tile in enumerate(row):
            if tile in config.exit_tiles and (active_exit_cells is None or (x, y) in active_exit_cells):
                distances[y][x] = 0
                heapq.heappush(queue, (0, x, y))

    while queue:
        current_cost, x, y = heapq.heappop(queue)
        if current_cost > distances[y][x]:
            continue
        for nx, ny in walkable_neighbors(x, y, config):
            step_cost = movement_cost(config.layout[ny][nx], config) + additional_costs.get((nx, ny), 0.0)
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
