#!/usr/bin/env python3
"""Portable, local sprite preparation, extraction and visual review.

AI generation is performed by the host agent's image tool, not by this script.
This module never reads credentials, opens the network, or modifies a game.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import sys
import numpy as np
from PIL import Image, ImageDraw

SKILL = Path(__file__).resolve().parents[1]
PRESETS = {
    'walk': {'columns':4,'rows':2,'count':8,'seconds':4/3,'loop':True},
    'death': {'columns':4,'rows':3,'count':12,'seconds':2.375,'loop':False},
}

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def job_read(job):
    job=Path(job).resolve()
    data=read(job/'job.json')
    if data.get('schema') not in [1,2,3]: raise ValueError('Unsupported job schema')
    return job,data

def request_text(action, character_name):
    spec=PRESETS[action]
    common=(f'Create a complete {action} animation sprite sheet of the supplied character. '
        f'Reference 1 is the authoritative pure-side mannequin pose sheet. Reference 2 is character appearance: {character_name}. '
        f'Exactly {spec["count"]} full-body poses, {spec["columns"]} columns by {spec["rows"]} rows, in reference order. '
        'Keep the exact profile camera facing SCREEN RIGHT, same scale and same cell floor baseline. '
        'Copy each reference pose, not the appearance reference standing pose. Preserve the character\'s own pixel-art style, '
        'face, body proportions, limbs, clothing and weapons across every frame. Keep complete figures inside each cell with padding. '
        'Do not merge characters, cut across cells, or swap the anatomical identities of legs. '
        'Use a genuine transparent background; if transparency is unavailable use solid magenta #FF00FF, including between limbs. '
        'No checkerboard, white backdrop, labels, shadows, borders or extra effects. ')
    if action=='walk':
        return common+('The BLUE reference leg is near/right, ORANGE is far/left; these are pose labels, not clothing colors. '
            'Near leg swings rear-to-front in row 1 and supports front-to-rear in row 2; far leg does the opposite. '
            'Both rows follow contact, down, passing, up. Frame 5 is the opposite foot contact from frame 1. '
            'Complete normal alternating steps with weight transfer, heel contact, toe-off, and shoulder/hip counter-motion. '
            'Last pose flows into first without standing still or repeating the first frame. No running or limping. '
            'Small natural weapon/cape motion, not an attack.\n')
    return common+('Follow the reference from standing through losing balance and falling backward to a fully settled body. '
        'Do not shrink the character, replace it with a generic corpse, dissolve it or fade it away. '
        'Maintain the same body scale throughout; the prone body remains full size. '
        'Preserve distinctive anatomy and equipment; keep all limbs and any dropped weapon inside each cell. '
        'Final frames settle into the same corpse, which stays still. This action plays once and does not loop.\n')

def prepare(character, out, actions=None, name='the supplied character', motion_plan=None, legacy_reference_reason=None, frame_indices=None, reference_bundle=None, background_mode=None):
    if reference_bundle is not None:
        if any(v is not None for v in [motion_plan,legacy_reference_reason,frame_indices,actions]):raise ValueError('Reference bundle defines its own actions, timing and rig; do not combine preparation modes')
        import reference_bundle as bundle_module
        return bundle_module.prepare(character,out,reference_bundle,name,background_mode or 'magenta')
    if background_mode is not None:raise ValueError('Explicit background-mode currently requires reference-bundle; other job modes select background at pack')
    if motion_plan is not None:
        if frame_indices is not None:raise ValueError('Set frame_count in the custom plan instead')
        if legacy_reference_reason is not None:raise ValueError('Choose a custom plan or explicit legacy reuse, not both')
        return prepare_custom(character,out,motion_plan,actions,name)
    require_text(legacy_reference_reason,'A custom motion plan is required. Legacy reuse requires --legacy-reference-reason explaining why the approved reference fits this character.')
    actions=actions or tuple(PRESETS)
    if not actions or any(a not in PRESETS for a in actions):raise ValueError('Choose walk and/or death')
    if frame_indices is not None and (list(actions)!=['walk'] or len(frame_indices)<4 or frame_indices[0]!=0 or any(not isinstance(i,int) or not 0<=i<8 for i in frame_indices) or any(a>=b for a,b in zip(frame_indices,frame_indices[1:]))):
        raise ValueError('Explicit walk phases must increase from zero, with at least four indices in 0..7')
    character=Path(character).resolve()
    if not character.is_file():raise ValueError('Character image does not exist')
    Image.open(character).verify()
    out=Path(out).resolve()
    if out.exists() and any(out.iterdir()):raise ValueError('Use a new empty job directory; existing work is preserved')
    out.mkdir(parents=True,exist_ok=True)
    Image.open(character).convert('RGBA').save(out/'character.png')
    data={'schema':1,'legacy_reference_reason':legacy_reference_reason,'name':name,'status':'ready_for_generation','character':'character.png','actions':{}}
    for action in actions:
        spec=dict(PRESETS[action])
        shutil.copy2(SKILL/f'assets/{action}-guide.png',out/f'{action}-guide.png')
        shutil.copy2(SKILL/f'assets/{action}-reference.png',out/f'{action}-reference.png')
        prompt=request_text(action,name)
        if frame_indices is not None:
            guide=Image.open(out/f'{action}-guide.png');w,h=guide.width//4,guide.height//2
            cols=4;rows=math.ceil(len(frame_indices)/cols);selected=Image.new('RGBA',(w*cols,h*rows))
            for i,n in enumerate(frame_indices):selected.alpha_composite(guide.convert('RGBA').crop((n%4*w,n//4*h,n%4*w+w,n//4*h+h)),(i%cols*w,i//cols*h))
            selected.save(out/f'{action}-guide.png')
            spec.update(count=len(frame_indices),columns=cols,rows=rows,reference_indices=frame_indices,phases=[i/8 for i in frame_indices])
            prompt=(f'Create exactly {len(frame_indices)} full-body walk poses in {cols} columns by {rows} rows. Reference 1 is the approved pure-right-profile walking reference at phases {spec["phases"]}; reference 2 supplies character identity only. Match each distinct pose in order, preserve anatomical near/far legs, costume, weapons, fixed cell origin and scale. Opposite contacts must exchange legs and passing poses must carry the lifted knee ahead of the hip. Do not repeat the same rear-leg pose. Use transparent background or flat magenta, no labels, borders or missing limbs. This is a reduced-frame walk loop, not extra in-between images.\n')
        spec.update({'guide':f'{action}-guide.png','reference':f'{action}-reference.png','request':f'{action}-request.txt','status':'awaiting_generation'})
        prompt+=contract_module().endpoints(out,action,spec)
        (out/f'{action}-request.txt').write_text(prompt,encoding='utf-8')
        data['actions'][action]=spec
    write(out/'job.json',data)
    return {'job':str(out),'status':data['status'],'requests':[str(out/f'{a}-request.txt') for a in actions],
            'next':'Host AI: inspect character and guide, then generate one complete action sheet using both references.'}

def mannequin_module():
    spec=importlib.util.spec_from_file_location('sprite_mannequin',Path(__file__).with_name('mannequin.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def quality_module():
    spec=importlib.util.spec_from_file_location('sprite_quality',Path(__file__).with_name('quality.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def contract_module():
    spec=importlib.util.spec_from_file_location('sprite_contract',Path(__file__).with_name('sprite_contract.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def phase_inputs(job,action,out):
    job,data=job_read(job);verify_job_contract(job,data)
    spec=data['actions'][action]
    if data['schema'] in [2,3] and not data.get('reference_review'):raise ValueError('Review the whole reference before splitting phases')
    out=Path(out).resolve()
    if out.exists():raise ValueError('Use a new phase-input directory')
    out.mkdir(parents=True);guide=Image.open(job/spec['guide']);entries=[]
    for i in range(spec['count']):
        col,row=i%spec['columns'],i//spec['columns']
        box=(round(col*guide.width/spec['columns']),round(row*guide.height/spec['rows']),round((col+1)*guide.width/spec['columns']),round((row+1)*guide.height/spec['rows']))
        path=out/f'pose-{i:03}.png';guide.crop(box).save(path)
        entries.append({'frame':i,'reference':str(path),'reference_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
          'character':str(job/data['character']),'phase':spec.get('phases',[n/spec['count'] for n in range(spec['count'])])[i],
          'requirement':'Transfer this exact whole-body pose to the same character. A single pose image, not a new cycle. Keep fixed canvas, scale, anatomical identities and camera. Include original character plus accepted neighboring frame when available; never propagate a rejected neighbor.'})
    write(out/'phases.json',{'action':action,'guide_sha256':hashlib.sha256((job/spec['guide']).read_bytes()).hexdigest(),'count':spec['count'],'frames':entries})
    return {'phase_inputs':str(out/'phases.json'),'status':'references_only','next':'These cells support inspection of the whole-sheet sequence. Generate one complete action sheet with the complete guide; do not independently generate these cells. Splitting alone is not approval.'}

def require_text(value,label):
    if not isinstance(value,str) or not value.strip() or value.strip().lower() in ['todo','tbd','none','ai:']:
        raise ValueError(label)

def validate_design(plan):
    analysis=plan.get('character_analysis',{})
    for field in ['anatomy','mass_and_balance','equipment']:
        require_text(analysis.get(field),'Missing character_analysis.'+field)
    mannequin=mannequin_module()
    issues=quality_module().reference_issues(plan,mannequin)
    if issues:raise ValueError('Reference motion rejected: '+'; '.join(issues))
    for name,action in plan['actions'].items():
        design=action.get('design',{})
        for field in ['intent','support_and_contact','phases','end_state']:
            require_text(design.get(field),'Missing '+name+'.design.'+field)
        points=[mannequin.positions(plan['joints'],k) for k in action['keys']]
        if len(points)<3 or not any(any(np.linalg.norm(p[j]-points[0][j])>1e-5 for j in p) for p in points[1:]):
            raise ValueError(name+': neutral scaffold is not an authored motion; provide changing whole-body keys')

def fingerprints(job,data):
    if data['schema']==3:
        paths={'bundle':data['reference_bundle'],'character':data['character']}
        for a,s in data['actions'].items():
            for k in ['guide','reference','landmarks']:paths[k+':'+a]=s[k]
            if s.get('endpoint_reference'):paths['endpoints:'+a]=s['endpoint_reference']
        return {k:hashlib.sha256((job/v).read_bytes()).hexdigest() for k,v in paths.items()}
    paths={'plan':data['motion_plan'],'character':data['character']}
    paths.update({'guide:'+a:s['guide'] for a,s in data['actions'].items()})
    paths.update({'endpoints:'+a:s['endpoint_reference'] for a,s in data['actions'].items() if s.get('endpoint_reference')})
    return {k:hashlib.sha256((job/v).read_bytes()).hexdigest() for k,v in paths.items()}

def verify_job_contract(job,data):
    if data['schema']==1:
        require_text(data.get('legacy_reference_reason'),'Legacy job lacks explicit reuse reason; prepare again with a custom plan or explicit compatibility choice')
        return
    if data['schema']==3:
        import reference_bundle as bundle_module
        bundle_module.validate(read(job/data['reference_bundle']),job/'reference')
    else:validate_design(read(job/data['motion_plan']))
    if not data.get('input_hashes') or fingerprints(job,data)!=data['input_hashes']:
        raise ValueError('Character, plan or guide changed; prepare a new reviewed job before generation/export')

def review_reference(job,report):
    job,data=job_read(job);verify_job_contract(job,data)
    if data['schema'] not in [2,3]:raise ValueError('Reference review reports apply to custom or imported 3D jobs')
    if data.get('reference_review'):raise ValueError('Reference already reviewed; prepare a new job to revise it')
    report=read(report)
    if report.get('input_hashes')!=data['input_hashes']:raise ValueError('Review must identify the current character, plan and guides using input_hashes from job.json')
    for name,spec in data['actions'].items():
        check=report.get('actions',{}).get(name,{})
        for field in ['anatomy','support_and_contact','timing','camera','end_state']:
            if check.get(field) is not True:raise ValueError(name+': reference review must pass '+field)
        require_text(check.get('notes'),name+': document observed reference motion in review notes')
    for spec in data['actions'].values():
        if data['schema']!=3:(job/spec['request']).write_text(spec.pop('request_draft'),encoding='utf-8')
        spec['status']='awaiting_generation_preflight' if data['schema']==3 else 'awaiting_generation'
    data['reference_review']=report;data['status']='awaiting_generation_preflight' if data['schema']==3 else 'ready_for_generation';write(job/'job.json',data)
    return {'status':data['status'],'requests':[] if data['schema']==3 else [str(job/s['request']) for s in data['actions'].values()],
            'notice':'Review records agent observations; it does not automatically certify animation quality.'}

def generation_check(job,adapter):
    """Fail before a provider call when output size exists only in prompt prose."""
    job,data=job_read(job);verify_job_contract(job,data)
    if data['schema']!=3:raise ValueError('Generation preflight requires an imported reference bundle')
    if not data.get('reference_review'):raise ValueError('Inspect and review the reference first')
    provider=read(adapter)
    require_text(provider.get('name'),'Name the actual available generation tool')
    require_text(provider.get('evidence'),'Record the inspected tool schema or official adapter documentation')
    params=provider.get('parameters',[]);binding=provider.get('canvas_binding',{})
    if binding.get('kind')=='width_height':
        keys=[binding.get('width'),binding.get('height')]
    elif binding.get('kind')=='size_string':keys=[binding.get('parameter')]
    else:raise ValueError('Generation blocked before submission: tool has no structured canvas-size control. Prompt wording is not a hard size setting. Do not retry generation.')
    if any(not isinstance(k,str) or k not in params or k in ['prompt','text','instructions'] for k in keys) or len(set(keys))!=len(keys):raise ValueError('Canvas binding must use actual dedicated tool parameters, not prompt text')
    packets={}
    for action,s in data['actions'].items():
        w=s['columns']*s['tile'][0];h=s['rows']*s['tile'][1]
        if [w,h] not in provider.get('supported_sizes',[]):raise ValueError(f'Generation blocked: provider has no confirmed support for {w}x{h}; choose compatible reference dimensions before preparing a new job')
        controls={keys[0]:w,keys[1]:h} if len(keys)==2 else {keys[0]:f'{w}x{h}'}
        if 'request_draft' not in s:raise ValueError('Prepare a new job to add generation-time controls; old unlocked requests cannot be retroactively certified')
        packets[action]={'schema':1,'action':action,'provider':provider['name'],'tool_arguments':controls,'prompt':s['request_draft'],
          'references':[str(job/s['guide']),str(job/data['character'])]+([str(job/s['endpoint_reference'])] if s.get('endpoint_reference') else []),'input_hashes':data['input_hashes'],
          'endpoints':s.get('endpoints'),
          'canvas':[w,h],'grid':[s['columns'],s['rows']],'cell_origin':s['origin'],'cell_ground_y':s['floor_y'],
          'background_mode':data['background_mode'],'automatic_retry':False,
          'limitation':'Dedicated size controls constrain canvas only. Pose, grid contents and equipment continuity remain model outputs, not hard skeletal bindings.'}
    # Validate every action first: rejection above leaves job and output untouched.
    for action,packet in packets.items():
        s=data['actions'][action];write(job/(action+'-generation.json'),packet)
        (job/s['request']).write_text(s['request_draft'],encoding='utf-8');s['status']='awaiting_generation'
    data['generation_preflight']={'adapter':provider,'input_hashes':data['input_hashes']};data['status']='ready_for_generation';write(job/'job.json',data)
    return {'status':data['status'],'packets':[str(job/(a+'-generation.json')) for a in packets],'notice':'Pass tool_arguments as actual provider arguments; never silently move them into prose or retry rejected output.'}

def prepare_custom(character,out,motion_plan,actions,name):
    mannequin=mannequin_module();plan=read(motion_plan);mannequin.validate(plan)
    if plan.get('design_status')!='authored':raise ValueError('Host AI must design this motion plan and set design_status to authored before character generation preparation. Render draft guides directly for inspection.')
    validate_design(plan)
    if actions is not None:
        if not actions or any(a not in plan['actions'] for a in actions):raise ValueError('Requested action is missing from the motion plan')
        plan['actions']={a:plan['actions'][a] for a in actions}
    character=Path(character).resolve();Image.open(character).verify();out=Path(out).resolve()
    if out.exists() and any(out.iterdir()):raise ValueError('Use a new empty job directory; existing work is preserved')
    out.mkdir(parents=True,exist_ok=True);Image.open(character).convert('RGBA').save(out/'character.png')
    mannequin.render(plan,out/'reference')
    guide=read(out/'reference/guide.json')
    data={'schema':2,'name':name,'status':'awaiting_reference_review','character':'character.png',
          'motion_plan':'reference/motion-plan.json','plan_sha256':guide['plan_sha256'],'actions':{}}
    for action,spec in guide['actions'].items():
        spec=dict(spec);spec['guide']='reference/'+spec['guide'];spec['reference']='reference/'+spec['reference']
        spec['request']=f'{action}-request.txt';spec['status']='awaiting_reference_review'
        prompt=(f'Create {spec["count"]} coherent full-body {action} key poses of {name}. '
                f'Reference 1 is this job\'s custom 3D mannequin guide, {spec["columns"]} columns by {spec["rows"]} rows; reference 2 is character appearance. '
                f'Motion intent: {spec.get("description","")}. '
                f'Character analysis: {json.dumps(plan["character_analysis"],ensure_ascii=False)}. '
                f'Authored action design: {json.dumps(plan["actions"][action]["design"],ensure_ascii=False)}. '
                f'Camera azimuth {guide["camera"]["azimuth"]} degrees, elevation {guide["camera"]["elevation"]} degrees; match the guide exactly. '
                'Preserve anatomy, number of limbs, body scale, costume and equipment. The guide colors identify limbs, not costume colors. '
                'Copy each whole-body pose in order. Keep equal cells, padding, the SAME camera framing and floor coordinate in every frame; '
                'preserve jump height and falling/root displacement rather than centering or grounding each pose separately. '
                'Use true transparent alpha, or uniform magenta only if the character does not contain magenta. No labels, grid lines, scenery or baked checkerboard. '
                +('Complete a seamless cycle using opposite support phases; do not duplicate the first pose at the end.' if spec['loop'] else 'Play the whole action once in sequence, ending in the last intended pose; do not loop or shrink away.')+'\n')
        spec['request_draft']=prompt+contract_module().endpoints(out,action,spec);data['actions'][action]=spec
    data['input_hashes']=fingerprints(out,data)
    write(out/'job.json',data)
    return {'job':str(out),'status':data['status'],'reference_preview':str(out/'reference/guide-review.html'),
            'requests':[],
            'next':'Host AI: inspect this job\'s reference motion before generating character sheets. Repair the plan if its poses are wrong, then submit review-reference with observations to unlock requests.'}

def remove_background(image, mode):
    rgba=np.array(image.convert('RGBA'))
    if mode=='auto':
        mode='alpha' if int(rgba[:,:,3].min())<255 else 'magenta'
    if mode=='magenta':
        c=rgba[:,:,:3].astype(np.int16)
        mask=(c[:,:,0]>180)&(c[:,:,2]>170)&(c[:,:,1]<100)&(np.minimum(c[:,:,0],c[:,:,2])-c[:,:,1]>90)
        if float(mask.mean())<.01:raise ValueError('No usable transparency or magenta background. Do not import a baked checkerboard.')
        rgba[mask]=0
    elif mode!='alpha':raise ValueError('Background must be auto, alpha or magenta')
    if int(rgba[:,:,3].min())==255:raise ValueError('Image is fully opaque; provide alpha or a supported keyed background')
    edge=np.concatenate([rgba[0,:,3],rgba[-1,:,3],rgba[:,0,3],rgba[:,-1,3]])
    if float((edge<=8).mean())<.98:raise ValueError('Cell background is not transparent around its perimeter; a token alpha pixel does not make a checkerboard transparent')
    return Image.fromarray(rgba)

def extract(raw, columns, rows, count, background='auto',rectangles=None):
    if columns<1 or rows<1 or not 1<=count<=columns*rows:raise ValueError('Invalid sheet grid')
    frames=[]
    for i in range(count):
        x,y=i%columns,i//columns
        box=rectangles[i] if rectangles is not None else (round(x*raw.width/columns),round(y*raw.height/rows),round((x+1)*raw.width/columns),round((y+1)*raw.height/rows))
        f=remove_background(raw.crop(box),background)
        b=f.getbbox()
        if b is None:raise ValueError(f'Frame {i} is empty')
        if b[0]==0 or b[1]==0 or b[2]==f.width or b[3]==f.height:
            raise ValueError(f'Frame {i} touches a cell edge. Check cropping/grid before export.')
        frames.append(f)
    return frames

def align(frames, action, tile=(512,448), body_height=316):
    tw,th=tile
    if tw<16 or th<16 or body_height<=0 or body_height>th-16:raise ValueError('Invalid tile or body height')
    floor=th-52
    heights=[f.getbbox()[3]-f.getbbox()[1] for f in frames]
    scale=body_height/(heights[0] if action=='death' else float(np.median(heights)))
    # One scale for the entire animation. Death retains its horizontal fall.
    head_x=[]
    for f in frames:
        b=f.getbbox()
        _,xs=np.where(np.asarray(f)[b[1]:b[1]+max(6,int(24/scale)),:,3]>128)
        head_x.append(float(np.median(xs)))
    death_tx=round((tw-frames[0].width*scale)/2)
    result=[]; anchors=[]
    for i,f in enumerate(frames):
        b=f.getbbox()
        tx=death_tx if action=='death' else round(tw/2-head_x[i]*scale)
        ty=round(floor-b[3]*scale)
        target=f.resize((round(f.width*scale),round(f.height*scale)),Image.Resampling.NEAREST)
        tb=target.getbbox()
        if tb[0]+tx<0 or tb[1]+ty<0 or tb[2]+tx>tw or tb[3]+ty>th:
            raise ValueError(f'Frame {i} will be cropped. Increase tile dimensions or reduce --height.')
        canvas=Image.new('RGBA',tile)
        canvas.alpha_composite(target,(tx,ty))
        result.append(canvas)
        anchors.append({'translation':[tx,ty],'scale':scale,'origin':[tw//2,floor],'bounds':canvas.getbbox()})
    return result,anchors

def data_url(path):
    return 'data:image/png;base64,'+base64.b64encode(Path(path).read_bytes()).decode()

def make_preview(job, data):
    entries=[]
    for action,spec in data['actions'].items():
        if spec.get('status')!='packed':continue
        clip=read(job/action/'clip.json')
        entries.append({'name':action,'character':data_url(job/action/'atlas.png'),
                        'reference':data_url(job/spec['reference']),
                        'reference_layout':spec.get('reference_layout',{'tile':[256,320],'columns':12,'count':72}),**clip})
    encoded=json.dumps(entries,ensure_ascii=False).replace('<','\\u003c')
    template=(SKILL/'assets/review.html').read_text(encoding='utf-8')
    (job/'review.html').write_text(template.replace('__CLIPS__',encoded),encoding='utf-8')

def align_registered(frames,tile,reference_tile,reference_origin):
    """One canvas transform preserves airborne/falling motion; no per-frame fitting."""
    tw,th=tile;rw,rh=reference_tile
    if len(tile)!=2 or min(tile)<16:raise ValueError('Invalid tile')
    fit=min(tw/rw,th/rh);offset=[(tw-rw*fit)/2,(th-rh*fit)/2]
    result=[];anchors=[]
    for i,f in enumerate(frames):
        if abs(f.width/f.height-rw/rh)>.04:raise ValueError('Generated cell aspect differs from guide. Check grid; do not stretch the character.')
        resized=f.resize((round(rw*fit),round(rh*fit)),Image.Resampling.NEAREST)
        canvas=Image.new('RGBA',tile);canvas.alpha_composite(resized,tuple(round(v) for v in offset));result.append(canvas)
        anchors.append({'translation':offset,'scale':fit,'origin':[round(reference_origin[k]*fit+offset[k]) for k in range(2)],'bounds':canvas.getbbox()})
    return result,anchors

def align_canvas(frames,tile,height):
    """One union-bound transform: never individually recenter or ground poses."""
    bounds=[f.getbbox() for f in frames]
    left=min(b[0] for b in bounds);top=min(b[1] for b in bounds)
    right=max(b[2] for b in bounds);bottom=max(b[3] for b in bounds)
    scale=height/(bottom-top);tx=round(tile[0]/2-(left+right)/2*scale);ty=round(tile[1]-24-bottom*scale)
    result=[];meta=[]
    for i,f in enumerate(frames):
        target=f.resize((round(f.width*scale),round(f.height*scale)),Image.Resampling.NEAREST);b=target.getbbox()
        if min(tx+b[0],ty+b[1])<0 or tx+b[2]>tile[0] or ty+b[3]>tile[1]:raise ValueError('Fixed canvas clips a pose; increase tile')
        canvas=Image.new('RGBA',tile);canvas.alpha_composite(target,(tx,ty));result.append(canvas)
        meta.append({'translation':[tx,ty],'scale':scale,'origin':[tile[0]//2,tile[1]-24],'bounds':canvas.getbbox()})
    return result,meta

def pack(job, action, image, background='auto', columns=None, rows=None, count=None,
         seconds=None, phases=None, tile=None, height=316, hold_from=None, observations=None, draft=False,crop_plan=None):
    job,data=job_read(job)
    verify_job_contract(job,data)
    if data['schema'] in [2,3] and not data.get('reference_review'):raise ValueError('Reference motion has not been reviewed; run review-reference before export')
    if data['schema']==3 and not draft and not data.get('generation_preflight'):raise ValueError('Generation-time canvas controls were not verified; only a diagnostic draft may be inspected')
    if action not in data['actions']:raise ValueError('Action was not prepared in this job')
    spec=data['actions'][action]
    if not isinstance(action,str) or not __import__('re').fullmatch(r'[a-z][a-z0-9_-]{0,63}',action):raise ValueError('Unsafe action name')
    tile=tuple(tile or spec.get('tile',[512,448]))
    columns=columns if columns is not None else spec['columns']
    rows=rows if rows is not None else spec['rows']
    count=count if count is not None else spec['count']
    if columns<1 or rows<1 or not 1<=count<=columns*rows:raise ValueError('Invalid sheet grid')
    seconds=seconds if seconds is not None else spec['seconds']
    if not math.isfinite(seconds) or seconds<=0:raise ValueError('Duration must be positive and finite')
    phases=phases if phases is not None else spec.get('phases',[i/count for i in range(count)])
    if len(phases)!=count or phases[0]!=0 or any(not math.isfinite(p) or p<0 or p>1 or (p==1 and spec['loop']) for p in phases) or any(a>=b for a,b in zip(phases,phases[1:])):
        raise ValueError('Phases must strictly increase from zero; only non-looping actions may include the settled endpoint one')
    if not draft:
        expected_phases=spec.get('phases',[i/spec['count'] for i in range(spec['count'])])
        if (columns,rows,count)!=(spec['columns'],spec['rows'],spec['count']) or list(phases)!=list(expected_phases):
            raise ValueError('Export grid, frame count and phases must match the pose-review contract. Prepare and review a revised job; use --draft only for diagnostics.')
    raw=Image.open(image)
    if data['schema']==3 and background not in ['auto',data['background_mode']]:raise ValueError('Background mode must match prepared generation contract')
    if data['schema']==3 and background=='auto':background=data['background_mode']
    crop_data=None;rectangles=None
    if crop_plan is not None:crop_data,rectangles=contract_module().load_crop(crop_plan,image,columns,rows,count,require_review=not draft)
    sources=extract(raw,columns,rows,count,background,rectangles)
    sequence_result=None
    if not draft:
        if observations is None:raise ValueError('Per-frame pose observations required before export. Use --draft only for isolated review, never delivery.')
        if spec.get('endpoints') and crop_plan is None:raise ValueError('New jobs require an inspected crop plan before final export; use crop-template and inspect its overlay')
        report=read(observations)
        if crop_data is not None and report.get('crop_plan_sha256')!=contract_module().digest(crop_plan):raise ValueError('Pose observations and export must use the identical reviewed crop plan')
        if crop_data is None and report.get('crop_plan_sha256'):raise ValueError('Supply the same crop plan used by pose observations')
        sequence_result=quality_module().check(job,data,action,image,report,mannequin_module(),rectangles)
        if count!=len(read(observations)['frames']):raise ValueError('Cannot change reviewed frame count')
    if spec.get('alignment')=='reference_canvas':frames,anchors=align_registered(sources,tile,spec['tile'],spec['origin'])
    else:frames,anchors=align_canvas(sources,tile,height)
    if hold_from is not None:
        if spec['loop'] or not 0<=hold_from<count:raise ValueError('--hold-from requires a valid zero-based pose in a non-looping action')
        for i in range(hold_from+1,count):
            frames[i]=frames[hold_from].copy()
            anchors[i]=dict(anchors[hold_from])
    dest=job/action;dest.mkdir(exist_ok=True)
    source=Path(image).resolve()
    saved_source=dest/('generated-source'+source.suffix.lower())
    if source!=saved_source.resolve():shutil.copy2(source,saved_source)
    tw,th=tile
    atlas=Image.new('RGBA',(tw*count,th))
    contact=Image.new('RGB',(tw*4,(th+24)*math.ceil(count/4)),'#26343e')
    for i,f in enumerate(frames):
        f.save(dest/f'frame-{i:03}.png');atlas.alpha_composite(f,(tw*i,0))
        x,y=i%4*tw,i//4*(th+24);contact.paste(f,(x,y),f)
        ImageDraw.Draw(contact).text((x+8,y+th+5),str(i+1),fill='white')
    atlas.save(dest/'atlas.png');contact.save(dest/'contact.png')
    clip={'schema':1,'action':action,'atlas':'atlas.png','tile':list(tile),'count':count,'seconds':seconds,
          'phases':phases,'loop':spec['loop'],'origin':anchors[0]['origin'],'frames':anchors,
          'hold_from':hold_from,'visual_review_passed':False,
          'alignment':spec.get('alignment','legacy_ground_registration'),'plan_sha256':data.get('plan_sha256'),
          'source':saved_source.name,
          'source_sha256':hashlib.sha256(Path(image).read_bytes()).hexdigest(),
          'draft':draft,'sequence_check':sequence_result}
    if crop_plan is not None:
        shutil.copy2(crop_plan,dest/'crop-plan.json');clip['crop_plan_sha256']=contract_module().digest(crop_plan)
    if observations is not None:
        shutil.copy2(observations,dest/'pose-observations.json')
    write(dest/'clip.json',clip)
    spec['status']='packed';data['status']='awaiting_visual_review';write(job/'job.json',data)
    make_preview(job,data)
    return {'action':action,'count':count,'preview':str(job/'review.html'),'atlas':str(dest/'atlas.png'),
            'status':'awaiting_visual_review','notice':'Technical export does not certify a natural gait or consistent artwork.'}

def parser():
    p=argparse.ArgumentParser(description=__doc__)
    commands=p.add_subparsers(dest='command',required=True)
    a=commands.add_parser('prepare');a.add_argument('--character',required=True);a.add_argument('--out',required=True)
    a.add_argument('--name',default='the supplied character');a.add_argument('--actions',nargs='+');a.add_argument('--motion-plan');a.add_argument('--legacy-reference-reason')
    a.add_argument('--frame-indices',nargs='+',type=int)
    a.add_argument('--reference-bundle');a.add_argument('--background-mode',choices=['alpha','magenta'],help='Imported reference bundles only; defaults to magenta')
    a=commands.add_parser('pack');a.add_argument('--job',required=True);a.add_argument('--action',required=True);a.add_argument('--image',required=True)
    a.add_argument('--background',choices=['auto','alpha','magenta'],default='auto')
    a.add_argument('--observations');a.add_argument('--draft',action='store_true')
    a.add_argument('--crop-plan')
    for key in ['columns','rows','count','hold-from']:a.add_argument('--'+key,type=int)
    a.add_argument('--seconds',type=float);a.add_argument('--phases',type=lambda x:[float(v) for v in x.split(',')])
    a.add_argument('--tile',type=lambda x:tuple(int(v) for v in x.lower().split('x')));a.add_argument('--height',type=int,default=316)
    a=commands.add_parser('review-reference');a.add_argument('--job',required=True);a.add_argument('--report',required=True)
    a=commands.add_parser('generation-check');a.add_argument('--job',required=True);a.add_argument('--adapter',required=True)
    a=commands.add_parser('pose-template');a.add_argument('--job',required=True);a.add_argument('--action',required=True);a.add_argument('--image',required=True);a.add_argument('--out',required=True)
    a.add_argument('--crop-plan')
    a=commands.add_parser('crop-template');a.add_argument('--image',required=True);a.add_argument('--out',required=True)
    for k in ['columns','rows','count']:a.add_argument('--'+k,type=int,required=True)
    a=commands.add_parser('crop-overlay');a.add_argument('--image',required=True);a.add_argument('--plan-path',required=True);a.add_argument('--out',required=True)
    a=commands.add_parser('phase-inputs');a.add_argument('--job',required=True);a.add_argument('--action',required=True);a.add_argument('--out',required=True)
    a=commands.add_parser('review');a.add_argument('--job',required=True)
    return p

def main():
    args=vars(parser().parse_args());command=args.pop('command')
    try:
        if command=='prepare':result=prepare(**args)
        elif command=='pack':result=pack(**args)
        elif command=='review-reference':result=review_reference(**args)
        elif command=='generation-check':result=generation_check(**args)
        elif command=='crop-template':result=contract_module().crop_template(**args)
        elif command=='crop-overlay':result=contract_module().crop_overlay(**args)
        elif command=='phase-inputs':result=phase_inputs(**args)
        elif command=='pose-template':
            job,data=job_read(args['job']);verify_job_contract(job,data)
            result=quality_module().observations_template(job,data,args['action'],args['image'],mannequin_module())
            if args.get('crop_plan'):
                s=data['actions'][args['action']];contract_module().load_crop(args['crop_plan'],args['image'],s['columns'],s['rows'],s['count'])
                result['crop_plan_sha256']=contract_module().digest(args['crop_plan'])
            write(args['out'],result)
            result={'observations_template':str(Path(args['out']).resolve()),'status':'needs_actual_pixel_observations'}
        else:
            job,data=job_read(args['job']);make_preview(job,data);result={'preview':str(job/'review.html')}
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,FileNotFoundError,KeyError) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr);return 2
    return 0

if __name__=='__main__':raise SystemExit(main())
