from __future__ import annotations

from typing import Any

import pygame

from utils import clamp_int


def compose_full_stadium_layout(
    stand_layout: list[str],
    field_tile: str = "F",
    corner_tile: str = "#",
    horizontal_stands: int = 1,
    vertical_stands: int = 1,
    field_width: int | None = None,
    field_height: int | None = None,
) -> list[str]:
    validate_layout(stand_layout)

    north = stack_layout_horizontal(stand_layout, horizontal_stands)
    south = mirror_layout_vertical(north)
    west = stack_layout_vertical(rotate_layout_counterclockwise(stand_layout), vertical_stands)
    east = stack_layout_vertical(rotate_layout_clockwise(stand_layout), vertical_stands)

    side_width = len(west[0])
    middle_width = max(field_width or len(north[0]), len(north[0]), len(south[0]))
    middle_height = max(field_height or len(west), len(west), len(east))

    north = center_layout(north, middle_width, len(north), corner_tile)
    south = center_layout(south, middle_width, len(south), corner_tile)
    west = center_layout(west, side_width, middle_height, corner_tile)
    east = center_layout(east, side_width, middle_height, corner_tile)

    rows: list[str] = []
    for row in north:
        rows.append(corner_tile * side_width + row + corner_tile * side_width)
    for index in range(middle_height):
        rows.append(west[index] + field_tile * middle_width + east[index])
    for row in south:
        rows.append(corner_tile * side_width + row + corner_tile * side_width)
    return rows




def stack_layout_horizontal(layout: list[str], count: int) -> list[str]:
    validate_layout(layout)
    if count <= 0:
        raise ValueError("Liczba poziomych trybun musi byc dodatnia.")
    return [row * count for row in layout]




def stack_layout_vertical(layout: list[str], count: int) -> list[str]:
    validate_layout(layout)
    if count <= 0:
        raise ValueError("Liczba pionowych trybun musi byc dodatnia.")
    return layout * count




def center_layout(layout: list[str], width: int, height: int, fill_tile: str) -> list[str]:
    validate_layout(layout)
    if width < len(layout[0]) or height < len(layout):
        raise ValueError("Nie mozna wycentrowac mapy w mniejszym obszarze.")

    top_padding = (height - len(layout)) // 2
    bottom_padding = height - len(layout) - top_padding
    centered = [fill_tile * width for _ in range(top_padding)]
    for row in layout:
        left_padding = (width - len(row)) // 2
        right_padding = width - len(row) - left_padding
        centered.append(fill_tile * left_padding + row + fill_tile * right_padding)
    centered.extend(fill_tile * width for _ in range(bottom_padding))
    return centered




def mirror_layout_vertical(layout: list[str]) -> list[str]:
    return ["".join(transform_edge_tile(tile, "mirror_vertical") for tile in row) for row in reversed(layout)]




def rotate_layout_clockwise(layout: list[str]) -> list[str]:
    validate_layout(layout)
    height = len(layout)
    width = len(layout[0])
    return [
        "".join(transform_edge_tile(layout[y][x], "clockwise") for y in range(height - 1, -1, -1))
        for x in range(width)
    ]




def rotate_layout_counterclockwise(layout: list[str]) -> list[str]:
    validate_layout(layout)
    height = len(layout)
    width = len(layout[0])
    return [
        "".join(transform_edge_tile(layout[y][x], "counterclockwise") for y in range(height))
        for x in range(width - 1, -1, -1)
    ]




def transform_edge_tile(tile: str, transform: str) -> str:
    transforms = {
        "mirror_vertical": {"D": "U", "U": "D", "P": "P", "L": "L"},
        "clockwise": {"U": "P", "P": "D", "D": "L", "L": "U"},
        "counterclockwise": {"U": "L", "L": "D", "D": "P", "P": "U"},
    }
    return transforms[transform].get(tile, tile)




def validate_layout(layout: list[str]) -> None:
    if not layout:
        raise ValueError("Mapa nie moze byc pusta.")
    width = len(layout[0])
    if width == 0:
        raise ValueError("Mapa nie moze miec pustych wierszy.")
    for index, row in enumerate(layout):
        if len(row) != width:
            raise ValueError(f"Wiersz mapy {index} ma dlugosc {len(row)}, oczekiwano {width}.")
