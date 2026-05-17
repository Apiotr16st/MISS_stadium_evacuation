from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import pygame

from config_loader import load_config
from crowd import CrowdSimulation
from models import ScaledSurfaceCache
from stadium import Stadium
from ui import build_viewport, draw_ui, draw_world_layers_to_screen, initial_window_size, run_config_panel


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pygame: model ewakuacji stadionu.")
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

    screen = pygame.display.set_mode(initial_window_size(config), pygame.RESIZABLE)
    pygame.display.set_caption(config.title)

    clock = pygame.time.Clock()
    font = pygame.font.SysFont("segoeui", 22, bold=True)
    small_font = pygame.font.SysFont("segoeui", 16)

    selected_count = run_config_panel(screen, clock, font, small_font, config)
    if selected_count is None:
        pygame.quit()
        return 0

    config = replace(config, crowd_count=selected_count)
    stadium = Stadium(config)
    crowd = CrowdSimulation(stadium)
    static_world_surface = pygame.Surface(config.world_size)
    stadium.draw(static_world_surface)
    dynamic_world_surface = pygame.Surface(config.world_size, pygame.SRCALPHA)
    static_world_cache = ScaledSurfaceCache()
    running = True

    while running:
        dt = clock.tick(config.fps) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode(event.size, pygame.RESIZABLE)
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                crowd.paused = not crowd.paused

        crowd.update(dt)

        viewport = build_viewport(screen.get_size(), config)
        screen.fill(pygame.Color("#151a1f"))
        dynamic_world_surface.fill((0, 0, 0, 0))
        crowd.draw_density(dynamic_world_surface)
        crowd.draw_agents(dynamic_world_surface)
        draw_world_layers_to_screen(
            screen,
            static_world_surface,
            dynamic_world_surface,
            viewport,
            static_world_cache,
        )
        draw_ui(screen, font, small_font, viewport, config, crowd)
        pygame.display.flip()

    pygame.quit()
    return 0
