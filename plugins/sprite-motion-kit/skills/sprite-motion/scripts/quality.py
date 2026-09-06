"""Pose correspondence gate. Landmarks are observed by the host, not inferred here.

This rejects measured pose mismatches, not every possible visual defect. It never
claims to recognize joints from pixels or to guarantee perfect generated motion.
"""
import hashlib,json,math
from pathlib import Path
import numpy as np
from PIL import Image

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def angle(a,b):
    a,b=np.array(a,float),np.array(b,float)
    if min(np.linalg.norm(a),np.linalg.norm(b))<1e-8:raise ValueError('Collapsed limb or coincident landmarks')
    return math.degrees(math.acos(float(np.clip(a@b/np.linalg.norm(a)/np.linalg.norm(b),-1,1))))

def reference_issues(plan,mannequin):
    """A normal plantigrade biped WALK must not keep both knees deeply folded.
    Other locomotion anatomies need their own explicit contract and visual check.
    This is intentionally not used to reject crouch, crawl, run or falling poses.
    """
    issues=[];ids={j['id'] for j in plan['joints']}
    for name,a in plan['actions'].items():
        kind=a.get('design',{}).get('motion_kind',name)
        if kind!='walk' or plan.get('body')!='humanoid':continue
        for side in ['near','far']:
            names=[side+'_'+j for j in ['hip','knee','ankle']]
            if not set(names)<=ids:
                issues.append(name+': define hip/knee/ankle landmarks for normal biped walk');continue
            extension=[]
            for t in np.linspace(0,a['seconds'],64,endpoint=False):
                p=mannequin.positions(plan['joints'],mannequin.sample(a,float(t)))
                h,k,f=[p[n] for n in names];extension.append(angle(h-k,f-k))
            if max(extension)<150:issues.append(name+': '+side+' support knee never extends; crouched reference is not a normal walk')
    return issues

def compare(reference,observed,edges):
    """Compare directed limb angles: translation/scale cannot hide wrong phases.
    No reordering, per-frame rotation, mirroring or left/right matching is allowed.
    """
    if len(reference)!=len(observed):raise ValueError('Every reference phase needs exactly one observed generated frame')
    if not edges:raise ValueError('No pose segments to compare')
    errors=[]
    for i,(ref,obs) in enumerate(zip(reference,observed)):
        if obs.get('frame')!=i:raise ValueError('Frame IDs must be complete, unique and in reference order')
        points=obs.get('points',{})
        for a,b in edges:
            for name in [a,b]:
                v=points.get(name)
                if not isinstance(v,list) or len(v)!=2 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in v):
                    raise ValueError(f'Frame {i+1}: missing/nonfinite observed landmark {name}')
            r=np.array(ref[b])-ref[a];o=np.array(points[b])-points[a]
            degrees=angle(r,o)
            if degrees>32:errors.append({'frame':i+1,'segment':[a,b],'angle_error':round(degrees,1)})
    if errors:raise ValueError('Generated poses do not match reference phases: '+json.dumps(errors[:12]))
    return {'passed':True,'frames':len(reference),'segments_per_frame':len(edges)}

def reference_points(job,data,action,mannequin):
    if data['schema']==1:
        path=Path(__file__).resolve().parents[1]/'assets'/f'{action}-landmarks.json'
        if not path.exists():raise ValueError('Legacy action has no measured pose contract; prepare a custom plan')
        ref=read(path);indices=data['actions'][action].get('reference_indices',list(range(len(ref['frames']))))
        return [ref['frames'][i] for i in indices],ref['edges']
    plan=read(job/data['motion_plan']);a=plan['actions'][action]
    view=mannequin.matrix([-plan['camera']['elevation'],plan['camera']['azimuth'],0])
    ids={j['id'] for j in plan['joints']}
    edges=[[j['parent'],j['id']] for j in plan['joints'] if j['parent'] and
           any(j['id'].endswith('_'+part) for part in ['knee','ankle','toe','elbow','hand','tip'])]
    if not edges:edges=[[j['parent'],j['id']] for j in plan['joints'] if j['parent']]
    needed={n for edge in edges for n in edge};frames=[]
    for t in np.linspace(0,a['seconds'],a['frame_count'],endpoint=not a['loop']):
        p=mannequin.positions(plan['joints'],mannequin.sample(a,float(t)))
        frames.append({n:[float((view@p[n])[0]),float(-(view@p[n])[1])] for n in needed})
    return frames,edges

def observations_template(job,data,action,image,mannequin):
    ref,edges=reference_points(job,data,action,mannequin)
    return {'source_sha256':digest(image),'guide_sha256':digest(job/data['actions'][action]['guide']),
      'action':action,'instructions':'Inspect generated pixels. Mark anatomical joints in cell-local pixel coordinates, x right/y down. Do not copy reference points. Occlusion/uncertainty means rejection or repair, not invented coordinates.',
      'frames':[{'frame':i,'points':{n:None for n in r}} for i,r in enumerate(ref)],
      'visual_checks':{k:False for k in ['landmarks_match_pixels','identity_and_equipment','support_and_weight','loop_or_settling','camera']},'notes':''}

def check(job,data,action,image,report,mannequin):
    if report.get('action')!=action or report.get('source_sha256')!=digest(image) or report.get('guide_sha256')!=digest(job/data['actions'][action]['guide']):
        raise ValueError('Pose observations must match the exact action, generated image and current guide')
    for k in ['landmarks_match_pixels','identity_and_equipment','support_and_weight','loop_or_settling','camera']:
        if report.get('visual_checks',{}).get(k) is not True:raise ValueError('Visual observation not passed: '+k)
    if not str(report.get('notes','')).strip():raise ValueError('Concrete visual observations required')
    ref,edges=reference_points(job,data,action,mannequin)
    result=compare(ref,report.get('frames',[]),edges)
    # Catch copied guide coordinates, off-canvas marks and marks in empty space.
    # This still does not identify which bone a foreground pixel belongs to.
    pixels=np.array(Image.open(image).convert('RGBA'));rgb=pixels[:,:,:3].astype(int)
    solid=(pixels[:,:,3]>32)&~((rgb[:,:,0]>180)&(rgb[:,:,2]>170)&(rgb[:,:,1]<100)&(np.minimum(rgb[:,:,0],rgb[:,:,2])-rgb[:,:,1]>90))
    spec=data['actions'][action];h,w=solid.shape
    for i,frame in enumerate(report['frames']):
        x0=round(i%spec['columns']*w/spec['columns']);x1=round((i%spec['columns']+1)*w/spec['columns'])
        y0=round(i//spec['columns']*h/spec['rows']);y1=round((i//spec['columns']+1)*h/spec['rows'])
        cell=solid[y0:y1,x0:x1];radius=max(2,round(min(cell.shape)*.012))
        for name,(x,y) in frame['points'].items():
            if not 0<=x<cell.shape[1] or not 0<=y<cell.shape[0]:raise ValueError(f'Frame {i+1}: landmark {name} lies outside generated cell')
            x,y=round(x),round(y)
            if not cell[max(0,y-radius):y+radius+1,max(0,x-radius):x+radius+1].any():raise ValueError(f'Frame {i+1}: landmark {name} lies on background; inspect actual pixels')
    result.update(source_sha256=digest(image),guide_sha256=report['guide_sha256'],action=action)
    return result
