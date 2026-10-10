import copy

import pytest

from server.game import Game
from server.models import Settings
from server.poses import POSES, make_view, review_view
from server.storage import Store
import server.poses as poses


@pytest.mark.parametrize('pose', POSES, ids=lambda p: p['id'])
@pytest.mark.parametrize('distance,focal_scale', [(3.0, 1.0), (4.5, 1.6)])
def test_legacy_review_recovers_original_distance(pose, distance, focal_scale, monkeypatch):
    monkeypatch.setattr(poses, 'VIEW_DISTANCE', distance)
    monkeypatch.setattr(poses, 'VIEW_FOCAL_SCALE', focal_scale)
    view = {'azimuth': 63, 'elevation': 12, 'target': poses.project(pose['points'], 63, 12)}
    original = copy.deepcopy(view)
    monkeypatch.setattr(poses, 'VIEW_DISTANCE', 6)
    monkeypatch.setattr(poses, 'VIEW_FOCAL_SCALE', 2)
    result = review_view(pose, view)
    assert result['distance'] == pytest.approx(distance)
    assert result['focal_scale'] == pytest.approx(focal_scale)
    assert result['azimuth'] == 63 and result['elevation'] == 12
    assert view == original


def test_new_review_keeps_recorded_camera_after_defaults_change(monkeypatch):
    view = make_view(POSES[0], Settings())
    monkeypatch.setattr(poses, 'VIEW_DISTANCE', 6)
    result = review_view(POSES[0], view)
    assert result['distance'] == 3
    assert result['target_height'] == .95
    assert result['focal_scale'] == 1


@pytest.mark.parametrize('phase', ['round_setup', 'playing', 'round_result', 'final_result'])
def test_review_camera_is_only_sent_to_its_observer_after_round(tmp_path, phase):
    store = Store(tmp_path / 'game.sqlite3')
    try:
        game = Game(store)
        for name in ('A', 'B', 'C'):
            game.join(name)
        game.setup()
        r = game.state['round']
        game.state['phase'] = phase
        for pid, view in r['views'].items():
            result = game.snapshot({'role': 'player', 'player_id': pid})['round']
            assert 'views' not in result
            if phase in ('round_result', 'final_result'):
                assert result['target_view'] == review_view(r['pose'], view)
            else:
                assert 'target_view' not in result
        for auth in ({}, {'role': 'admin'}, {'role': 'player', 'player_id': r['poser_id']}):
            assert 'target_view' not in game.snapshot(auth)['round']
    finally:
        store.close()
