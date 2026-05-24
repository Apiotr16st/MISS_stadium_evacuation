from __future__ import annotations

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
    west_stand = rotate_layout_counterclockwise(stand_layout)
    east_stand = rotate_layout_clockwise(stand_layout)
    west = stack_layout_vertical(west_stand, vertical_stands)
    east = stack_layout_vertical(east_stand, vertical_stands)

    side_width = len(west[0])
    middle_width = max(field_width or len(north[0]), len(north[0]), len(south[0]))
    middle_height = max(field_height or len(west), len(west), len(east))

    north = center_layout(north, middle_width, len(north), corner_tile)
    south = center_layout(south, middle_width, len(south), corner_tile)
    west = center_layout(west, side_width, middle_height, corner_tile)
    east = center_layout(east, side_width, middle_height, corner_tile)
    corners = build_corner_blocks(stand_layout, side_width, len(north), corner_tile)

    rows: list[str] = []
    for index, row in enumerate(north):
        rows.append(corners["nw"][index] + row + corners["ne"][index])
    for index in range(middle_height):
        rows.append(west[index] + field_tile * middle_width + east[index])
    for index, row in enumerate(south):
        rows.append(corners["sw"][index] + row + corners["se"][index])
    return rows




def build_full_stadium_sector_map(
    stand_layout: list[str],
    stadium_layout: list[str],
    horizontal_stands: int,
    vertical_stands: int,
) -> dict[tuple[int, int], str]:
    validate_layout(stand_layout)
    validate_layout(stadium_layout)
    stand_width = len(stand_layout[0])
    stand_height = len(stand_layout)
    side_width = stand_height
    middle_width = len(stadium_layout[0]) - side_width * 2
    middle_height = len(stadium_layout) - stand_height * 2
    north_width = len(stack_layout_horizontal(stand_layout, horizontal_stands)[0])
    west_height = len(stack_layout_vertical(rotate_layout_counterclockwise(stand_layout), vertical_stands))
    north_left = side_width + (middle_width - north_width) // 2
    west_top = stand_height + (middle_height - west_height) // 2
    sectors: dict[tuple[int, int], str] = {}

    add_sector_rect(sectors, "north_west", 0, 0, side_width, stand_height)
    add_sector_rect(sectors, "north_east", side_width + middle_width, 0, side_width, stand_height)
    add_sector_rect(sectors, "south_west", 0, stand_height + middle_height, side_width, stand_height)
    add_sector_rect(
        sectors,
        "south_east",
        side_width + middle_width,
        stand_height + middle_height,
        side_width,
        stand_height,
    )

    current = north_left
    for index, width in enumerate(joined_span_sizes(stand_width, horizontal_stands), start=1):
        add_sector_rect(sectors, f"north_{index}", current, 0, width, stand_height)
        add_sector_rect(sectors, f"south_{index}", current, stand_height + middle_height, width, stand_height)
        current += width

    current = west_top
    for index, height in enumerate(joined_span_sizes(stand_width, vertical_stands), start=1):
        add_sector_rect(sectors, f"west_{index}", 0, current, side_width, height)
        add_sector_rect(sectors, f"east_{index}", side_width + middle_width, current, side_width, height)
        current += height
    return sectors




def joined_span_sizes(size: int, count: int) -> list[int]:
    if count <= 1:
        return [size]
    return [size - 1] + [size - 2 for _ in range(count - 2)] + [size - 1]




def add_sector_rect(
    sectors: dict[tuple[int, int], str],
    sector_id: str,
    left: int,
    top: int,
    width: int,
    height: int,
) -> None:
    for y in range(top, top + height):
        for x in range(left, left + width):
            sectors[(x, y)] = sector_id




def stack_layout_horizontal(layout: list[str], count: int) -> list[str]:
    validate_layout(layout)
    if count <= 0:
        raise ValueError("Liczba poziomych trybun musi byc dodatnia.")
    if count == 1:
        return list(layout)

    stacked: list[str] = []
    for row in layout:
        parts = [row[:-1]]
        parts.extend(row[1:-1] for _ in range(count - 2))
        parts.append(row[1:])
        stacked.append("".join(parts))
    return stacked




def stack_layout_vertical(layout: list[str], count: int) -> list[str]:
    validate_layout(layout)
    if count <= 0:
        raise ValueError("Liczba pionowych trybun musi byc dodatnia.")
    if count == 1:
        return list(layout)

    stacked = list(layout[:-1])
    for _ in range(count - 2):
        stacked.extend(layout[1:-1])
    stacked.extend(layout[1:])
    return stacked




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




def build_corner_blocks(stand_layout: list[str], width: int, height: int, fill_tile: str) -> dict[str, list[str]]:
    corner_layout = fit_layout(rotate_layout_counterclockwise(stand_layout), width, height, fill_tile)
    nw = corner_layout
    ne = center_layout(mirror_layout_horizontal(corner_layout), width, height, fill_tile)
    sw = center_layout(mirror_layout_vertical(corner_layout), width, height, fill_tile)
    se = center_layout(mirror_layout_vertical(mirror_layout_horizontal(corner_layout)), width, height, fill_tile)
    return {"nw": nw, "ne": ne, "sw": sw, "se": se}




def fit_layout(layout: list[str], width: int, height: int, fill_tile: str) -> list[str]:
    validate_layout(layout)
    current_width = len(layout[0])
    current_height = len(layout)
    x_offset = max(0, (current_width - width) // 2)
    y_offset = max(0, (current_height - height) // 2)
    cropped = [row[x_offset:x_offset + min(width, current_width)] for row in layout[y_offset:y_offset + min(height, current_height)]]
    return center_layout(cropped, width, height, fill_tile)




def mirror_layout_horizontal(layout: list[str]) -> list[str]:
    return ["".join(transform_edge_tile(tile, "mirror_horizontal") for tile in reversed(row)) for row in layout]




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
        "mirror_horizontal": {"P": "L", "L": "P", "D": "D", "U": "U"},
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
