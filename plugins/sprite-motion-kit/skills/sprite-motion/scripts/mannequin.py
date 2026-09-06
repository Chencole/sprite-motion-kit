#!/usr/bin/env python3
"""Render AI-authored skeletal motion plans as local, orthographic 3D pose guides.

Only Pillow and NumPy are required. No model call, Blender or network is hidden
here. The host AI edits the rig and keyframes; this tool validates and renders.
"""
from __future__ import annotations
import argparse
import base64
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import numpy as np
from PIL import Image, ImageDraw

SKILL=Path(__file__).resolve().parents[1]
COLORS={'body':'#b99059','near':'#4d9ed3','far':'#de8846','head':'#d9b77d','extra':'#7caa82'}

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path,data):Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def safe_name(value):return isinstance(value,str) and re.fullmatch(r'[a-z][a-z0-9_-]{0,63}',value) is not None
def vector(value,n=3):
    return isinstance(value,list) and len(value)==n and all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in value)

def rig(body):
    nodes=[]
    def add(name,parent,offset,radius=.065,color='body'):
        nodes.append({'id':name,'parent':parent,'offset':offset,'radius':radius,'color':color})
    if body=='humanoid':
        add('pelvis',None,[0,1.04,0],.13)
        add('spine','pelvis',[0,.22,0],.12);add('chest','spine',[0,.23,0],.15)
        add('neck','chest',[0,.17,0],.07);add('head','neck',[0,.19,0],.14)
        add('nose','head',[.13,0,0],.04,'head')
        for side,z,color in [('near',.15,'near'),('far',-.15,'far')]:
            add(side+'_hip','pelvis',[0,-.06,z],.085,color)
            add(side+'_knee',side+'_hip',[0,-.45,0],.065,color)
            add(side+'_ankle',side+'_knee',[0,-.43,0],.055,color)
            add(side+'_toe',side+'_ankle',[.16,-.10,0],.055,color)
            add(side+'_shoulder','chest',[0,0,z*1.35],.085,color)
            add(side+'_elbow',side+'_shoulder',[0,-.28,0],.055,color)
            add(side+'_hand',side+'_elbow',[0,-.27,0],.07,color)
    elif body=='quadruped':
        add('pelvis',None,[-.4,.78,0],.18)
        add('chest','pelvis',[.8,0,0],.20);add('neck','chest',[.18,.22,0],.13)
        add('head','neck',[.25,.18,0],.17);add('nose','head',[.22,-.03,0],.09,'head')
        add('tail','pelvis',[-.35,.05,0],.075,'extra');add('tail_tip','tail',[-.35,-.1,0],.04,'extra')
        for end,parent in [('hind','pelvis'),('front','chest')]:
            for side,z,color in [('near',.19,'near'),('far',-.19,'far')]:
                name=end+'_'+side
                add(name+'_hip',parent,[0,-.06,z],.075,color)
                add(name+'_knee',name+'_hip',[.02,-.31,0],.055,color)
                add(name+'_ankle',name+'_knee',[-.02,-.31,0],.05,color)
                add(name+'_toe',name+'_ankle',[.13,-.1,0],.05,color)
    else:raise ValueError('Scaffold body must be humanoid or quadruped; edit joints for other bodies')
    return nodes

def matrix(euler):
    x,y,z=np.radians(euler);cx,sx=math.cos(x),math.sin(x);cy,sy=math.cos(y),math.sin(y);cz,sz=math.cos(z),math.sin(z)
    return np.array([[cz,-sz,0],[sz,cz,0],[0,0,1]])@np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]])@np.array([[1,0,0],[0,cx,-sx],[0,sx,cx]])

def positions(nodes,key):
    out={};rot={};root_rot=matrix(key.get('root_rotation',[0,0,0]));root=np.array(key.get('root',[0,0,0]),float)
    for node in nodes:
        parent=node['parent'];basis=root_rot if parent is None else rot[parent]
        # Root-node offset locates its pivot. Root rotation acts around that pivot.
        out[node['id']]=root+np.array(node['offset']) if parent is None else out[parent]+basis@node['offset']
        rot[node['id']]=basis@matrix(key.get('rotations',{}).get(node['id'],[0,0,0]))
    return out

def grounded(nodes,key):
    """Scaffold convenience only: lift the whole authored pose above the floor."""
    points=positions(nodes,key)
    lowest=min(points[n['id']][1]-n['radius'] for n in nodes)
    key['root'][1]-=lowest
    return key

def scaffold(body,actions,examples=False):
    nodes=rig(body);clips={}
    for name in actions:
        if not safe_name(name):raise ValueError('Action IDs use lowercase letters, digits, _ or -')
        keys=[];seconds=1.4 if name in ['walk','run'] else (1.2 if name=='jump' else 2.4)
        if not examples:
            keys=[grounded(nodes,{'time':t,'root':[0,0,0],'rotations':{}}) for t in [0,seconds]]
        elif name in ['walk','run']:
            for i in range(9):
                t=i/8;rots={}
                for n in nodes:
                    if not n['id'].endswith('_hip'):continue
                    side=0 if 'near' in n['id'] else .5
                    if body=='quadruped' and n['id'].startswith('hind'):side+=.5
                    phase=(t+side)%1;hip=27*math.cos(phase*2*math.pi)
                    knee=-8-48*max(0,-math.sin(phase*2*math.pi));prefix=n['id'][:-4]
                    rots[n['id']]=[0,0,hip];rots[prefix+'_knee']=[0,0,knee];rots[prefix+'_ankle']=[0,0,-hip-knee]
                    if body=='humanoid':rots[prefix+'_shoulder']=[0,0,-hip*.5];rots[prefix+'_elbow']=[0,0,-15]
                keys.append(grounded(nodes,{'time':round(t*seconds,6),'root':[0,0,0],'rotations':rots}))
            keys[-1]=copy.deepcopy(keys[0]);keys[-1]['time']=seconds
        elif name=='jump':
            for t,height,bend in [(0,0,0),(.18,-.12,55),(.32,.20,20),(.52,.75,40),(.72,.4,20),(.87,-.12,50),(1,0,0)]:
                rots={}
                for n in nodes:
                    if n['id'].endswith('_hip'):
                        prefix=n['id'][:-4];rots[n['id']]=[0,0,bend*.5];rots[prefix+'_knee']=[0,0,-bend];rots[prefix+'_ankle']=[0,0,bend*.5]
                k=grounded(nodes,{'time':round(t*seconds,6),'root':[0,0,0],'rotations':rots})
                k['root'][1]+=max(0,height);keys.append(k)
        elif name=='death':
            for t,angle,bend in [(0,0,0),(.15,8,35),(.32,30,55),(.50,65,40),(.67,90,15),(.80,90,0),(1,90,0)]:
                rots={}
                for n in nodes:
                    if n['id'].endswith('_knee'):rots[n['id']]=[0,0,-bend]
                # Quadrupeds roll onto a flank instead of using a human backward fall.
                rotation=[angle,0,0] if body=='quadruped' else [0,0,angle]
                keys.append(grounded(nodes,{'time':round(t*seconds,6),'root':[0,0,0],'root_rotation':rotation,'rotations':rots}))
        else:
            keys=[grounded(nodes,{'time':t,'root':[0,0,0],'rotations':{}}) for t in [0,seconds]]
        clips[name]={'description':f'AI: design a character-appropriate {name}; these are editable starter keys, not approved motion.',
            'seconds':seconds,'loop':name in ['walk','run'],'frame_count':8 if name in ['walk','run'] else 12,'columns':4,
            'interpolation':'smooth','keys':keys}
    return {'schema':2,'name':body+' motion study','design_status':'needs_motion_design','body':body,
        'camera':{'azimuth':0,'elevation':0},'frame_size':[384,384], 'joints':nodes,'actions':clips}

def validate(plan):
    if plan.get('schema')!=2:raise ValueError('Motion plan schema must be 2')
    if not isinstance(plan.get('name'),str):raise ValueError('Plan needs a name')
    size=plan.get('frame_size')
    if not vector(size,2) or any(not isinstance(x,int) or not 64<=x<=1024 for x in size):raise ValueError('frame_size must be two integers in 64..1024')
    camera=plan.get('camera',{})
    if any(not isinstance(camera.get(k),(int,float)) or not math.isfinite(camera[k]) or abs(camera[k])>360 for k in ['azimuth','elevation']):raise ValueError('Finite camera azimuth/elevation required')
    nodes=plan.get('joints',[]);seen=set();roots=0
    if not 2<=len(nodes)<=96:raise ValueError('Rig must have 2..96 joints')
    for n in nodes:
        name=n.get('id');parent=n.get('parent')
        if not safe_name(name) or name in seen:raise ValueError('Joint IDs must be unique safe names')
        if parent is None:roots+=1
        elif parent not in seen:raise ValueError('Joints must be parent-first; parent is missing or cyclic')
        if not vector(n.get('offset')) or max(abs(x) for x in n['offset'])>100:raise ValueError('Invalid joint offset')
        radius=n.get('radius')
        if not isinstance(radius,(int,float)) or not math.isfinite(radius) or not 0<radius<=10:raise ValueError('Invalid joint radius')
        if n.get('color','body') not in COLORS:raise ValueError('Unknown joint color group')
        seen.add(name)
    if roots!=1:raise ValueError('Rig needs exactly one root')
    actions=plan.get('actions',{})
    if not isinstance(actions,dict) or not 1<=len(actions)<=128:raise ValueError('Plan needs 1..128 actions; split larger exports into jobs')
    for name,a in actions.items():
        if not safe_name(name):raise ValueError('Unsafe action name')
        seconds=a.get('seconds');count=a.get('frame_count');cols=a.get('columns')
        if not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or not .05<=seconds<=60:raise ValueError('Duration must be .05..60 seconds')
        if not isinstance(count,int) or not 2<=count<=64 or not isinstance(cols,int) or not 1<=cols<=16:raise ValueError('Invalid frame_count/columns')
        if not isinstance(a.get('loop'),bool) or a.get('interpolation','smooth') not in ['linear','smooth']:raise ValueError('Invalid loop/interpolation')
        keys=a.get('keys',[])
        if not 2<=len(keys)<=128:raise ValueError('Each action needs 2..128 keys')
        times=[k.get('time') for k in keys]
        if any(not isinstance(t,(int,float)) or not math.isfinite(t) for t in times) or times[0]!=0 or abs(times[-1]-seconds)>1e-6 or any(b<=a for a,b in zip(times,times[1:])):raise ValueError('Key times must increase from 0 to duration')
        for key in keys:
            for field in ['root','root_rotation']:
                if not vector(key.get(field,[0,0,0])) or max(abs(x) for x in key.get(field,[0,0,0]))>1000:raise ValueError('Invalid root transform')
            if not isinstance(key.get('rotations',{}),dict):raise ValueError('rotations must be an object')
            for joint,angles in key.get('rotations',{}).items():
                if joint not in seen or not vector(angles) or max(abs(x) for x in angles)>360:raise ValueError('Unknown joint or invalid rotation')
        if a['loop']:
            first=positions(nodes,keys[0]);last=positions(nodes,keys[-1])
            if max(np.linalg.norm(first[j]-last[j]) for j in seen)>.001:raise ValueError(f'{name}: loop endpoints do not match; author a closing key')
    return {'valid':True,'joints':len(nodes),'actions':list(actions),'camera':camera,'design_status':plan.get('design_status','unspecified')}

def sample(action,time):
    keys=action['keys'];time=max(0,min(action['seconds'],time))
    right=next((i for i,k in enumerate(keys) if k['time']>=time),len(keys)-1)
    left=max(0,right-1);a,b=keys[left],keys[right]
    t=0 if right==left else (time-a['time'])/(b['time']-a['time'])
    if action.get('interpolation','smooth')=='smooth':t=t*t*(3-2*t)
    def mix(v,w,angles=False):
        v,w=np.array(v,float),np.array(w,float);delta=w-v
        if angles:delta=(delta+180)%360-180
        return (v+delta*t).tolist()
    rotations={j:mix(a.get('rotations',{}).get(j,[0,0,0]),b.get('rotations',{}).get(j,[0,0,0]),True) for j in set(a.get('rotations',{}))|set(b.get('rotations',{}))}
    return {'time':time,'root':mix(a.get('root',[0,0,0]),b.get('root',[0,0,0])),
        'root_rotation':mix(a.get('root_rotation',[0,0,0]),b.get('root_rotation',[0,0,0]),True),'rotations':rotations}

def triangles(nodes,points):
    result=[]
    def tri(a,b,c,color):result.append((np.array([a,b,c]),color))
    for n in nodes:
        center=points[n['id']];radius=n['radius'];color=COLORS[n.get('color','body')]
        # Low-resolution spheres/cylinders are a real shaded 3D pose proxy.
        for i in range(6):
            p0=math.pi*i/6;p1=math.pi*(i+1)/6
            for j in range(10):
                t0=2*math.pi*j/10;t1=2*math.pi*(j+1)/10
                def vertex(p,t):return center+radius*np.array([math.sin(p)*math.cos(t),math.cos(p),math.sin(p)*math.sin(t)])
                a,b,c,d=vertex(p0,t0),vertex(p1,t0),vertex(p1,t1),vertex(p0,t1)
                tri(a,b,c,color);tri(a,c,d,color)
        if n['parent'] is not None:
            start=points[n['parent']];axis=center-start;length=np.linalg.norm(axis)
            if length<1e-8:continue
            axis/=length;cross=np.array([0,1.,0]) if abs(axis[1])<.9 else np.array([1.,0,0])
            u=np.cross(axis,cross);u/=np.linalg.norm(u);v=np.cross(axis,u)
            for j in range(10):
                a0=2*math.pi*j/10;a1=2*math.pi*(j+1)/10
                offset=lambda a:radius*.68*(u*math.cos(a)+v*math.sin(a))
                a,b,c,d=start+offset(a0),center+offset(a0),center+offset(a1),start+offset(a1)
                tri(a,b,c,color);tri(a,c,d,color)
    return result

def render_frame(nodes,key,view,scale,origin,size):
    points=positions(nodes,key);image=Image.new('RGBA',size);draw=ImageDraw.Draw(image)
    light=np.array([-.4,.75,1.]);light/=np.linalg.norm(light);faces=[]
    for vertices,color in triangles(nodes,points):
        q=vertices@view.T;normal=np.cross(q[1]-q[0],q[2]-q[0]);length=np.linalg.norm(normal)
        if length<1e-10:continue
        shade=.35+.65*abs(float(normal@light/length))
        rgb=tuple(round(int(color[i:i+2],16)*shade) for i in [1,3,5])
        xy=[(origin[0]+p[0]*scale,origin[1]-p[1]*scale) for p in q]
        faces.append((float(q[:,2].mean()),xy,rgb+(255,)))
    for _,xy,color in sorted(faces,key=lambda f:f[0]):draw.polygon(xy,fill=color)
    return image,points

def data_url(path):return 'data:image/png;base64,'+base64.b64encode(Path(path).read_bytes()).decode()

def render(plan,out,preview_count=48):
    validate(plan);out=Path(out).resolve()
    if out.exists() and any(out.iterdir()):raise ValueError('Render into an empty directory; previous guides are preserved')
    out.mkdir(parents=True,exist_ok=True);write(out/'motion-plan.json',plan)
    view=matrix([-plan['camera']['elevation'],plan['camera']['azimuth'],0]);nodes=plan['joints'];size=plan['frame_size']
    # A single camera registration across ALL actions preserves jump height,
    # root travel, and full-size corpses. Never fit or floor-align each frame.
    bounds=[]
    for action in plan['actions'].values():
        for t in np.linspace(0,action['seconds'],max(49,action['frame_count'])):
            points=positions(nodes,sample(action,float(t)))
            for n in nodes:
                p=view@points[n['id']];r=n['radius'];bounds.extend([p[:2]-r,p[:2]+r])
    bounds=np.array(bounds);low=np.minimum(bounds.min(axis=0),[0,0]);high=np.maximum(bounds.max(axis=0),[0,0])
    scale=min((size[0]-40)/(high[0]-low[0]),(size[1]-40)/(high[1]-low[1]))
    origin=[round((size[0]-(high[0]+low[0])*scale)/2),round((size[1]+(high[1]+low[1])*scale)/2)]
    manifest={'schema':2,'plan_sha256':hashlib.sha256((out/'motion-plan.json').read_bytes()).hexdigest(),
        'frame_size':size,'origin':origin,'pixels_per_unit':scale,'camera':plan['camera'],'actions':{},'warnings':[]}
    entries=[]
    for name,action in plan['actions'].items():
        count=action['frame_count'];columns=action['columns'];rows=math.ceil(count/columns)
        guide=Image.new('RGBA',(size[0]*columns,size[1]*rows));atlas=Image.new('RGBA',(size[0]*preview_count,size[1]))
        frames=out/name;frames.mkdir();joint_frames=[]
        times=np.linspace(0,action['seconds'],count,endpoint=not action['loop'])
        for i,time in enumerate(times):
            im,points=render_frame(nodes,sample(action,float(time)),view,scale,origin,size)
            im.save(frames/f'pose-{i:03}.png');guide.alpha_composite(im,(i%columns*size[0],i//columns*size[1]))
            joint_frames.append({'time':float(time),'joints':{j:p.tolist() for j,p in points.items()}})
        write(frames/'joints.json',joint_frames);guide.save(out/f'{name}-guide.png')
        for i,time in enumerate(np.linspace(0,action['seconds'],preview_count,endpoint=not action['loop'])):
            im,_=render_frame(nodes,sample(action,float(time)),view,scale,origin,size);atlas.alpha_composite(im,(i*size[0],0))
        atlas.save(out/f'{name}-reference.png')
        spec={k:action[k] for k in ['seconds','loop']};spec.update({'count':count,'columns':columns,'rows':rows,
            'guide':f'{name}-guide.png','reference':f'{name}-reference.png','tile':size,'origin':origin,
            'alignment':'reference_canvas','description':action.get('description',''),
            'reference_layout':{'tile':size,'columns':preview_count,'count':preview_count}})
        manifest['actions'][name]=spec
        entries.append({'name':name,'image':data_url(out/f'{name}-reference.png'),'tile':size,'count':preview_count,'seconds':action['seconds'],'loop':action['loop']})
    write(out/'guide.json',manifest)
    template=(SKILL/'assets/guide-review.html').read_text(encoding='utf-8')
    (out/'guide-review.html').write_text(template.replace('__GUIDES__',json.dumps(entries).replace('<','\\u003c')),encoding='utf-8')
    return {'status':'awaiting_reference_review','guide':str(out/'guide.json'),'preview':str(out/'guide-review.html'),'actions':list(manifest['actions'])}

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('create');a.add_argument('--body',choices=['humanoid','quadruped'],default='humanoid');a.add_argument('--actions',nargs='+',required=True);a.add_argument('--example-motion',action='store_true');a.add_argument('--out',required=True)
    a=sub.add_parser('validate');a.add_argument('--plan',required=True)
    a=sub.add_parser('render');a.add_argument('--plan',required=True);a.add_argument('--out',required=True)
    args=parser.parse_args()
    try:
        if args.cmd=='create':
            path=Path(args.out)
            if path.exists():raise ValueError('Plan already exists')
            data=scaffold(args.body,args.actions,args.example_motion);validate(data);path.parent.mkdir(parents=True,exist_ok=True);write(path,data)
            result={'plan':str(path.resolve()),'status':'needs_motion_design','next':'Host AI: edit anatomy, keys, timing and description for the requested character; then validate/render.'}
        elif args.cmd=='validate':result=validate(read(args.plan))
        else:result=render(read(args.plan),args.out)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,KeyError,TypeError,OSError) as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
