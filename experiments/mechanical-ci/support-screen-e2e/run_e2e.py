"""Synthetic-only PrusaSlicer -> hash-bound ROI -> support-screen integration.

Public source is a frozen export, never modified by this script.
No printer communication, private geometry, installation, or publication.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from decimal import Decimal as D

COMMIT = 'e45770fb168b6ba64ee41922ec70adab76eddb55'
SUPPORT = {'Support material', 'Support material interface'}
OVERRIDES = {'dont_support_bridges': '0', 'support_material_buildplate_only': '0',
    'support_material_style': 'grid', 'support_material_pattern': 'rectilinear',
    'support_material_interface_pattern': 'rectilinear', 'support_material_spacing': '2',
    'support_material_interface_spacing': '0', 'support_material_with_sheath': '0',
    'support_material_angle': '0', 'use_relative_e_distances': '1', 'layer_gcode': 'G92 E0'}

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write(path, obj):
    with Path(path).open('x') as f:
        f.write(json.dumps(obj, indent=2, allow_nan=False) + '\n')

def audit(text):
    """Independent Decimal modal scan; never calls product parser or clipper."""
    xyz = [None] * 3
    role, width, height = None, None, None
    debt = D(0)
    relative = False
    events = []
    for line, raw in enumerate(text.splitlines(), 1):
        raw = raw.strip()
        if raw.startswith(';TYPE:'): role = raw[6:].strip()
        if raw.startswith(';WIDTH:'): width = D(raw[7:])
        if raw.startswith(';HEIGHT:'): height = D(raw[8:])
        code = raw.split(';', 1)[0].split()
        if not code: continue
        if code[0] == 'M83': relative = True
        if code[0] == 'M82': relative = False
        if code[0] not in ('G0', 'G1'): continue
        args = {s[0]: D(s[1:]) for s in code[1:]}
        old = xyz[:]
        xyz = [args.get(k, v) for k, v in zip('XYZ', xyz)]
        if 'E' not in args: continue
        assert relative, 'independent oracle requires explicit M83'
        e = args['E']
        if e <= 0:
            debt -= e
            continue
        recovered = min(debt, e)
        debt -= recovered
        if e == recovered: continue
        assert None not in xyz and None not in old, 'unlocated oracle deposition'
        start = [a + (b-a)*recovered/e for a,b in zip(old, xyz)]
        events.append({'line': line, 'role': role, 'start': start, 'end': xyz[:],
                       'width': width, 'height': height})
    return events

def interior(event, region):
    points = [event['start'], event['end'], [(a+b)/2 for a,b in zip(event['start'],event['end'])]]
    return any(all(D(str(lo)) < q < D(str(hi)) for q,lo,hi in zip(p,region['min_mm'],region['max_mm'])) for p in points)

def regions(dx=0, dy=0):
    return [
        {'id':'body', 'min_mm':[85+dx,84+dy,4], 'max_mm':[95+dx,96+dy,10]},
        {'id':'interface', 'min_mm':[85+dx,84+dy,10], 'max_mm':[95+dx,96+dy,12]},
        {'id':'far', 'min_mm':[140,140,4], 'max_mm':[150,150,10]}]

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source-root',type=Path,required=True)
    p.add_argument('--slicer',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    root=a.output.resolve()
    root.mkdir(parents=True,exist_ok=False)
    src=a.source_root.resolve()
    env=dict(os.environ, PYTHONPATH=str(src/'tools/mechanical-ci/src'))
    version=subprocess.run([str(a.slicer),'--help'],capture_output=True,text=True,check=True)
    header=(version.stdout+version.stderr).splitlines()[0]
    assert re.match(r'PrusaSlicer-2\.9\.2(?:\+|\s|$)',header), header
    provenance={'source_commit':COMMIT,'slicer_header':header,'slicer_sha256':digest(a.slicer),
                'python_version':sys.version.split()[0], 'script_sha256':digest(__file__),
                'source_sha256':{str(f.relative_to(src)):digest(f) for f in sorted((src/'tools/mechanical-ci/src').rglob('*.py'))}}
    write(root/'provenance.json',provenance)
    import cadquery as cq
    def box(x,y,z,dx,dy,dz):
        return cq.Workplane('XY').box(dx,dy,dz,centered=False).translate((x,y,z))
    shelf=box(0,0,0,30,20,2).union(box(0,0,2,3,20,12)).union(box(3,0,12,22,20,2))
    inputs=root/'inputs'; inputs.mkdir()
    mesh=inputs/'shelf.stl'
    cq.exporters.export(shelf,str(mesh),tolerance=.02,angularTolerance=.1)
    base=(src/'tools/mechanical-ci/examples/synthetic/analysis_profile.ini').read_text()
    assert all(not re.search(r'^'+re.escape(k)+r'\s*=',base,re.M) for k in OVERRIDES)
    profile=inputs/'profile.ini'
    profile.write_text(base+'\n'+'\n'.join(k+' = '+v for k,v in OVERRIDES.items())+'\n')
    cases=[('a_auto',[90,90],'auto',regions()),('a_none',[90,90],'none',regions()),
           ('b_auto',[110,100],'auto',regions(20,10)+[dict(r,id='old_'+r['id']) for r in regions()[:2]])]
    plan={'geometry_boxes_mm':[[0,0,0,30,20,2],[0,0,2,3,20,12],[3,0,12,22,20,2]],
          'cases':[{'name':n,'center_mm':c,'support_mode':m,'regions':r} for n,c,m,r in cases],
          'mesh_sha256':digest(mesh),'profile_sha256':digest(profile),'cadquery_version':cq.__version__,
          'oracle':'Independent Decimal modal parser and strictly interior endpoint/midpoint witnesses; no product clipping calls.',
          'pose_oracle':'External perimeter extrema on base z0.4..1.8 and wall z4..10 within 0.6 mm of all four CAD XY bounds; all endpoints in expanded box; widths <=0.6 mm.',
          'physical_validation':'not_performed'}
    write(root/'preregistered-plan.json',plan)
    def cli(args, expected=0):
        result=subprocess.run([sys.executable,'-m','physical_ci']+list(map(str,args)),env=env,capture_output=True,text=True,timeout=180)
        if result.returncode!=expected: raise RuntimeError(f'CLI return {result.returncode}, expected {expected}: {result.stderr}')
        return result
    observations=[]
    for name,center,mode,rois in cases:
        manifest={'schema_version':1,'name':name,'units':'mm',
          'assembly_to_print':[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
          'artifacts':{'print_mesh':{'path':'shelf.stl','sha256':digest(mesh),'frame':'print'},
                       'profile':{'path':'profile.ini','sha256':digest(profile),'frame':'configuration'}},
          'slicing':{'engine':'PrusaSlicer','expected_version':'2.9.2','center_mm':center,'support_mode':mode}}
        manifest_path=inputs/(name+'.json'); write(manifest_path,manifest)
        out=root/name
        cli(['slice',manifest_path,'--slicer',a.slicer,'--output-dir',out,'--segments'])
        gcode=out/'toolpath.analysis-only.gcode'
        events=audit(gcode.read_text())
        dx,dy=center[0]-15,center[1]-10
        base_events=[e for e in events if e['role']=='External perimeter' and D('.4')<=e['end'][2]<=D('1.8')]
        assert base_events, 'base landmark missing'
        extrema=[]
        for axis,lo,hi in [(0,dx,dx+30),(1,dy,dy+20)]:
            values=[p[axis] for e in base_events for p in (e['start'],e['end'])]
            assert abs(min(values)-D(lo))<D('.6') and abs(max(values)-D(hi))<D('.6'), 'base pose changed'
            extrema.append([float(min(values)),float(max(values))])
        walls=[e for e in events if e['role']=='External perimeter' and D(4)<=e['end'][2]<=D(10)]
        assert walls, 'wall landmark missing'
        for feature,xhi in [(base_events,dx+30),(walls,dx+3)]:
            assert all(e['width']<=D('.6') for e in feature), 'pose oracle width exceeds frozen tolerance'
            for axis,lo,hi in [(0,dx,xhi),(1,dy,dy+20)]:
                values=[p[axis] for e in feature for p in (e['start'],e['end'])]
                assert abs(min(values)-D(lo))<D('.6') and abs(max(values)-D(hi))<D('.6'), 'feature pose extrema changed'
        assert all(D(dx)-D('.6')<p[0]<D(dx+3)+D('.6') and D(dy)-D('.6')<p[1]<D(dy+20)+D('.6') for e in walls for p in (e['start'],e['end'])), 'wall pose changed'
        assert all(p[0]+e['width']/2<D(140) and p[1]+e['width']/2<D(140) for e in events for p in (e['start'],e['end'])), 'far ROI not independently separated'
        roi=out/'roi.json'; write(roi,{'schema_version':1,'frame':'gcode_machine_coordinates','units':'mm','gcode_sha256':digest(gcode),'regions':rois})
        input_hashes_before={p.name:digest(p) for p in (mesh,profile,gcode,roi)}
        report=out/'screen.json'; cli(['screen-support',gcode,'--roi',roi,'--output',report])
        result=json.loads(report.read_text())
        assert result['coverage_complete'], result['coverage_gaps']
        assert result['physical_validation']=='not_performed' and result['support_removal']=='not_implemented' and result['printer_ready'] is False
        assert not any(h['roi_id']=='far' for h in result['observed_hits'])
        witnesses={}
        if mode=='auto':
            for region,role in [(rois[0],'Support material'),(rois[1],'Support material interface')]:
                candidates=[e for e in events if e['role']==role and interior(e,region)]
                assert candidates, f'no independent {role} witness in fixed {region["id"]} ROI'
                witness=candidates[0]
                assert any(h['line']==witness['line'] and h['roi_id']==region['id'] for h in result['observed_hits']), 'screen missed independent witness'
                witnesses[region['id']]={'line':witness['line'],'role':role,'start_mm':list(map(float,witness['start'])),'end_mm':list(map(float,witness['end']))}
            if name=='b_auto': assert not any(h['roi_id'].startswith('old_') for h in result['observed_hits'])
        else:
            assert not any(e['role'] in SUPPORT for e in events), 'support-off emitted support deposition'
            assert not result['observed_hits'] and result['screened_support_events']==0
        repeat=out/'screen-repeat.json'; cli(['screen-support',gcode,'--roi',roi,'--output',repeat])
        assert repeat.read_bytes()==report.read_bytes(), 'nondeterministic screening'
        bad=json.loads(roi.read_text()); bad['gcode_sha256']='0'*64
        badroi=out/'bad-hash-roi.json'; write(badroi,bad)
        badout=out/'bad-hash-result.json'; cli(['screen-support',gcode,'--roi',badroi,'--output',badout],2)
        assert not badout.exists()
        input_hashes_after={p.name:digest(p) for p in (mesh,profile,gcode,roi)}
        assert input_hashes_after==input_hashes_before, 'E2E input changed between observations'
        observations.append({'input_hashes_before':input_hashes_before,'input_hashes_after':input_hashes_after,'case':name,'gcode_sha256':digest(gcode),'roi_sha256':digest(roi),'report_sha256':digest(report),
            'independent_events':len(events),'screened_support_events':result['screened_support_events'],
            'observed_hit_count':len(result['observed_hits']),'coverage_complete':result['coverage_complete'],
            'base_perimeter_extrema_xy_mm':extrema,'interior_witnesses':witnesses,
            'repeat_byte_equal':True,'bad_hash_rejected':True})
        write(root/(name+'-checkpoint.json'),observations[-1])
    write(root/'summary.json',{'checks_passed':True,'source_commit':COMMIT,'cases':observations,
        'physical_validation':'not_performed','support_removal':'not_implemented','printer_ready':False,
        'limits':['Synthetic geometry/profile only; no physical print or removal trial.',
                  'Fixed ROIs do not certify manufacturing or CAD-to-G-code transformations for other inputs.',
                  'Screen repeats are deterministic; identical bytes across separate slicer runs are not claimed.']})
    print(json.dumps({'checks_passed':True,'cases':len(observations)}))

if __name__=='__main__': main()
