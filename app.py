from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import pygame

from config_loader import load_config
from crowd import CrowdSimulation, spawn_capacity
from experiments import ExperimentRecorder
from models import ScaledSurfaceCache, ScenarioChoice, ScenarioConfig, SimulationSetup, StadiumConfig
from scenarios import ScenarioRuntime, load_scenario_catalog
from stadium import Stadium
from ui import build_viewport, draw_ui, draw_world_layers_to_screen, initial_window_size, run_config_panel


SIMULATION_HZ = 30
MAX_SIMULATION_STEPS_PER_FRAME = 1


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
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Uruchom eksperyment bez GUI i bez renderowania.",
    )
    parser.add_argument(
        "--scenario",
        default="baseline",
        help="ID scenariusza dla trybu headless albo 'baseline'.",
    )
    parser.add_argument("--agents", type=int, help="Liczba agentow dla trybu headless.")
    parser.add_argument("--seed", type=int, help="Seed losowania dla trybu headless.")
    parser.add_argument(
        "--scenario-start",
        type=float,
        help="Nadpisz czas startu scenariusza w trybie headless [s].",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=300.0,
        help="Maksymalny czas symulowany przebiegu headless [s].",
    )
    parser.add_argument(
        "--sample-interval",
        type=float,
        default=1.0,
        help="Interwal zapisu probek CSV w trybie headless [s].",
    )
    parser.add_argument(
        "--results-dir",
        default="results",
        help="Katalog wynikow CSV w trybie headless.",
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

    if args.headless:
        return run_headless(config, args)

    screen = pygame.display.set_mode(initial_window_size(config), pygame.RESIZABLE)
    pygame.display.set_caption(config.title)

    clock = pygame.time.Clock()
    font = pygame.font.SysFont("segoeui", 22, bold=True)
    small_font = pygame.font.SysFont("segoeui", 16)

    scenario_choices, scenario_errors = load_scenario_catalog(Path("scenarios"), config)
    max_crowd_count = spawn_capacity(Stadium(config))
    setup = run_config_panel(
        screen,
        clock,
        font,
        small_font,
        config,
        scenario_choices,
        scenario_errors,
        max_crowd_count,
    )
    if setup is None:
        pygame.quit()
        return 0

    config = apply_setup(config, setup)
    stadium = Stadium(config)
    scenario = ScenarioRuntime(stadium, setup.scenario, setup.scenario_start_time)
    crowd = CrowdSimulation(stadium, scenario)
    recorder = ExperimentRecorder(config, setup, setup.scenario, scenario)
    static_world_surface = pygame.Surface(config.world_size)
    stadium.draw(static_world_surface)
    dynamic_world_surface = pygame.Surface(config.world_size, pygame.SRCALPHA)
    static_world_cache = ScaledSurfaceCache()
    running = True
    result_path: Path | None = None
    run_status: str | None = None
    simulation_step = 1.0 / SIMULATION_HZ
    simulation_accumulator = 0.0

    while running:
        frame_dt = min(
            clock.tick(config.fps) / 1000.0,
            simulation_step * MAX_SIMULATION_STEPS_PER_FRAME,
        )
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                if not recorder.finished:
                    result_path = recorder.finalize("cancelled", crowd)
                running = False
            elif event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode(event.size, pygame.RESIZABLE)
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                if not recorder.finished:
                    result_path = recorder.finalize("cancelled", crowd)
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                crowd.paused = not crowd.paused

        if not recorder.finished and not crowd.paused:
            simulation_accumulator = min(
                simulation_accumulator + frame_dt,
                simulation_step * MAX_SIMULATION_STEPS_PER_FRAME,
            )
            steps = 0
            while simulation_accumulator >= simulation_step and steps < MAX_SIMULATION_STEPS_PER_FRAME:
                crowd.update(simulation_step)
                recorder.update(simulation_step, crowd)
                simulation_accumulator -= simulation_step
                steps += 1
                if crowd.evacuated_count == len(crowd.agents):
                    result_path = recorder.finalize("completed", crowd)
                    run_status = "zakonczony"
                    break
                if crowd.elapsed >= setup.max_duration:
                    result_path = recorder.finalize("timed_out", crowd)
                    run_status = "limit czasu"
                    break
        elif crowd.paused:
            simulation_accumulator = 0.0

        viewport = build_viewport(screen.get_size(), config)
        screen.fill(pygame.Color("#151a1f"))
        dynamic_world_surface.fill((0, 0, 0, 0))
        crowd.draw_hazard(dynamic_world_surface)
        crowd.draw_density(dynamic_world_surface)
        crowd.draw_agents(dynamic_world_surface)
        draw_world_layers_to_screen(
            screen,
            static_world_surface,
            dynamic_world_surface,
            viewport,
            static_world_cache,
        )
        draw_ui(screen, font, small_font, viewport, config, crowd, result_path, run_status)
        pygame.display.flip()

    pygame.quit()
    return 0


def run_headless(config: StadiumConfig, args: argparse.Namespace) -> int:
    scenario_choices, scenario_errors = load_scenario_catalog(Path("scenarios"), config)
    if scenario_errors:
        print(f"Blad scenariusza: {scenario_errors[0]}", file=sys.stderr)
        pygame.quit()
        return 1

    scenario = select_scenario(args.scenario, scenario_choices)
    if scenario is False:
        known = ", ".join(["baseline"] + [choice.config.id for choice in scenario_choices if choice.config])
        print(f"Nieznany scenariusz: {args.scenario}. Dostepne: {known}", file=sys.stderr)
        pygame.quit()
        return 1

    crowd_count = config.crowd_count if args.agents is None else args.agents
    seed = config.crowd_seed if args.seed is None else args.seed
    capacity = spawn_capacity(Stadium(config))
    if crowd_count <= 0 or crowd_count > capacity:
        print(f"Liczba agentow musi nalezec do zakresu 1..{capacity}.", file=sys.stderr)
        pygame.quit()
        return 1
    if args.max_duration <= 0 or args.sample_interval <= 0:
        print("Czas przebiegu i interwal probek musza byc dodatnie.", file=sys.stderr)
        pygame.quit()
        return 1
    if args.scenario_start is not None and args.scenario_start < 0:
        print("Czas startu scenariusza musi byc nieujemny.", file=sys.stderr)
        pygame.quit()
        return 1

    setup = SimulationSetup(
        crowd_count=crowd_count,
        agent_radius=config.agent_radius,
        agent_speed=config.agent_speed,
        crowd_personal_space=config.crowd_personal_space,
        crowd_congestion_weight=config.crowd_congestion_weight,
        crowd_seed=seed,
        crowd_spawn_jitter=config.crowd_spawn_jitter,
        crowd_repulsion_strength=config.crowd_repulsion_strength,
        crowd_wall_repulsion_strength=config.crowd_wall_repulsion_strength,
        crowd_max_speed_multiplier=config.crowd_max_speed_multiplier,
        crowd_collision_iterations=config.crowd_collision_iterations,
        crowd_repath_interval=config.crowd_repath_interval,
        max_duration=args.max_duration,
        sample_interval=args.sample_interval,
        scenario_start_time=args.scenario_start,
        scenario=scenario,
    )
    config = apply_setup(config, setup)
    stadium = Stadium(config)
    runtime = ScenarioRuntime(stadium, scenario, setup.scenario_start_time)
    crowd = CrowdSimulation(stadium, runtime)
    recorder = ExperimentRecorder(config, setup, scenario, runtime, Path(args.results_dir))
    simulation_step = 1.0 / SIMULATION_HZ
    wall_start = time.perf_counter()
    status = "timed_out"

    while crowd.elapsed + 1e-9 < setup.max_duration and crowd.evacuated_count < len(crowd.agents):
        dt = min(simulation_step, setup.max_duration - crowd.elapsed)
        crowd.update(dt)
        recorder.update(dt, crowd)
    if crowd.evacuated_count == len(crowd.agents):
        status = "completed"
    result_path = recorder.finalize(status, crowd)
    wall_seconds = time.perf_counter() - wall_start
    print(
        f"Headless OK: scenario={runtime.scenario_id}, agents={len(crowd.agents)}, "
        f"status={status}, simulated={crowd.elapsed:.2f}s, wall={wall_seconds:.2f}s, "
        f"evacuated={crowd.evacuated_count}, result={result_path}"
    )
    pygame.quit()
    return 0


def select_scenario(
    requested: str,
    choices: list[ScenarioChoice],
) -> ScenarioConfig | None | bool:
    if requested.lower() in {"baseline", "none", "brak"}:
        return None
    for choice in choices:
        if choice.config is not None and requested in {choice.config.id, choice.config.source_path.stem}:
            return choice.config
    return False


def apply_setup(config: StadiumConfig, setup: SimulationSetup) -> StadiumConfig:
    return replace(
        config,
        crowd_count=setup.crowd_count,
        agent_radius=setup.agent_radius,
        agent_speed=setup.agent_speed,
        crowd_personal_space=setup.crowd_personal_space,
        crowd_congestion_weight=setup.crowd_congestion_weight,
        crowd_seed=setup.crowd_seed,
        crowd_spawn_jitter=setup.crowd_spawn_jitter,
        crowd_repulsion_strength=setup.crowd_repulsion_strength,
        crowd_wall_repulsion_strength=setup.crowd_wall_repulsion_strength,
        crowd_max_speed_multiplier=setup.crowd_max_speed_multiplier,
        crowd_collision_iterations=setup.crowd_collision_iterations,
        crowd_repath_interval=setup.crowd_repath_interval,
    )
