from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pygame

from crowd import CrowdSimulation
from models import ScenarioChoice, ScenarioConfig, ScaledSurfaceCache, SimulationSetup, StadiumConfig, Viewport


def draw_ui(
    surface: pygame.Surface,
    font: pygame.font.Font,
    small_font: pygame.font.Font,
    viewport: Viewport,
    config: StadiumConfig,
    crowd: CrowdSimulation,
    result_path: Path | None = None,
    run_status: str | None = None,
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
    if run_status is not None:
        y = draw_text(surface, font, f"Wynik: {run_status}", x, y + 18, pygame.Color("#9ef0b5"))
    if result_path is not None:
        y = draw_text(surface, small_font, "Plik wyniku:", x, y + 8, pygame.Color("#b8c1c9"))
        result_text = str(result_path)
        for start in range(0, len(result_text), 30):
            y = draw_text(surface, small_font, result_text[start:start + 30], x, y + 3, pygame.Color("#b8c1c9"))




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
    scenario_choices: list[ScenarioChoice],
    scenario_errors: list[str],
) -> SimulationSetup | None:
    basic_specs = [
        InputSpec("Liczba agentow", "crowd_count", str(config.crowd_count), True),
        InputSpec("Promien agenta", "agent_radius", str(config.agent_radius)),
        InputSpec("Predkosc bazowa", "agent_speed", str(config.agent_speed)),
        InputSpec("Dystans osobisty", "crowd_personal_space", str(config.crowd_personal_space)),
        InputSpec("Waga zatloczenia", "crowd_congestion_weight", str(config.crowd_congestion_weight), False, True),
        InputSpec("Limit czasu [s]", "max_duration", "300"),
    ]
    advanced_specs = [
        InputSpec("Seed", "crowd_seed", str(config.crowd_seed), True, True),
        InputSpec("Spawn jitter", "crowd_spawn_jitter", str(config.crowd_spawn_jitter), False, True),
        InputSpec("Odpychanie agentow", "crowd_repulsion_strength", str(config.crowd_repulsion_strength), False, True),
        InputSpec("Odpychanie scian", "crowd_wall_repulsion_strength", str(config.crowd_wall_repulsion_strength), False, True),
        InputSpec("Mnoznik max predkosci", "crowd_max_speed_multiplier", str(config.crowd_max_speed_multiplier)),
        InputSpec("Iteracje kolizji", "crowd_collision_iterations", str(config.crowd_collision_iterations), True),
        InputSpec("Interwal trasy [s]", "crowd_repath_interval", str(config.crowd_repath_interval)),
        InputSpec("Interwal zapisu [s]", "sample_interval", "1.0"),
    ]
    specs = basic_specs + advanced_specs
    values = {spec.key: spec.default for spec in specs}
    active_key: str | None = basic_specs[0].key
    selected_scenario = 0
    advanced = False
    error_message = ""

    while True:
        clock.tick(config.fps)
        width, height = screen.get_size()
        panel = pygame.Rect(0, 0, min(900, width - 40), min(640, height - 30))
        panel.center = (width // 2, height // 2)
        left = panel.left + 30
        right = panel.left + panel.width // 2 + 12
        field_width = panel.width // 2 - 52
        basic_rects = build_input_rects(left, panel.top + 98, field_width, basic_specs)
        advanced_rects = build_input_rects(right, panel.top + 98, field_width, advanced_specs)
        scenario_rect = pygame.Rect(left, panel.top + 98 + len(basic_specs) * 52 + 14, field_width, 38)
        prev_rect = pygame.Rect(scenario_rect.left, scenario_rect.top, 36, 38)
        next_rect = pygame.Rect(scenario_rect.right - 36, scenario_rect.top, 36, 38)
        advanced_rect = pygame.Rect(left, panel.bottom - 57, 174, 34)
        start_rect = pygame.Rect(panel.right - 154, panel.bottom - 60, 124, 38)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return None
                if event.key == pygame.K_RETURN:
                    setup, error_message = parse_setup(values, scenario_choices[selected_scenario].config)
                    if setup is not None:
                        return setup
                if active_key is not None and event.key == pygame.K_BACKSPACE:
                    values[active_key] = values[active_key][:-1]
                elif active_key is not None and event.unicode in "0123456789.-":
                    values[active_key] = (values[active_key] + event.unicode)[:12]

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                active_key = None
                for key, rect in basic_rects.items():
                    if rect.collidepoint(event.pos):
                        active_key = key
                if advanced:
                    for key, rect in advanced_rects.items():
                        if rect.collidepoint(event.pos):
                            active_key = key
                if prev_rect.collidepoint(event.pos):
                    selected_scenario = (selected_scenario - 1) % len(scenario_choices)
                elif next_rect.collidepoint(event.pos):
                    selected_scenario = (selected_scenario + 1) % len(scenario_choices)
                elif advanced_rect.collidepoint(event.pos):
                    advanced = not advanced
                elif start_rect.collidepoint(event.pos):
                    setup, error_message = parse_setup(values, scenario_choices[selected_scenario].config)
                    if setup is not None:
                        return setup

        screen.fill(pygame.Color("#151a1f"))
        pygame.draw.rect(screen, pygame.Color("#101418"), panel, border_radius=6)
        pygame.draw.rect(screen, pygame.Color("#37424d"), panel, 1, border_radius=6)

        draw_text(screen, font, "Konfiguracja eksperymentu", panel.left + 30, panel.top + 22, pygame.Color("#f4f7f8"))
        draw_text(screen, small_font, "Parametry podstawowe", left, panel.top + 72, pygame.Color("#b8c1c9"))
        draw_inputs(screen, small_font, basic_specs, basic_rects, values, active_key)
        draw_text(screen, small_font, "Scenariusz", scenario_rect.left, scenario_rect.top - 18, pygame.Color("#b8c1c9"))
        pygame.draw.rect(screen, pygame.Color("#20272e"), scenario_rect, border_radius=4)
        draw_button(screen, small_font, prev_rect, "<")
        draw_button(screen, small_font, next_rect, ">")
        scenario_label = scenario_choices[selected_scenario].label
        rendered = small_font.render(scenario_label, True, pygame.Color("#f4f7f8"))
        screen.blit(rendered, rendered.get_rect(center=scenario_rect.center))

        if advanced:
            draw_text(screen, small_font, "Parametry zaawansowane", right, panel.top + 72, pygame.Color("#b8c1c9"))
            draw_inputs(screen, small_font, advanced_specs, advanced_rects, values, active_key)
        draw_button(screen, small_font, advanced_rect, "Ukryj zaawansowane" if advanced else "Zaawansowane")
        draw_button(screen, small_font, start_rect, "Start")
        status = error_message or (scenario_errors[0] if scenario_errors else "")
        if status:
            draw_text(screen, small_font, status[:88], left, panel.bottom - 92, pygame.Color("#f28b82"))

        pygame.display.flip()




@dataclass(frozen=True)
class InputSpec:
    label: str
    key: str
    default: str
    integer: bool = False
    allow_zero: bool = False


def build_input_rects(left: int, top: int, width: int, specs: list[InputSpec]) -> dict[str, pygame.Rect]:
    return {
        spec.key: pygame.Rect(left, top + index * 52 + 18, width, 30)
        for index, spec in enumerate(specs)
    }


def draw_inputs(
    surface: pygame.Surface,
    font: pygame.font.Font,
    specs: list[InputSpec],
    rects: dict[str, pygame.Rect],
    values: dict[str, str],
    active_key: str | None,
) -> None:
    for spec in specs:
        rect = rects[spec.key]
        draw_text(surface, font, spec.label, rect.left, rect.top - 17, pygame.Color("#b8c1c9"))
        pygame.draw.rect(surface, pygame.Color("#20272e"), rect, border_radius=4)
        pygame.draw.rect(
            surface,
            pygame.Color("#ffd166" if active_key == spec.key else "#62707b"),
            rect,
            1,
            border_radius=4,
        )
        draw_text(surface, font, values[spec.key], rect.left + 10, rect.top + 6, pygame.Color("#f4f7f8"))


def parse_setup(
    values: dict[str, str],
    scenario: ScenarioConfig | None,
) -> tuple[SimulationSetup | None, str]:
    try:
        parsed: dict[str, int | float] = {}
        integer_keys = {"crowd_count", "crowd_seed", "crowd_collision_iterations"}
        for key, text in values.items():
            parsed[key] = int(text) if key in integer_keys else float(text)
    except ValueError:
        return None, "Wszystkie parametry musza byc poprawnymi liczbami."
    positive_keys = {
        "crowd_count",
        "agent_radius",
        "agent_speed",
        "crowd_personal_space",
        "crowd_max_speed_multiplier",
        "crowd_collision_iterations",
        "crowd_repath_interval",
        "max_duration",
        "sample_interval",
    }
    if any(float(parsed[key]) <= 0 for key in positive_keys):
        return None, "Parametry predkosci, czasu, liczby i rozmiaru musza byc dodatnie."
    non_negative_keys = {
        "crowd_congestion_weight",
        "crowd_spawn_jitter",
        "crowd_repulsion_strength",
        "crowd_wall_repulsion_strength",
    }
    if any(float(parsed[key]) < 0 for key in non_negative_keys):
        return None, "Parametry sil i zatloczenia nie moga byc ujemne."
    return (
        SimulationSetup(
            crowd_count=int(parsed["crowd_count"]),
            agent_radius=float(parsed["agent_radius"]),
            agent_speed=float(parsed["agent_speed"]),
            crowd_personal_space=float(parsed["crowd_personal_space"]),
            crowd_congestion_weight=float(parsed["crowd_congestion_weight"]),
            crowd_seed=int(parsed["crowd_seed"]),
            crowd_spawn_jitter=float(parsed["crowd_spawn_jitter"]),
            crowd_repulsion_strength=float(parsed["crowd_repulsion_strength"]),
            crowd_wall_repulsion_strength=float(parsed["crowd_wall_repulsion_strength"]),
            crowd_max_speed_multiplier=float(parsed["crowd_max_speed_multiplier"]),
            crowd_collision_iterations=int(parsed["crowd_collision_iterations"]),
            crowd_repath_interval=float(parsed["crowd_repath_interval"]),
            max_duration=float(parsed["max_duration"]),
            sample_interval=float(parsed["sample_interval"]),
            scenario=scenario,
        ),
        "",
    )




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
