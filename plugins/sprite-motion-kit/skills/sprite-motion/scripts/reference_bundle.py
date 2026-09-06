"""Import a rendered, measured 3D reference without replacing its approved rig.

No model is bundled or called here. The host supplies source references and uses
the emitted full-sheet request with its image generator. Final export is still
subject to pose evidence, alpha, registration and visual review.
"""
import hashlib,json,math,re,shutil
from pathlib import Path
import numpy as np
from PIL import Image

def assess_phase_coverage(phases,loop):
    """Measure normalized sample coverage; this cannot prove source-clip timing."""
    if not isinstance(phases,list) or len(phases)<3 or type(loop)is not bool:
        raise ValueError('At least three ordered phases and explicit loop behavior are required')
    if any(type(x)not in (int,float) or not math.isfinite(x) or x<0 or x>1 for x in phases) or phases[0]!=0 or any(a>=b for a,b in zip(phases,phases[1:])) or (loop and phases[-1]==1):
        raise ValueError('Invalid ordered phases')
    gaps=[b-a for a,b in zip(phases,phases[1:])]
    report={'sample_count':len(phases),'first_phase':phases[0],'last_phase':phases[-1],
            'loop':loop,'passed':True,'issues':[]}
    if loop:
        # Allow uneven key selection, but not a missing half-cycle hidden at wrap.
        wrap=1-phases[-1];uniform=1/len(phases);median=float(np.median(gaps))
        report.update(wrap_gap=wrap,largest_gap=max(gaps+[wrap]),uniform_gap=uniform,
                      max_gap_limit=2*uniform,wrap_gap_limit=1.5*median)
        if report['largest_gap']>report['max_gap_limit']+1e-9:
            report['issues'].append('A cyclic sampling gap exceeds twice the uniform phase interval')
        if wrap>report['wrap_gap_limit']+1e-9:
            report['issues'].append('The unsampled last-to-first gap exceeds 1.5 times the median interior interval')
    elif phases[-1]!=1:
        report['issues'].append('One-shot sampling must include phase 1 to preserve its final pose')
    report['passed']=not report['issues']
    return report

def assess_sampled_humanoid_walk(frames,gait_mode='normal',design=None):
    """Assess measured side-view leg motion without inferring anatomy or contacts."""
    if gait_mode not in ('normal','crouched','digitigrade'):
        raise ValueError('Walk gait_mode must be normal, crouched or digitigrade')
    reason=(design or {}).get('gait_reason','')
    if gait_mode!='normal' and (not isinstance(reason,str) or not reason.strip()):
        raise ValueError('A crouched/digitigrade gait needs explicit design.gait_reason')
    required=[side+'_'+joint for side in ('near','far') for joint in ('hip','knee','ankle')]
    missing=sorted({joint for frame in frames for joint in required if joint not in frame})
    if not frames or missing:
        return {'status':'not_assessed','passed':None,'reason':'The named near/far hip, knee and ankle joints are unavailable; no humanoid gait is inferred',
                'missing_joints':missing or required,'requires_visual_review':True}
    lengths=[];extensions={'near':[],'far':[]};offsets={'near':[],'far':[]}
    for frame in frames:
        for joint in required:
            p=frame[joint]
            if not isinstance(p,(list,tuple)) or len(p)!=2 or any(type(v)not in (int,float) or not math.isfinite(v) for v in p):
                raise ValueError('Humanoid walk landmarks must be finite projected x/y coordinates')
        for side in ('near','far'):
            hip=np.asarray(frame[side+'_hip'],dtype=float);knee=np.asarray(frame[side+'_knee'],dtype=float);ankle=np.asarray(frame[side+'_ankle'],dtype=float)
            upper=hip-knee;lower=ankle-knee;a=float(np.linalg.norm(upper));b=float(np.linalg.norm(lower))
            if min(a,b)<=1e-9:raise ValueError('Humanoid walk contains a zero-length projected leg segment')
            lengths.append(a+b);extensions[side].append(math.degrees(math.acos(float(np.clip(np.dot(upper,lower)/(a*b),-1,1)))))
            offsets[side].append(float(ankle[0]-hip[0]))
    tolerance=.05*float(np.median(lengths));issues=[];legs={}
    for side in ('near','far'):
        low,high=min(offsets[side]),max(offsets[side]);extension=max(extensions[side]);crosses=low < -tolerance and high > tolerance
        legs[side]={'ankle_minus_hip_x_range':[low,high],'crosses_hip':crosses,'max_knee_extension_degrees':extension}
        if not crosses:issues.append(side+' ankle never moves clearly to both sides of its hip')
        if gait_mode=='normal' and extension<150:issues.append(side+' knee never reaches the 150 degree normal-walk extension threshold')
    separation=[float(frame['near_ankle'][0]-frame['far_ankle'][0]) for frame in frames]
    exchanges=min(separation)<-tolerance and max(separation)>tolerance
    if not exchanges:issues.append('Near/far ankle ordering never exchanges across the sampled cycle')
    return {'status':'passed' if not issues else 'failed','passed':not issues,'gait_mode':gait_mode,
            'extension_requirement_degrees':150 if gait_mode=='normal' else None,'extension_exception_reason':reason if gait_mode!='normal' else None,
            'crossing_tolerance_pixels':tolerance,'legs':legs,'ankle_separation_x_range':[min(separation),max(separation)],
            'ankle_order_exchanges':exchanges,'issues':issues,'requires_visual_review':True}

def local(root,name):
    p=(root/name).resolve()
    if not p.is_relative_to(root.resolve()) or not p.is_file():raise ValueError('Reference file must exist inside bundle directory')
    return p

def validate(data,root):
    import motion
    if data.get('schema')!=1:raise ValueError('Unsupported reference bundle schema')
    for k in ['source_description','reuse_reason']:motion.require_text(data.get(k),'Missing bundle '+k)
    if not re.fullmatch('[0-9a-f]{64}',data.get('source_asset_sha256','')):raise ValueError('Record the source 3D asset fingerprint')
    for k in ['anatomy','mass_and_balance','equipment']:motion.require_text(data.get('character_analysis',{}).get(k),'Missing character analysis '+k)
    if not data.get('actions'):raise ValueError('Bundle needs actions')
    assessments={}
    for name,s in data['actions'].items():
        if not re.fullmatch('[a-z][a-z0-9_-]{0,63}',name):raise ValueError('Unsafe action name')
        for k in ['intent','support_and_contact','phases','end_state']:motion.require_text(s.get('design',{}).get(k),'Missing action design '+k)
        for k in ['columns','rows','count']:
            if type(s.get(k)) is not int or s[k]<1:raise ValueError('Invalid grid/count')
        if s['count']<3 or s['count']>s['columns']*s['rows']:raise ValueError('Invalid action frame count')
        if type(s.get('loop')) is not bool or not math.isfinite(s.get('seconds',0)) or s['seconds']<=0:raise ValueError('Invalid duration/loop')
        phases=s.get('phases',[])
        if not isinstance(phases,list) or len(phases)!=s['count']:raise ValueError('Invalid ordered phases')
        coverage=assess_phase_coverage(phases,s['loop'])
        if not coverage['passed']:raise ValueError(name+' reference phase coverage: '+'; '.join(coverage['issues']))
        assessments[name]={'phase_coverage':coverage}
        tile=s.get('tile',[])
        if len(tile)!=2 or any(type(x)is not int or x<16 for x in tile):raise ValueError('Invalid cell size')
        if len(s.get('origin',[]))!=2 or any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in s['origin']):raise ValueError('Fixed origin required')
        if not 0<s.get('floor_y',0)<tile[1]:raise ValueError('Fixed cell ground baseline required')
        with Image.open(local(root,s['guide'])) as guide:
            if guide.size!=(s['columns']*tile[0],s['rows']*tile[1]):raise ValueError('Guide dimensions must match the declared fixed cells')
        layout=s.get('reference_layout',{});rt=layout.get('tile',[])
        if len(rt)!=2 or any(type(x)is not int or x<16 for x in rt) or type(layout.get('columns'))is not int or layout['columns']<1 or type(layout.get('count'))is not int or layout['count']<3:raise ValueError('Invalid playback reference layout')
        with Image.open(local(root,s['reference'])) as preview:
            if preview.size!=(rt[0]*layout['columns'],rt[1]*math.ceil(layout['count']/layout['columns'])):raise ValueError('Playback dimensions differ from layout')
        landmarks=json.loads(local(root,s['landmarks']).read_text(encoding='utf-8-sig'))
        if len(landmarks.get('frames',[]))!=s['count'] or not landmarks.get('edges'):raise ValueError('Every phase needs projected 3D landmarks')
        names={n for edge in landmarks['edges'] for n in edge}
        for f in landmarks['frames']:
            for n in names:
                p=f.get(n)
                if not isinstance(p,list) or len(p)!=2 or any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in p) or not(0<=p[0]<tile[0] and 0<=p[1]<tile[1]):raise ValueError('Projected landmark missing or outside canvas')
        if not any(landmarks['frames'][i]!=landmarks['frames'][0] for i in range(1,s['count'])):raise ValueError('Static references do not describe an action')
        if name=='walk':
            assessment=assess_sampled_humanoid_walk(landmarks['frames'],s.get('gait_mode','normal'),s.get('design'))
            assessments[name]['sampled_humanoid_walk']=assessment
            if assessment['passed'] is False:raise ValueError('Walk reference gait: '+'; '.join(assessment['issues']))
    return assessments

def prepare(character,out,bundle,name,background_mode):
    import motion
    bundle=Path(bundle).resolve();root=bundle.parent;data=motion.read(bundle);assessments=validate(data,root)
    image=Image.open(character).convert('RGBA')
    if background_mode not in ['alpha','magenta']:raise ValueError('Select alpha or magenta')
    rgb=np.asarray(image).astype(int)
    if background_mode=='magenta' and np.any((rgb[:,:,3]>128)&(rgb[:,:,0]>180)&(rgb[:,:,2]>170)&(rgb[:,:,1]<100)&(np.minimum(rgb[:,:,0],rgb[:,:,2])-rgb[:,:,1]>90)):
        raise ValueError('Character contains the magenta key color; use alpha mode to preserve its artwork')
    out=Path(out).resolve()
    if out.exists() and any(out.iterdir()):raise ValueError('Use a new empty job directory')
    (out/'reference').mkdir(parents=True,exist_ok=True);image.save(out/'character.png')
    job={'schema':3,'name':name,'status':'awaiting_reference_review','character':'character.png','reference_bundle':'reference/bundle.json','background_mode':background_mode,'actions':{}}
    copied=json.loads(json.dumps(data))
    for action,s in data['actions'].items():
        spec=dict(s);spec['reference_assessment']=assessments[action]
        for k in ['guide','reference','landmarks']:
            suffix=Path(s[k]).suffix;target=f'{action}-{k}{suffix}'
            shutil.copy2(local(root,s[k]),out/'reference'/target)
            copied['actions'][action][k]=target;spec[k]='reference/'+target
        spec.update(alignment='reference_canvas',request=action+'-request.txt',status='awaiting_reference_review')
        background=('Use a perfectly uniform solid saturated magenta #FF00FF background, including gaps between bones and weapons. Do NOT draw a transparency checkerboard, white background, ground line, halo or shadow. The exporter keys this color to real alpha; the delivered atlas will be transparent.' if background_mode=='magenta' else 'Output genuine RGBA transparency, never a painted checkerboard or white background.')
        width=s['columns']*s['tile'][0];height=s['rows']*s['tile'][1]
        spec['request_draft']=(f'OUTPUT CANVAS: {width} x {height} pixels, aspect {width}:{height}. Exactly {s["columns"]} equal columns by {s["rows"]} equal rows. Never change the sheet aspect ratio. '
          f'Generate ONE coherent complete sprite sheet of {name}, not separate frame images. Reference 1 controls camera, silhouette, placement and every action phase; reference 2 supplies appearance ONLY, never its standing pose or camera. '
          'The body, head and both feet must match the projected orientation of reference 1, including when the appearance picture faces another direction. Do not copy and slightly vary the standing character. '
          f'Action {action}. Design: {json.dumps(s["design"],ensure_ascii=False)}. '
          f'Exactly {s["count"]} frames, {s["columns"]} columns and {s["rows"]} rows. Reference cell is {s["tile"][0]} by {s["tile"][1]}; total sheet aspect ratio must match it. '
          f'CELL COORDINATE CONTRACT: origin {s["origin"]}, ground y={s["floor_y"]} measured from EACH cell top. All rows share this same local coordinate. Scale all these coordinates uniformly if output size differs. '
          'Transfer the reference projected positions into the same cells; do not individually fit, recenter, resize, floor-align or rearrange poses. Ground-contact feet meet the common ground, airborne feet retain reference height, and falling bodies retain root displacement. '
          'Preserve the same head, body dimensions, clothes and weapon sizes. Sword and shield stay bound to their original hands and follow the arms naturally. Every cell must keep the entire character and equipment inside padding. Blue/orange guide limbs are labels, not costume colors. Trace their changing near/far support identities across BOTH rows, not just the first row. '
          +background+' '+('Complete both opposite support phases and flow back into the first pose without a duplicate endpoint.' if s['loop'] else 'End at the full-size settled final pose and hold; no shrinking or disappearance.')+'\n')
        spec['request_draft']+=motion.contract_module().endpoints(out,action,spec)
        job['actions'][action]=spec
    motion.write(out/'reference/bundle.json',copied);job['input_hashes']=motion.fingerprints(out,job);motion.write(out/'job.json',job)
    return {'job':str(out),'status':job['status'],'requests':[],'next':'Inspect imported reference playback and projected contacts, then review-reference to unlock whole-sheet generation requests.'}
