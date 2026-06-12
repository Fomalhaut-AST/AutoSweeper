import random
from pathlib import Path
from types import SimpleNamespace

from autosweeper import (
    UNKNOWN,
    BoardRegion,
    choose_opening_cell,
    detect_board_region,
    deterministic_closure,
    is_fresh_board,
    looks_like_grid_region,
    resolve_game_size,
    solve_board,
)

try:
    from PIL import Image
except Exception:
    Image = None


def solve(board, mines=None, guess=False):
    return solve_board(board, mines, guess, random.Random(0))


def args(**overrides):
    values = {
        "preset": None,
        "rows": None,
        "cols": None,
        "mines": None,
        "no_mine_prompt": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_presets_cover_beginner_intermediate_and_expert_aliases():
    assert resolve_game_size(args(preset="basic")) == (9, 9, 10)
    assert resolve_game_size(args(preset="beginner")) == (9, 9, 10)
    assert resolve_game_size(args(preset="medium")) == (16, 16, 40)
    assert resolve_game_size(args(preset="intermediate")) == (16, 16, 40)
    assert resolve_game_size(args(preset="hard")) == (16, 30, 99)
    assert resolve_game_size(args(preset="expert")) == (16, 30, 99)


def test_basic_zero_constraint_marks_all_neighbors_safe():
    board = [
        [0, UNKNOWN],
        [UNKNOWN, UNKNOWN],
    ]

    result = solve(board)

    assert result.valid
    assert result.safe == {(0, 1), (1, 0), (1, 1)}
    assert result.mines == set()
    assert result.guess is None


def test_basic_full_constraint_marks_all_neighbors_mines():
    board = [
        [3, UNKNOWN],
        [UNKNOWN, UNKNOWN],
    ]

    result = solve(board)

    assert result.valid
    assert result.safe == set()
    assert result.mines == {(0, 1), (1, 0), (1, 1)}
    assert result.guess is None


def test_subset_difference_finds_safe_cell_before_enumeration():
    a = (0, 0)
    b = (0, 1)
    c = (0, 2)

    result = deterministic_closure(
        [
            (frozenset({a, b}), 1),
            (frozenset({a, b, c}), 1),
        ],
        {a, b, c},
        flags=0,
        total_mines=None,
    )

    assert result.valid
    assert result.safe == {c}
    assert result.mines == set()


def test_total_mine_count_can_mark_all_unknown_mines():
    board = [[UNKNOWN, UNKNOWN, UNKNOWN]]

    result = solve(board, mines=3)

    assert result.valid
    assert result.safe == set()
    assert result.mines == {(0, 0), (0, 1), (0, 2)}
    assert result.guess is None


def test_default_does_not_guess_when_only_probability_exists():
    board = [[UNKNOWN, 1, UNKNOWN]]

    result = solve(board)

    assert result.valid
    assert result.safe == set()
    assert result.mines == set()
    assert result.guess is None


def test_guess_is_opt_in():
    board = [[UNKNOWN, 1, UNKNOWN]]

    result = solve(board, guess=True)

    assert result.valid
    assert result.safe == set()
    assert result.mines == set()
    assert result.guess in {(0, 0), (0, 2)}


def test_total_mine_count_does_not_force_one_giant_component_when_no_action():
    board = [
        [UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN],
        [UNKNOWN, 1, UNKNOWN, UNKNOWN],
        [UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN],
    ]

    result = solve(board, mines=3)

    assert result.valid
    assert "超过精确枚举上限" not in result.reason


def test_large_constraint_closure_returns_quickly_on_realistic_board():
    board_text = """
    # # # # # # # # 1 1 . 1 1 # # # # # # # # # # # # # # # # #
    # # # # # # # # F 2 . 1 F 3 F # # # # # # # # # # # # # # #
    # # # # # # # # F 2 . 1 1 3 F F 2 F F # # # # # # # # # # #
    # # # # # # # # 3 2 1 . . 1 2 2 2 2 3 # # # # # # # # # # #
    # # # # # # # # 2 F 1 . . . . . . . 1 # # # # # # # # # # #
    # # # # # # # # # 3 3 1 . . . . . 1 2 # # # # # # # # # # #
    # # # # # # # # # F F 1 . . . . . 1 F # # # # # # # # # # #
    # # # # # # # # # # 4 2 1 . . . . 1 3 # # # # # # # # # # #
    # # # # # # # # # # 3 F 2 1 1 . . . 2 # # # # # # # # # # #
    # # # # # # # # # # # 2 2 F 1 . 1 2 4 # # # # # # # # # # #
    # # # # # # # # # # # # # 2 2 . 2 F F # # # # # # # # # # #
    # # # # # # # # # # # # # F 2 2 3 F # # # # # # # # # # # #
    # # # # # # # # # # # # # 3 F 3 F 3 # # # # # # # # # # # #
    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    """
    mapping = {"#": UNKNOWN, "F": -2, ".": 0}
    board = [
        [mapping.get(token, int(token)) if token not in mapping else mapping[token] for token in line.split()]
        for line in board_text.strip().splitlines()
    ]

    result = solve(board, mines=99)

    assert result.valid


def test_opening_click_defaults_to_centerish_cell():
    assert choose_opening_cell(9, 9, "center", random.Random(0)) == (4, 4)
    assert choose_opening_cell(16, 30, "center", random.Random(0)) == (7, 14)


def test_opening_click_can_be_disabled():
    assert choose_opening_cell(9, 9, "none", random.Random(0)) is None


def test_fresh_board_detection():
    assert is_fresh_board([[UNKNOWN, UNKNOWN], [UNKNOWN, UNKNOWN]])
    assert not is_fresh_board([[UNKNOWN, 0], [UNKNOWN, UNKNOWN]])
    assert not is_fresh_board([[UNKNOWN, -2], [UNKNOWN, UNKNOWN]])


def test_grid_region_aspect_fallback():
    assert looks_like_grid_region(BoardRegion(0, 0, 300, 160), 16, 30)
    assert not looks_like_grid_region(BoardRegion(0, 0, 300, 300), 16, 30)


def test_detect_board_region_from_full_reference_image():
    if Image is None:
        return
    image_path = Path(__file__).with_name("fig.png")
    image = Image.open(image_path).convert("RGB")

    region = detect_board_region(image, 16, 30)

    assert region is not None
    assert abs(region.left - 19) <= 4
    assert abs(region.top - 95) <= 4
    assert abs(region.width - 1171) <= 8
    assert abs(region.height - 625) <= 8


def test_detect_board_region_from_loose_reference_selection():
    if Image is None:
        return
    image_path = Path(__file__).with_name("fig.png")
    image = Image.open(image_path).convert("RGB")
    offset = (73, 51)
    canvas = Image.new("RGB", (image.width + 180, image.height + 140), (240, 240, 240))
    canvas.paste(image, offset)

    region = detect_board_region(canvas, 16, 30)

    assert region is not None
    assert abs(region.left - (offset[0] + 19)) <= 6
    assert abs(region.top - (offset[1] + 95)) <= 6
    assert abs(region.width - 1171) <= 8
    assert abs(region.height - 625) <= 8
