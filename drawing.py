from __future__ import annotations

import pygame

from models import TileStyle
from utils import clamp


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

    if tile == "F":
        pygame.draw.rect(surface, style.color, rect)
        return

    pygame.draw.rect(surface, pygame.Color("#252c33"), rect, 1)




def draw_field_markings(surface: pygame.Surface, rect: pygame.Rect) -> None:
    pitch = rect.inflate(-max(12, rect.width // 70), -max(12, rect.height // 70))
    if pitch.width <= 0 or pitch.height <= 0:
        return

    stripe_width = max(24, pitch.width // 12)
    stripe = pygame.Surface((stripe_width, pitch.height), pygame.SRCALPHA)
    stripe.fill((255, 255, 255, 13))
    for index, x in enumerate(range(pitch.left, pitch.right, stripe_width)):
        if index % 2 == 0:
            surface.blit(stripe, (x, pitch.top))

    line_color = pygame.Color("#e7f1df")
    line_width = max(2, min(pitch.width, pitch.height) // 170)
    pygame.draw.rect(surface, line_color, pitch, line_width)
    pygame.draw.line(surface, line_color, (pitch.centerx, pitch.top), (pitch.centerx, pitch.bottom), line_width)

    center_radius = max(8, min(pitch.width, pitch.height) // 9)
    pygame.draw.circle(surface, line_color, pitch.center, center_radius, line_width)
    pygame.draw.circle(surface, line_color, pitch.center, max(2, line_width + 1))

    penalty_w = max(20, pitch.width // 6)
    penalty_h = max(30, pitch.height // 2)
    goal_w = max(10, pitch.width // 17)
    goal_h = max(18, pitch.height // 4)
    left_penalty = pygame.Rect(pitch.left, pitch.centery - penalty_h // 2, penalty_w, penalty_h)
    right_penalty = pygame.Rect(pitch.right - penalty_w, pitch.centery - penalty_h // 2, penalty_w, penalty_h)
    left_goal = pygame.Rect(pitch.left, pitch.centery - goal_h // 2, goal_w, goal_h)
    right_goal = pygame.Rect(pitch.right - goal_w, pitch.centery - goal_h // 2, goal_w, goal_h)
    pygame.draw.rect(surface, line_color, left_penalty, line_width)
    pygame.draw.rect(surface, line_color, right_penalty, line_width)
    pygame.draw.rect(surface, line_color, left_goal, line_width)
    pygame.draw.rect(surface, line_color, right_goal, line_width)

    spot_radius = max(2, line_width + 1)
    spot_offset = max(penalty_w // 2, round(pitch.width * 0.105))
    left_spot = (pitch.left + spot_offset, pitch.centery)
    right_spot = (pitch.right - spot_offset, pitch.centery)
    pygame.draw.circle(surface, line_color, left_spot, spot_radius)
    pygame.draw.circle(surface, line_color, right_spot, spot_radius)

    arc_radius = max(12, round(pitch.width * 0.087))
    previous_clip = surface.get_clip()
    surface.set_clip(previous_clip.clip(pygame.Rect(left_penalty.right, pitch.top, pitch.width, pitch.height)))
    pygame.draw.circle(surface, line_color, left_spot, arc_radius, line_width)
    surface.set_clip(previous_clip.clip(pygame.Rect(pitch.left, pitch.top, right_penalty.left - pitch.left, pitch.height)))
    pygame.draw.circle(surface, line_color, right_spot, arc_radius, line_width)
    surface.set_clip(previous_clip)




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
