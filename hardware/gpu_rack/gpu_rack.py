# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["build123d"]
# ///
# run: uv run gpu_rack.py
from itertools import combinations
from pathlib import Path

from build123d import (
    Compound,
    Face,
    Plane,
    Pos,
    Rot,
    Wire,
    export_step,
    export_stl,
    extrude,
    mirror,
)

HERE = Path(__file__).parent
STL = HERE / "stl"
STEP = HERE / "step"

# name: (length, height, thickness) in mm
CARDS = {
    "gigabyte_gaming_oc": (331, 138, 50),
    "sapphire_pulse": (313, 133.75, 52.67),
    "asrock_phantom": (330, 140, 57.6),
}
STACK = ["asrock_phantom", "sapphire_pulse", "gigabyte_gaming_oc", "gigabyte_gaming_oc"]

BAY_X = 345  # card length direction, between posts
BAY_Y = 145  # card height direction, between rail webs
PITCH = 95
POST_X, POST_Y = 16, 22
WEB_Y = 12
ARM_X = 50  # corner piece ends here, rail starts
GUSSET = 24
REST_Z = 16  # top of ledge, cards sit here
LIP_Z = 22
LEDGE_Y = 20
LEDGE_THICK = 5
RAIL_FLOOR = 4  # slot floor in the corner piece; carries the rail
RAIL_Y0 = 2
FOOT_Z = 30
PEG_LEN = 8
FIT = 0.3  # peg/socket clearance per side
DOVE_FIT = 0.2
DOVE_NECK, DOVE_WIDE, DOVE_DEPTH = 8, 12, 6
TAIL_DEPTH = 8
TAIL_NECK_Y, TAIL_WIDE_Y = 7, 10
TIE_Z = 30
TIE_FLOOR = 2

FRAME_X = BAY_X + 2 * POST_X
FRAME_Y = BAY_Y + 2 * WEB_Y
TIE_GAP = FRAME_Y - 2 * POST_Y  # post face to post face
POST_CX = POST_X / 2


def prism(points, direction, length):
    return extrude(Face(Wire.make_polygon(points, close=True)), length, dir=direction)


def box(x0, y0, z0, x1, y1, z1):
    return prism([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)], (0, 0, 1), z1 - z0)


def prism_z(xy_points, z0, z1):
    return prism([(x, y, z0) for x, y in xy_points], (0, 0, 1), z1 - z0)


def prism_along_x(yz_points, x0, x1):
    return prism([(x0, y, z) for y, z in yz_points], (1, 0, 0), x1 - x0)


def prism_along_y(xz_points, y0, y1):
    return prism([(x, y0, z) for x, z in xz_points], (0, 1, 0), y1 - y0)


def mirror_x(m):
    return Pos(FRAME_X, 0, 0) * mirror(m, Plane.YZ)


def corner():
    body = (
        box(0, 0, 0, POST_X, POST_Y, PITCH)
        + box(0, 0, 0, ARM_X, WEB_Y, LIP_Z)
        + prism_along_y(
            [(POST_X, LIP_Z), (POST_X + GUSSET, LIP_Z), (POST_X, LIP_Z + GUSSET)], 0, WEB_Y
        )
        + box(4, 3, PITCH, 12, 9, PITCH + PEG_LEN)
    )
    neck = DOVE_NECK / 2 + DOVE_FIT
    wide = DOVE_WIDE / 2 + DOVE_FIT
    tie_slot = prism_z(
        [
            (POST_CX - wide, POST_Y - DOVE_DEPTH),
            (POST_CX + wide, POST_Y - DOVE_DEPTH),
            (POST_CX + neck, POST_Y + 0.01),
            (POST_CX - neck, POST_Y + 0.01),
        ],
        TIE_FLOOR,
        PITCH + 0.01,
    )
    tip = ARM_X - TAIL_DEPTH - DOVE_FIT
    rail_slot = prism_z(
        [
            (tip, RAIL_Y0 - DOVE_FIT),
            (ARM_X + 0.01, RAIL_Y0 - DOVE_FIT),
            (ARM_X + 0.01, TAIL_NECK_Y + DOVE_FIT),
            (tip, TAIL_WIDE_Y + DOVE_FIT),
        ],
        RAIL_FLOOR,
        LIP_Z + 0.01,
    )
    socket = box(4 - FIT, 3 - FIT, -0.01, 12 + FIT, 9 + FIT, PEG_LEN + 1)
    return body - tie_slot - rail_slot - socket


def rail():
    x0, x1 = ARM_X + 0.2, FRAME_X - ARM_X - 0.2
    tail = prism_z(
        [
            (ARM_X - TAIL_DEPTH, RAIL_Y0),
            (x0 + 0.01, RAIL_Y0),
            (x0 + 0.01, TAIL_NECK_Y),
            (ARM_X - TAIL_DEPTH, TAIL_WIDE_Y),
        ],
        RAIL_FLOOR,
        LIP_Z,
    )
    return (
        box(x0, RAIL_Y0, RAIL_FLOOR, x1, WEB_Y, LIP_Z)
        + box(x0, WEB_Y, REST_Z - LEDGE_THICK, x1, WEB_Y + LEDGE_Y, REST_Z)
        + prism_along_x(
            [(WEB_Y, 5), (WEB_Y + 12, REST_Z - LEDGE_THICK), (WEB_Y, REST_Z - LEDGE_THICK)],
            x0,
            x1,
        )
        + tail
        + mirror_x(tail)
    )


def tie():
    # outline runs through both dovetails; extruded upright so flanks print accurately
    neck, wide = DOVE_NECK / 2, DOVE_WIDE / 2
    body = 5  # half thickness between the posts
    end = TIE_GAP / 2
    tip = end + DOVE_DEPTH - 0.3
    return prism_z(
        [
            (-wide, -tip),
            (wide, -tip),
            (neck, -end),
            (body, -end),
            (body, end),
            (neck, end),
            (wide, tip),
            (-wide, tip),
            (-neck, end),
            (-body, end),
            (-body, -end),
            (-neck, -end),
        ],
        0,
        TIE_Z,
    )


def foot():
    return (
        box(0, 0, 0, POST_X, POST_Y, FOOT_Z)
        + box(0, -40, 0, POST_X, POST_Y, 6)
        + box(4, 3, FOOT_Z, 12, 9, FOOT_Z + PEG_LEN)
    )


def assembly(corner_m, rail_m, tie_m, foot_m):
    sides = (lambda m: m, lambda m: Pos(FRAME_X, FRAME_Y, 0) * Rot(0, 0, 180) * m)
    corner_r = mirror_x(corner_m)
    foot_r = mirror_x(foot_m)
    parts = []
    for side in sides:
        parts += [side(foot_m), side(foot_r)]
    for level in range(len(STACK)):
        z = FOOT_Z + level * PITCH
        for side in sides:
            parts += [Pos(0, 0, z) * side(m) for m in (corner_m, corner_r, rail_m)]
        for cx in (POST_CX, FRAME_X - POST_CX):
            parts.append(Pos(cx, FRAME_Y / 2, z + TIE_FLOOR) * tie_m)
    return parts


def card_boxes():
    boxes = []
    for level, name in enumerate(STACK):
        length, height, thick = CARDS[name]
        x0 = (FRAME_X - length) / 2
        y0 = (FRAME_Y - height) / 2
        z0 = FOOT_Z + level * PITCH + REST_Z
        boxes.append(box(x0, y0, z0, x0 + length, y0 + height, z0 + thick))
    return boxes


def overlap(a, b):
    ba, bb = a.bounding_box(), b.bounding_box()
    if any(lo >= hi for lo, hi in zip([*ba.min, *bb.min], [*bb.max, *ba.max])):
        return 0
    common = a & b
    return common.volume if common else 0


def check(corner_m, rail_m, tie_m, foot_m):
    for name, (length, height, thick) in CARDS.items():
        assert length < BAY_X, name  # nosec B101
        assert height < BAY_Y, name  # nosec B101
        worst_overlap = LEDGE_Y - (BAY_Y - height)
        assert worst_overlap > 5, f"{name} can slide off ledge: {worst_overlap}"  # nosec B101
        assert PITCH - thick - LEDGE_THICK > 25, f"{name} intake gap"  # nosec B101
    for name, m in (("corner", corner_m), ("rail", rail_m), ("tie", tie_m), ("foot", foot_m)):
        assert m.is_valid, name  # nosec B101
        assert len(m.solids()) == 1, f"{name} has loose pieces"  # nosec B101
        size = m.bounding_box().size
        assert max(size.X, size.Y) < 340, f"{name} too big for the bed"  # nosec B101
    parts = assembly(corner_m, rail_m, tie_m, foot_m)
    for card in card_boxes():
        for part in parts:
            assert overlap(card, part) < 1e-6, "card collides with rack"  # nosec B101
    for a, b in combinations(parts, 2):
        assert overlap(a, b) < 1e-6, "rack parts collide"  # nosec B101
    return parts


if __name__ == "__main__":
    corner_m, rail_m, tie_m, foot_m = corner(), rail(), tie(), foot()
    parts = check(corner_m, rail_m, tie_m, foot_m)
    STL.mkdir(exist_ok=True)
    STEP.mkdir(exist_ok=True)
    for name, part, count in (
        ("corner_left", corner_m, 8),
        ("corner_right", mirror_x(corner_m), 8),
        ("rail", Rot(90, 0, 0) * rail_m, 8),  # web on the bed, no supports
        ("tie", tie_m, 8),
        ("foot", foot_m, 4),
    ):
        export_stl(part, STL / f"{name}_print_x{count}.stl")
        export_step(part, STEP / f"{name}_x{count}.step")
        size = part.bounding_box().size
        print(name, f"x{count}", [round(v, 1) for v in size], f"{part.volume / 1000:.0f} cm3")
    whole = Compound(children=parts)
    export_stl(whole, STL / "assembly_preview_only.stl")
    export_step(whole, STEP / "assembly.step")
    print("overall", [round(v, 1) for v in whole.bounding_box().size])
