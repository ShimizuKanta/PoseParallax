"""Translation/scale invariant comparison. No rotation or mirror alignment.

Preserving orientation is essential: players must find the assigned view.
"""
import math
from .poses import ANGLES, EDGES


def normalize(points, indices):
    cx = sum(points[i][0] for i in indices) / len(indices)
    cy = sum(points[i][1] for i in indices) / len(indices)
    scale = math.sqrt(sum((points[i][0] - cx) ** 2 + (points[i][1] - cy) ** 2
                          for i in indices) / len(indices))
    if scale < 1e-5:
        return None
    return {i: ((points[i][0] - cx) / scale, (points[i][1] - cy) / scale) for i in indices}


def direction(a, b):
    return math.atan2(b[1] - a[1], b[0] - a[0])


def angle_distance(a, b):
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


def match(target, points, settings):
    visible = [i for i in settings.joints if points[i][2] >= settings.confidence_threshold]
    invalid = len(visible) < settings.min_visible or (
        settings.hidden_policy == "require" and len(visible) != len(settings.joints))
    if invalid:
        return {"score": 0, "matched": False, "visible": len(visible), "reason": "全身が映る位置に移動してください"}
    actual, goal = normalize(points, visible), normalize(target, visible)
    if actual is None or goal is None:
        return {"score": 0, "matched": False, "visible": len(visible), "reason": "人物を検出できません"}
    components = {i: [max(0, 1 - math.dist(actual[i], goal[i]) / 1.2)] for i in visible}
    for a, b in EDGES:
        if a in actual and b in actual:
            value = max(0, 1 - angle_distance(direction(actual[a], actual[b]),
                                             direction(goal[a], goal[b])) / (math.pi / 2))
            components[a].append(value)
            components[b].append(value)
    for a, b, c in ANGLES:
        if all(i in actual for i in (a, b, c)):
            live_angle = angle_distance(direction(actual[b], actual[a]), direction(actual[b], actual[c]))
            goal_angle = angle_distance(direction(goal[b], goal[a]), direction(goal[b], goal[c]))
            components[b].append(max(0, 1 - abs(live_angle - goal_angle) / (math.pi / 2)))
    # Every selected, sufficiently visible joint must pass, rather than an average hiding bad limbs.
    score = round(100 * min(sum(v) / len(v) for v in components.values()), 1)
    return {"score": score, "matched": score >= settings.score_threshold,
            "visible": len(visible), "reason": "そのままキープ！" if score >= settings.score_threshold else "手足の向きと立ち位置を合わせよう"}
