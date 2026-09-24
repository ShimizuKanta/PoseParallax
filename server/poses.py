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


def skeleton(arms):
    points = [[0.0, 0.0, 0.0] for _ in range(33)]
    coords = {0: (0, 1.72, 0.02), 11: (.23, 1.45, 0), 12: (-.23, 1.45, 0),
              23: (.16, .94, 0), 24: (-.16, .94, 0), 25: (.22, .49, .02),
              26: (-.22, .49, .02), 27: (.3, .05, 0), 28: (-.3, .05, 0), **arms}
    for index, xyz in coords.items():
        points[index] = list(xyz)
    return points


POSES = [
    {"id": "welcome", "name": "ひらいて、こんにちは", "points": skeleton({
        13: (.49, 1.5, .03), 15: (.55, 1.79, .04),
        14: (-.52, 1.4, .05), 16: (-.8, 1.42, .08)})},
    {"id": "airplane", "name": "ひこうき", "points": skeleton({
        13: (.51, 1.43, .03), 15: (.8, 1.4, .08),
        14: (-.51, 1.43, -.04), 16: (-.8, 1.4, -.1)})},
    {"id": "goal", "name": "ゴール！", "points": skeleton({
        13: (.5, 1.47, .02), 15: (.51, 1.77, .06),
        14: (-.5, 1.47, .02), 16: (-.51, 1.77, .06)})},
    {"id": "diagonal", "name": "ななめのサイン", "points": skeleton({
        13: (.43, 1.65, .02), 15: (.62, 1.87, .08),
        14: (-.43, 1.24, .02), 16: (-.63, 1.03, .08)})},
]


def project(points, azimuth, elevation):
    a, e = math.radians(azimuth), math.radians(elevation)
    right = (math.cos(a), 0, -math.sin(a))
    up = (-math.sin(a) * math.sin(e), math.cos(e), -math.cos(a) * math.sin(e))
    outward = (math.sin(a) * math.cos(e), math.sin(e), math.cos(a) * math.cos(e))
    result = []
    for x, y, z in points:
        p = (x, y - .95, z)
        depth = 4.5 - sum(v * w for v, w in zip(p, outward))
        result.append([.5 + 1.6 * sum(v * w for v, w in zip(p, right)) / depth,
                       .5 - 1.6 * sum(v * w for v, w in zip(p, up)) / depth, 1.0])
    return result


def make_view(pose, settings, rng=random):
    for _ in range(300):
        a = rng.uniform(settings.azimuth_min, settings.azimuth_max)
        e = rng.uniform(settings.elevation_min, settings.elevation_max)
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
