"""Evidence-based row registration; never floor-align every animation frame."""
import math
from PIL import Image
import sprite_contract as contract

def register(clean,plan,evidence):
    if evidence.get('source_sha256')!=plan['source_sha256'] or evidence.get('boxes')!=plan['boxes']:raise ValueError('Registration evidence belongs to different source or crop geometry')
    columns,rows,count=plan['grid'];rects=plan['boxes']
    contacts=evidence.get('contacts',[])
    if len(contacts)!=rows:raise ValueError('Record one inspected ground contact per source row; do not infer ground from airborne frame bottoms')
    grounds=[]
    for row,c in enumerate(contacts):
        i=c.get('frame');point=c.get('source_point')
        if type(i)is not int or not 0<=i<count or i//columns!=row or not c.get('notes','').strip():raise ValueError('Ground evidence must identify an inspected contact frame in each row')
        if not isinstance(point,list) or len(point)!=2 or any(type(v)is not int for v in point):raise ValueError('Ground contact needs integer source coordinates')
        x,y=point;r=rects[i]
        if not(r[0]<=x<r[2] and r[1]<=y<r[3]) or clean.getpixel((x,y))[3]<=8:raise ValueError('Ground contact must touch visible foreground in the specified frame')
        grounds.append(y-r[1])
    target=grounds[0];offsets=[target-y for y in grounds]
    top=max(0,-min(offsets));offsets=[v+top for v in offsets]
    w=max(r[2]-r[0] for r in rects);h=max(r[3]-r[1]+offsets[i//columns] for i,r in enumerate(rects))
    frames=[]
    for i,r in enumerate(rects):
        canvas=Image.new('RGBA',(w,h));canvas.alpha_composite(clean.crop(r),(0,offsets[i//columns]));frames.append(canvas)
    return frames,{'row_ground_y':grounds,'row_translation_y':offsets,'common_ground_y':target+top,'global_top_padding':top,'contacts':contacts,'source_sha256':plan['source_sha256']}
