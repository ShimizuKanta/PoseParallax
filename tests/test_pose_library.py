"""Geometry and usability guards for the authored full-body library."""
from itertools import combinations
import json
import math
from pathlib import Path
import random

import pytest

from server.poses import (POSES, JOINTS, LIMBS, UPPER_ARM, FOREARM, THIGH, SHIN,
                          body_pose, make_view)
from server.models import Settings


def joint_angle(points, root, joint, end):
    a = [x-y for x, y in zip(points[root], points[joint])]
    b = [x-y for x, y in zip(points[end], points[joint])]
    cosine = sum(x*y for x, y in zip(a,b)) / (math.dist(points[root], points[joint]) * math.dist(points[end], points[joint]))
    return math.degrees(math.acos(max(-1, min(1, cosine))))


@pytest.mark.parametrize('pose', POSES, ids=lambda p: p['id'])
def test_limb_proportions_and_grounded_stance(pose):
    points = pose['points']
    assert len(points) == 33
    assert all(math.isfinite(v) for p in points for v in p)
    for (a,b), length in zip(LIMBS, [UPPER_ARM, FOREARM] * 2 + [THIGH, SHIN] * 2):
        assert math.dist(points[a], points[b]) == pytest.approx(length)
    assert math.dist(points[11], points[12]) == pytest.approx(.46)
    assert math.dist(points[23], points[24]) == pytest.approx(.32)
    for shoulder, elbow, wrist in [(11,13,15),(12,14,16)]:
        assert 45 <= joint_angle(points, shoulder, elbow, wrist) < 180
    shoulder_center = [(points[11][j] + points[12][j]) / 2 for j in range(3)]
    hip_center = [(points[23][j] + points[24][j]) / 2 for j in range(3)]
    spine = [a-b for a,b in zip(shoulder_center,hip_center)]
    assert math.degrees(math.acos(spine[1] / math.sqrt(sum(v*v for v in spine)))) <= 25
    assert min(points[27][1], points[28][1]) == pytest.approx(.05)  # Never both feet airborne.
    assert max(points[27][1], points[28][1]) <= .36
    assert abs(points[27][0] - points[28][0]) <= .70
    assert abs(points[27][2] - points[28][2]) <= .60
    for hip, knee, ankle in [(23,25,27),(24,26,28)]:
        assert points[knee][1] > points[ankle][1] > 0
        assert points[hip][1] > points[knee][1]
        flexion = 180 - joint_angle(points, hip, knee, ankle)
        if points[ankle][1] < .051:
            assert flexion <= 65  # Loaded knees only use shallow bends.
            # The knee sits in front of the straight hip-to-ankle line, not behind it.
            ratio = (points[knee][1] - points[hip][1]) / (points[ankle][1] - points[hip][1])
            straight_z = points[hip][2] + ratio * (points[ankle][2] - points[hip][2])
            assert points[knee][2] > straight_z
        else:
            assert flexion <= 90


def test_pool_is_varied_with_rare_balance_and_english_names():
    assert len(POSES) >= 20
    assert len({p['id'] for p in POSES}) == len(POSES)
    assert len({p['name'] for p in POSES}) == len(POSES)
    lifted = [p for p in POSES if max(p['points'][27][1], p['points'][28][1]) > .051]
    assert 0 < len(lifted) / len(POSES) <= .15
    depth_poses = [p for p in POSES if max(p['points'][i][2] for i in JOINTS) - min(p['points'][i][2] for i in JOINTS) >= .4]
    assert len(depth_poses) >= len(POSES) // 2
    twisted = [p for p in POSES if abs(p['points'][11][2] - p['points'][12][2]) >= .15]
    assert len(twisted) >= len(POSES) // 3
    english = json.loads((Path(__file__).parents[1] / 'frontend/src/locales/en.json').read_text(encoding='utf-8'))
    assert all(p['name'] in english for p in POSES)
    # Ignore position offsets when checking for near-duplicate skeletal shapes.
    def centered(pose):
        center = [(pose['points'][23][j] + pose['points'][24][j]) / 2 for j in range(3)]
        return [[pose['points'][i][j] - center[j] for j in range(3)] for i in JOINTS]
    for a,b in combinations(POSES, 2):
        rms = math.sqrt(sum(math.dist(x,y)**2 for x,y in zip(centered(a), centered(b))) / len(JOINTS))
        assert rms > .12, (a['id'], b['id'])


@pytest.mark.parametrize('pose', POSES, ids=lambda p: p['id'])
def test_default_views_remain_attainable_for_all_observers(pose):
    rng = random.Random(5921)
    for _ in range(49):
        view = make_view(pose, Settings(), rng)
        assert all(0 < view['target'][i][0] < 1 and 0 < view['target'][i][1] < 1 for i in JOINTS)


def test_authoring_rejects_unreachable_limb_instead_of_stretching():
    with pytest.raises(ValueError, match='outside its reach'):
        body_pose('invalid', 'Invalid', ((2,0,0),(0,1,0)), ((-.5,0,0),(0,1,0)))
