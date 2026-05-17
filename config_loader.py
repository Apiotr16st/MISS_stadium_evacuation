from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pygame

from layout_builder import compose_full_stadium_layout, validate_layout
from models import StadiumConfig, TileStyle
from utils import build_ends, build_offsets, cell_center


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
    window_max_width = int(window.get("max_width", 1400))
    window_max_height = int(window.get("max_height", 900))
    ui_width = int(window.get("ui_width", 310))

    tile_styles = parse_tile_styles(raw.get("tiles", {}))
    layout_block = raw.get("layout", {})
    layout = load_layout(layout_block, raw, config_path.parent)
    layout, stadium_segment_count, scale_crowd_by_segments = expand_layout_if_needed(layout, layout_block)

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
    col_rights = build_ends(col_lefts, col_widths)
    row_bottoms = build_ends(row_tops, row_heights)
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
    if scale_crowd_by_segments:
        crowd_count *= stadium_segment_count
    crowd_seed = int(crowd.get("seed", 7))
    crowd_spawn_jitter = float(crowd.get("spawn_jitter", radius * 0.9))
    crowd_repath_interval = float(crowd.get("repath_interval", 0.35))
    crowd_personal_space = float(crowd.get("personal_space", radius * 0.85))
    crowd_repulsion_strength = float(crowd.get("repulsion_strength", speed * 6.0))
    crowd_wall_repulsion_strength = float(crowd.get("wall_repulsion_strength", speed * 4.5))
    crowd_max_speed_multiplier = float(crowd.get("max_speed_multiplier", 1.45))
    crowd_collision_iterations = int(crowd.get("collision_iterations", 1))

    return StadiumConfig(
        title=title,
        fps=fps,
        window_max_width=window_max_width,
        window_max_height=window_max_height,
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
        crowd_collision_iterations=max(1, crowd_collision_iterations),
        config_path=config_path,
        col_widths=col_widths,
        row_heights=row_heights,
        col_lefts=col_lefts,
        row_tops=row_tops,
        col_rights=col_rights,
        row_bottoms=row_bottoms,
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
            collision=bool(raw_style.get("collision", raw_style.get("solid", False))),
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




def expand_layout_if_needed(layout: list[str], layout_block: dict[str, Any]) -> tuple[list[str], int, bool]:
    full_stadium = layout_block.get("full_stadium", False)
    if isinstance(full_stadium, dict):
        enabled = bool(full_stadium.get("enabled", True))
        field_tile = str(full_stadium.get("field_tile", "F"))
        corner_tile = str(full_stadium.get("corner_tile", "#"))
        horizontal_stands = int(full_stadium.get("horizontal_stands", 1))
        vertical_stands = int(full_stadium.get("vertical_stands", 1))
        scale_crowd = bool(full_stadium.get("scale_crowd_by_segments", False))
        field_width = optional_positive_int(full_stadium.get("field_width"))
        field_height = optional_positive_int(full_stadium.get("field_height"))
    else:
        enabled = bool(full_stadium)
        field_tile = str(layout_block.get("field_tile", "F"))
        corner_tile = str(layout_block.get("corner_tile", "#"))
        horizontal_stands = 1
        vertical_stands = 1
        scale_crowd = False
        field_width = optional_positive_int(layout_block.get("field_width"))
        field_height = optional_positive_int(layout_block.get("field_height"))

    if not enabled:
        return layout, 1, False

    expanded = compose_full_stadium_layout(
        layout,
        field_tile=field_tile,
        corner_tile=corner_tile,
        horizontal_stands=horizontal_stands,
        vertical_stands=vertical_stands,
        field_width=field_width,
        field_height=field_height,
    )
    segment_count = horizontal_stands * 2 + vertical_stands * 2
    return expanded, segment_count, scale_crowd




def optional_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("Wymiary pelnego stadionu musza byc dodatnie.")
    return parsed




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
