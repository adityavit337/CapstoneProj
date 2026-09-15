"""Manual, sequential measurements of a stationary BLE tag."""
import math
from .position import trilaterate


def calculate_survey(payload):
    def number(value, name, low, high):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a number")
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{name} must be between {low} and {high}")
        return float(value)

    if not isinstance(payload, dict):
        raise ValueError("Expected a survey object")
    a = number(payload.get('reference'), 'RSSI at 1 m', -127, -1)
    n = number(payload.get('exponent'), 'Path-loss exponent', 1, 6)
    width = number(payload.get('width'), 'Room width', 1, 100)
    height = number(payload.get('height'), 'Room height', 1, 100)
    rows = payload.get('points')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
        raise ValueError('Enter 1 to 20 survey readings')
    points = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError('Invalid survey point')
        x = number(row.get('x'), 'X coordinate', 0, width)
        y = number(row.get('y'), 'Y coordinate', 0, height)
        rssi = number(row.get('rssi'), 'RSSI', -127, -1)
        points.append(dict(label=str(i+1), x=x, y=y, rssi=rssi,
                           distance=10 ** ((a-rssi)/(10*n))))
    result = dict(points=points, position=None, width=width, height=height,
                  reference=a, exponent=n,
                  status='Distance calculated. Add at least 3 non-collinear receiver locations to estimate position.')
    if len(points) >= 3:
        anchors = [(p['x'], p['y']) for p in points]
        if len(set(anchors)) != len(anchors):
            result['status'] = 'Use distinct receiver locations to estimate position.'
        else:
            try:
                result['position'] = trilaterate(anchors, [p['distance'] for p in points], bounds=(width, height))
                result['status'] = 'Sequential survey fit. Tag must have stayed fixed throughout all readings.'
            except ValueError as exc:
                result['status'] = str(exc) + ': spread receiver locations across the room.'
    return result
