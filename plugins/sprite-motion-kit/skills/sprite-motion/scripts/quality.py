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
    # A repeated neutral pose can sit within the per-frame angle tolerance for
    # an entire small attack. Check the *changing* direction of each segment
    # separately; averaging over the whole body hides an unmoving weapon arm.
    # Unit directions allow fixed limb lengths/body proportions to differ.
    motion_checks=[];motion_errors=[]
    for a,b in edges:
        rv=np.array([np.array(f[b])-f[a] for f in reference],float)
        ov=np.array([np.array(f['points'][b])-f['points'][a] for f in observed],float)
        ru=rv/np.linalg.norm(rv,axis=1,keepdims=True)
        ou=ov/np.linalg.norm(ov,axis=1,keepdims=True)
        reference_swing=math.degrees(math.acos(float(np.clip(np.min(ru@ru.T),-1,1))))
        # Require both angular change and meaningful travel at the generated
        # character's segment length. A tiny segment rotating less than three
        # pixels cannot be distinguished reliably from annotation differences.
        projected_travel=2*math.sin(math.radians(reference_swing)/2)*float(np.median(np.linalg.norm(ov,axis=1)))
        if reference_swing<20 or projected_travel<3:continue
        observed_swing=math.degrees(math.acos(float(np.clip(np.min(ou@ou.T),-1,1))))
        amplitude_ratio=observed_swing/reference_swing
        rc=ru-ru.mean(axis=0);oc=ou-ou.mean(axis=0)
        denominator=float(np.linalg.norm(rc)*np.linalg.norm(oc))
        correlation=float(np.clip(np.sum(rc*oc)/denominator,-1,1)) if denominator>1e-10 else 0.
        measurement={'segment':[a,b],'reference_swing_degrees':round(reference_swing,3),
                     'observed_swing_degrees':round(observed_swing,3),
                     'expected_travel_pixels':round(projected_travel,3),
                     'amplitude_ratio':round(amplitude_ratio,4),'phase_correlation':round(correlation,4)}
        motion_checks.append(measurement)
        # Retain at least half of the reference swing and its phase direction;
        # a static pose, token wiggle or reversed/uncorrelated swing must fail.
        if amplitude_ratio<.5 or correlation<.5:motion_errors.append(measurement)
    if motion_errors:raise ValueError('Generated segment motion loses material movement or reference phases: '+json.dumps(motion_errors[:12]))
    # Angles alone allow a whole row to float above its intended origin. Fit one
    # scale for the entire clip, then allow only a constant offset per landmark
    # (body proportions differ); changing offsets between frames are drift.
    names=sorted({n for edge in edges for n in edge})
    r=np.array([[f[n] for n in names] for f in reference],float)
    o=np.array([[f['points'][n] for n in names] for f in observed],float)
    ratios=[]
    for rf,of in zip(reference,observed):
        for a,b in edges:
            ratios.append(np.linalg.norm(np.array(of['points'][b])-of['points'][a])/np.linalg.norm(np.array(rf[b])-rf[a]))
    scale=float(np.median(ratios))
    residual=o-r*scale
    residual-=np.median(residual,axis=0,keepdims=True)
    offsets=np.median(residual,axis=1)
    extent=max(1.,float(np.ptp(r[:,:,1]))*scale)
    drift=np.ptp(offsets,axis=0)
    if float(max(drift))>max(2.,extent*.01):
        raise ValueError('Generated cell registration drifts between frames: '+json.dumps({'span_pixels':drift.tolist(),'tolerance':max(2.,extent*.01)}))
    return {'passed':True,'frames':len(reference),'segments_per_frame':len(edges),
            'segment_motion':motion_checks,'registration_span_pixels':drift.tolist()}

def reference_points(job,data,action,mannequin):
    if data['schema']==3:
        spec=data['actions'][action];ref=read(job/spec['landmarks'])
        return ref['frames'],ref['edges']
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

def endpoint_check(reference,observed,edges,loop):
    names=sorted({n for edge in edges for n in edge});ratios=[]
    for r,o in zip(reference,observed):
        for a,b in edges:
            length=np.linalg.norm(np.array(r[b])-r[a])
            if length>1e-8:ratios.append(np.linalg.norm(np.array(o['points'][b])-o['points'][a])/length)
    if not ratios:raise ValueError('Endpoint check has no measurable pose segments')
    scale=float(np.median(ratios));start,end=(-1,0) if loop else (0,-1)
    errors=[]
    for n in names:
        expected=(np.array(reference[end][n])-reference[start][n])*scale
        actual=np.array(observed[end]['points'][n])-observed[start]['points'][n]
        errors.append(float(np.linalg.norm(actual-expected)))
    extent=float(np.ptp(np.array([[r[n][1] for n in names] for r in reference])))*scale
    tolerance=max(3.,extent*.06)
    if max(errors)>tolerance:raise ValueError('Endpoint transition differs from reference; inspect last-to-first seam or first-to-settled pose')
    return {'transition':'last_to_first' if loop else 'first_to_settled','max_error_pixels':max(errors),'tolerance_pixels':tolerance}

def observations_template(job,data,action,image,mannequin):
    ref,edges=reference_points(job,data,action,mannequin)
    return {'source_sha256':digest(image),'guide_sha256':digest(job/data['actions'][action]['guide']),
      'action':action,'instructions':'Inspect generated pixels. Mark anatomical joints in cell-local pixel coordinates, x right/y down. Do not copy reference points. Occlusion/uncertainty means rejection or repair, not invented coordinates.',
      'frames':[{'frame':i,'points':{n:None for n in r}} for i,r in enumerate(ref)],
      'visual_checks':{k:False for k in ['landmarks_match_pixels','identity_and_equipment','support_and_weight','loop_or_settling','camera']},'notes':''}

def check(job,data,action,image,report,mannequin,rectangles=None,point_offsets=None):
    if report.get('action')!=action or report.get('source_sha256')!=digest(image) or report.get('guide_sha256')!=digest(job/data['actions'][action]['guide']):
        raise ValueError('Pose observations must match the exact action, generated image and current guide')
    for k in ['landmarks_match_pixels','identity_and_equipment','support_and_weight','loop_or_settling','camera']:
        if report.get('visual_checks',{}).get(k) is not True:raise ValueError('Visual observation not passed: '+k)
    if not str(report.get('notes','')).strip():raise ValueError('Concrete visual observations required')
    ref,edges=reference_points(job,data,action,mannequin)
    measured=report.get('frames',[])
    if point_offsets is not None:
        if len(point_offsets)!=len(measured) or any(len(p)!=2 or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in p) for p in point_offsets):raise ValueError('Crop coordinate offsets must cover every observed frame')
        import copy
        measured=copy.deepcopy(measured)
        for frame,offset in zip(measured,point_offsets):
            for name,point in frame['points'].items():
                if isinstance(point,list) and len(point)==2:frame['points'][name]=[point[k]+offset[k] for k in range(2)]
    result=compare(ref,measured,edges)
    result['endpoints']=endpoint_check(ref,measured,edges,data['actions'][action]['loop'])
    # Catch copied guide coordinates, off-canvas marks and marks in empty space.
    # This still does not identify which bone a foreground pixel belongs to.
    pixels=np.array(Image.open(image).convert('RGBA'));rgb=pixels[:,:,:3].astype(int)
    solid=(pixels[:,:,3]>32)&~((rgb[:,:,0]>180)&(rgb[:,:,2]>170)&(rgb[:,:,1]<100)&(np.minimum(rgb[:,:,0],rgb[:,:,2])-rgb[:,:,1]>90))
    spec=data['actions'][action];h,w=solid.shape
    for i,frame in enumerate(report['frames']):
        x0=round(i%spec['columns']*w/spec['columns']);x1=round((i%spec['columns']+1)*w/spec['columns'])
        y0=round(i//spec['columns']*h/spec['rows']);y1=round((i//spec['columns']+1)*h/spec['rows'])
        if rectangles is not None:x0,y0,x1,y1=rectangles[i]
        cell=solid[y0:y1,x0:x1];radius=max(2,round(min(cell.shape)*.012))
        for name,(x,y) in frame['points'].items():
            if not 0<=x<cell.shape[1] or not 0<=y<cell.shape[0]:raise ValueError(f'Frame {i+1}: landmark {name} lies outside generated cell')
            x,y=round(x),round(y)
            if not cell[max(0,y-radius):y+radius+1,max(0,x-radius):x+radius+1].any():raise ValueError(f'Frame {i+1}: landmark {name} lies on background; inspect actual pixels')
    result.update(source_sha256=digest(image),guide_sha256=report['guide_sha256'],action=action)
    return result
