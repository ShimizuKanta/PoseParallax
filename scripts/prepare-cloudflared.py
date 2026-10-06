"""Download the pinned official connector at build time, not on participant PCs."""
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

root = Path(__file__).resolve().parent.parent
manifest = json.loads((root / 'packaging/cloudflared.json').read_text())
platform = manifest['platforms'][sys.platform]
destination = root / 'vendor/cloudflared'
destination.mkdir(parents=True, exist_ok=True)
executable = destination / platform['filename']
if not executable.exists() or hashlib.sha256(executable.read_bytes()).hexdigest() != platform['sha256']:
    url = f"https://github.com/cloudflare/cloudflared/releases/download/{manifest['version']}/{platform['asset']}"
    request = urllib.request.Request(url, headers={'User-Agent': 'PoseParallax-build'})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != platform['sha256']:
        raise RuntimeError('cloudflared checksum mismatch')
    temporary = executable.with_suffix('.download')
    temporary.write_bytes(data); temporary.replace(executable)
executable.chmod(0o755)
with urllib.request.urlopen(manifest['license_url'], timeout=30) as response:
    (destination / 'LICENSE.txt').write_bytes(response.read())
(destination / 'VERSION.txt').write_text(manifest['version'] + '\n')
print('Prepared cloudflared ' + manifest['version'])
