"""Inspect existing whole-sheet outputs without accepting or altering a job.

This diagnostic command does not generate images, relax production packing,
recenter poses, stretch artwork or mark any action complete.
"""
import argparse,json,math
from pathlib import Path
from PIL import Image
import motion
import sprite_contract as contract

def preview(job,images,out,registration=None):
    job,data=motion.job_read(job);motion.verify_job_contract(job,data)
    sources=motion.read(images);out=Path(out).resolve()
    if set(sources)!=set(data['actions']):raise ValueError('Provide every action in the prepared job for the complete diagnostic sample')
    if out.exists():raise ValueError('Use a new diagnostic directory; existing previews are preserved')
    registrations=motion.read(registration) if registration else {}
    if registrations and set(registrations)!=set(data['actions']):raise ValueError('Registration must account for every requested action')
    entries=[];records=[];prepared=[]
    for action,spec in data['actions'].items():
        source=Path(sources[action]).resolve()
        with Image.open(source) as raw:
            clean=motion.remove_background(raw,data.get('background_mode','auto'))
        cols,rows,n=spec['columns'],spec['rows'],spec['count']
        plan=contract.automatic_plan(source,clean,cols,rows,n)
        rects=plan['boxes']
        w,h=max(r[2]-r[0] for r in rects),max(r[3]-r[1] for r in rects)
        registered=None;registration_report=None
        if registration:
            from registration import register
            registered,registration_report=register(clean,plan,registrations[action]);w,h=registered[0].size
        atlas=Image.new('RGBA',(w*n,h));warnings=[]
        expected=spec.get('tile',[w,h])
        if abs((clean.width/cols)/(clean.height/rows)-expected[0]/expected[1])>.04:
            warnings.append('原图网格比例与参考不符；按原像素预览，未拉伸修正。')
        frames=[]
        for i in range(n):
            x,y=i%cols,i//cols
            box=rects[i]
            frame=registered[i] if registered is not None else clean.crop(box);bounds=frame.getbbox()
            if not bounds:warnings.append(f'第{i+1}帧为空。')
            elif bounds[0]==0 or bounds[1]==0 or bounds[2]==frame.width or bounds[3]==frame.height:
                warnings.append(f'第{i+1}帧碰到格子边缘，可能跨格或被裁切。')
            atlas.alpha_composite(frame,(i*w,0));frames.append({'source_box':box,'translation':[0,registration_report['row_translation_y'][y] if registration_report else 0],'scale':1})
        prepared.append((action,atlas,plan,source))
        clip={'name':action,'tile':[w,h],'count':n,'seconds':spec['seconds'],'phases':spec.get('phases',[i/n for i in range(n)]),'loop':spec['loop'],'draft':True,'sequence_check':None,'warnings':warnings,'reference':motion.data_url(job/spec['reference']),'reference_layout':spec['reference_layout']}
        entries.append(clip);records.append({'action':action,'source':str(source),'frames':frames,'warnings':warnings,'accepted':False,'registration':registration_report})
    out.mkdir(parents=True)
    for entry,(action,atlas,plan,source) in zip(entries,prepared):
        motion.write(out/(action+'-crop.json'),plan)
        contract.crop_overlay(source,out/(action+'-crop.json'),out/(action+'-crop.png'))
        for i in range(entry['count']):
            atlas.crop((i*entry['tile'][0],0,(i+1)*entry['tile'][0],entry['tile'][1])).save(out/f'{action}-frame-{i:03}.png')
        path=out/(action+'-diagnostic.png');atlas.save(path);entry['character']=motion.data_url(path)
    template=(motion.SKILL/'assets/review.html').read_text(encoding='utf-8')
    template=template.replace('动作参考与角色同步播放 · Reference / generated character','五动作诊断单例 · 插件自动透明间隔裁切 · 未通过验收')
    (out/'review.html').write_text(template.replace('__CLIPS__',json.dumps(entries,ensure_ascii=False).replace('<','\\u003c')),encoding='utf-8')
    motion.write(out/'diagnostics.json',{'status':'diagnostic_only','job_modified':False,'new_generation_calls':0,'actions':records})
    return {'preview':str(out/'review.html'),'actions':list(data['actions']),'status':'diagnostic_only'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['job','images','out']:p.add_argument('--'+k,required=True)
    p.add_argument('--registration',help='Source-bound inspected ground contacts, one per row for each action')
    print(json.dumps(preview(**vars(p.parse_args())),ensure_ascii=False))
