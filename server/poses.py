"""Small, curated skeleton library. Metres; +Y up, +Z toward a front camera.

Indices follow MediaPipe's anatomical left/right landmark convention.
"""
from itertools import combinations
import math
import random

JOINTS = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]
EDGES = [(11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
         (11, 23), (12, 24), (23, 24), (23, 25), (25, 27), (24, 26), (26, 28)]
LIMBS = [(11, 13), (13, 15), (12, 14), (14, 16),
         (23, 25), (25, 27), (24, 26), (26, 28)]
ANGLES = [(11, 13, 15), (12, 14, 16), (23, 25, 27), (24, 26, 28),
          (13, 11, 23), (14, 12, 24), (11, 23, 25), (12, 24, 26)]


# Every pose uses the same proportions. Author wrist positions and bend planes,
# then solve the two limb segments; do not stretch limbs to reach a target.
UPPER_ARM, FOREARM = .29, .28
THIGH, SHIN = .45, .44


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def scale(vector, amount):
    return tuple(x * amount for x in vector)


def unit(vector):
    length = math.sqrt(sum(x * x for x in vector))
    if length < 1e-8:
        raise ValueError("A limb direction must be nonzero")
    return scale(vector, 1 / length)


def rotate(vector, yaw=0, pitch=0, roll=0):
    """Local anatomical coordinates: +X left, +Y up, +Z forward."""
    x, y, z = vector
    a, b, c = map(math.radians, (yaw, pitch, roll))
    x, y = math.cos(c) * x - math.sin(c) * y, math.sin(c) * x + math.cos(c) * y
    y, z = math.cos(b) * y - math.sin(b) * z, math.sin(b) * y + math.cos(b) * z
    return (math.cos(a) * x + math.sin(a) * z, y, -math.sin(a) * x + math.cos(a) * z)


def bend_joint(root, end, lengths, pole):
    """Two-bone IK; the pole explicitly chooses the elbow/knee bending side."""
    delta = tuple(b - a for a, b in zip(root, end))
    distance = math.dist(root, end)
    first, second = lengths
    if not abs(first - second) < distance < first + second:
        raise ValueError("Authored limb target is outside its reach")
    direction = unit(delta)
    along = (first * first - second * second + distance * distance) / (2 * distance)
    projection = sum(a * b for a, b in zip(pole, direction))
    perpendicular = unit(add(pole, scale(direction, -projection)))
    return add(root, add(scale(direction, along), scale(perpendicular, math.sqrt(max(0, first * first - along * along)))))


def body_pose(pose_id, name, left, right, *, hips=(0, .91, 0),
              feet=((.25, .05, .02), (-.25, .05, -.02)),
              turn=0, pelvis_turn=0, side_lean=0, forward_lean=0, lifted=None):
    """Curated full-body pose, never a randomly distorted human skeleton.

    Arm inputs are (wrist offset from shoulder, elbow pole), in torso space.
    Lifted-leg inputs are (side, thigh direction, shin direction). All other
    ankles stay planted and their knees bend toward anatomical forward.
    """
    points = [[0.0, 0.0, 0.0] for _ in range(33)]
    torso = lambda v: rotate(v, turn, forward_lean, -side_lean)
    shoulder_center = add(hips, torso((0, .51, 0)))
    points[0] = list(add(shoulder_center, torso((0, .28, .02))))
    for side, arm, foot, shoulder, elbow, wrist, hip, knee, ankle in (
        (1, left, feet[0], 11, 13, 15, 23, 25, 27),
        (-1, right, feet[1], 12, 14, 16, 24, 26, 28),
    ):
        points[shoulder] = list(add(shoulder_center, torso((side * .23, 0, 0))))
        points[wrist] = list(add(points[shoulder], torso(arm[0])))
        points[elbow] = list(bend_joint(points[shoulder], points[wrist], (UPPER_ARM, FOREARM), torso(arm[1])))
        points[hip] = list(add(hips, rotate((side * .16, 0, 0), pelvis_turn)))
        if lifted is not None and lifted[0] == side:
            points[knee] = list(add(points[hip], scale(unit(rotate(lifted[1], pelvis_turn)), THIGH)))
            points[ankle] = list(add(points[knee], scale(unit(rotate(lifted[2], pelvis_turn)), SHIN)))
        else:
            points[ankle] = list(foot)
            points[knee] = list(bend_joint(points[hip], foot, (THIGH, SHIN), rotate((0, 0, 1), pelvis_turn)))
    return {"id": pose_id, "name": name, "points": points}


# One unweighted pool. Only 3 of 24 poses lift a foot; no difficulty tiers.
# Stances use moderate steps, shallow bends, and no floor contact or jumps.
POSES = [
    body_pose("welcome", "ひらいて、こんにちは",
        ((.13, .49, .04), (.8, .3, .3)), ((-.54, -.04, .08), (-.7, -.4, .2)),
        side_lean=6, feet=((.28, .05, .12), (-.25, .05, -.12))),
    body_pose("airplane", "ななめ飛行のひこうき",
        ((.54, .04, -.04), (.7, -.5, .3)), ((-.53, -.06, .10), (-.7, -.4, .3)),
        hips=(0, .88, 0), side_lean=10, forward_lean=12,
        feet=((.30, .05, -.12), (-.28, .05, .16))),
    body_pose("goal", "からだでY！",
        ((.26, .48, .04), (.8, .3, .3)), ((-.26, .48, .04), (-.8, .3, .3)),
        feet=((.30, .05, .12), (-.30, .05, -.12))),
    body_pose("diagonal", "からだでK！",
        ((.34, .39, .07), (.8, .2, .4)), ((-.45, -.24, .10), (-.7, -.6, .2)),
        hips=(-.03, .88, 0), side_lean=-6,
        feet=((.34, .05, .24), (-.23, .05, -.10))),
    body_pose("crossed_arms", "胸の前でクロス",
        ((-.37, .06, .26), (.8, -.7, .2)), ((.34, -.28, .23), (-.8, -.7, .2)),
        hips=(0, .88, 0), turn=-12,
        feet=((.25, .05, .18), (-.28, .05, -.18))),
    body_pose("boxing", "ボクシングのかまえ",
        ((-.08, .02, .49), (.8, -.7, .1)), ((.06, -.15, .31), (-.8, -.8, .1)),
        hips=(0, .87, 0), turn=22, pelvis_turn=8, forward_lean=5,
        feet=((.25, .05, .24), (-.27, .05, -.24))),
    body_pose("archery", "弓を引くポーズ",
        ((.55, .04, .04), (.5, -.5, .2)), ((.08, .12, .25), (-1, .25, -.2)),
        hips=(0, .88, 0), turn=28, pelvis_turn=8,
        feet=((.30, .05, .18), (-.28, .05, -.16))),
    body_pose("superhero", "地上のスーパーヒーロー",
        ((.12, .22, .49), (.8, -.2, .5)), ((-.18, -.43, -.20), (-.8, -.5, -.3)),
        hips=(0, .88, 0), forward_lean=14, turn=-12,
        feet=((.25, .05, .22), (-.27, .05, -.18))),
    body_pose("running", "走り出す一歩",
        ((-.02, -.05, .39), (.8, -.8, .1)), ((-.12, -.28, -.35), (-.8, -.8, -.2)),
        hips=(0, .85, 0), turn=-18, pelvis_turn=8, forward_lean=12,
        feet=((.24, .05, -.28), (-.24, .05, .28))),
    body_pose("marching", "ひざと反対の手を上げる",
        ((.45, -.22, .12), (.8, -.5, .3)), ((-.12, .51, .04), (-.8, .3, .3)),
        hips=(-.10, .90, 0), side_lean=-5,
        feet=((.25, .05, 0), (-.23, .05, -.05)),
        lifted=(1, (.16, -.38, .88), (.12, -.97, -.20))),
    body_pose("knee_compass", "ひざ上げコンパス",
        ((.43, .22, .10), (.8, .2, .3)), ((.04, -.32, .31), (-.8, -.7, .1)),
        hips=(.10, .90, 0), side_lean=5, turn=12,
        feet=((.23, .05, -.05), (-.25, .05, 0)),
        lifted=(-1, (-.25, -.42, .86), (-.10, -.97, -.20))),
    body_pose("light_squat", "小さくしゃがんで前ならえ",
        ((.10, -.03, .51), (.8, -.6, .1)), ((-.12, -.19, .49), (-.8, -.6, .1)),
        hips=(0, .81, -.03), forward_lean=12,
        feet=((.29, .05, .06), (-.29, .05, .06))),
    body_pose("light_lunge", "一歩前で手を上げる",
        ((.14, .50, .03), (.8, .3, .3)), ((-.36, -.32, .14), (-.8, -.6, .2)),
        hips=(0, .85, .02), turn=-12, forward_lean=6,
        feet=((.24, .05, .31), (-.25, .05, -.27))),
    body_pose("side_lean", "横に傾く三日月",
        ((.08, .52, .08), (.8, .3, .2)), ((-.22, -.37, .13), (-.8, -.7, .2)),
        hips=(-.03, .88, 0), side_lean=14,
        feet=((.30, .05, .12), (-.26, .05, -.12))),
    body_pose("forward_lean", "前をのぞくロボット",
        ((.28, -.23, .30), (.8, -.7, .1)), ((-.26, -.10, .40), (-.8, -.7, .1)),
        hips=(0, .85, -.08), forward_lean=22,
        feet=((.26, .05, .17), (-.28, .05, -.16))),
    body_pose("twisted_reach", "ひねって、あっちとこっち",
        ((.45, .20, .18), (.8, .1, .3)), ((-.18, -.18, .46), (-.8, -.7, .1)),
        hips=(0, .88, 0), turn=32, pelvis_turn=-2, side_lean=-5,
        feet=((.28, .05, -.15), (-.29, .05, .16))),
    body_pose("cross_body", "ひじを反対のひざへ",
        ((.32, .32, .12), (.8, .2, .3)), ((.32, -.36, .14), (.8, -1, .5)),
        hips=(0, .81, -.04), turn=20, forward_lean=18, side_lean=7,
        feet=((.24, .05, .24), (-.28, .05, -.14))),
    body_pose("skiing", "ゆるやかスキー",
        ((.18, -.37, -.30), (.8, -.8, .1)), ((-.18, -.39, -.22), (-.8, -.8, .1)),
        hips=(0, .82, -.08), forward_lean=20,
        feet=((.27, .05, .06), (-.27, .05, .20))),
    body_pose("dance_groove", "ひねってダンス",
        ((.24, .32, .15), (.8, .2, .3)), ((-.38, -.24, .14), (-.8, -.7, .2)),
        hips=(.03, .85, 0), turn=-28, pelvis_turn=-4, side_lean=-9,
        feet=((.28, .05, -.21), (-.30, .05, .22))),
    body_pose("disco", "ディスコの決めポーズ",
        ((.37, .36, .12), (.8, .2, .3)), ((.16, -.44, .17), (-.8, -.7, .1)),
        hips=(.04, .87, 0), side_lean=-12, turn=12,
        feet=((.25, .05, -.16), (-.33, .05, .19))),
    body_pose("windmill", "風車のポーズ",
        ((.45, -.12, -.28), (.8, -.5, -.3)), ((-.18, .42, .28), (-.8, .2, .3)),
        hips=(0, .86, 0), turn=18, side_lean=9, forward_lean=10,
        feet=((.29, .05, .20), (-.28, .05, -.20))),
    body_pose("backward_reach", "うしろへ手を伸ばす",
        ((.27, .33, .23), (.8, .2, .3)), ((-.22, -.36, -.33), (-.8, -.7, -.1)),
        hips=(0, .88, .03), turn=-24, forward_lean=-6,
        feet=((.26, .05, .20), (-.29, .05, -.15))),
    body_pose("warrior", "前へ進む戦士",
        ((.36, .06, .40), (.8, -.4, .3)), ((-.36, -.12, -.36), (-.8, -.5, -.2)),
        hips=(0, .85, .02), turn=24, pelvis_turn=6, forward_lean=16,
        feet=((.26, .05, .30), (-.28, .05, -.26))),
    body_pose("tree_four", "フラミンゴの4",
        ((.13, .49, .05), (.8, .3, .3)), ((-.49, -.10, .13), (-.8, -.4, .2)),
        hips=(-.10, .90, 0), side_lean=-5,
        feet=((.25, .05, 0), (-.23, .05, -.02)),
        lifted=(1, (.60, -.75, .28), (-.60, -.65, .47))),
]


VIEW_TARGET_HEIGHT = .95
VIEW_DISTANCE = 4.5
MIN_CAMERA_HEIGHT = .50
MIN_VIEW_ELEVATION = math.degrees(math.asin((MIN_CAMERA_HEIGHT - VIEW_TARGET_HEIGHT) / VIEW_DISTANCE))


def project(points, azimuth, elevation):
    a, e = math.radians(azimuth), math.radians(elevation)
    right = (math.cos(a), 0, -math.sin(a))
    up = (-math.sin(a) * math.sin(e), math.cos(e), -math.cos(a) * math.sin(e))
    outward = (math.sin(a) * math.cos(e), math.sin(e), math.cos(a) * math.cos(e))
    result = []
    for x, y, z in points:
        p = (x, y - VIEW_TARGET_HEIGHT, z)
        depth = VIEW_DISTANCE - sum(v * w for v, w in zip(p, outward))
        result.append([.5 + 1.6 * sum(v * w for v, w in zip(p, right)) / depth,
                       .5 - 1.6 * sum(v * w for v, w in zip(p, up)) / depth, 1.0])
    return result


def make_view(pose, settings, rng=random):
    # Camera height = target height + orbit distance * sin(elevation).
    # Sample the intersection directly so a narrow valid range cannot be
    # missed by repeatedly drawing candidates below the floor-height limit.
    elevation_min = max(settings.elevation_min, MIN_VIEW_ELEVATION)
    if elevation_min > settings.elevation_max:
        raise ValueError("この仰角範囲ではカメラの高さが床から50cm未満になります。仰角の最大値を上げてください。")
    for _ in range(300):
        a = rng.uniform(settings.azimuth_min, settings.azimuth_max)
        e = rng.uniform(elevation_min, settings.elevation_max)
        points = project(pose["points"], a, e)
        height = max(points[i][1] for i in JOINTS) - min(points[i][1] for i in JOINTS)
        if height <= 1e-6:
            continue
        # Check every displayed joint pair, including non-connected and non-mirrored joints.
        if any(math.dist(points[i][:2], points[j][:2]) / height < settings.min_keypoint_separation
               for i, j in combinations(JOINTS, 2)):
            continue
        if any(math.dist(points[i][:2], points[j][:2]) / height < settings.min_limb_ratio
               for i, j in LIMBS):
            continue
        if any(math.dist(points[i][:2], points[i + 1][:2]) / height < settings.min_side_separation
               for i in (11, 13, 15, 23, 25, 27)):
            continue
        return {"azimuth": a, "elevation": e, "target": points}
    raise ValueError("この視点条件では問題を作れません。角度範囲を広げるか、関節点の最小間隔・手足の長さの条件を緩めてください。")
