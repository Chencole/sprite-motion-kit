"""Build a release archive from explicitly distributable files only."""
import hashlib
import json
from pathlib import Path
import zipfile

root=Path(__file__).resolve().parents[1]
out=root/'dist';out.mkdir(exist_ok=True)
version=json.loads((root/'plugins/sprite-motion-kit/.codex-plugin/plugin.json').read_text(encoding='utf-8-sig'))['version'].split('+')[0]
target=out/f'sprite-motion-kit-{version}.zip'
files=[root/'README.md',root/'LICENSE',root/'requirements.txt',root/'.agents/plugins/marketplace.json']
for folder in ['plugins','docs','scripts','tests']:
    files.extend(p for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ['.pyc','.pyo'])
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(files):z.write(p,p.relative_to(root).as_posix())
checksum=hashlib.sha256(target.read_bytes()).hexdigest()
(out/'SHA256SUMS.txt').write_text(f'{checksum}  {target.name}\n',encoding='ascii')
print(f'{target.name}: {len(files)} files, {target.stat().st_size} bytes')
