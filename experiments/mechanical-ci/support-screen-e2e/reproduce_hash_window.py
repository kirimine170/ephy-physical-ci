"""Deterministic interleaving control for the post-read hash-check window.

Mutates synthetic copies only, after CLI validation and before screen completion.
No product code edits; patch is in-memory and scoped to this test process.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--fixture',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    sys.path.insert(0,str(args.source_root.resolve()/'tools/mechanical-ci/src'))
    from physical_ci import cli
    from physical_ci.manifest import sha256
    original=cli.screen_support
    args.output.mkdir(parents=True,exist_ok=False)
    results=[]
    for target_name in ('gcode','roi'):
        folder=args.output/target_name; folder.mkdir()
        gcode=folder/'synthetic.gcode'; roi=folder/'roi.json'; report=folder/'report.json'
        shutil.copyfile(args.fixture/'toolpath.analysis-only.gcode',gcode)
        shutil.copyfile(args.fixture/'roi.json',roi)
        before={'gcode_sha256':sha256(gcode),'roi_sha256':sha256(roi)}
        def mutate_then_screen(*a,**kw):
            target=gcode if target_name=='gcode' else roi
            with target.open('a') as f:
                f.write('\n; synthetic concurrent edit\n' if target_name=='gcode' else '\n ')
            return original(*a,**kw)
        with patch.object(cli,'screen_support',side_effect=mutate_then_screen):
            code=cli.main(['screen-support',str(gcode),'--roi',str(roi),'--output',str(report)])
        after={'gcode_sha256':sha256(gcode),'roi_sha256':sha256(roi)}
        result=json.loads(report.read_text())
        reproduced=code==0 and before!=after and all(result[k]==v for k,v in before.items())
        assert reproduced, 'expected main-e45770f hash-window behavior changed'
        results.append({'mutated':target_name,'exit_code':code,'before':before,'after':after,
                        'report_hashes':{k:result[k] for k in before},'reproduced':reproduced})
    (args.output/'summary.json').write_text(json.dumps({'source_commit':'e45770fb168b6ba64ee41922ec70adab76eddb55',
        'controls':results,'conclusion':'Reports bind bytes read earlier; they do not prove paths stayed unchanged through report creation. Before/after equality likewise does not exclude transient changes.'},indent=2)+'\n')

if __name__=='__main__': main()
