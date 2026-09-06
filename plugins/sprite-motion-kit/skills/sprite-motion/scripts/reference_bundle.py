"""Import a rendered, measured 3D reference without replacing its approved rig.

No model is bundled or called here. The host supplies source references and uses
the emitted full-sheet request with its image generator. Final export is still
subject to pose evidence, alpha, registration and visual review.
"""
import hashlib,json,math,re,shutil
from pathlib import Path
import numpy as np
from PIL import Image

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
    for name,s in data['actions'].items():
        if not re.fullmatch('[a-z][a-z0-9_-]{0,63}',name):raise ValueError('Unsafe action name')
        for k in ['intent','support_and_contact','phases','end_state']:motion.require_text(s.get('design',{}).get(k),'Missing action design '+k)
        for k in ['columns','rows','count']:
            if type(s.get(k)) is not int or s[k]<1:raise ValueError('Invalid grid/count')
        if s['count']<3 or s['count']>s['columns']*s['rows']:raise ValueError('Invalid action frame count')
        if type(s.get('loop')) is not bool or not math.isfinite(s.get('seconds',0)) or s['seconds']<=0:raise ValueError('Invalid duration/loop')
        phases=s.get('phases',[])
        if len(phases)!=s['count'] or phases[0]!=0 or any(not math.isfinite(x) or x<0 or x>1 or (s['loop'] and x==1) for x in phases) or any(a>=b for a,b in zip(phases,phases[1:])):raise ValueError('Invalid ordered phases')
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

def prepare(character,out,bundle,name,background_mode):
    import motion
    bundle=Path(bundle).resolve();root=bundle.parent;data=motion.read(bundle);validate(data,root)
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
        spec=dict(s)
        for k in ['guide','reference','landmarks']:
            suffix=Path(s[k]).suffix;target=f'{action}-{k}{suffix}'
            shutil.copy2(local(root,s[k]),out/'reference'/target)
            copied['actions'][action][k]=target;spec[k]='reference/'+target
        spec.update(alignment='reference_canvas',request=action+'-request.txt',status='awaiting_reference_review')
        background=('Use a perfectly uniform solid saturated magenta #FF00FF background, including gaps between bones and weapons. Do NOT draw a transparency checkerboard, white background, ground line, halo or shadow. The exporter keys this color to real alpha; the delivered atlas will be transparent.' if background_mode=='magenta' else 'Output genuine RGBA transparency, never a painted checkerboard or white background.')
        spec['request_draft']=(f'Generate ONE coherent complete sprite sheet of {name}, not separate frame images. Reference 1 gives the exact projected 3D action, reference 2 gives the character appearance. '
          f'Action {action}. Design: {json.dumps(s["design"],ensure_ascii=False)}. '
          f'Exactly {s["count"]} frames, {s["columns"]} columns and {s["rows"]} rows. Reference cell is {s["tile"][0]} by {s["tile"][1]}; total sheet aspect ratio must match it. '
          f'CELL COORDINATE CONTRACT: origin {s["origin"]}, ground y={s["floor_y"]} measured from EACH cell top. All rows share this same local coordinate. Scale all these coordinates uniformly if output size differs. '
          'Transfer the reference projected positions into the same cells; do not individually fit, recenter, resize, floor-align or rearrange poses. Ground-contact feet meet the common ground, airborne feet retain reference height, and falling bodies retain root displacement. '
          'Preserve the same head, body dimensions, clothes and weapon sizes. Sword and shield stay bound to their original hands and follow the arms naturally. Every cell must keep the entire character and equipment inside padding. Blue/orange guide limbs are labels, not costume colors. '
          +background+' '+('Complete both opposite support phases and flow back into the first pose without a duplicate endpoint.' if s['loop'] else 'End at the full-size settled final pose and hold; no shrinking or disappearance.')+'\n')
        job['actions'][action]=spec
    motion.write(out/'reference/bundle.json',copied);job['input_hashes']=motion.fingerprints(out,job);motion.write(out/'job.json',job)
    return {'job':str(out),'status':job['status'],'requests':[],'next':'Inspect imported reference playback and projected contacts, then review-reference to unlock whole-sheet generation requests.'}
