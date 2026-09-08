"""Convert measured 3D joint projections into actual sequence conditioning.

This prepares inputs, never calls a model. Coordinates and phase order are kept
verbatim; no image-based pose detector or new procedural gait is involved.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile

from PIL import Image, ImageDraw
import motion

# OpenPose COCO-18 channel order, as consumed by SD1.5 OpenPose ControlNet.
# Facial joints are optional. A mesh head center is NOT a measured nose.
JOINTS = ('nose', 'neck', 'right_shoulder', 'right_elbow', 'right_wrist',
          'left_shoulder', 'left_elbow', 'left_wrist', 'right_hip',
          'right_knee', 'right_ankle', 'left_hip', 'left_knee', 'left_ankle',
          'right_eye', 'left_eye', 'right_ear', 'left_ear')
EDGES = ((1,2),(1,5),(2,3),(3,4),(5,6),(6,7),(1,8),(8,9),(9,10),
         (1,11),(11,12),(12,13),(1,0),(0,14),(14,16),(0,15),(15,17))
COLORS = ((255,0,0),(255,85,0),(255,170,0),(255,255,0),(170,255,0),
          (85,255,0),(0,255,0),(0,255,85),(0,255,170),(0,255,255),
          (0,170,255),(0,85,255),(0,0,255),(85,0,255),(170,0,255),
          (255,0,255),(255,0,170),(255,0,85))


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mapped_points(frame, mapping, size):
    """Explicit anatomical mapping, fixed for the whole clip; no x-sorting."""
    if set(mapping) - set(JOINTS):
        raise ValueError('Unknown OpenPose target joint')
    needed = set(JOINTS[2:14])
    if not needed.issubset(mapping):
        raise ValueError('Map both shoulders, elbows, wrists, hips, knees and ankles')
    sources = list(mapping.values())
    if any(not isinstance(s,str) or not s for s in sources) or len(set(sources)) != len(sources):
        raise ValueError('Each anatomical joint needs a distinct measured source')
    points = {}
    for target, source in mapping.items():
        value = frame.get(source)
        if not isinstance(value,list) or len(value)!=2 or any(type(x) not in (float,int) or not math.isfinite(x) for x in value):
            raise ValueError('Missing or invalid projected joint: '+source)
        if not (0 <= value[0] < size[0] and 0 <= value[1] < size[1]):
            raise ValueError('Projected joint is outside the fixed canvas: '+source)
        points[target] = list(value)
    if 'neck' not in points:
        # Explicit geometric midpoint, not a guessed face/body measurement.
        points['neck'] = [(a+b)/2 for a,b in zip(points['right_shoulder'],points['left_shoulder'])]
    return points


def draw_openpose(points, size):
    """RGB channel colors and ellipse limbs follow OpenPose control-map format.

    Format reference: huggingface/controlnet_aux open_pose/util.py draw_bodypose.
    Pillow drawing avoids introducing a pose-detector dependency or model.
    """
    image = Image.new('RGB',size,(0,0,0)); draw = ImageDraw.Draw(image)
    for (i,j), color in zip(EDGES,COLORS):
        if JOINTS[i] not in points or JOINTS[j] not in points:
            continue
        a,b=points[JOINTS[i]],points[JOINTS[j]]
        dx,dy=b[0]-a[0],b[1]-a[1]; length=math.hypot(dx,dy)
        if length<1e-8:continue
        cx,cy=(a[0]+b[0])/2,(a[1]+b[1])/2; ux,uy=dx/length,dy/length
        polygon=[]
        for n in range(36):
            angle=n*math.tau/36; along=length/2*math.cos(angle); across=4*math.sin(angle)
            polygon.append((cx+along*ux-across*uy,cy+along*uy+across*ux))
        draw.polygon(polygon,fill=tuple(int(c*.6) for c in color))
    for joint,color in zip(JOINTS,COLORS):
        if joint in points:
            x,y=points[joint];draw.ellipse((x-4,y-4,x+4,y+4),fill=color)
    return image


def prepare(job, action, mapping_file, out):
    job,data=motion.job_read(job);motion.verify_job_contract(job,data)
    if data['schema']!=3:
        raise ValueError('This experimental converter requires measured imported 3D projections; do not infer anatomy from proxy pixels')
    if not data.get('reference_review'):
        raise ValueError('Review the actual 3D reference first')
    if action not in data['actions']:raise ValueError('Action is absent from the job')
    mapping=motion.read(mapping_file)
    if mapping.get('body')!='humanoid' or not mapping.get('anatomical_mapping_reason','').strip():
        raise ValueError('Declare humanoid anatomy and explain the measured left/right mapping')
    spec=data['actions'][action];size=tuple(spec['tile']);count=spec['count']
    if any(type(n)is not int or n<=0 or n%8 for n in size):
        raise ValueError('Use original reference dimensions divisible by 8; this path never silently resizes')
    source=motion.read(job/spec['landmarks'])['frames']
    if len(source)!=count:raise ValueError('Projected frames must match the exact selected guide phases')
    points=[mapped_points(f,mapping['joints'],size) for f in source]
    images=[draw_openpose(p,size) for p in points]
    target=Path(out).resolve()
    if target.exists():raise ValueError('Use a new output directory; original art is preserved')
    target.parent.mkdir(parents=True,exist_ok=True)
    # Assemble privately and publish the complete input package atomically.
    with tempfile.TemporaryDirectory(prefix='.conditioning-',dir=target.parent) as temp:
        work=Path(temp);entries=[]
        for i,image in enumerate(images):
            path=work/f'control-{i:03}.png';image.save(path)
            entries.append({'path':path.name,'sha256':fingerprint(path)})
        character=job/data['character'];shutil.copy2(character,work/'character.png')
        cols=spec['columns'];rows=math.ceil(count/cols)
        sheet=Image.new('RGB',(cols*size[0],rows*size[1]))
        for i,image in enumerate(images):sheet.paste(image,((i%cols)*size[0],(i//cols)*size[1]))
        sheet.save(work/'control-sheet.png')
        result={'schema':1,'action':action,'frame_count':count,'width':size[0],'height':size[1],
                'columns':cols,'seconds':spec['seconds'],'loop':spec['loop'],'phases':spec['phases'],
                'origin':spec['origin'],'floor_y':spec['floor_y'],
                'character':{'path':'character.png','sha256':fingerprint(character)},
                'controls':[{'type':'openpose','frames':entries}],
                'input_hashes':data['input_hashes'],'approval':'diagnostic_only',
                'anatomical_mapping':mapping,'mapped_points':points,
                'generation_executed':False,
                'limitations':['OpenPose body channels do not encode sword/shield geometry, toes, fingers or unseen facial joints.',
                               'A shoulder midpoint is used for neck only when no measured neck mapping is supplied.',
                               'Pose/identity/time conditioning remains statistical, not an exact skeleton or loop lock.',
                               'This action study does not satisfy the five-action full-character requirement.']}
        motion.write(work/'conditioning.json',result)
        work.rename(target)
    return {'conditioning':str(target/'conditioning.json'),'generation_executed':False,'status':'conditioning_prepared'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',required=True);parser.add_argument('--action',required=True)
    parser.add_argument('--mapping',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args()
    try: print(json.dumps(prepare(args.job,args.action,args.mapping,args.out),ensure_ascii=False))
    except (ValueError,KeyError,OSError) as error: parser.exit(2,str(error)+'\n')
