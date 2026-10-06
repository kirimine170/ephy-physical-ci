from pathlib import Path
from decimal import Decimal as D
import json,re,hashlib,struct,zipfile,xml.etree.ElementTree as ET
import argparse
parser=argparse.ArgumentParser(description='Audit only these synthetic BambuStudio files; not a general G-code parser')
parser.add_argument('--root',type=Path,required=True)
R=parser.parse_args().root.resolve()
roles={'Outer wall','Inner wall','Sparse infill','Internal solid infill','Top surface','Gap infill','Bridge','Bottom surface','Floating vertical shell'}
def digest(b):return hashlib.sha256(b).hexdigest()
def audit(path):
 text=path.read_text();xyz={a:None for a in 'XYZ'};e=D(0);erel=False;absolute=True;role=None;width=None;layer=None;layerh=None;events=[];debt=D(0);planes=[];heights=[]
 for line_no,line in enumerate(text.splitlines(),1):
  s=line.strip()
  if s.startswith('; FEATURE:'):role=s.split(':',1)[1].strip()
  if s.startswith('; LINE_WIDTH:'):width=D(s.split(':',1)[1].strip())
  if s.startswith('; Z_HEIGHT:'):layer=D(s.split(':',1)[1].strip());planes.append(layer)
  if s.startswith('; LAYER_HEIGHT:'):layerh=D(s.split(':',1)[1].strip());heights.append(layerh)
  code=s.split(';',1)[0].strip();parts=code.split()
  if not parts:continue
  cmd=parts[0]
  if cmd=='G90':absolute=True
  if cmd=='G91':absolute=False
  if cmd=='M83':erel=True
  if cmd=='M82':erel=False
  v={m.group(1):D(m.group(2)) for m in re.finditer(r'([XYZE])\s*(-?(?:\d+(?:\.\d*)?|\.\d+))',code)}
  if cmd=='G92':
   if 'E'in v:e=v['E']
   for a in 'XYZ':
    if a in v:xyz[a]=v[a]
  if cmd not in ['G0','G1','G2','G3']:continue
  start=xyz.copy()
  for a in 'XYZ':
   if a in v:xyz[a]=v[a] if absolute else (xyz[a]+v[a] if xyz[a] is not None else None)
  de=(v['E'] if erel else v['E']-e) if 'E'in v else D(0)
  if 'E'in v:e=(e+v['E']) if erel else v['E']
  if de<0:debt-=de
  effective=max(D(0),de-debt)
  if de>0:debt=max(D(0),debt-de)
  if effective<=0 or role not in roles or None in start.values() or None in xyz.values() or start==xyz:continue
  assert start['Z']==xyz['Z']==layer,(path,line_no,start,xyz,layer)
  assert width is not None and layerh is not None
  events.append({'line':line_no,'command':cmd,'arc_IJR':{m.group(1):str(D(m.group(2))) for m in re.finditer(r'([IJR])\s*(-?(?:\d+(?:\.\d*)?|\.\d+))',code)},'role':role,'start':start.copy(),'end':xyz.copy(),'width':width,'height':layerh})
 assert events
 outer=[x for x in events if x['role']=='Outer wall' and x['end']['Z']==D('.4')];assert outer
 assert all(x['command']=='G1' for x in outer), 'arc-aware extrema required for outerwall audit'
 pts=[p for x in outer for p in [x['start'],x['end']]]
 ylo=min(p['Y'] for p in pts);yhi=max(p['Y'] for p in pts)
 return {'gcode_sha256':digest(path.read_bytes()),'layer_Z_tags':list(map(str,planes)),'layer_heights':sorted(set(map(str,heights))),'model_deposition_Z':list(map(str,sorted({x['end']['Z'] for x in events}))), 'model_layer_count':len({x['end']['Z'] for x in events}),'model_top_Z':str(max(x['end']['Z'] for x in events)),'model_event_count':len(events),'model_path_signature_sha256':digest(json.dumps([{k:v for k,v in event.items() if k!='line'} for event in events],default=str,sort_keys=True).encode()),'outer_at_Z0p4':{'xy_centerline_bounds':{a:[str(min(p[a] for p in pts)),str(max(p[a] for p in pts))] for a in 'XY'},'widths':sorted({str(x['width']) for x in outer}),'y_nominal_envelope':[str(min(p['Y']-x['width']/2 for x in outer for p in [x['start'],x['end']])),str(max(p['Y']+x['width']/2 for x in outer for p in [x['start'],x['end']]))],'witness_lines':[x['line'] for x in outer]}}
results={}
for rec in json.loads((R/'cases.json').read_text()):
 name=rec['name'];out=R/'results'/name;d=json.loads((out/'resolved.json').read_text());report=audit(out/'plate_1.gcode')
 report['resolved_condition']={k:d[k] for k in ['precise_z_height','layer_height','initial_layer_print_height','wall_loops','sparse_infill_density','nozzle_diameter','enable_support','slicing_mode']}
 assert report['resolved_condition']=={'precise_z_height':'0','layer_height':'0.2','initial_layer_print_height':'0.2','wall_loops':'3','sparse_infill_density':'20%','nozzle_diameter':['0.4'],'enable_support':'0','slicing_mode':'regular'}
 mesh=R/'inputs'/(name+'.stl');b=mesh.read_bytes();n=struct.unpack_from('<I',b,80)[0];verts=[struct.unpack_from('<3f',b,84+50*i+12+12*j) for i in range(n) for j in range(3)];report['input_bbox']=[[min(v[i] for v in verts),max(v[i] for v in verts)] for i in range(3)]
 with zipfile.ZipFile(out/'analysis_only.3mf') as z:
  assert z.read('Metadata/plate_1.gcode')==(out/'plate_1.gcode').read_bytes()
  models=[k for k in z.namelist() if k.startswith('3D/Objects/') and k.endswith('.model')]
  coordinates=[]
  for model in models:
   tree=ET.fromstring(z.read(model));coordinates += [[float(v.attrib[a]) for a in 'xyz'] for v in tree.iter() if v.tag.endswith('}vertex')]
  report['export_3mf_vertices_bbox']=[[min(v[i] for v in coordinates),max(v[i] for v in coordinates)] for i in range(3)]
  report['export_instance_transforms']=[e.attrib.get('transform','identity') for e in ET.fromstring(z.read('3D/3dmodel.model')).iter() if e.tag.endswith('}item') or e.tag.endswith('}component')]
  # Bounded to the one-object/one-component/one-instance historical fixtures.
  core='{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}'
  production='{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}'
  tree=ET.fromstring(z.read('3D/3dmodel.model'))
  objects=tree.findall(core+'resources/'+core+'object')
  items=tree.findall(core+'build/'+core+'item')
  assert tree.attrib.get('unit')=='millimeter'
  assert len(models)==len(objects)==len(items)==1, 'unsupported 3MF topology'
  components=objects[0].findall(core+'components/'+core+'component')
  assert len(components)==1 and items[0].attrib['objectid']==objects[0].attrib['id']
  component=components[0]
  assert component.attrib[production+'path']=='/'+models[0]
  mesh_tree=ET.fromstring(z.read(models[0]))
  mesh_objects=mesh_tree.findall(core+'resources/'+core+'object')
  assert mesh_tree.attrib.get('unit')=='millimeter'
  assert len(mesh_objects)==1 and component.attrib['objectid']==mesh_objects[0].attrib['id']
  translation=[D(0)]*3
  for node in (component,items[0]):
   transform=list(map(D,node.attrib.get('transform','1 0 0 0 1 0 0 0 1 0 0 0').split()))
   assert len(transform)==12 and all(v.is_finite() for v in transform)
   assert transform[:9]==list(map(D,[1,0,0,0,1,0,0,0,1])), 'nonidentity rotation/scale'
   translation=[a+b for a,b in zip(translation,transform[9:])]
  for axis in range(3):
   for bound in range(2):
    assert abs(D(str(report['export_3mf_vertices_bbox'][axis][bound]))+translation[axis]-D(str(report['input_bbox'][axis][bound])))<=D('0.00001'), 'export/input pose mismatch'
  report['export_pose_verified']=True
 results[name]=report
(R/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
for n,r in results.items():print(n,r['model_layer_count'],r['model_top_Z'],r['outer_at_Z0p4']['xy_centerline_bounds']['Y'],r['outer_at_Z0p4']['y_nominal_envelope'])
