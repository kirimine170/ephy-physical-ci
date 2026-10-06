from pathlib import Path
import json,hashlib,os,subprocess
import cadquery as cq
import argparse,zipfile
parser=argparse.ArgumentParser(description='Nonprinting original cuboid reproduction; no network or printer operation')
parser.add_argument('--appdir',type=Path,required=True,help='Extracted official BambuStudio squashfs-root')
parser.add_argument('--output',type=Path,required=True,help='Fresh output directory')
parser.add_argument('--library-path',default='',help='Optional existing runtime library directories')
args=parser.parse_args();R=args.output.resolve();R.mkdir(parents=True,exist_ok=False)
package=Path(__file__).resolve().parent
appdir=args.appdir.resolve();binary=appdir/'bin/bambu-studio'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(binary)=='d267ad0b4589c46cb18f49e2414f87a529b446dc992cb6ab8a728fe43f549eb8','Different binary; use recorded official release'
for name in ['profiles','inputs','results','data']:(R/name).mkdir()
manifest=json.loads((package/'data-manifest.json').read_text())
with zipfile.ZipFile(package/'evidence.zip') as z:
 for name in ['profiles/machine.json','profiles/filament.json','profiles/process_fixed.json']:
  raw=z.read(name);assert hashlib.sha256(raw).hexdigest()==manifest[name]['sha256'];(R/name).write_bytes(raw)
process=R/'profiles/process_fixed.json'
plan={'source':'original synthetic cuboids, not case CAD','heights_mm':[2.4,2.5,2.6,2.7,2.8],'flat_bbox':'[80,90]x[80,88]x[0,H]','side_bbox':'[80,90]x[80,80+H]x[0,8]','hypotheses':'Flat thickness projects to machine Z. Side thickness projects to machine Y. Compare deposition, not travel; no physical accuracy claim. Profile unchanged across runs.','profile_hashes':{n:sha(R/'profiles'/n) for n in ['machine.json','filament.json','process_fixed.json']},'binary_sha256':sha(binary),'appimage_sha256':'d501b103fac5424513ec0e8d6bc145fb30719de2c7d94d7320d723740c81a7fd','cadquery_version':cq.__version__}
(R/'preregistered-plan.json').write_text(json.dumps(plan,indent=2))
env=dict(os.environ);env.pop('DISPLAY',None);env.pop('WAYLAND_DISPLAY',None);env['LD_LIBRARY_PATH']=str(appdir/'bin')+(':'+args.library_path if args.library_path else '')
records=[]
for axis in ['flat','side']:
 for h in plan['heights_mm']:
  name=f'{axis}_{h:.1f}';out=R/'results'/name;out.mkdir(exist_ok=True)
  dimensions=(10,8,h) if axis=='flat' else (10,h,8)
  mesh=R/'inputs'/(name+'.stl');shape=cq.Solid.makeBox(*dimensions,cq.Vector(80,80,0));cq.exporters.export(shape,str(mesh),tolerance=.005,angularTolerance=.05)
  cmd=[str(binary),'--datadir',str(R/'data'),'--load-settings',str(R/'profiles/machine.json')+';'+str(process),'--load-filaments',str(R/'profiles/filament.json'),'--curr-bed-type','Textured PEI Plate','--arrange','0','--allow-rotations=0','--orient','0','--slice','0','--debug','3','--export-3mf','analysis_only.3mf','--export-settings',str(out/'resolved.json'),'--outputdir',str(out),str(mesh)]
  (out/'command.json').write_text(json.dumps(cmd,indent=2));cp=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=120);(out/'run.log').write_text(cp.stdout+cp.stderr)
  rec={'name':name,'exit_code':cp.returncode,'dimensions':dimensions,'mesh_sha256':sha(mesh),'result':json.loads((out/'result.json').read_text()) if (out/'result.json').exists() else None};records.append(rec);(R/'run-manifest.json').write_text(json.dumps(records,indent=2));print(name,cp.returncode,flush=True)
  assert cp.returncode==0 and rec['result']['return_code']==0,rec

(R/'cases.json').write_text((package/'cases.json').read_text())
