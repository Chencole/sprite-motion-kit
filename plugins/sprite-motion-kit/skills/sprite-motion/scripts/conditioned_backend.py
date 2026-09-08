"""Optional local AnimateDiff/ControlNet/IP-Adapter diagnostic backend.

`check` only reads inputs. Only explicit `run` loads models and performs ONE
whole-sequence inference. No downloads, retries, control/output resizing or loop guarantee.
API: https://huggingface.co/docs/diffusers/api/pipelines/animatediff
IP loader: https://huggingface.co/docs/diffusers/api/loaders/ip_adapter
Model config: base_model, motion_adapter, controlnets:[{type,path,scale}],
ip_adapter:{path,subfolder,weight_name,image_encoder_folder,scale,background_rgb}, prompt,
negative_prompt, steps, guidance_scale, seed, device (cpu/cuda[:N]/mps),
cpu_offload (boolean; defaults to true for CUDA, false otherwise).
Appearance is alpha-composited on background_rgb (default [128,128,128]) and
center-padded to a square without resizing, preserving the full character for CLIP.
scheduler:{type:"ddim",timestep_spacing:"leading"} is optional. Leading matches
DDIM's fixed integer previous-step calculation; linspace/trailing are explicit
overrides. beta_schedule remains linear. This is not a visual-quality guarantee.
All model paths are local Diffusers directories; IP encoder path is relative
to ip_adapter.path, independently of its weight subfolder.
"""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from PIL import Image


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def local(root, value, directory=False):
    if not isinstance(value, str) or not value.strip() or '://' in value:
        raise ValueError('A local path is required')
    path=(root/value).resolve()
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError('Missing local '+('directory: ' if directory else 'file: ')+str(path))
    return path


def number(value, name, minimum=0):
    if type(value) not in (int,float) or not math.isfinite(value) or value<minimum:
        raise ValueError('Invalid '+name)
    return value


def load_manifest(path):
    """Read and verify every declared asset; never import inference dependencies."""
    path=Path(path).resolve(); data=json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('schema')!=1 or data.get('approval')!='diagnostic_only':
        raise ValueError('Expected schema 1 diagnostic_only conditioning manifest')
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}',data.get('action','')):raise ValueError('Invalid action')
    for key in ('frame_count','width','height','columns'):
        if type(data.get(key)) is not int or data[key]<1:raise ValueError('Invalid '+key)
    if data['frame_count']<2 or data['width']%8 or data['height']%8:
        raise ValueError('At least two frames, valid columns and dimensions divisible by 8 are required')
    if type(data.get('loop')) is not bool or number(data.get('seconds'),'seconds')<=0:raise ValueError('Invalid timing')
    hashes=data.get('input_hashes')
    if not isinstance(hashes,dict) or not hashes or any(not isinstance(k,str) or not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v) for k,v in hashes.items()):
        raise ValueError('input_hashes must contain source SHA-256 provenance')
    def asset(record, size=None):
        if not isinstance(record,dict):raise ValueError('Each conditioning asset needs a path and SHA-256')
        asset_path=local(path.parent,record.get('path'))
        if record.get('sha256')!=digest(asset_path):raise ValueError('Conditioning asset hash mismatch: '+str(asset_path))
        with Image.open(asset_path) as image:
            image.load()
            if size and image.size!=size:raise ValueError('Conditioning frame dimensions differ from manifest')
            if size and image.mode!='RGB':raise ValueError('Prepared control frames must be RGB')
        return str(asset_path)
    character=asset(data.get('character',{})); controls=data.get('controls',[]); paths=[]
    if not isinstance(controls,list) or not controls:raise ValueError('At least one control sequence is required')
    for control in controls:
        if not isinstance(control,dict):raise ValueError('Each control sequence must be an object')
        if not isinstance(control.get('type'),str) or not control['type'].strip():raise ValueError('Control type is required')
        frames=control.get('frames',[])
        if not isinstance(frames,list) or len(frames)!=data['frame_count']:raise ValueError('Every ControlNet needs the complete frame sequence')
        paths.append([asset(frame,(data['width'],data['height'])) for frame in frames])
    return data,character,paths


def load_config(path, manifest):
    path=Path(path).resolve(); config=json.loads(path.read_text(encoding='utf-8-sig'))
    for key in ('base_model','motion_adapter'):config[key]=str(local(path.parent,config.get(key),True))
    # SDXL/SD2 checkpoints cannot be substituted for this explicitly SD1.5 route.
    unet=json.loads(local(Path(config['base_model']),'unet/config.json').read_text(encoding='utf-8-sig'))
    if unet.get('cross_attention_dim')!=768:raise ValueError('This backend requires an SD1.5-compatible UNet (cross_attention_dim=768)')
    controls=config.get('controlnets',[])
    if not isinstance(controls,list) or len(controls)!=len(manifest['controls']):raise ValueError('ControlNet models must match the ordered control sequences')
    for model,control in zip(controls,manifest['controls']):
        if not isinstance(model,dict):raise ValueError('Each ControlNet model must be an object')
        if model.get('type')!=control['type']:raise ValueError('ControlNet type/order differs from the manifest')
        model['path']=str(local(path.parent,model.get('path'),True)); model['scale']=float(number(model.get('scale'),'ControlNet scale'))
    ip=config.get('ip_adapter',{})
    if not isinstance(ip,dict):raise ValueError('ip_adapter must be an object')
    root=local(path.parent,ip.get('path'),True)
    subfolder=ip.get('subfolder',''); weight=ip.get('weight_name',''); encoder=ip.get('image_encoder_folder','')
    for value in (subfolder,weight,encoder):
        if not isinstance(value,str) or Path(value).is_absolute() or '..' in Path(value).parts:raise ValueError('IP-Adapter paths must stay inside its local root')
    if not weight or Path(weight).name!=weight or not encoder:raise ValueError('IP weight filename and image_encoder_folder are required')
    local(root, str(Path(subfolder)/weight)); local(root,encoder,True)
    ip.update(path=str(root),subfolder=Path(subfolder).as_posix(),image_encoder_folder='./'+Path(encoder).as_posix(),scale=float(number(ip.get('scale'),'IP-Adapter scale')))
    ip.setdefault('background_rgb',[128,128,128])
    if not isinstance(ip['background_rgb'],list) or len(ip['background_rgb'])!=3 or any(type(c) is not int or not 0<=c<=255 for c in ip['background_rgb']):
        raise ValueError('IP-Adapter background_rgb must contain three integers in [0,255]')
    scheduler=config.setdefault('scheduler',{})
    if not isinstance(scheduler,dict):raise ValueError('scheduler must be an object')
    scheduler.setdefault('type','ddim'); scheduler.setdefault('timestep_spacing','leading')
    if set(scheduler)-{'type','timestep_spacing'} or scheduler['type']!='ddim' or scheduler['timestep_spacing'] not in ('leading','linspace','trailing'):
        raise ValueError('Supported scheduler: type=ddim, timestep_spacing=leading/linspace/trailing')
    if type(config.get('steps')) is not int or config['steps']<1:raise ValueError('steps must be a positive integer')
    number(config.get('guidance_scale'),'guidance_scale')
    if type(config.get('seed')) is not int or not 0<=config['seed']<2**63:raise ValueError('seed must be an integer in [0, 2**63)')
    if not isinstance(config.get('prompt'),str) or not config['prompt'].strip():raise ValueError('A complete action prompt is required')
    if not isinstance(config.get('negative_prompt',''),str):raise ValueError('negative_prompt must be text')
    if not re.fullmatch(r'cpu|mps|cuda(?::\d+)?',config.get('device','')):raise ValueError('Explicit cpu, cuda[:N] or mps device required')
    config.setdefault('cpu_offload',config['device'].startswith('cuda'))
    if type(config['cpu_offload']) is not bool or (config['cpu_offload'] and not config['device'].startswith('cuda')):
        raise ValueError('cpu_offload must be boolean and is available only for CUDA')
    return config


def check(manifest,config):
    data,_,_=load_manifest(manifest); load_config(config,data)
    return {'status':'inputs_validated','action':data['action'],'inference_calls':0,'models_loaded':False,'visual_review_passed':False}


def check_prompt_tokens(tokenizer,settings):
    """Use this model's actual tokenizer; never silently cut off constraints."""
    limit=tokenizer.model_max_length
    for field in ('prompt','negative_prompt'):
        tokens=tokenizer.encode(settings.get(field,''),add_special_tokens=True,truncation=False)
        if len(tokens)>limit:
            raise ValueError(f'{field} exceeds the selected model token limit ({len(tokens)} > {limit}); shorten it explicitly before inference')


def prepare_appearance(image, background_rgb):
    """Composite and square-pad at original scale; never crop or mutate the source."""
    background=tuple(background_rgb); width,height=image.size; side=max(width,height)
    rgba=image.convert('RGBA'); alpha_bbox=rgba.getchannel('A').getbbox()
    composited=Image.alpha_composite(Image.new('RGBA',image.size,background+(255,)),rgba).convert('RGB')
    offset=((side-width)//2,(side-height)//2); prepared=Image.new('RGB',(side,side),background)
    prepared.paste(composited,offset)
    return prepared,{'operation':'alpha_composite_then_center_pad_square','source_size':[width,height],
                    'source_mode':image.mode,'source_alpha_bbox':list(alpha_bbox) if alpha_bbox else None,
                    'prepared_size':[side,side],'background_rgb':list(background),'offset':list(offset),'scale':1.0}


def run(manifest,config,out):
    data,character,controls=load_manifest(manifest); settings=load_config(config,data); out=Path(out).resolve()
    if out.exists():raise ValueError('Use a new output directory; existing diagnostics are preserved')
    manifest_hash,config_hash=digest(manifest),digest(config)
    def rgb(path):
        with Image.open(path) as image:return image.convert('RGB')
    sequences=[[rgb(path) for path in sequence] for sequence in controls]
    with Image.open(character) as source:appearance,appearance_transform=prepare_appearance(source,settings['ip_adapter']['background_rgb'])
    appearance_transform['source_sha256']=data['character']['sha256']
    import torch
    from transformers import CLIPTokenizer
    from diffusers import AnimateDiffControlNetPipeline, ControlNetModel, MotionAdapter, DDIMScheduler
    tokenizer=CLIPTokenizer.from_pretrained(settings['base_model'],subfolder='tokenizer',local_files_only=True)
    check_prompt_tokens(tokenizer,settings)
    device=settings['device']
    if device.startswith('cuda') and (not torch.cuda.is_available() or int(device.split(':')[1] if ':' in device else 0)>=torch.cuda.device_count()):raise ValueError('Requested CUDA device is unavailable')
    if device=='mps' and not torch.backends.mps.is_available():raise ValueError('Requested MPS device is unavailable')
    dtype=torch.float32 if device=='cpu' else torch.float16
    kwargs={'local_files_only':True,'torch_dtype':dtype,'use_safetensors':True}
    adapter=MotionAdapter.from_pretrained(settings['motion_adapter'],**kwargs)
    models=[ControlNetModel.from_pretrained(model['path'],**kwargs) for model in settings['controlnets']]
    pipe=AnimateDiffControlNetPipeline.from_pretrained(settings['base_model'],motion_adapter=adapter,controlnet=models[0] if len(models)==1 else models,**kwargs)
    pipe.scheduler=DDIMScheduler.from_pretrained(settings['base_model'],subfolder='scheduler',local_files_only=True,clip_sample=False,beta_schedule='linear',timestep_spacing=settings['scheduler']['timestep_spacing'],steps_offset=1)
    ip=settings['ip_adapter']; pipe.load_ip_adapter(ip['path'],subfolder=ip['subfolder'],weight_name=ip['weight_name'],image_encoder_folder=ip['image_encoder_folder'],local_files_only=True)
    pipe.set_ip_adapter_scale(ip['scale']); pipe.vae.enable_slicing()
    if settings['cpu_offload']:
        pipe.enable_model_cpu_offload(gpu_id=int(device.split(':')[1] if ':' in device else 0))
    else:pipe.to(device)
    scales=[model['scale'] for model in settings['controlnets']]
    # One CPU-seeded noise stream and one complete temporal call, never per-cell calls.
    output=pipe(prompt=settings['prompt'],negative_prompt=settings.get('negative_prompt',''),conditioning_frames=sequences[0] if len(models)==1 else sequences,
                ip_adapter_image=appearance,num_frames=data['frame_count'],width=data['width'],height=data['height'],
                num_inference_steps=settings['steps'],guidance_scale=settings['guidance_scale'],controlnet_conditioning_scale=scales[0] if len(models)==1 else scales,
                generator=torch.Generator(device='cpu').manual_seed(settings['seed']),num_videos_per_prompt=1,output_type='pil',return_dict=True)
    batches=output.frames
    if len(batches)!=1 or len(batches[0])!=data['frame_count']:raise ValueError('Backend returned an unexpected frame count; no layout repair attempted')
    frames=batches[0]; size=(data['width'],data['height'])
    if any(not isinstance(frame,Image.Image) or frame.size!=size or frame.mode!='RGB' for frame in frames):
        raise ValueError('Backend must return complete RGB frames at the exact requested dimensions')
    scheduler_report={'class':type(pipe.scheduler).__name__,'config':dict(pipe.scheduler.config),'timesteps':pipe.scheduler.timesteps.tolist()}
    out.mkdir(parents=True); columns=data['columns']; rows=math.ceil(len(frames)/columns)
    appearance.save(out/'appearance-input.png'); appearance_transform.update(path='appearance-input.png',sha256=digest(out/'appearance-input.png'))
    atlas=Image.new('RGB',(size[0]*columns,size[1]*rows),(255,0,255)); records=[]
    for i,frame in enumerate(frames):
        target=out/f'frame-{i:03}.png'; frame.save(target); atlas.paste(frame,((i%columns)*size[0],(i//columns)*size[1]))
        records.append({'path':target.name,'sha256':digest(target)})
    atlas.save(out/'generated-sheet.png')
    report={'status':'diagnostic_only','action':data['action'],'inference_calls':1,'accepted':False,'visual_review_passed':False,
            'manifest_sha256':manifest_hash,'config_sha256':config_hash,'input_hashes':data['input_hashes'],'settings':settings,
            'appearance_transform':appearance_transform,'scheduler':scheduler_report,
            'frames':records,'frame_count':len(frames),'tile':list(size),'columns':columns,'rows':rows,'seconds':data['seconds'],'loop':data['loop'],
            'atlas':'generated-sheet.png','atlas_sha256':digest(out/'generated-sheet.png'),'background':'RGB; no transparency or key-background guarantee',
            'loop_notice':'loop is review playback semantics only; generation does not guarantee a closed cycle'}
    if 'phases' in data:report['phases']=data['phases']
    (out/'generation-result.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); commands=parser.add_subparsers(dest='command',required=True)
    for name in ('check','run'):
        command=commands.add_parser(name); command.add_argument('--manifest',required=True); command.add_argument('--config',required=True)
        if name=='run':command.add_argument('--out',required=True)
    args=vars(parser.parse_args()); name=args.pop('command')
    print(json.dumps((run if name=='run' else check)(**args),ensure_ascii=False,indent=2))
