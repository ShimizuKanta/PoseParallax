import copy
import math
import pytest
from pydantic import ValidationError
from server.game import Game, GameError
from server.matching import match
from server.models import KeypointFrame, Settings
from server.poses import POSES, project
from server.storage import Store


@pytest.fixture
def game(tmp_path):
    store = Store(tmp_path / "game.sqlite3")
    now = [1000.0]
    game = Game(store, clock=lambda: now[0])
    game.advance = lambda seconds: now.__setitem__(0, now[0] + seconds)
    yield game
    store.close()


def prepare(game, members=3, **settings):
    game.configure(Settings(**settings))
    players = [game.join(f"Player {i}") for i in range(members)]
    game.connections.update(players)
    game.setup()
    for pid in players:
        game.ready(pid, game.state["round"]["id"])
    game.start()
    return game.observers()


def frame(game, pid, visible=True):
    r = game.state["round"]
    points = copy.deepcopy(r["views"][pid]["target"])
    if not visible:
        for p in points:
            p[2] = 0
    return game.frame(pid, KeypointFrame(type="pose", round_id=r["id"], keypoints=points))


def test_matching_translation_scale_but_not_mirror():
    target = project(POSES[0]["points"], 15, 0)
    transformed = [[x * 1.7 + .3, y * 1.7 - .2, c] for x, y, c in target]
    assert match(target, transformed, Settings())["score"] == 100
    mirrored = [[1 - x, y, c] for x, y, c in target]
    assert not match(target, mirrored, Settings())["matched"]


def test_hidden_joints_require_or_ignore():
    target = project(POSES[0]["points"], 0, 0)
    actual = copy.deepcopy(target)
    actual[15][2] = 0
    assert not match(target, actual, Settings())["matched"]
    assert match(target, actual, Settings(hidden_policy="ignore"))["matched"]


def test_latched_clears_remain_after_mismatch(game):
    a, b = prepare(game, hold_seconds=.5)
    frame(game, a)
    game.advance(.6)
    frame(game, a)
    game.advance(.2)
    frame(game, a, False)
    assert a in game.state["round"]["cleared"]
    frame(game, b)
    game.advance(.6)
    frame(game, b)
    assert game.state["phase"] == "round_result"
    assert game.state["history"][0]["outcome"] == "cleared"


def test_simultaneous_needs_overlap_and_restarts_after_stale_gap(game):
    a, b = prepare(game, clear_mode="simultaneous", hold_seconds=2)
    frame(game, a)
    frame(game, b)
    game.advance(.8)
    frame(game, a)
    frame(game, b)
    # No ticker runs in this interval: a fresh frame must still reset a stale hold.
    game.advance(1.1)
    frame(game, a)
    frame(game, b)
    game.advance(.5)
    frame(game, a)
    frame(game, b)
    assert game.state["phase"] == "playing"
    for _ in range(4):
        game.advance(.4)
        frame(game, a)
        frame(game, b)
    assert game.state["phase"] == "round_result"


def test_disconnect_resets_simultaneous_hold(game):
    a, b = prepare(game, clear_mode="simultaneous", hold_seconds=.5)
    frame(game, a)
    frame(game, b)
    game.advance(.3)
    game.disconnect(b)
    game.advance(.3)
    game.tick()
    assert game.state["phase"] == "playing"
    game.connections.add(b)
    frame(game, a)
    frame(game, b)
    game.advance(.6)
    frame(game, a)
    frame(game, b)
    assert game.state["phase"] == "round_result"


def test_only_observers_and_current_round_can_submit(game):
    observer, = prepare(game, members=2)
    r = game.state["round"]
    payload = KeypointFrame(type="pose", round_id="previous", keypoints=r["views"][observer]["target"])
    assert game.frame(observer, payload) is None
    payload.round_id = r["id"]
    assert game.frame(r["poser_id"], payload) is None


def test_setup_requires_online_and_ready(game):
    a, b = game.join("A"), game.join("B")
    game.setup()
    with pytest.raises(GameError):
        game.start()
    game.connections.update([a, b])
    with pytest.raises(GameError):
        game.start()
    for pid in [a, b]:
        game.ready(pid, game.state["round"]["id"])
    game.start()
    assert game.state["phase"] == "playing"


def test_remove_rechecks_end_condition_and_poser_removal_cancels(game):
    a, b = prepare(game, hold_seconds=0)
    frame(game, a)
    game.remove(b)
    assert game.state["history"][-1]["outcome"] == "cleared"
    game.setup()
    game.remove(game.state["round"]["poser_id"])
    assert game.state["history"][-1]["outcome"] == "poser_left"


def test_last_observer_removal_is_not_a_win(game):
    a, = prepare(game, members=2)
    game.remove(a)
    assert game.state["history"][-1]["outcome"] == "cancelled"


def test_timeout_does_not_accept_late_success(game):
    a, = prepare(game, members=2, hold_seconds=0, round_seconds=15)
    game.advance(16)
    frame(game, a)
    assert game.state["history"][-1]["outcome"] == "timeout"


def test_settings_snapshot_and_saved_defaults(game):
    prepare(game)
    game.configure(Settings(score_threshold=90, clear_mode="simultaneous"))
    assert game.state["round"]["settings"]["score_threshold"] == 65
    assert Settings(**game.store.get("defaults")).score_threshold == 90


def test_restart_preserves_players_results_and_aborts_active_round(game):
    prepare(game)
    restored = Game(game.store, game.clock)
    assert len(restored.active()) == 3
    assert restored.state["history"][-1]["outcome"] == "server_restart"
    assert restored.connections == set()


def test_max_50_players_and_fair_poser_rotation(game):
    ids = [game.join(str(i)) for i in range(50)]
    with pytest.raises(GameError):
        game.join("51")
    game.configure(Settings(rounds=50))
    posers = []
    for _ in range(50):
        game.setup()
        posers.append(game.state["round"]["poser_id"])
        assert len(game.observers()) == 49
        game.finish("skipped")
    assert set(posers) == set(ids)
    game.setup()
    assert game.state["phase"] == "final_result"


def test_observer_never_gets_pose_or_other_targets(game):
    a, b = prepare(game)
    snapshot = game.snapshot({"role": "player", "player_id": a})
    assert "pose" not in snapshot["round"]
    assert "views" not in snapshot["round"]
    assert "azimuth" not in snapshot["round"]
    assert snapshot["round"]["target"] == game.state["round"]["views"][a]["target"]
    assert "target" not in game.snapshot()["round"]


def test_impossible_view_settings_fail_without_mutating_game(game):
    game.join("A")
    game.join("B")
    game.configure(Settings(azimuth_min=90, azimuth_max=90, elevation_min=0, elevation_max=0,
                            min_side_separation=.3, min_limb_ratio=.3))
    with pytest.raises(ValueError):
        game.setup()
    assert game.state["phase"] == "waiting"
    assert game.state["round"] is None


def test_new_group_archives_old_event_and_removes_roster(game):
    prepare(game)
    old_id = game.state["id"]
    game.action("end")
    game.action("new_event", name="Group B")
    assert game.state["id"] != old_id
    assert game.state["name"] == "Group B"
    assert not game.active()
    assert len(game.store.get("event:" + old_id)["history"]) == 1


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_pose_input_is_rejected(value):
    with pytest.raises(ValidationError):
        KeypointFrame(type="pose", round_id="x", keypoints=[[value, 0, 1]] * 33)


def test_invalid_settings_are_rejected():
    with pytest.raises(ValidationError):
        Settings(azimuth_min=90, azimuth_max=0)
    with pytest.raises(ValidationError):
        Settings(joints=[11, 12, 13, 14], min_visible=8)


def test_camera_stopping_revokes_ready(game):
    players = [game.join("A"), game.join("B")]
    game.connections.update(players)
    game.setup()
    rid = game.state["round"]["id"]
    for pid in players:
        game.ready(pid, rid)
    game.ready(players[0], rid, False)
    with pytest.raises(GameError):
        game.start()
