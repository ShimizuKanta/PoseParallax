# Build on Windows with: python -m PyInstaller packaging/windows/PoseParallax.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

root = Path(SPECPATH).parents[1]
if not (root / 'dist/models/pose_landmarker_lite.task').exists():
    raise RuntimeError('Run npm ci, npm run assets, npm run build first')
connector = root / 'vendor/cloudflared'
import os
if not (connector / ('cloudflared.exe' if os.name == 'nt' else 'cloudflared')).exists():
    raise RuntimeError('Run python scripts/prepare-cloudflared.py first')
a = Analysis([str(root / 'desktop/entry.py')], pathex=[str(root)],
    binaries=[], datas=[(str(root / 'dist'), 'dist'), (str(connector), 'cloudflared')] + copy_metadata('uvicorn'),
    hiddenimports=collect_submodules('uvicorn') + collect_submodules('websockets'),
    hookspath=[], runtime_hooks=[], excludes=['pytest', 'httpx', 'uvloop'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='PoseParallax',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='PoseParallax')
