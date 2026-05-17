from __future__ import annotations

import bisect

import pygame

from models import StadiumConfig, Vec2


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




def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))




def clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))




def index_at_position(value: float, starts: list[int], ends: list[int]) -> int:
    if not starts:
        return -1
    if value < starts[0]:
        return -1
    return bisect.bisect_right(ends, value)




def build_offsets(sizes: list[int]) -> list[int]:
    offsets: list[int] = []
    current = 0
    for size in sizes:
        offsets.append(current)
        current += size
    return offsets




def build_ends(starts: list[int], sizes: list[int]) -> list[int]:
    return [start + size for start, size in zip(starts, sizes)]




def cell_center(
    cell: tuple[int, int],
    col_lefts: list[int],
    row_tops: list[int],
    col_widths: list[int],
    row_heights: list[int],
) -> Vec2:
    x, y = cell
    return Vec2(col_lefts[x] + col_widths[x] / 2, row_tops[y] + row_heights[y] / 2)
