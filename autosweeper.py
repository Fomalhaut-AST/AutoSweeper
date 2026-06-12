# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import ctypes
import math
import random
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from fractions import Fraction
from typing import (
    TYPE_CHECKING,
    DefaultDict,
    Dict,
    FrozenSet,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
)

try:
    from PIL import Image, ImageGrab
except ImportError:  # pragma: no cover - shown to users without Pillow installed.
    Image = None
    ImageGrab = None

if TYPE_CHECKING:
    from PIL.Image import Image as PilImage
else:
    PilImage = object


UNKNOWN = -1
FLAG = -2
Cell = Tuple[int, int]
Constraint = Tuple[FrozenSet[Cell], int]


PRESETS = {
    "beginner": (9, 9, 10),
    "basic": (9, 9, 10),
    "easy": (9, 9, 10),
    "intermediate": (16, 16, 40),
    "medium": (16, 16, 40),
    "expert": (16, 30, 99),
    "hard": (16, 30, 99),
}

PRESET_HELP = (
    "常见难度预设：basic/beginner/easy=9x9 10雷，"
    "medium/intermediate=16x16 40雷，hard/expert=16x30 99雷"
)


@dataclass(frozen=True)
class BoardRegion:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def translated(self, dx: int, dy: int) -> "BoardRegion":
        return BoardRegion(self.left + dx, self.top + dy, self.width, self.height)


@dataclass
class ComponentSolution:
    cells: List[Cell]
    total_by_mines: Dict[int, int]
    mine_by_mines: Dict[int, List[int]]


@dataclass
class SolverResult:
    safe: Set[Cell]
    mines: Set[Cell]
    guess: Optional[Cell]
    probabilities: Dict[Cell, Fraction]
    reason: str
    valid: bool = True


@dataclass
class DeterministicResult:
    safe: Set[Cell]
    mines: Set[Cell]
    constraints: List[Constraint]
    reason: str
    valid: bool = True


def enable_dpi_awareness() -> None:
    if not hasattr(ctypes, "windll"):
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def select_region() -> BoardRegion:
    import tkinter as tk

    if not hasattr(ctypes, "windll"):
        raise RuntimeError("The drag selector currently supports Windows desktop sessions.")

    user32 = ctypes.windll.user32
    virtual_left = user32.GetSystemMetrics(76)
    virtual_top = user32.GetSystemMetrics(77)
    virtual_width = user32.GetSystemMetrics(78)
    virtual_height = user32.GetSystemMetrics(79)

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.28)
    root.geometry(f"{virtual_width}x{virtual_height}+{virtual_left}+{virtual_top}")
    root.configure(bg="black")

    canvas = tk.Canvas(root, cursor="crosshair", bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_text(
        24,
        24,
        anchor="nw",
        fill="white",
        font=("Microsoft YaHei UI", 16, "bold"),
        text="拖拽框选扫雷窗口或棋盘区域；Esc 取消",
    )

    state: Dict[str, Optional[int]] = {"x0": None, "y0": None, "rect": None}
    selected: Dict[str, Optional[BoardRegion]] = {"region": None}

    def to_canvas(x_root: int, y_root: int) -> Tuple[int, int]:
        return x_root - virtual_left, y_root - virtual_top

    def on_press(event: tk.Event) -> None:
        x, y = to_canvas(event.x_root, event.y_root)
        state["x0"], state["y0"] = x, y
        if state["rect"] is not None:
            canvas.delete(state["rect"])
        state["rect"] = canvas.create_rectangle(
            x, y, x, y, outline="#00e5ff", width=3
        )

    def on_drag(event: tk.Event) -> None:
        if state["x0"] is None or state["y0"] is None or state["rect"] is None:
            return
        x, y = to_canvas(event.x_root, event.y_root)
        canvas.coords(state["rect"], state["x0"], state["y0"], x, y)

    def on_release(event: tk.Event) -> None:
        if state["x0"] is None or state["y0"] is None:
            return
        x1, y1 = to_canvas(event.x_root, event.y_root)
        x0, y0 = state["x0"], state["y0"]
        left = min(x0, x1) + virtual_left
        top = min(y0, y1) + virtual_top
        right = max(x0, x1) + virtual_left
        bottom = max(y0, y1) + virtual_top
        if right - left >= 20 and bottom - top >= 20:
            selected["region"] = BoardRegion(
                int(left), int(top), int(right - left), int(bottom - top)
            )
            root.destroy()

    def on_escape(_: tk.Event) -> None:
        selected["region"] = None
        root.destroy()

    root.bind("<ButtonPress-1>", on_press)
    root.bind("<B1-Motion>", on_drag)
    root.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_escape)
    root.focus_force()
    root.mainloop()

    if selected["region"] is None:
        raise KeyboardInterrupt("Selection cancelled.")
    return selected["region"]


def grab_region(region: BoardRegion) -> PilImage:
    if ImageGrab is None:
        raise RuntimeError("Pillow is not installed. Run: pip install pillow")
    bbox = (region.left, region.top, region.right, region.bottom)
    try:
        return ImageGrab.grab(bbox=bbox, all_screens=True).convert("RGB")
    except TypeError:
        return ImageGrab.grab(bbox=bbox).convert("RGB")


def _is_cell_edge_pixel(pixel: Tuple[int, int, int]) -> bool:
    red, green, blue = pixel
    return (
        min(red, green, blue) >= 225
        or max(red, green, blue) <= 165
        or (
            145 <= red <= 210
            and 145 <= green <= 210
            and 145 <= blue <= 210
            and max(red, green, blue) - min(red, green, blue) <= 35
        )
    )


def _axis_edge_scores(image: PilImage, vertical: bool) -> List[float]:
    width, height = image.size
    pixels = image.load()
    if pixels is None:
        raise RuntimeError("无法读取截图像素。")
    contrast_threshold = 25

    def get_pixel(x: int, y: int) -> Tuple[int, int, int]:
        return pixels[x, y]

    def has_local_contrast(x: int, y: int) -> bool:
        pixel = get_pixel(x, y)
        if vertical:
            before = get_pixel(max(0, x - 1), y)
            after = get_pixel(min(width - 1, x + 1), y)
        else:
            before = get_pixel(x, max(0, y - 1))
            after = get_pixel(x, min(height - 1, y + 1))
        return max(
            max(abs(pixel[i] - before[i]) for i in range(3)),
            max(abs(pixel[i] - after[i]) for i in range(3)),
        ) >= contrast_threshold

    if vertical:
        return [
            sum(
                1
                for y in range(height)
                if _is_cell_edge_pixel(get_pixel(x, y)) and has_local_contrast(x, y)
            )
            / max(1, height)
            for x in range(width)
        ]
    return [
        sum(
            1
            for x in range(width)
            if _is_cell_edge_pixel(get_pixel(x, y)) and has_local_contrast(x, y)
        )
        / max(1, width)
        for y in range(height)
    ]


def _best_grid_axis(
    line_scores: Sequence[float],
    count: int,
    min_cell: float = 8.0,
    max_cell: float = 80.0,
) -> Optional[Tuple[int, int, float]]:
    length = len(line_scores)
    if count <= 0 or length < count * min_cell:
        return None

    max_score = max(line_scores) if line_scores else 0.0
    if max_score <= 0:
        return None

    threshold = max(0.08, max_score * 0.35)
    peaks: List[int] = []
    index = 0
    while index < length:
        if line_scores[index] < threshold:
            index += 1
            continue
        start = index
        while index < length and line_scores[index] >= threshold:
            index += 1
        end = index
        peak = max(range(start, end), key=lambda pos: line_scores[pos])
        peaks.append(peak)

    if len(peaks) < count + 1:
        return None

    def local_score(position: int) -> float:
        left = max(0, position - 2)
        right = min(length, position + 3)
        return max(line_scores[left:right])

    min_span = count * min_cell
    max_span = count * max_cell
    strong_threshold = max(0.10, max_score * 0.28)
    best: Optional[Tuple[int, int, float]] = None

    for start_index, start in enumerate(peaks):
        for end in peaks[start_index + count :]:
            span = end - start
            if span < min_span:
                continue
            if span > max_span:
                break

            step = span / count
            positions = [int(round(start + i * step)) for i in range(count + 1)]
            if len(set(positions)) != count + 1 or positions[-1] >= length:
                continue

            scores = [local_score(pos) for pos in positions]
            inner_scores = scores[1:-1]
            strong_count = sum(1 for value in inner_scores if value >= strong_threshold)
            if inner_scores and strong_count < len(inner_scores) * 0.58:
                continue

            border_score = (scores[0] + scores[-1]) / 2
            average_score = sum(scores) / len(scores)
            span_bonus = min(1.0, span / max(1.0, length))
            score = average_score + 0.20 * border_score + 0.03 * span_bonus

            if best is None or score > best[2]:
                best = (positions[0], positions[-1] + 1, score)

    return best


def detect_board_region(
    image: PilImage, rows: int, cols: int, min_score: float = 0.45
) -> Optional[BoardRegion]:
    image = image.convert("RGB")
    x_axis = _best_grid_axis(_axis_edge_scores(image, vertical=True), cols)
    y_axis = _best_grid_axis(_axis_edge_scores(image, vertical=False), rows)
    if x_axis is None or y_axis is None:
        return None

    left, right, x_score = x_axis
    top, bottom, y_score = y_axis
    if min(x_score, y_score) < min_score:
        return None
    if right - left < cols * 6 or bottom - top < rows * 6:
        return None

    return BoardRegion(left, top, right - left, bottom - top)


def looks_like_grid_region(region: BoardRegion, rows: int, cols: int, tolerance: float = 0.12) -> bool:
    if rows <= 0 or cols <= 0 or region.width <= 0 or region.height <= 0:
        return False
    expected = cols / rows
    actual = region.width / region.height
    return abs(actual - expected) / expected <= tolerance


def resolve_board_region(
    selected_region: BoardRegion,
    selected_image: PilImage,
    rows: int,
    cols: int,
    auto_crop: bool,
    crop_min_score: float,
) -> BoardRegion:
    if not auto_crop:
        print("已关闭自动棋盘定位，直接使用框选区域。")
        return selected_region

    detected = detect_board_region(selected_image, rows, cols, min_score=crop_min_score)
    if detected is not None:
        absolute = detected.translated(selected_region.left, selected_region.top)
        print(
            "自动定位棋盘："
            f"left={absolute.left}, top={absolute.top}, "
            f"width={absolute.width}, height={absolute.height}"
        )
        return absolute

    if looks_like_grid_region(selected_region, rows, cols):
        print("自动定位棋盘失败；框选区域宽高比接近棋盘，按框选区域继续。")
        return selected_region

    raise RuntimeError(
        "自动定位棋盘失败，且框选区域不像核心棋盘。请重新框选包含扫雷棋盘的窗口区域，"
        "或用 --no-auto-crop 直接按框选区域识别。"
    )


class ClassicRecognizer:
    def __init__(self, rows: int, cols: int) -> None:
        self.rows = rows
        self.cols = cols

    def recognize(self, board_image: PilImage) -> List[List[int]]:
        width, height = board_image.size
        board: List[List[int]] = []
        for r in range(self.rows):
            row: List[int] = []
            y0 = round(r * height / self.rows)
            y1 = round((r + 1) * height / self.rows)
            for c in range(self.cols):
                x0 = round(c * width / self.cols)
                x1 = round((c + 1) * width / self.cols)
                crop = board_image.crop((x0, y0, x1, y1))
                row.append(self._recognize_cell(crop))
            board.append(row)
        return board

    def _recognize_cell(self, crop: PilImage) -> int:
        crop = crop.convert("RGB")
        width, height = crop.size
        if width < 6 or height < 6:
            return UNKNOWN

        edge = max(1, min(width, height) // 6)
        top_pixels = list(crop.crop((0, 0, width, edge)).getdata())
        left_pixels = list(crop.crop((0, 0, edge, height)).getdata())
        bottom_pixels = list(crop.crop((0, height - edge, width, height)).getdata())
        right_pixels = list(crop.crop((width - edge, 0, width, height)).getdata())

        white_tl = self._ratio(top_pixels + left_pixels, lambda p: min(p) >= 225)
        dark_br = self._ratio(bottom_pixels + right_pixels, lambda p: max(p) <= 170)
        raised = white_tl >= 0.12 and dark_br >= 0.08

        inset_x = max(1, int(width * 0.18))
        inset_y = max(1, int(height * 0.18))
        center = crop.crop((inset_x, inset_y, width - inset_x, height - inset_y))
        center_pixels = list(center.getdata())
        min_colored = max(2, int(len(center_pixels) * 0.012))

        red_count = sum(1 for p in center_pixels if p[0] > 150 and p[1] < 95 and p[2] < 95)
        if raised and red_count >= min_colored:
            return FLAG

        number = self._recognize_number(center_pixels, min_colored)
        if number is not None:
            return number
        return UNKNOWN if raised else 0

    @staticmethod
    def _ratio(pixels: Sequence[Tuple[int, int, int]], predicate) -> float:
        if not pixels:
            return 0.0
        return sum(1 for p in pixels if predicate(p)) / len(pixels)

    @staticmethod
    def _recognize_number(
        pixels: Sequence[Tuple[int, int, int]], min_colored: int
    ) -> Optional[int]:
        counts = {i: 0 for i in range(1, 9)}
        for red, green, blue in pixels:
            if blue > 150 and red < 90 and green < 120:
                counts[1] += 1
            elif green > 85 and red < 115 and blue < 115:
                counts[2] += 1
            elif red > 150 and green < 110 and blue < 110:
                counts[3] += 1
            elif blue > 70 and red < 85 and green < 85:
                counts[4] += 1
            elif red > 70 and green < 85 and blue < 85:
                counts[5] += 1
            elif green > 75 and blue > 75 and red < 85 and abs(green - blue) < 90:
                counts[6] += 1
            elif red < 65 and green < 65 and blue < 65:
                counts[7] += 1
            elif (
                75 <= red <= 170
                and 75 <= green <= 170
                and 75 <= blue <= 170
                and max(red, green, blue) - min(red, green, blue) <= 35
            ):
                counts[8] += 1

        number, count = max(counts.items(), key=lambda item: item[1])
        return number if count >= min_colored else None


class MouseController:
    LEFT_DOWN = 0x0002
    LEFT_UP = 0x0004
    RIGHT_DOWN = 0x0008
    RIGHT_UP = 0x0010

    def __init__(self, dry_run: bool = False, click_delay: float = 0.06) -> None:
        self.dry_run = dry_run
        self.click_delay = click_delay
        self.user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None

    def click(self, x: int, y: int, button: str) -> None:
        if self.dry_run:
            print(f"[dry-run] {button}-click at ({x}, {y})")
            return
        if self.user32 is None:
            raise RuntimeError("Mouse control currently supports Windows only.")
        down, up = (
            (self.LEFT_DOWN, self.LEFT_UP)
            if button == "left"
            else (self.RIGHT_DOWN, self.RIGHT_UP)
        )
        self.user32.SetCursorPos(int(x), int(y))
        time.sleep(min(0.03, self.click_delay))
        self.user32.mouse_event(down, 0, 0, 0, 0)
        time.sleep(0.01)
        self.user32.mouse_event(up, 0, 0, 0, 0)
        time.sleep(self.click_delay)


def neighbors(cell: Cell, rows: int, cols: int) -> Iterable[Cell]:
    r, c = cell
    for nr in range(max(0, r - 1), min(rows, r + 2)):
        for nc in range(max(0, c - 1), min(cols, c + 2)):
            if nr != r or nc != c:
                yield nr, nc


def collect_constraints(
    board: Sequence[Sequence[int]],
) -> Tuple[Optional[str], List[Constraint], Set[Cell], int]:
    rows, cols = len(board), len(board[0])
    merged: Dict[FrozenSet[Cell], int] = {}
    all_unknowns = {
        (r, c)
        for r in range(rows)
        for c in range(cols)
        if board[r][c] == UNKNOWN
    }
    total_flags = sum(1 for row in board for value in row if value == FLAG)

    for r in range(rows):
        for c in range(cols):
            value = board[r][c]
            if value < 0:
                continue
            adjacent_unknowns: List[Cell] = []
            adjacent_flags = 0
            for nr, nc in neighbors((r, c), rows, cols):
                if board[nr][nc] == UNKNOWN:
                    adjacent_unknowns.append((nr, nc))
                elif board[nr][nc] == FLAG:
                    adjacent_flags += 1
            remaining = value - adjacent_flags
            if remaining < 0:
                return f"cell {(r, c)} requires fewer flags than already marked", [], all_unknowns, total_flags
            if remaining > len(adjacent_unknowns):
                return (
                    f"cell {(r, c)} requires {remaining} mines among {len(adjacent_unknowns)} cells",
                    [],
                    all_unknowns,
                    total_flags,
                )
            if adjacent_unknowns:
                key = frozenset(adjacent_unknowns)
                if key in merged and merged[key] != remaining:
                    return f"conflicting constraints around cell {(r, c)}", [], all_unknowns, total_flags
                merged[key] = remaining

    return None, list(merged.items()), all_unknowns, total_flags


def merge_constraints(constraints: Iterable[Constraint]) -> Tuple[Optional[str], List[Constraint]]:
    merged: Dict[FrozenSet[Cell], int] = {}
    for cells, count in constraints:
        if not cells:
            if count != 0:
                return "empty constraint requires mines", []
            continue
        if count < 0 or count > len(cells):
            return f"constraint requires {count} mines among {len(cells)} cells", []
        previous = merged.get(cells)
        if previous is not None and previous != count:
            return "conflicting duplicate constraints", []
        merged[cells] = count
    return None, sorted(merged.items(), key=lambda item: (len(item[0]), sorted(item[0])))


def simplify_constraints(
    constraints: Iterable[Constraint],
    known_safe: Set[Cell],
    known_mines: Set[Cell],
) -> Tuple[Optional[str], List[Constraint]]:
    simplified: List[Constraint] = []
    for cells, count in constraints:
        mine_hits = len(cells & known_mines)
        reduced_cells = frozenset(cells - known_safe - known_mines)
        reduced_count = count - mine_hits
        if reduced_count < 0:
            return "too many known mines inside a constraint", []
        if reduced_count > len(reduced_cells):
            return "not enough unknown cells left to satisfy a constraint", []
        if reduced_cells:
            simplified.append((reduced_cells, reduced_count))
        elif reduced_count != 0:
            return "empty reduced constraint is unsatisfied", []
    return merge_constraints(simplified)


def deterministic_closure(
    local_constraints: Sequence[Constraint],
    unknowns: Set[Cell],
    flags: int,
    total_mines: Optional[int],
    max_rounds: int = 12,
    max_constraints: int = 600,
    max_pairwise_constraints: int = 160,
) -> DeterministicResult:
    known_safe: Set[Cell] = set()
    known_mines: Set[Cell] = set()
    constraints: Set[Constraint] = set(local_constraints)
    derived_count = 0

    if total_mines is not None:
        remaining_mines = total_mines - flags
        if remaining_mines < 0:
            return DeterministicResult(set(), set(), [], "已标记雷数超过总雷数。", False)
        if remaining_mines > len(unknowns):
            return DeterministicResult(set(), set(), [], "剩余总雷数超过未开格数量。", False)
        if unknowns:
            constraints.add((frozenset(unknowns), remaining_mines))

    truncated = False

    for _ in range(max_rounds):
        error, normalized = simplify_constraints(constraints, known_safe, known_mines)
        if error:
            return DeterministicResult(set(), set(), [], f"确定性约束矛盾：{error}", False)

        constraints = set(normalized)
        safe_before = len(known_safe)
        mine_before = len(known_mines)
        constraint_before = len(constraints)
        additions: Set[Constraint] = set()

        for cells, count in normalized:
            if count == 0:
                known_safe.update(cells)
            elif count == len(cells):
                known_mines.update(cells)

        if known_safe & known_mines:
            return DeterministicResult(set(), set(), [], "同一格同时被推为安全和地雷。", False)

        items = sorted(normalized, key=lambda item: (len(item[0]), sorted(item[0])))
        if len(items) > max_pairwise_constraints:
            truncated = True
            items_for_pairwise = items[:max_pairwise_constraints]
        else:
            items_for_pairwise = items

        for i, (left_cells, left_count) in enumerate(items_for_pairwise):
            for right_cells, right_count in items_for_pairwise[i + 1 :]:
                if left_cells == right_cells:
                    continue

                if left_cells < right_cells:
                    diff = frozenset(right_cells - left_cells)
                    additions.add((diff, right_count - left_count))
                    continue
                if right_cells < left_cells:
                    diff = frozenset(left_cells - right_cells)
                    additions.add((diff, left_count - right_count))
                    continue

                overlap = frozenset(left_cells & right_cells)
                if not overlap:
                    continue

                left_only = frozenset(left_cells - overlap)
                right_only = frozenset(right_cells - overlap)
                lower = max(
                    0,
                    left_count - len(left_only),
                    right_count - len(right_only),
                )
                upper = min(len(overlap), left_count, right_count)
                if lower > upper:
                    return DeterministicResult(set(), set(), [], "交集约束上下界矛盾。", False)

                if lower == upper:
                    additions.add((overlap, lower))

                left_min = max(0, left_count - upper)
                left_max = min(len(left_only), left_count - lower)
                right_min = max(0, right_count - upper)
                right_max = min(len(right_only), right_count - lower)

                if left_only and left_min == left_max:
                    additions.add((left_only, left_min))
                if right_only and right_min == right_max:
                    additions.add((right_only, right_min))
                if left_only and left_max == 0:
                    known_safe.update(left_only)
                if right_only and right_max == 0:
                    known_safe.update(right_only)
                if left_only and left_min == len(left_only):
                    known_mines.update(left_only)
                if right_only and right_min == len(right_only):
                    known_mines.update(right_only)

        for cells, count in additions:
            if not cells:
                if count != 0:
                    return DeterministicResult(set(), set(), [], "派生出空集矛盾约束。", False)
                continue
            if count < 0 or count > len(cells):
                return DeterministicResult(set(), set(), [], "派生约束的雷数越界。", False)
            constraints.add((cells, count))
            if len(constraints) >= max_constraints:
                truncated = True
                break
        derived_count += max(0, len(constraints) - constraint_before)

        if len(constraints) >= max_constraints:
            break
        if (
            len(known_safe) == safe_before
            and len(known_mines) == mine_before
            and len(constraints) == constraint_before
        ):
            break
    else:
        truncated = True

    safe = known_safe & unknowns
    mines = known_mines & unknowns
    suffix = "；已达到规模上限，转入精确枚举" if truncated else ""
    reason = (
        f"确定性闭包推出 {len(safe)} 个安全格、{len(mines)} 个雷；"
        f"派生约束 {derived_count} 条{suffix}"
    )
    return DeterministicResult(safe, mines, sorted(constraints, key=lambda item: (len(item[0]), sorted(item[0]))), reason, True)


def split_components(
    constraints: Sequence[Constraint],
) -> List[Tuple[List[Cell], List[Constraint]]]:
    cell_to_constraints: DefaultDict[Cell, List[int]] = defaultdict(list)
    for idx, (cells, _) in enumerate(constraints):
        for cell in cells:
            cell_to_constraints[cell].append(idx)

    remaining = set(cell_to_constraints)
    components: List[Tuple[List[Cell], List[Constraint]]] = []

    while remaining:
        first = remaining.pop()
        queue: deque[Cell] = deque([first])
        comp_cells: Set[Cell] = {first}
        comp_constraint_ids: Set[int] = set()

        while queue:
            cell = queue.popleft()
            for constraint_id in cell_to_constraints[cell]:
                if constraint_id in comp_constraint_ids:
                    continue
                comp_constraint_ids.add(constraint_id)
                for next_cell in constraints[constraint_id][0]:
                    if next_cell not in comp_cells:
                        comp_cells.add(next_cell)
                        remaining.discard(next_cell)
                        queue.append(next_cell)

        comp_constraints = [constraints[i] for i in sorted(comp_constraint_ids)]
        components.append((sorted(comp_cells), comp_constraints))

    return components


def enumerate_component(
    cells: List[Cell], constraints: Sequence[Constraint]
) -> Optional[ComponentSolution]:
    index = {cell: i for i, cell in enumerate(cells)}
    local_constraints: List[Tuple[List[int], int]] = []
    for constraint_cells, count in constraints:
        local_constraints.append(([index[cell] for cell in constraint_cells], count))

    constraint_cells = [items for items, _ in local_constraints]
    required = [count for _, count in local_constraints]
    assigned = [0] * len(local_constraints)
    unassigned = [len(items) for items in constraint_cells]

    var_to_constraints: List[List[int]] = [[] for _ in cells]
    for constraint_id, items in enumerate(constraint_cells):
        for var in items:
            var_to_constraints[var].append(constraint_id)

    order = sorted(range(len(cells)), key=lambda i: (-len(var_to_constraints[i]), cells[i]))
    assignment = [0] * len(cells)
    total_by_mines: DefaultDict[int, int] = defaultdict(int)
    mine_by_mines: DefaultDict[int, List[int]] = defaultdict(lambda: [0] * len(cells))

    def dfs(position: int, mines_so_far: int) -> None:
        if position == len(order):
            if all(assigned[i] == required[i] for i in range(len(required))):
                total_by_mines[mines_so_far] += 1
                mine_counts = mine_by_mines[mines_so_far]
                for i, value in enumerate(assignment):
                    if value:
                        mine_counts[i] += 1
            return

        var = order[position]
        for value in (0, 1):
            assignment[var] = value
            touched = var_to_constraints[var]
            ok = True
            for constraint_id in touched:
                unassigned[constraint_id] -= 1
                assigned[constraint_id] += value
                if (
                    assigned[constraint_id] > required[constraint_id]
                    or assigned[constraint_id] + unassigned[constraint_id] < required[constraint_id]
                ):
                    ok = False
            if ok:
                dfs(position + 1, mines_so_far + value)
            for constraint_id in touched:
                assigned[constraint_id] -= value
                unassigned[constraint_id] += 1
            assignment[var] = 0

    dfs(0, 0)
    if not total_by_mines:
        return None
    return ComponentSolution(cells, dict(total_by_mines), dict(mine_by_mines))


def convolve(left: Dict[int, int], right: Dict[int, int]) -> Dict[int, int]:
    result: DefaultDict[int, int] = defaultdict(int)
    for left_mines, left_count in left.items():
        for right_mines, right_count in right.items():
            result[left_mines + right_mines] += left_count * right_count
    return dict(result)


def outside_distribution(count: int) -> Dict[int, int]:
    return {mines: math.comb(count, mines) for mines in range(count + 1)}


def solve_board(
    board: Sequence[Sequence[int]],
    total_mines: Optional[int],
    allow_guess: bool,
    rng: random.Random,
    max_component_cells: int = 28,
) -> SolverResult:
    error, constraints, unknowns, flags = collect_constraints(board)
    if error:
        return SolverResult(set(), set(), None, {}, f"识别或标记状态产生矛盾：{error}", False)

    deterministic = deterministic_closure(constraints, unknowns, flags, total_mines)
    if not deterministic.valid:
        return SolverResult(set(), set(), None, {}, deterministic.reason, False)
    if deterministic.safe or deterministic.mines:
        return SolverResult(
            deterministic.safe,
            deterministic.mines,
            None,
            {},
            deterministic.reason,
            True,
        )

    if total_mines is None:
        constraints = deterministic.constraints
    frontier = {cell for cells, _ in constraints for cell in cells}
    outside = sorted(unknowns - frontier)
    probabilities: Dict[Cell, Fraction] = {}
    safe: Set[Cell] = set()
    mines: Set[Cell] = set()

    component_defs = split_components(constraints)
    components: List[ComponentSolution] = []
    for cells, comp_constraints in component_defs:
        if len(cells) > max_component_cells:
            return SolverResult(
                set(),
                set(),
                None,
                {},
                (
                    f"{deterministic.reason}；没有零风险动作。"
                    f"边界分量含 {len(cells)} 个未知格，超过精确枚举上限 {max_component_cells}"
                ),
                True,
            )
        solution = enumerate_component(cells, comp_constraints)
        if solution is None:
            return SolverResult(set(), set(), None, {}, "约束系统无解，通常是识别区域或行列数不匹配。", False)
        components.append(solution)

    if total_mines is not None:
        remaining_mines = total_mines - flags
        if remaining_mines < 0:
            return SolverResult(set(), set(), None, {}, "已标记雷数超过总雷数。", False)

        prefix: List[Dict[int, int]] = [{0: 1}]
        for component in components:
            prefix.append(convolve(prefix[-1], component.total_by_mines))

        suffix: List[Dict[int, int]] = [{} for _ in range(len(components) + 1)]
        suffix[-1] = outside_distribution(len(outside))
        for i in range(len(components) - 1, -1, -1):
            suffix[i] = convolve(components[i].total_by_mines, suffix[i + 1])

        total_ways = suffix[0].get(remaining_mines, 0)
        if total_ways == 0:
            return SolverResult(set(), set(), None, {}, "总雷数与当前识别到的棋盘状态不一致。", False)

        for i, component in enumerate(components):
            other_dist = convolve(prefix[i], suffix[i + 1])
            occurrences = [0] * len(component.cells)
            for local_mines, local_count in component.total_by_mines.items():
                other_count = other_dist.get(remaining_mines - local_mines, 0)
                if not other_count:
                    continue
                mine_counts = component.mine_by_mines[local_mines]
                for cell_index, mine_count in enumerate(mine_counts):
                    _ = local_count
                    occurrences[cell_index] += mine_count * other_count
            for cell, occurrence in zip(component.cells, occurrences):
                probabilities[cell] = Fraction(occurrence, total_ways)

        if outside:
            occurrence_each = 0
            component_dist = prefix[-1]
            for component_mines, component_count in component_dist.items():
                outside_mines = remaining_mines - component_mines
                if 1 <= outside_mines <= len(outside):
                    occurrence_each += component_count * math.comb(
                        len(outside) - 1, outside_mines - 1
                    )
            for cell in outside:
                probabilities[cell] = Fraction(occurrence_each, total_ways)

    else:
        for component in components:
            denominator = sum(component.total_by_mines.values())
            occurrences = [0] * len(component.cells)
            for mine_counts in component.mine_by_mines.values():
                for cell_index, mine_count in enumerate(mine_counts):
                    occurrences[cell_index] += mine_count
            for cell, occurrence in zip(component.cells, occurrences):
                probabilities[cell] = Fraction(occurrence, denominator)

    for cell, probability in probabilities.items():
        if probability == 0:
            safe.add(cell)
        elif probability == 1:
            mines.add(cell)

    guess = None
    if not safe and not mines and allow_guess and unknowns:
        guess = choose_guess(board, probabilities, rng)

    reason = (
        f"{deterministic.reason}；精确枚举 {len(components)} 个边界连通分量，"
        f"{len(frontier)} 个边界未知格，{len(outside)} 个非边界未知格"
    )
    return SolverResult(safe, mines, guess, probabilities, reason, True)


def choose_guess(
    board: Sequence[Sequence[int]], probabilities: Dict[Cell, Fraction], rng: random.Random
) -> Cell:
    rows, cols = len(board), len(board[0])
    unknowns = [
        (r, c)
        for r in range(rows)
        for c in range(cols)
        if board[r][c] == UNKNOWN
    ]
    if not probabilities:
        center = ((rows - 1) / 2, (cols - 1) / 2)
        return min(unknowns, key=lambda cell: (cell[0] - center[0]) ** 2 + (cell[1] - center[1]) ** 2)

    center = ((rows - 1) / 2, (cols - 1) / 2)

    def revealed_neighbors(cell: Cell) -> int:
        return sum(
            1
            for nr, nc in neighbors(cell, rows, cols)
            if board[nr][nc] >= 0
        )

    candidates = [
        (
            probabilities[cell],
            -revealed_neighbors(cell),
            (cell[0] - center[0]) ** 2 + (cell[1] - center[1]) ** 2,
            rng.random(),
            cell,
        )
        for cell in unknowns
        if cell in probabilities
    ]
    if candidates:
        return min(candidates)[-1]
    return rng.choice(unknowns)


def choose_opening_cell(rows: int, cols: int, strategy: str, rng: random.Random) -> Optional[Cell]:
    if strategy == "none":
        return None
    if strategy == "random":
        return rng.randrange(rows), rng.randrange(cols)

    center = ((rows - 1) / 2, (cols - 1) / 2)
    if strategy == "corner":
        corners = [(0, 0), (0, cols - 1), (rows - 1, 0), (rows - 1, cols - 1)]
        return max(corners, key=lambda cell: (cell[0] - center[0]) ** 2 + (cell[1] - center[1]) ** 2)

    candidates = [(r, c) for r in range(rows) for c in range(cols)]
    return min(candidates, key=lambda cell: (cell[0] - center[0]) ** 2 + (cell[1] - center[1]) ** 2)


def cell_center(region: BoardRegion, rows: int, cols: int, cell: Cell) -> Tuple[int, int]:
    r, c = cell
    x = region.left + (c + 0.5) * region.width / cols
    y = region.top + (r + 0.5) * region.height / rows
    return int(round(x)), int(round(y))


def board_to_text(board: Sequence[Sequence[int]]) -> str:
    symbols = {UNKNOWN: "#", FLAG: "F", 0: "."}
    return "\n".join(" ".join(symbols.get(value, str(value)) for value in row) for row in board)


def board_signature(board: Sequence[Sequence[int]]) -> Tuple[Tuple[int, ...], ...]:
    return tuple(tuple(row) for row in board)


def prompt_int(label: str, default: Optional[int] = None, allow_blank: bool = False) -> Optional[int]:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        value = input(f"{label}{suffix}: ").strip()
        if not value and default is not None:
            return default
        if not value and allow_blank:
            return None
        try:
            parsed = int(value)
            if parsed > 0:
                return parsed
        except ValueError:
            pass
        print("请输入正整数。")


def prompt_required_int(label: str, default: Optional[int] = None) -> int:
    value = prompt_int(label, default=default)
    if value is None:
        raise RuntimeError(f"{label} 不能为空。")
    return value


def resolve_game_size(args: argparse.Namespace) -> Tuple[int, int, Optional[int]]:
    rows = args.rows
    cols = args.cols
    mines = args.mines
    if args.preset:
        preset_rows, preset_cols, preset_mines = PRESETS[args.preset]
        rows = rows or preset_rows
        cols = cols or preset_cols
        mines = preset_mines if mines is None else mines

    if rows is None:
        rows = prompt_required_int("行数 rows")
    if cols is None:
        cols = prompt_required_int("列数 cols")
    if mines is None and not args.no_mine_prompt:
        mines = prompt_int("总雷数 mines（可留空跳过）", allow_blank=True)
    if rows is None or cols is None:
        raise RuntimeError("行数和列数不能为空。")
    return rows, cols, mines


def click_cells(
    cells: Iterable[Cell],
    region: BoardRegion,
    rows: int,
    cols: int,
    mouse: MouseController,
    button: str,
) -> None:
    for cell in sorted(cells):
        x, y = cell_center(region, rows, cols, cell)
        mouse.click(x, y, button)


def is_fresh_board(board: Sequence[Sequence[int]]) -> bool:
    return all(value == UNKNOWN for row in board for value in row)


def run(args: argparse.Namespace) -> int:
    if ImageGrab is None:
        print("缺少 Pillow。请先运行：pip install pillow", file=sys.stderr)
        return 2

    enable_dpi_awareness()
    rows, cols, mines = resolve_game_size(args)
    rng = random.Random(args.seed)

    print(f"棋盘参数：{rows} 行 x {cols} 列，雷数：{mines if mines is not None else '未知'}")
    print("即将进入框选模式，可以框选整个扫雷窗口或核心棋盘区域。")
    time.sleep(0.6)
    selected_region = select_region()
    print(
        f"已选择区域：left={selected_region.left}, top={selected_region.top}, "
        f"width={selected_region.width}, height={selected_region.height}"
    )
    print("等待选择遮罩消失...")
    time.sleep(args.after_select_delay)
    print("正在截图并定位核心棋盘区域...")
    selected_image = grab_region(selected_region)
    try:
        region = resolve_board_region(
            selected_region,
            selected_image,
            rows,
            cols,
            auto_crop=not args.no_auto_crop,
            crop_min_score=args.crop_min_score,
        )
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print("开始识别和执行。")
    recognizer = ClassicRecognizer(rows, cols)
    mouse = MouseController(dry_run=args.dry_run, click_delay=args.click_delay)
    previous_signature: Optional[Tuple[Tuple[int, ...], ...]] = None
    unchanged_rounds = 0

    for step in range(1, args.max_steps + 1):
        time.sleep(args.step_delay)
        image = grab_region(region)
        board = recognizer.recognize(image)
        signature = board_signature(board)

        if signature == previous_signature:
            unchanged_rounds += 1
        else:
            unchanged_rounds = 0
        previous_signature = signature

        unknown_count = sum(1 for row in board for value in row if value == UNKNOWN)
        flag_count = sum(1 for row in board for value in row if value == FLAG)
        open_count = rows * cols - unknown_count - flag_count
        print(
            f"\n[step {step}] open={open_count}, unknown={unknown_count}, flags={flag_count}"
        )
        if args.print_board or args.once:
            print(board_to_text(board))

        if args.once:
            return 0
        if unknown_count == 0:
            print("没有未开格，结束。")
            return 0

        if is_fresh_board(board):
            first_cell = choose_opening_cell(rows, cols, args.first_click, rng)
            if first_cell is None:
                print("全新棋盘；--first-click none 已关闭自动开局。")
                return 0
            x, y = cell_center(region, rows, cols, first_cell)
            print(f"全新棋盘，先开局点击 {first_cell}，屏幕坐标=({x}, {y})。")
            mouse.click(x, y, "left")
            if args.dry_run:
                return 0
            continue

        if unchanged_rounds >= 2 and not args.dry_run:
            print("连续多轮棋盘没有变化，可能是区域/行列数不准或游戏窗口未响应，已停止。")
            return 1

        result = solve_board(
            board,
            total_mines=mines,
            allow_guess=args.guess and not args.no_guess,
            rng=rng,
            max_component_cells=args.max_component_cells,
        )
        print(f"求解：{result.reason}")
        if not result.valid:
            print(result.reason)
            return 1

        if result.mines:
            print(f"标雷 {len(result.mines)} 个：{sorted(result.mines)}")
            click_cells(result.mines, region, rows, cols, mouse, "right")
        if result.safe:
            print(f"开安全格 {len(result.safe)} 个：{sorted(result.safe)}")
            click_cells(result.safe, region, rows, cols, mouse, "left")

        if result.mines or result.safe:
            if args.dry_run:
                return 0
            continue

        if result.guess is not None:
            probability = result.probabilities.get(result.guess)
            if probability is None:
                probability_text = "未知"
            else:
                probability_text = f"{float(probability):.2%} ({probability})"
            print(f"无零风险推理步，猜测 {result.guess}，估计为雷概率：{probability_text}")
            x, y = cell_center(region, rows, cols, result.guess)
            mouse.click(x, y, "left")
            if args.dry_run:
                return 0
            continue

        print("没有可证明安全的格子；默认不猜。要允许概率猜测请加 --guess。")
        return 0

    print("达到最大步数，已停止。")
    return 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Classic Minesweeper screen recognizer and exact-constraint solver."
    )
    parser.add_argument("--preset", choices=sorted(PRESETS), help=PRESET_HELP)
    parser.add_argument("--rows", type=int, help="棋盘行数")
    parser.add_argument("--cols", type=int, help="棋盘列数")
    parser.add_argument("--mines", type=int, help="总雷数；提供后可启用全局雷数概率")
    parser.add_argument("--no-mine-prompt", action="store_true", help="未传 --mines 时不询问总雷数")
    parser.add_argument("--guess", action="store_true", help="无零风险步时允许按最低估计雷率猜测")
    parser.add_argument("--no-guess", action="store_true", help="兼容旧参数；当前默认已经不猜")
    parser.add_argument(
        "--first-click",
        choices=("center", "corner", "random", "none"),
        default="center",
        help="全新棋盘的自动第一下策略",
    )
    parser.add_argument("--once", action="store_true", help="只识别并打印棋盘，不点击")
    parser.add_argument("--dry-run", action="store_true", help="打印计划点击，不实际移动鼠标")
    parser.add_argument("--print-board", action="store_true", help="每轮打印识别棋盘")
    parser.add_argument("--no-auto-crop", action="store_true", help="关闭自动棋盘定位，直接使用框选区域")
    parser.add_argument("--crop-min-score", type=float, default=0.45, help="自动棋盘定位的最低置信阈值")
    parser.add_argument("--max-steps", type=int, default=500, help="最大循环步数")
    parser.add_argument("--max-component-cells", type=int, default=28, help="单个边界分量精确枚举的最大未知格数")
    parser.add_argument("--click-delay", type=float, default=0.06, help="每次点击后的等待秒数")
    parser.add_argument("--step-delay", type=float, default=0.15, help="每轮截图前等待秒数")
    parser.add_argument("--after-select-delay", type=float, default=0.35, help="框选结束后等待遮罩消失的秒数")
    parser.add_argument("--seed", type=int, default=None, help="猜测时的随机种子")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\n已取消。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
