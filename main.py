from __future__ import annotations

import argparse
import json
import math
import sys
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
class StadiumConfig:
    title: str
    fps: int
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
    config_path: Path
    col_widths: list[int]
    row_heights: list[int]
    col_lefts: list[int]
    row_tops: list[int]

    @property
    def width(self) -> int:
        return len(self.layout[0])

    @property
    def height(self) -> int:
        return len(self.layout)

    @property
    def world_size(self) -> tuple[int, int]:
        return sum(self.col_widths), sum(self.row_heights)


@dataclass
class Agent:
    position: Vec2
    radius: float
    speed: float
    color: pygame.Color

    def update(self, dt: float, keys: pygame.key.ScancodeWrapper, stadium: "Stadium") -> None:
        direction = Vec2(0, 0)
        if keys[pygame.K_w]:
            direction.y -= 1
        if keys[pygame.K_s]:
            direction.y += 1
        if keys[pygame.K_a]:
            direction.x -= 1
        if keys[pygame.K_d]:
            direction.x += 1

        if direction.length_squared() == 0:
            return

        direction = direction.normalize()
        movement = direction * self.speed * dt
        self._move_axis(Vec2(movement.x, 0), stadium)
        self._move_axis(Vec2(0, movement.y), stadium)

    def _move_axis(self, movement: Vec2, stadium: "Stadium") -> None:
        self.position += movement
        if movement.x == 0 and movement.y == 0:
            return

        for rect in stadium.nearby_solid_rects(self.position, self.radius):
            if not circle_intersects_rect(self.position, self.radius, rect):
                continue

            if movement.x > 0:
                self.position.x = rect.left - self.radius
            elif movement.x < 0:
                self.position.x = rect.right + self.radius
            elif movement.y > 0:
                self.position.y = rect.top - self.radius
            elif movement.y < 0:
                self.position.y = rect.bottom + self.radius

    def draw(self, surface: pygame.Surface) -> None:
        center = (round(self.position.x), round(self.position.y))
        pygame.draw.circle(surface, pygame.Color("#1d1f24"), center, round(self.radius + 3))
        pygame.draw.circle(surface, self.color, center, round(self.radius))
        pygame.draw.circle(surface, pygame.Color("#ffffff"), center, max(2, round(self.radius * 0.24)))


class Stadium:
    def __init__(self, config: StadiumConfig):
        self.config = config
        self.tile_size = config.tile_size
        self.solid_rects: list[tuple[str, pygame.Rect]] = []
        for y, row in enumerate(config.layout):
            for x, tile in enumerate(row):
                if tile in config.solid_tiles:
                    for rect in self.tile_collision_rects(x, y, tile):
                        self.solid_rects.append((tile, rect))

    def tile_at_pixel(self, position: Vec2) -> str:
        x = index_at_position(position.x, self.config.col_lefts, self.config.col_widths)
        y = index_at_position(position.y, self.config.row_tops, self.config.row_heights)
        if x < 0 or y < 0 or y >= self.config.height or x >= self.config.width:
            return "#"
        return self.config.layout[y][x]

    def nearby_solid_rects(self, position: Vec2, radius: float) -> list[pygame.Rect]:
        min_x = max(0, index_at_position(position.x - radius, self.config.col_lefts, self.config.col_widths) - 1)
        max_x = min(
            self.config.width - 1,
            index_at_position(position.x + radius, self.config.col_lefts, self.config.col_widths) + 1,
        )
        min_y = max(0, index_at_position(position.y - radius, self.config.row_tops, self.config.row_heights) - 1)
        max_y = min(
            self.config.height - 1,
            index_at_position(position.y + radius, self.config.row_tops, self.config.row_heights) + 1,
        )

        rects: list[pygame.Rect] = []
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                tile = self.config.layout[y][x]
                if tile in self.config.solid_tiles:
                    rects.extend(self.tile_collision_rects(x, y, tile))
        return rects

    def tile_collision_rects(self, x: int, y: int, tile: str) -> list[pygame.Rect]:
        style = self.config.tile_styles[tile]
        tile_rect = self.tile_rect(x, y)
        if style.edges:
            return [edge_rect(tile_rect, style, edge, visual=False) for edge in style.edges]

        return [
            aligned_size_rect(
                tile_rect,
                style.collision_width_ratio,
                style.collision_height_ratio,
                style.collision_align_x,
                style.collision_align_y,
            )
        ]

    def tile_rect(self, x: int, y: int) -> pygame.Rect:
        return pygame.Rect(
            self.config.col_lefts[x],
            self.config.row_tops[y],
            self.config.col_widths[x],
            self.config.row_heights[y],
        )

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(pygame.Color("#151a1f"))
        for y, row in enumerate(self.config.layout):
            for x, tile in enumerate(row):
                style = self.config.tile_styles[tile]
                draw_tile(surface, self.tile_rect(x, y), tile, style)


def circle_intersects_rect(center: Vec2, radius: float, rect: pygame.Rect) -> bool:
    closest_x = max(rect.left, min(center.x, rect.right))
    closest_y = max(rect.top, min(center.y, rect.bottom))
    dx = center.x - closest_x
    dy = center.y - closest_y
    return dx * dx + dy * dy < radius * radius


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

    pygame.draw.rect(surface, pygame.Color("#252c33"), rect, 1)


def draw_ui(
    surface: pygame.Surface,
    font: pygame.font.Font,
    small_font: pygame.font.Font,
    config: StadiumConfig,
    agent: Agent,
    current_tile: str,
) -> None:
    world_w, world_h = config.world_size
    panel = pygame.Rect(world_w, 0, config.ui_width, world_h)
    pygame.draw.rect(surface, pygame.Color("#101418"), panel)
    pygame.draw.line(surface, pygame.Color("#37424d"), (world_w, 0), (world_w, world_h), 2)

    x = world_w + 18
    y = 20
    y = draw_text(surface, font, "Model trybuny", x, y, pygame.Color("#f4f7f8"))
    y = draw_text(surface, small_font, "WSAD: ruch agenta", x, y + 12, pygame.Color("#b8c1c9"))
    y = draw_text(surface, small_font, "Esc: zamknij symulacje", x, y + 5, pygame.Color("#b8c1c9"))
    y = draw_text(surface, small_font, f"Config: {config.config_path.name}", x, y + 5, pygame.Color("#b8c1c9"))

    y += 20
    y = draw_text(surface, font, "Status", x, y, pygame.Color("#f4f7f8"))
    tile_name = config.tile_styles[current_tile].name
    y = draw_text(surface, small_font, f"Kafelek: {current_tile} - {tile_name}", x, y + 8, pygame.Color("#b8c1c9"))
    y = draw_text(
        surface,
        small_font,
        f"Pozycja: {agent.position.x:.0f}, {agent.position.y:.0f}",
        x,
        y + 5,
        pygame.Color("#b8c1c9"),
    )

    if current_tile in config.exit_tiles:
        y = draw_text(surface, font, "Tunel ewakuacyjny", x, y + 18, pygame.Color("#9ef0b5"))
        y = draw_text(surface, small_font, "Agent dotarl do wyjscia.", x, y + 4, pygame.Color("#d8ffe6"))

    y += 26
    y = draw_text(surface, font, "Legenda", x, y, pygame.Color("#f4f7f8"))
    for symbol, style in config.tile_styles.items():
        if symbol == "A":
            continue
        swatch = pygame.Rect(x, y + 12, 18, 18)
        pygame.draw.rect(surface, style.color, swatch, border_radius=3)
        pygame.draw.rect(surface, pygame.Color("#62707b"), swatch, 1, border_radius=3)
        draw_text(surface, small_font, f"{symbol}  {style.name}", x + 28, y + 9, pygame.Color("#c9d2d9"))
        y += 28


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


def draw_edge(surface: pygame.Surface, rect: pygame.Rect, edge: str) -> None:
    pygame.draw.rect(surface, pygame.Color("#4f2229"), rect, border_radius=3)
    if edge == "D":
        pygame.draw.line(surface, pygame.Color("#8c3b45"), rect.midtop, rect.midbottom, 1)
        pygame.draw.line(surface, pygame.Color("#2a1116"), rect.bottomleft, rect.bottomright, 2)
        return

    pygame.draw.line(surface, pygame.Color("#8c3b45"), rect.midleft, rect.midright, 1)
    pygame.draw.line(surface, pygame.Color("#2a1116"), rect.topright, rect.bottomright, 2)


def edge_rect(rect: pygame.Rect, style: TileStyle, edge: str, visual: bool) -> pygame.Rect:
    if edge == "P":
        return aligned_size_rect(rect, 1.0, 1.0, "right", "center")
    if edge == "D":
        return aligned_size_rect(rect, 1.0, 1.0, "center", "bottom")
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


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def index_at_position(value: float, starts: list[int], sizes: list[int]) -> int:
    if not starts:
        return -1
    for index, start in enumerate(starts):
        if start <= value < start + sizes[index]:
            return index
    if value < starts[0]:
        return -1
    return len(starts)


def build_offsets(sizes: list[int]) -> list[int]:
    offsets: list[int] = []
    current = 0
    for size in sizes:
        offsets.append(current)
        current += size
    return offsets


def cell_center(
    cell: tuple[int, int],
    col_lefts: list[int],
    row_tops: list[int],
    col_widths: list[int],
    row_heights: list[int],
) -> Vec2:
    x, y = cell
    return Vec2(col_lefts[x] + col_widths[x] / 2, row_tops[y] + row_heights[y] / 2)


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
    ui_width = int(window.get("ui_width", 310))

    tile_styles = parse_tile_styles(raw.get("tiles", {}))
    layout_block = raw.get("layout", {})
    layout = load_layout(layout_block, raw, config_path.parent)

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

    return StadiumConfig(
        title=title,
        fps=fps,
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
        config_path=config_path,
        col_widths=col_widths,
        row_heights=row_heights,
        col_lefts=col_lefts,
        row_tops=row_tops,
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


def validate_layout(layout: list[str]) -> None:
    if not layout:
        raise ValueError("Mapa nie moze byc pusta.")
    width = len(layout[0])
    if width == 0:
        raise ValueError("Mapa nie moze miec pustych wierszy.")
    for index, row in enumerate(layout):
        if len(row) != width:
            raise ValueError(f"Wiersz mapy {index} ma dlugosc {len(row)}, oczekiwano {width}.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pygame: model pojedynczej trybuny stadionu.")
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

    stadium = Stadium(config)
    agent = Agent(
        position=Vec2(config.spawn_position),
        radius=config.agent_radius,
        speed=config.agent_speed,
        color=config.agent_color,
    )

    world_w, world_h = config.world_size
    screen = pygame.display.set_mode((world_w + config.ui_width, world_h))
    pygame.display.set_caption(config.title)

    clock = pygame.time.Clock()
    font = pygame.font.SysFont("segoeui", 22, bold=True)
    small_font = pygame.font.SysFont("segoeui", 16)
    running = True

    while running:
        dt = clock.tick(config.fps) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        keys = pygame.key.get_pressed()
        agent.update(dt, keys, stadium)
        current_tile = stadium.tile_at_pixel(agent.position)

        stadium.draw(screen)
        agent.draw(screen)
        draw_ui(screen, font, small_font, config, agent, current_tile)
        pygame.display.flip()

    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
