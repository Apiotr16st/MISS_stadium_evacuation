from __future__ import annotations

import pygame

from crowd import CrowdSimulation
from models import ScaledSurfaceCache, StadiumConfig, Viewport
from utils import clamp_int


def draw_ui(
    surface: pygame.Surface,
    font: pygame.font.Font,
    small_font: pygame.font.Font,
    viewport: Viewport,
    config: StadiumConfig,
    crowd: CrowdSimulation,
) -> None:
    panel = viewport.ui_rect
    pygame.draw.rect(surface, pygame.Color("#101418"), panel)
    pygame.draw.line(surface, pygame.Color("#37424d"), panel.topleft, panel.bottomleft, 2)

    x = panel.left + 18
    y = 20
    y = draw_text(surface, font, "Model stadionu", x, y, pygame.Color("#f4f7f8"))
    y = draw_text(surface, small_font, "Space: pauza / wznowienie", x, y + 12, pygame.Color("#b8c1c9"))
    y = draw_text(surface, small_font, "Esc: zamknij symulacje", x, y + 5, pygame.Color("#b8c1c9"))
    y = draw_text(surface, small_font, f"Config: {config.config_path.name}", x, y + 5, pygame.Color("#b8c1c9"))
    y = draw_text(surface, small_font, f"Skala widoku: {viewport.scale:.2f}x", x, y + 5, pygame.Color("#b8c1c9"))

    y += 20
    y = draw_text(surface, font, "Status", x, y, pygame.Color("#f4f7f8"))
    y = draw_text(surface, small_font, f"Czas: {crowd.elapsed:5.1f} s", x, y + 8, pygame.Color("#b8c1c9"))
    y = draw_text(surface, small_font, f"Na stadionie: {len(crowd.active_agents)}", x, y + 5, pygame.Color("#b8c1c9"))
    y = draw_text(surface, small_font, f"Ewakuowani: {crowd.evacuated_count}/{len(crowd.agents)}", x, y + 5, pygame.Color("#b8c1c9"))
    y = draw_text(surface, small_font, f"Max gestosc/kafelek: {crowd.max_cell_count}", x, y + 5, pygame.Color("#b8c1c9"))
    if crowd.paused:
        y = draw_text(surface, font, "Pauza", x, y + 18, pygame.Color("#ffd166"))
    elif crowd.evacuated_count == len(crowd.agents):
        y = draw_text(surface, font, "Ewakuacja zakonczona", x, y + 18, pygame.Color("#9ef0b5"))




def build_viewport(screen_size: tuple[int, int], config: StadiumConfig) -> Viewport:
    screen_w, screen_h = screen_size
    ui_width = min(config.ui_width, max(220, screen_w // 3))
    world_area = pygame.Rect(0, 0, max(1, screen_w - ui_width), screen_h)
    ui_rect = pygame.Rect(world_area.right, 0, ui_width, screen_h)
    world_w, world_h = config.world_size
    scale = min(world_area.width / world_w, world_area.height / world_h)
    scale = max(0.05, scale)
    scaled_w = max(1, round(world_w * scale))
    scaled_h = max(1, round(world_h * scale))
    world_rect = pygame.Rect(0, 0, scaled_w, scaled_h)
    world_rect.center = world_area.center
    return Viewport(world_rect=world_rect, ui_rect=ui_rect, scale=scale)




def draw_world_to_screen(
    screen: pygame.Surface,
    world_surface: pygame.Surface,
    viewport: Viewport,
) -> None:
    if viewport.world_rect.size == world_surface.get_size():
        screen.blit(world_surface, viewport.world_rect.topleft)
        return

    scaled_world = pygame.transform.smoothscale(world_surface, viewport.world_rect.size)
    screen.blit(scaled_world, viewport.world_rect.topleft)




def draw_world_layers_to_screen(
    screen: pygame.Surface,
    static_world: pygame.Surface,
    dynamic_world: pygame.Surface,
    viewport: Viewport,
    static_cache: ScaledSurfaceCache,
) -> None:
    if viewport.world_rect.size == static_world.get_size():
        screen.blit(static_world, viewport.world_rect.topleft)
        screen.blit(dynamic_world, viewport.world_rect.topleft)
        return

    if static_cache.size != viewport.world_rect.size or static_cache.surface is None:
        static_cache.size = viewport.world_rect.size
        static_cache.surface = pygame.transform.scale(static_world, viewport.world_rect.size)
    screen.blit(static_cache.surface, viewport.world_rect.topleft)

    scaled_dynamic = pygame.transform.scale(dynamic_world, viewport.world_rect.size)
    screen.blit(scaled_dynamic, viewport.world_rect.topleft)




def run_config_panel(
    screen: pygame.Surface,
    clock: pygame.time.Clock,
    font: pygame.font.Font,
    small_font: pygame.font.Font,
    config: StadiumConfig,
) -> int | None:
    count_text = str(config.crowd_count)
    input_active = True
    width, height = screen.get_size()

    panel = pygame.Rect(0, 0, min(430, width - 60), 250)
    panel.center = (width // 2, height // 2)
    input_rect = pygame.Rect(panel.left + 34, panel.top + 112, panel.width - 68, 42)
    minus_rect = pygame.Rect(panel.left + 34, panel.top + 154, 52, 38)
    plus_rect = pygame.Rect(panel.left + 96, panel.top + 154, 52, 38)
    start_rect = pygame.Rect(panel.right - 154, panel.top + 154, 120, 38)

    while True:
        clock.tick(config.fps)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return None
                if event.key == pygame.K_RETURN:
                    return clamp_agent_count(count_text)
                if event.key == pygame.K_BACKSPACE and input_active:
                    count_text = count_text[:-1]
                elif input_active and event.unicode.isdigit():
                    count_text = (count_text + event.unicode).lstrip("0")[:4] or "0"

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                input_active = input_rect.collidepoint(event.pos)
                if minus_rect.collidepoint(event.pos):
                    count_text = str(max(1, clamp_agent_count(count_text) - 10))
                elif plus_rect.collidepoint(event.pos):
                    count_text = str(min(9999, clamp_agent_count(count_text) + 10))
                elif start_rect.collidepoint(event.pos):
                    return clamp_agent_count(count_text)

        screen.fill(pygame.Color("#151a1f"))
        pygame.draw.rect(screen, pygame.Color("#101418"), panel, border_radius=6)
        pygame.draw.rect(screen, pygame.Color("#37424d"), panel, 1, border_radius=6)

        y = draw_text(screen, font, "Konfiguracja symulacji", panel.left + 34, panel.top + 28, pygame.Color("#f4f7f8"))
        draw_text(screen, small_font, "Liczba agentow", panel.left + 34, y + 18, pygame.Color("#b8c1c9"))

        pygame.draw.rect(screen, pygame.Color("#20272e"), input_rect, border_radius=4)
        pygame.draw.rect(
            screen,
            pygame.Color("#ffd166" if input_active else "#62707b"),
            input_rect,
            1,
            border_radius=4,
        )
        draw_text(screen, font, count_text or "0", input_rect.left + 14, input_rect.top + 8, pygame.Color("#f4f7f8"))

        draw_button(screen, small_font, minus_rect, "-10")
        draw_button(screen, small_font, plus_rect, "+10")
        draw_button(screen, small_font, start_rect, "Start")

        pygame.display.flip()




def clamp_agent_count(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = 1
    return clamp_int(value, 1, 9999)




def draw_button(surface: pygame.Surface, font: pygame.font.Font, rect: pygame.Rect, label: str) -> None:
    pygame.draw.rect(surface, pygame.Color("#26313a"), rect, border_radius=4)
    pygame.draw.rect(surface, pygame.Color("#62707b"), rect, 1, border_radius=4)
    rendered = font.render(label, True, pygame.Color("#f4f7f8"))
    surface.blit(rendered, rendered.get_rect(center=rect.center))




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




def initial_window_size(config: StadiumConfig) -> tuple[int, int]:
    world_w, world_h = config.world_size
    desired_w = world_w + config.ui_width
    desired_h = world_h

    display_info = pygame.display.Info()
    desktop_w = display_info.current_w or desired_w
    desktop_h = display_info.current_h or desired_h
    max_w = min(config.window_max_width, max(640, desktop_w - 80))
    max_h = min(config.window_max_height, max(480, desktop_h - 120))
    return max(640, min(desired_w, max_w)), max(480, min(desired_h, max_h))
