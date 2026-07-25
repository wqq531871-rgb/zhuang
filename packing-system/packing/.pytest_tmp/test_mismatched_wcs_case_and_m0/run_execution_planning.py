
import json
import sys
from pathlib import Path

output = Path(sys.argv[sys.argv.index('--output') + 1])
wcs = Path(sys.argv[sys.argv.index('--wcs-output') + 1])
wcs_map = Path(sys.argv[sys.argv.index('--wcs-map-output') + 1])
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({'pallets': []}), encoding='utf-8')
wcs.write_text(json.dumps([{'box_unique_id': 'missing'}]), encoding='utf-8')
wcs_map.write_text(json.dumps({}), encoding='utf-8')
