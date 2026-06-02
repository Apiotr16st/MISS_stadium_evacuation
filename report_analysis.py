from __future__ import annotations

import csv
import os
import statistics
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame


SCENARIO_ORDER = ["baseline", "fire_north_sector", "bombing_east_sector", "panic_west_sector"]
SCENARIO_LABELS = {
    "baseline": "Baseline",
    "fire_north_sector": "Fire",
    "bombing_east_sector": "Bombing",
    "panic_west_sector": "Panic",
}
SCENARIO_COLORS = {
    "baseline": pygame.Color("#2070b4"),
    "fire_north_sector": pygame.Color("#df7627"),
    "bombing_east_sector": pygame.Color("#b93232"),
    "panic_west_sector": pygame.Color("#8046a8"),
}
REPORT_SEEDS = {101, 202, 303}
OUTPUT_DIRECTORY = Path("report_figures")


def load_run(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    if not rows:
        raise ValueError(f"Empty result file: {path}")
    final = rows[-1]
    return {
        "path": path,
        "rows": rows,
        "scenario": final["scenario_id"],
        "seed": int(final["seed"]),
        "agents": int(final["crowd_count"]),
        "status": final["status"],
        "time": float(final["final_elapsed_time"]),
        "evacuated": int(final["final_evacuated_agents"]),
        "fraction": float(final["final_evacuated_fraction"]),
        "mean": optional_float(final["evacuation_time_mean"]),
        "p95": optional_float(final["evacuation_time_p95"]),
        "density": int(final["final_maximum_density"]),
        "panic": int(final["final_panicked_agents_total"]),
        "exposure": float(final["final_hazard_exposure_agent_seconds"]),
    }


def optional_float(value: str) -> float | None:
    return float(value) if value else None


def latest_runs(directory: Path) -> dict[tuple[str, int, int], dict[str, object]]:
    selected: dict[tuple[str, int, int], dict[str, object]] = {}
    for path in sorted(directory.glob("*.csv")):
        run = load_run(path)
        key = (str(run["scenario"]), int(run["agents"]), int(run["seed"]))
        selected[key] = run
    return selected


def write_summary(
    path: Path,
    rows: list[list[str]],
    header: list[str],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)


def aggregate_scenarios(runs: dict[tuple[str, int, int], dict[str, object]]) -> list[dict[str, float | str]]:
    aggregated = []
    for scenario in SCENARIO_ORDER:
        group = [runs[(scenario, 1000, seed)] for seed in sorted(REPORT_SEEDS)]
        if not all(run["status"] == "completed" for run in group):
            raise ValueError(f"Scenario {scenario} contains an unfinished selected run.")
        aggregated.append(
            {
                "scenario": scenario,
                "time": statistics.fmean(float(run["time"]) for run in group),
                "time_min": min(float(run["time"]) for run in group),
                "time_max": max(float(run["time"]) for run in group),
                "mean": statistics.fmean(float(run["mean"]) for run in group),
                "p95": statistics.fmean(float(run["p95"]) for run in group),
                "density": statistics.fmean(float(run["density"]) for run in group),
                "panic": statistics.fmean(float(run["panic"]) for run in group),
                "exposure": statistics.fmean(float(run["exposure"]) for run in group),
            }
        )
    return aggregated


def draw_chart_base(title: str, y_label: str) -> tuple[pygame.Surface, pygame.Rect, pygame.font.Font, pygame.font.Font]:
    surface = pygame.Surface((1100, 620))
    surface.fill(pygame.Color("#ffffff"))
    font = pygame.font.SysFont("arial", 23)
    small = pygame.font.SysFont("arial", 17)
    title_render = font.render(title, True, pygame.Color("#17212b"))
    surface.blit(title_render, (80, 25))
    plot = pygame.Rect(95, 85, 930, 445)
    pygame.draw.line(surface, pygame.Color("#273442"), plot.bottomleft, plot.bottomright, 2)
    pygame.draw.line(surface, pygame.Color("#273442"), plot.topleft, plot.bottomleft, 2)
    label = small.render(y_label, True, pygame.Color("#273442"))
    surface.blit(label, (20, 55))
    return surface, plot, font, small


def draw_grid(surface: pygame.Surface, plot: pygame.Rect, maximum: float, small: pygame.font.Font) -> None:
    for index in range(6):
        value = maximum * index / 5
        y = plot.bottom - round(plot.height * index / 5)
        pygame.draw.line(surface, pygame.Color("#e1e6eb"), (plot.left, y), (plot.right, y), 1)
        rendered = small.render(f"{value:.0f}", True, pygame.Color("#53606b"))
        surface.blit(rendered, (plot.left - rendered.get_width() - 12, y - rendered.get_height() // 2))


def save_scenario_bar_chart(aggregated: list[dict[str, float | str]]) -> None:
    surface, plot, _font, small = draw_chart_base(
        "Total evacuation time by emergency scenario (1000 agents, three seeds)",
        "seconds",
    )
    maximum = 220.0
    draw_grid(surface, plot, maximum, small)
    column_width = plot.width // len(aggregated)
    for index, item in enumerate(aggregated):
        center_x = plot.left + column_width * index + column_width // 2
        value = float(item["time"])
        bar_width = 105
        bar_height = round(plot.height * value / maximum)
        rect = pygame.Rect(center_x - bar_width // 2, plot.bottom - bar_height, bar_width, bar_height)
        color = SCENARIO_COLORS[str(item["scenario"])]
        pygame.draw.rect(surface, color, rect, border_radius=3)
        low_y = plot.bottom - round(plot.height * float(item["time_min"]) / maximum)
        high_y = plot.bottom - round(plot.height * float(item["time_max"]) / maximum)
        pygame.draw.line(surface, pygame.Color("#17212b"), (center_x, high_y), (center_x, low_y), 2)
        pygame.draw.line(surface, pygame.Color("#17212b"), (center_x - 14, high_y), (center_x + 14, high_y), 2)
        pygame.draw.line(surface, pygame.Color("#17212b"), (center_x - 14, low_y), (center_x + 14, low_y), 2)
        value_render = small.render(f"{value:.1f}", True, pygame.Color("#17212b"))
        surface.blit(value_render, (center_x - value_render.get_width() // 2, rect.top - 30))
        label = small.render(SCENARIO_LABELS[str(item["scenario"])], True, pygame.Color("#273442"))
        surface.blit(label, (center_x - label.get_width() // 2, plot.bottom + 15))
    pygame.image.save(surface, OUTPUT_DIRECTORY / "scenario_evacuation_time.png")


def save_evacuation_curve_chart(runs: dict[tuple[str, int, int], dict[str, object]]) -> None:
    surface, plot, _font, small = draw_chart_base(
        "Cumulative evacuation for representative runs (seed 101, 1000 agents)",
        "evacuated [%]",
    )
    draw_grid(surface, plot, 100.0, small)
    maximum_time = 145.0
    for index in range(6):
        value = maximum_time * index / 5
        x = plot.left + round(plot.width * index / 5)
        rendered = small.render(f"{value:.0f}", True, pygame.Color("#53606b"))
        surface.blit(rendered, (x - rendered.get_width() // 2, plot.bottom + 14))
    time_label = small.render("simulated time [s]", True, pygame.Color("#273442"))
    surface.blit(time_label, (plot.centerx - time_label.get_width() // 2, plot.bottom + 43))
    for scenario in SCENARIO_ORDER:
        run = runs[(scenario, 1000, 101)]
        points = []
        for row in run["rows"]:
            x = plot.left + round(plot.width * min(float(row["sample_time"]), maximum_time) / maximum_time)
            y = plot.bottom - round(plot.height * int(row["evacuated_agents"]) / 1000)
            points.append((x, y))
        if len(points) > 1:
            pygame.draw.lines(surface, SCENARIO_COLORS[scenario], False, points, 3)
    legend_x = plot.left + 25
    for index, scenario in enumerate(SCENARIO_ORDER):
        x = legend_x + index * 210
        pygame.draw.line(surface, SCENARIO_COLORS[scenario], (x, 568), (x + 30, 568), 4)
        label = small.render(SCENARIO_LABELS[scenario], True, pygame.Color("#273442"))
        surface.blit(label, (x + 38, 558))
    pygame.image.save(surface, OUTPUT_DIRECTORY / "evacuation_curves.png")


def save_load_chart(load_runs: list[dict[str, object]]) -> None:
    surface, plot, _font, small = draw_chart_base(
        "Baseline run duration or observation limit versus crowd size (seed 101)",
        "simulated seconds",
    )
    maximum = 330.0
    draw_grid(surface, plot, maximum, small)
    column_width = plot.width // len(load_runs)
    for index, run in enumerate(load_runs):
        center_x = plot.left + column_width * index + column_width // 2
        value = float(run["time"])
        height = round(plot.height * value / maximum)
        rect = pygame.Rect(center_x - 55, plot.bottom - height, 110, height)
        pygame.draw.rect(surface, pygame.Color("#2070b4"), rect, border_radius=3)
        prefix = ">=" if run["status"] != "completed" else ""
        value_render = small.render(f"{prefix}{value:.1f}", True, pygame.Color("#17212b"))
        surface.blit(value_render, (center_x - value_render.get_width() // 2, rect.top - 29))
        label = small.render(str(run["agents"]), True, pygame.Color("#273442"))
        surface.blit(label, (center_x - label.get_width() // 2, plot.bottom + 15))
        if run["status"] != "completed":
            fraction = small.render(f"{float(run['fraction']) * 100:.2f}%", True, pygame.Color("#ffffff"))
            surface.blit(fraction, (center_x - fraction.get_width() // 2, rect.top + 15))
    x_label = small.render("number of agents", True, pygame.Color("#273442"))
    surface.blit(x_label, (plot.centerx - x_label.get_width() // 2, plot.bottom + 43))
    pygame.image.save(surface, OUTPUT_DIRECTORY / "load_evacuation_time.png")


def main() -> None:
    pygame.init()
    OUTPUT_DIRECTORY.mkdir(exist_ok=True)
    scenario_runs = latest_runs(Path("results/report_runs"))
    aggregated = aggregate_scenarios(scenario_runs)
    load_lookup = latest_runs(Path("results/report_load"))
    load_runs = [load_lookup[("baseline", agents, 101)] for agents in (500, 1000, 2000, 4200, 7731, 11262)]
    write_summary(
        OUTPUT_DIRECTORY / "scenario_summary.csv",
        [
            [
                SCENARIO_LABELS[str(item["scenario"])],
                f"{float(item['time']):.2f}",
                f"{float(item['mean']):.2f}",
                f"{float(item['p95']):.2f}",
                f"{float(item['density']):.2f}",
                f"{float(item['panic']):.2f}",
                f"{float(item['exposure']):.2f}",
            ]
            for item in aggregated
        ],
        ["scenario", "total_time_mean", "agent_time_mean", "p95_mean", "max_density_mean", "panicked_mean", "exposure_mean"],
    )
    write_summary(
        OUTPUT_DIRECTORY / "load_summary.csv",
        [
            [
                str(run["agents"]),
                str(run["status"]),
                f"{float(run['time']):.2f}",
                str(run["evacuated"]),
                f"{float(run['fraction']) * 100:.2f}",
                f"{float(run['mean']):.2f}",
                str(run["density"]),
            ]
            for run in load_runs
        ],
        ["agents", "status", "elapsed_time", "evacuated", "evacuated_percent", "agent_time_mean", "max_density"],
    )
    save_scenario_bar_chart(aggregated)
    save_evacuation_curve_chart(scenario_runs)
    save_load_chart(load_runs)
    for item in aggregated:
        print(
            SCENARIO_LABELS[str(item["scenario"])],
            f"total={float(item['time']):.2f}",
            f"mean={float(item['mean']):.2f}",
            f"p95={float(item['p95']):.2f}",
            f"panic={float(item['panic']):.2f}",
            f"exposure={float(item['exposure']):.2f}",
        )
    for run in load_runs:
        print(
            "Load",
            run["agents"],
            run["status"],
            f"elapsed={float(run['time']):.2f}",
            f"evacuated={run['evacuated']}/{run['agents']}",
            f"fraction={float(run['fraction']) * 100:.2f}%",
            f"density={run['density']}",
        )
    pygame.quit()


if __name__ == "__main__":
    main()
