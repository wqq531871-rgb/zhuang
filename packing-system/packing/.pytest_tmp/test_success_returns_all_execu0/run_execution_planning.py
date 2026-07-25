
import json
import sys
from pathlib import Path

source = Path(sys.argv[1])
output = Path(sys.argv[sys.argv.index('--output') + 1])
wcs = Path(sys.argv[sys.argv.index('--wcs-output') + 1])
if '--wcs-map-output' in sys.argv:
    wcs_map = Path(sys.argv[sys.argv.index('--wcs-map-output') + 1])
else:
    wcs_map = wcs.with_name(wcs.stem + '_map.json')
output.parent.mkdir(parents=True, exist_ok=True)
wcs.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({'pallets': []}), encoding='utf-8')
wcs.write_text(json.dumps([]), encoding='utf-8')
wcs_map.write_text(json.dumps({}), encoding='utf-8')
