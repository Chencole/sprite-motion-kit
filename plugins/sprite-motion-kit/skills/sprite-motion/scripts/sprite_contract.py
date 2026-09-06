"""Explicit endpoint references and source-bound fixed crop geometry."""
import hashlib,json,math
from pathlib import Path
from PIL import Image,ImageDraw

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def endpoints(job,action,spec):
    phases=spec.get('phases',[i/(spec['count'] if spec['loop'] else spec['count']-1) for i in range(spec['count'])])
    spec['phases']=phases
    contract={'first_frame':0,'last_frame':spec['count']-1,'first_phase':phases[0],
      'last_phase':phases[-1],'transition':'last_to_first' if spec['loop'] else 'hold_last',
      'duplicate_first_at_end':False,'guide_sha256':digest(job/spec['guide'])}
    with Image.open(job/spec['guide']) as guide:
        w,h=guide.width/spec['columns'],guide.height/spec['rows'];tw,th=round(w),round(h)
        strip=Image.new('RGBA',(tw*3,th))
        for col,i in enumerate([0,spec['count']-1,0 if spec['loop'] else spec['count']-1]):
            x,y=i%spec['columns'],i//spec['columns']
            strip.paste(guide.crop((round(x*w),round(y*h),round((x+1)*w),round((y+1)*h))),(col*tw,0))
    path=action+'-endpoints.png';strip.save(job/path)
    spec['endpoints']=contract;spec['endpoint_reference']=path
    return (' ENDPOINT CONTRACT: reference 3 shows FIRST pose, LAST pose, then NEXT playback pose. '
      +('Last must continue into first with the same limb identities and natural next-step direction; do not duplicate the first pose as the last frame or pause.' if spec['loop'] else 'Start at the first pose, finish at the last reference pose and HOLD it at full size; never wrap back to standing.')
      +' Keep equipment attached throughout the endpoint transition. The complete guide still controls all intermediate phases. ')

def boxes(plan,size,columns,rows,count):
    if plan.get('schema') not in [1,2] or plan.get('image_size')!=list(size):raise ValueError('Crop plan dimensions do not match source')
    if plan.get('grid')!=[columns,rows,count]:raise ValueError('Crop plan frame grid differs from action')
    rects=plan.get('boxes',[])
    if len(rects)!=count:raise ValueError('Crop plan needs every frame in order')
    for r in rects:
        if not isinstance(r,list) or len(r)!=4 or any(type(v)is not int for v in r) or not(0<=r[0]<r[2]<=size[0] and 0<=r[1]<r[3]<=size[1]):raise ValueError('Invalid crop rectangle')
    widths=[r[2]-r[0] for r in rects];heights=[r[3]-r[1] for r in rects]
    if plan.get('schema')==1 and (max(widths)-min(widths)>1 or max(heights)-min(heights)>1):raise ValueError('All frames need the same canvas; individual body crops are forbidden')
    for i,r in enumerate(rects):
        row,col=divmod(i,columns)
        if col and (r[0]<rects[i-1][2] or r[1]!=rects[i-1][1] or r[3]!=rects[i-1][3]):raise ValueError('Crop columns must be ordered, disjoint and share row bounds')
        if row and (r[0]!=rects[col][0] or r[2]!=rects[col][2] or r[1]<rects[i-columns][3]):raise ValueError('Crop rows must be ordered with common column bounds')
    if plan.get('schema')==2:
        if count!=columns*rows or plan.get('method')!='transparent_separators':raise ValueError('Automatic crop must partition every cell')
        for i,r in enumerate(rects):
            row,col=divmod(i,columns)
            if (r[0]!=(0 if col==0 else rects[i-1][2]) or r[1]!=(0 if row==0 else rects[i-columns][3]) or (col==columns-1 and r[2]!=size[0]) or (row==rows-1 and r[3]!=size[1])):raise ValueError('Automatic partition may not discard source pixels')
    return rects

def load_crop(path,image,columns,rows,count,require_review=True):
    plan=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if plan.get('source_sha256')!=digest(image):raise ValueError('Crop plan belongs to a different source image')
    with Image.open(image) as im:rects=boxes(plan,im.size,columns,rows,count)
    if require_review and (plan.get('reviewed') is not True or not str(plan.get('notes','')).strip()):raise ValueError('Inspect the crop overlay and record actual grid observations before final export')
    return plan,rects

def crop_template(image,columns,rows,count,out):
    out=Path(out)
    if out.exists():raise ValueError('Use a new crop plan path')
    if columns<1 or rows<1 or not 1<=count<=columns*rows:raise ValueError('Invalid grid')
    with Image.open(image) as im:
        w,h=im.size;rects=[]
        for i in range(count):
            x,y=i%columns,i//columns;rects.append([round(x*w/columns),round(y*h/rows),round((x+1)*w/columns),round((y+1)*h/rows)])
        plan={'schema':1,'source_sha256':digest(image),'image_size':[w,h],'grid':[columns,rows,count],'boxes':rects,'reviewed':False,'notes':''}
    out.write_text(json.dumps(plan,indent=2),encoding='utf-8');crop_overlay(image,out,out.with_suffix('.png'))
    return {'crop_plan':str(out),'overlay':str(out.with_suffix('.png')),'status':'needs_grid_review'}

def crop_overlay(image,plan_path,out):
    plan=json.loads(Path(plan_path).read_text(encoding='utf-8-sig'));_,rects=load_crop(plan_path,image,*plan['grid'],require_review=False)
    with Image.open(image) as im:
        display=im.convert('RGB');draw=ImageDraw.Draw(display)
        for i,(x0,y0,x1,y1) in enumerate(rects):
            draw.rectangle((x0,y0,x1-1,y1-1),outline='#00ffff',width=2);draw.text((x0+5,y0+5),str(i+1),fill='#00ffff')
        display.save(out)
    return {'overlay':str(out)}


def automatic_plan(image, clean, columns, rows, count):
    """Find clear separators near the requested grid, preserving every source pixel."""
    import numpy as np
    if columns<1 or rows<1 or count!=columns*rows:raise ValueError('Automatic cutting requires a complete rectangular grid')
    alpha=np.asarray(clean.convert('RGBA'))[:,:,3]>0
    def cuts(length,parts,occupied):
        found=[0]
        for i in range(1,parts):
            nominal=round(length*i/parts);radius=max(2,round(length/parts*.18))
            candidates=[v for v in range(max(2,nominal-radius),min(length-2,nominal+radius)+1) if not occupied[v-1:v+1].any()]
            if not candidates:raise ValueError('No safe transparent separator; retain original sheet and inspect overlap instead of cutting anatomy')
            found.append(min(candidates,key=lambda v:(abs(v-nominal),v)))
        return found+[length]
    xs=cuts(clean.width,columns,alpha.any(axis=0));ys=cuts(clean.height,rows,alpha.any(axis=1))
    rects=[[xs[x],ys[y],xs[x+1],ys[y+1]] for y in range(rows) for x in range(columns)]
    plan={'schema':2,'method':'transparent_separators','source_sha256':digest(image),'image_size':list(clean.size),'grid':[columns,rows,count],'boxes':rects,'reviewed':False,'notes':'Automatic separator detection; visual motion review still required.'}
    boxes(plan,clean.size,columns,rows,count)
    validate_pixels(clean,rects)
    return plan


def validate_pixels(clean,rects):
    """Refuse empty/edge-clipped cells and pixels lost in margins or gutters."""
    remaining=clean.getchannel('A').copy()
    for i,r in enumerate(rects):
        frame=clean.crop(r);b=frame.getbbox()
        if b is None:raise ValueError(f'Frame {i+1} is empty')
        if b[0]==0 or b[1]==0 or b[2]==frame.width or b[3]==frame.height:raise ValueError(f'Frame {i+1} touches a cut edge; no clipped animation may be exported')
        remaining.paste(0,tuple(r))
    if remaining.getbbox():raise ValueError('Crop plan would discard foreground outside its cells')
