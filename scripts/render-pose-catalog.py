"""Generate a reviewable front/oblique SVG contact sheet from the actual poses."""
from html import escape
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.poses import POSES, EDGES, JOINTS, rotate


def render():
    english = json.loads((ROOT / 'frontend/src/locales/en.json').read_text())
    rows = (len(POSES) + 3) // 4
    height = 64 + rows * 270
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}" role="img" aria-labelledby="title desc">',
           '<title id="title">Pose Parallax common pose pool</title>',
           '<desc id="desc">Each pose shown from the front and at 60 degrees. Green is anatomical left, blue is right, cyan is center. All poses belong to one randomly selected pool.</desc>',
           f'<rect width="1200" height="{height}" fill="#101827"/>',
           '<style>text{font-family:system-ui,sans-serif;fill:#eef1f6;font-size:13px}.caption{fill:#9ba8bb;font-size:10px}</style>',
           f'<text x="16" y="26">POSE PARALLAX — {len(POSES)} POSES / ONE COMMON POOL</text>',
           '<text x="16" y="46" class="caption">Front and 60° views · Green: left / Blue: right / Cyan: center · Lines indicate the floor</text>']
    for n, pose in enumerate(POSES):
        x, y = (n % 4) * 300, 64 + (n // 4) * 270
        out.append(f'<g transform="translate({x},{y})"><rect x="5" y="5" width="290" height="260" rx="10" fill="#1a2535"/>')
        out.append(f'<text x="16" y="25">{n+1:02} {escape(english[pose["name"]])}</text><text x="16" y="43" class="caption">{pose["id"]}</text>')
        for angle, center in [(0, 76), (60, 222)]:
            points = [rotate(p, -angle) for p in pose['points']]
            def xy(index):
                return center + points[index][0] * 92, 245 - points[index][1] * 92
            out.append(f'<path d="M{center-65} 245h130" stroke="#35475c"/><text class="caption" x="{center-16}" y="259">{angle}°</text>')
            for a, b in EDGES + [(0, 11), (0, 12)]:
                color = '#80e4df' if a < 11 or b < 11 or a % 2 != b % 2 else '#75df91' if a % 2 else '#609ce8'
                ax, ay = xy(a); bx, by = xy(b)
                out.append(f'<path d="M{ax:.2f} {ay:.2f}L{bx:.2f} {by:.2f}" stroke="{color}" stroke-width="4" stroke-linecap="round"/>')
            for i in JOINTS + [0]:
                px, py = xy(i)
                color = '#80e4df' if i == 0 else '#75df91' if i % 2 else '#609ce8'
                out.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{11 if i == 0 else 3.5}" fill="{color}"/>')
        out.append('</g>')
    out.append('</svg>')
    (ROOT / 'docs/pose_catalog.svg').write_text('\n'.join(out) + '\n', encoding='utf-8')


if __name__ == '__main__':
    render()
