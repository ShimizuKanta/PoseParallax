from itertools import combinations
import math
import random

import pytest
from pydantic import ValidationError

from server.game import Game
from server.models import Settings
from server.poses import JOINTS, POSES, make_view
from server.storage import Store


def minimum_spacing(points):
    height = max(points[i][1] for i in JOINTS) - min(points[i][1] for i in JOINTS)
    return min(math.dist(points[a][:2], points[b][:2]) / height for a, b in combinations(JOINTS, 2))


@pytest.mark.parametrize("pose", POSES, ids=lambda pose: pose["id"])
def test_every_displayed_joint_pair_meets_configured_spacing(pose):
    settings = Settings(min_keypoint_separation=.1)
    for seed in range(12):
        view = make_view(pose, settings, random.Random(seed))
        assert minimum_spacing(view["target"]) >= .1


def grid_points(nearby=False):
    points = [[0.0, 0.0, 1.0] for _ in range(33)]
    for n, i in enumerate(JOINTS):
        points[i] = [float(n % 4), float(n // 4), 1.0]
    if nearby:
        # Left wrist near right shoulder: neither a limb edge nor a mirrored pair.
        points[15] = [points[12][0] + .01, points[12][1] + .01, 1.0]
    return points


def test_non_adjacent_joint_proximity_causes_view_regeneration(monkeypatch):
    bad, good = grid_points(True), grid_points()
    candidates = iter([bad, good])
    monkeypatch.setattr("server.poses.project", lambda *args: next(candidates))
    result = make_view(POSES[0], Settings(), random.Random(0))
    assert result["target"] == good


def test_zero_disables_additional_spacing_condition(monkeypatch):
    points = grid_points(True)
    monkeypatch.setattr("server.poses.project", lambda *args: points)
    result = make_view(POSES[0], Settings(min_keypoint_separation=0), random.Random(0))
    assert result["target"] == points


def test_unachievable_spacing_is_not_silently_relaxed(monkeypatch):
    monkeypatch.setattr("server.poses.project", lambda *args: grid_points(True))
    with pytest.raises(ValueError, match="最小間隔"):
        make_view(POSES[0], Settings(min_keypoint_separation=.1), random.Random(0))


def test_old_defaults_migrate_and_new_distance_persists(tmp_path):
    store = Store(tmp_path / "settings.sqlite3")
    try:
        store.put("defaults", {"min_side_separation": .05})
        game = Game(store)
        assert game.defaults.min_keypoint_separation == .08
        game.configure(Settings(min_keypoint_separation=.12))
        assert Game(store).defaults.min_keypoint_separation == .12
    finally:
        store.close()


@pytest.mark.parametrize("distance", [-.01, .31, float("nan")])
def test_invalid_distance_is_rejected(distance):
    with pytest.raises(ValidationError):
        Settings(min_keypoint_separation=distance)
