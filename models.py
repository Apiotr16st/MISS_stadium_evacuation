from __future__ import annotations

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
    collision: bool
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
class SectorExit:
    id: str
    sector_id: str
    cells: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class StadiumMetadata:
    cell_sectors: dict[tuple[int, int], str]
    sector_cells: dict[str, tuple[tuple[int, int], ...]]
    sector_bounds: dict[str, pygame.Rect]
    sector_exits: dict[str, tuple[SectorExit, ...]]


@dataclass(frozen=True)
class ScenarioConfig:
    id: str
    name: str
    type: str
    parameters: dict[str, Any]
    source_path: Path


@dataclass(frozen=True)
class ScenarioChoice:
    label: str
    config: ScenarioConfig | None


@dataclass(frozen=True)
class SimulationSetup:
    crowd_count: int
    agent_radius: float
    agent_speed: float
    crowd_personal_space: float
    crowd_congestion_weight: float
    crowd_seed: int
    crowd_spawn_jitter: float
    crowd_repulsion_strength: float
    crowd_wall_repulsion_strength: float
    crowd_max_speed_multiplier: float
    crowd_collision_iterations: int
    crowd_repath_interval: float
    max_duration: float
    sample_interval: float
    scenario: ScenarioConfig | None


@dataclass(frozen=True)
class StadiumConfig:
    title: str
    fps: int
    window_max_width: int
    window_max_height: int
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
    crowd_collision_iterations: int
    crowd_congestion_weight: float
    config_path: Path
    metadata: StadiumMetadata
    col_widths: list[int]
    row_heights: list[int]
    col_lefts: list[int]
    row_tops: list[int]
    col_rights: list[int]
    row_bottoms: list[int]

    @property
    def width(self) -> int:
        return len(self.layout[0])

    @property
    def height(self) -> int:
        return len(self.layout)

    @property
    def world_size(self) -> tuple[int, int]:
        return sum(self.col_widths), sum(self.row_heights)


@dataclass(frozen=True)
class Viewport:
    world_rect: pygame.Rect
    ui_rect: pygame.Rect
    scale: float


@dataclass
class ScaledSurfaceCache:
    size: tuple[int, int] | None = None
    surface: pygame.Surface | None = None
