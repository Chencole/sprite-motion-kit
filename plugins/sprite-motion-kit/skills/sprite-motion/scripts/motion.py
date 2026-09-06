#!/usr/bin/env python3
"""Portable, local sprite preparation, extraction and visual review.

AI generation is performed by the host agent's image tool, not by this script.
This module never reads credentials, opens the network, or modifies a game.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
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
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def job_read(job):
    job=Path(job).resolve()
    data=read(job/'job.json')
    if data.get('schema')!=1: raise ValueError('Unsupported job schema')
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

def prepare(character, out, actions=('walk','death'), name='the supplied character'):
    if not actions or any(a not in PRESETS for a in actions):raise ValueError('Choose walk and/or death')
    character=Path(character).resolve()
    if not character.is_file():raise ValueError('Character image does not exist')
    Image.open(character).verify()
    out=Path(out).resolve()
    if out.exists() and any(out.iterdir()):raise ValueError('Use a new empty job directory; existing work is preserved')
    out.mkdir(parents=True,exist_ok=True)
    Image.open(character).convert('RGBA').save(out/'character.png')
    data={'schema':1,'name':name,'status':'ready_for_generation','character':'character.png','actions':{}}
    for action in actions:
        spec=dict(PRESETS[action])
        shutil.copy2(SKILL/f'assets/{action}-guide.png',out/f'{action}-guide.png')
        shutil.copy2(SKILL/f'assets/{action}-reference.png',out/f'{action}-reference.png')
        prompt=request_text(action,name)
        (out/f'{action}-request.txt').write_text(prompt,encoding='utf-8')
        spec.update({'guide':f'{action}-guide.png','reference':f'{action}-reference.png','request':f'{action}-request.txt','status':'awaiting_generation'})
        data['actions'][action]=spec
    write(out/'job.json',data)
    return {'job':str(out),'status':data['status'],'requests':[str(out/f'{a}-request.txt') for a in actions],
            'next':'Host AI: inspect character and guide, then generate one complete action sheet using both references.'}

def remove_background(image, mode):
    rgba=np.array(image.convert('RGBA'))
    if mode=='auto':
        mode='alpha' if int(rgba[:,:,3].min())<255 else 'magenta'
    if mode=='magenta':
        c=rgba[:,:,:3].astype(np.int16)
        mask=np.minimum(c[:,:,0],c[:,:,2])-c[:,:,1]>30
        if float(mask.mean())<.01:raise ValueError('No usable transparency or magenta background. Do not import a baked checkerboard.')
        rgba[mask]=0
    elif mode!='alpha':raise ValueError('Background must be auto, alpha or magenta')
    if int(rgba[:,:,3].min())==255:raise ValueError('Image is fully opaque; provide alpha or a supported keyed background')
    return Image.fromarray(rgba)

def extract(raw, columns, rows, count, background='auto'):
    if columns<1 or rows<1 or not 1<=count<=columns*rows:raise ValueError('Invalid sheet grid')
    frames=[]
    for i in range(count):
        x,y=i%columns,i//columns
        box=(round(x*raw.width/columns),round(y*raw.height/rows),round((x+1)*raw.width/columns),round((y+1)*raw.height/rows))
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
                        'reference':data_url(job/spec['reference']),**clip})
    encoded=json.dumps(entries,ensure_ascii=False).replace('<','\\u003c')
    template=(SKILL/'assets/review.html').read_text(encoding='utf-8')
    (job/'review.html').write_text(template.replace('__CLIPS__',encoded),encoding='utf-8')

def pack(job, action, image, background='auto', columns=None, rows=None, count=None,
         seconds=None, phases=None, tile=(512,448), height=316, hold_from=None):
    job,data=job_read(job)
    if action not in data['actions']:raise ValueError('Action was not prepared in this job')
    spec=data['actions'][action]
    columns=columns if columns is not None else spec['columns']
    rows=rows if rows is not None else spec['rows']
    count=count if count is not None else spec['count']
    if columns<1 or rows<1 or not 1<=count<=columns*rows:raise ValueError('Invalid sheet grid')
    seconds=seconds if seconds is not None else spec['seconds']
    if not math.isfinite(seconds) or seconds<=0:raise ValueError('Duration must be positive and finite')
    phases=phases if phases is not None else [i/count for i in range(count)]
    if len(phases)!=count or phases[0]!=0 or any(not math.isfinite(p) or p<0 or p>=1 for p in phases) or any(a>=b for a,b in zip(phases,phases[1:])):
        raise ValueError('Phases must match frame count and strictly increase from zero to below one')
    raw=Image.open(image)
    sources=extract(raw,columns,rows,count,background)
    frames,anchors=align(sources,action,tile,height)
    if hold_from is not None:
        if action!='death' or not 0<=hold_from<count:raise ValueError('--hold-from is a valid zero-based death pose only')
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
          'source':saved_source.name,
          'source_sha256':hashlib.sha256(Path(image).read_bytes()).hexdigest()}
    write(dest/'clip.json',clip)
    spec['status']='packed';data['status']='awaiting_visual_review';write(job/'job.json',data)
    make_preview(job,data)
    return {'action':action,'count':count,'preview':str(job/'review.html'),'atlas':str(dest/'atlas.png'),
            'status':'awaiting_visual_review','notice':'Technical export does not certify a natural gait or consistent artwork.'}

def parser():
    p=argparse.ArgumentParser(description=__doc__)
    commands=p.add_subparsers(dest='command',required=True)
    a=commands.add_parser('prepare');a.add_argument('--character',required=True);a.add_argument('--out',required=True)
    a.add_argument('--name',default='the supplied character');a.add_argument('--actions',nargs='+',choices=PRESETS,default=list(PRESETS))
    a=commands.add_parser('pack');a.add_argument('--job',required=True);a.add_argument('--action',choices=PRESETS,required=True);a.add_argument('--image',required=True)
    a.add_argument('--background',choices=['auto','alpha','magenta'],default='auto')
    for key in ['columns','rows','count','hold-from']:a.add_argument('--'+key,type=int)
    a.add_argument('--seconds',type=float);a.add_argument('--phases',type=lambda x:[float(v) for v in x.split(',')])
    a.add_argument('--tile',type=lambda x:tuple(int(v) for v in x.lower().split('x')),default=(512,448));a.add_argument('--height',type=int,default=316)
    a=commands.add_parser('review');a.add_argument('--job',required=True)
    return p

def main():
    args=vars(parser().parse_args());command=args.pop('command')
    try:
        if command=='prepare':result=prepare(**args)
        elif command=='pack':result=pack(**args)
        else:
            job,data=job_read(args['job']);make_preview(job,data);result={'preview':str(job/'review.html')}
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,FileNotFoundError,KeyError) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr);return 2
    return 0

if __name__=='__main__':raise SystemExit(main())
