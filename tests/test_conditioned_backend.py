"""Fake pipeline plus optional real preprocessing/scheduler checks; no artwork assessment."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image

S=Path(__file__).resolve().parents[1]/'plugins/sprite-motion-kit/skills/sprite-motion/scripts'
sys.path.insert(0,str(S))
import conditioned_backend as backend


class ConditionedBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        Image.new('RGB',(20,24),'brown').save(self.root/'character.png')
        self.manifest={'schema':1,'action':'custom_stride','frame_count':4,'width':32,'height':40,'columns':2,
                       'seconds':1.3,'loop':True,'approval':'diagnostic_only','character':self.asset('character.png'),
                       'controls':[],'input_hashes':{'character':backend.digest(self.root/'character.png')}}
        for kind in ('openpose','depth'):
            frames=[]
            for i in range(4):
                name=f'{kind}-{i}.png';Image.new('RGB',(32,40),(10+i,20,30)).save(self.root/name);frames.append(self.asset(name))
            self.manifest['controls'].append({'type':kind,'frames':frames})
        for folder in ('base/unet','base/scheduler','motion','openpose','depth','ip/models','ip/models/image_encoder'):
            (self.root/folder).mkdir(parents=True,exist_ok=True)
        (self.root/'base/unet/config.json').write_text('{"cross_attention_dim":768}',encoding='utf-8')
        (self.root/'ip/models/adapter.safetensors').write_bytes(b'local fixture, not real weights')
        self.config={'base_model':'base','motion_adapter':'motion','controlnets':[{'type':kind,'path':kind,'scale':scale} for kind,scale in [('openpose',1.1),('depth',.7)]],
                     'ip_adapter':{'path':'ip','subfolder':'models','weight_name':'adapter.safetensors','image_encoder_folder':'models/image_encoder','scale':.65},
                     'prompt':'A complete custom stride with fixed character identity','negative_prompt':'blur','steps':12,'guidance_scale':6.5,'seed':37,'device':'cpu'}
        self.manifest_path=self.root/'conditioning.json';self.config_path=self.root/'models.json';self.out=self.root/'output';self.write()

    def asset(self,name):return {'path':name,'sha256':backend.digest(self.root/name)}
    def write(self):
        self.manifest_path.write_text(json.dumps(self.manifest),encoding='utf-8');self.config_path.write_text(json.dumps(self.config),encoding='utf-8')

    def dependencies(self):
        self.pipe=Mock();self.frames=[Image.new('RGB',(32,40),(i*30,80,90)) for i in range(4)]
        self.pipe.return_value=SimpleNamespace(frames=[self.frames]);self.generator=Mock();self.generator.manual_seed.return_value=self.generator
        self.torch=SimpleNamespace(float32='fp32',float16='fp16',Generator=Mock(return_value=self.generator),
                                   cuda=SimpleNamespace(is_available=lambda:False,device_count=lambda:0),backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda:False)))
        self.diffusers=SimpleNamespace(AnimateDiffControlNetPipeline=Mock(),ControlNetModel=Mock(),MotionAdapter=Mock(),DDIMScheduler=Mock())
        self.diffusers.AnimateDiffControlNetPipeline.from_pretrained.return_value=self.pipe
        self.diffusers.DDIMScheduler.from_pretrained.return_value=SimpleNamespace(
            config={'beta_schedule':'linear','timestep_spacing':'leading','steps_offset':1},
            timesteps=SimpleNamespace(tolist=lambda:[914,831,748,665,582,499,416,333,250,167,84,1]))
        self.tokenizer=SimpleNamespace(model_max_length=77,encode=lambda text,**kwargs: [0]+text.split()+[1])
        self.transformers=SimpleNamespace(CLIPTokenizer=Mock())
        self.transformers.CLIPTokenizer.from_pretrained.return_value=self.tokenizer
        return patch.dict(sys.modules,{'torch':self.torch,'diffusers':self.diffusers,'transformers':self.transformers})

    def test_long_prompt_is_rejected_before_model_loading_or_generation(self):
        self.config['prompt']='word '*78;self.write()
        with self.dependencies(),self.assertRaisesRegex(ValueError,'token limit'):
            backend.run(self.manifest_path,self.config_path,self.out)
        self.diffusers.MotionAdapter.from_pretrained.assert_not_called()
        self.pipe.assert_not_called();self.assertFalse(self.out.exists())

    def test_check_is_read_only_and_does_not_import_or_load_optional_dependencies(self):
        with patch.dict(sys.modules,{'torch':None,'diffusers':None}):
            result=backend.check(self.manifest_path,self.config_path)
        self.assertEqual(result['inference_calls'],0);self.assertFalse(result['models_loaded']);self.assertFalse(self.out.exists())

    def test_multiple_controls_are_one_ordered_full_sequence_call_with_local_models(self):
        with self.dependencies():result=backend.run(self.manifest_path,self.config_path,self.out)
        self.pipe.assert_called_once();call=self.pipe.call_args.kwargs
        self.assertEqual((call['num_frames'],call['width'],call['height']),(4,32,40))
        self.assertEqual(call['controlnet_conditioning_scale'],[1.1,.7]);self.assertEqual(call['num_videos_per_prompt'],1)
        self.assertEqual(call['num_inference_steps'],12);self.assertEqual(call['guidance_scale'],6.5)
        self.assertEqual([[frame.getpixel((0,0)) for frame in sequence] for sequence in call['conditioning_frames']], [[(10+i,20,30) for i in range(4)]]*2)
        self.assertEqual(call['ip_adapter_image'].size,(24,24));self.assertIs(call['generator'],self.generator)
        self.assertEqual(call['ip_adapter_image'].getpixel((0,0)),(128,128,128))
        self.assertEqual(result['appearance_transform']['offset'],[2,0]);self.assertEqual(result['appearance_transform']['scale'],1)
        self.assertEqual(result['appearance_transform']['source_sha256'],self.manifest['character']['sha256'])
        self.assertEqual(backend.digest(self.root/'character.png'),self.manifest['character']['sha256'])
        with Image.open(self.out/'appearance-input.png') as prepared:self.assertEqual(prepared.tobytes(),call['ip_adapter_image'].tobytes())
        self.assertEqual(result['scheduler']['timesteps'],[914,831,748,665,582,499,416,333,250,167,84,1])
        self.assertEqual(result['scheduler']['config']['beta_schedule'],'linear')
        self.assertEqual(self.diffusers.DDIMScheduler.from_pretrained.call_args.kwargs['timestep_spacing'],'leading')
        self.torch.Generator.assert_called_once_with(device='cpu');self.generator.manual_seed.assert_called_once_with(37)
        for loader in (self.diffusers.MotionAdapter,self.diffusers.ControlNetModel,self.diffusers.AnimateDiffControlNetPipeline,self.diffusers.DDIMScheduler):
            for recorded in loader.from_pretrained.call_args_list:self.assertIs(recorded.kwargs['local_files_only'],True)
        ipcall=self.pipe.load_ip_adapter.call_args
        self.assertEqual(ipcall.args[0],str(self.root/'ip'));self.assertEqual(ipcall.kwargs['subfolder'],'models')
        self.assertEqual(ipcall.kwargs['weight_name'],'adapter.safetensors');self.assertEqual(ipcall.kwargs['image_encoder_folder'],'./models/image_encoder')
        self.assertTrue(ipcall.kwargs['local_files_only']);self.pipe.set_ip_adapter_scale.assert_called_once_with(.65)
        self.pipe.vae.enable_slicing.assert_called_once_with();self.pipe.to.assert_called_once_with('cpu')
        self.pipe.enable_model_cpu_offload.assert_not_called()
        self.assertEqual(result['status'],'diagnostic_only');self.assertFalse(result['accepted']);self.assertFalse(result['visual_review_passed'])
        self.assertIn('does not guarantee',result['loop_notice']);self.assertIn('RGB',result['background'])
        with Image.open(self.out/'generated-sheet.png') as atlas:
            self.assertEqual(atlas.mode,'RGB');self.assertEqual(atlas.size,(64,80))
            for i,frame in enumerate(self.frames):self.assertEqual(atlas.crop(((i%2)*32,(i//2)*40,(i%2+1)*32,(i//2+1)*40)).tobytes(),frame.tobytes())
        for i,frame in enumerate(self.frames):
            with Image.open(self.out/f'frame-{i:03}.png') as saved:self.assertEqual(saved.tobytes(),frame.tobytes())

    def test_single_control_uses_flat_frame_list_and_float_scale(self):
        self.manifest['controls']=self.manifest['controls'][:1];self.config['controlnets']=self.config['controlnets'][:1];self.write()
        with self.dependencies():backend.run(self.manifest_path,self.config_path,self.out)
        call=self.pipe.call_args.kwargs;self.assertEqual(len(call['conditioning_frames']),4)
        self.assertTrue(all(isinstance(frame,Image.Image) for frame in call['conditioning_frames']))
        self.assertEqual(call['controlnet_conditioning_scale'],1.1)
        self.assertFalse(isinstance(self.diffusers.AnimateDiffControlNetPipeline.from_pretrained.call_args.kwargs['controlnet'],list))

    def test_invalid_inputs_fail_before_inference_or_output_creation(self):
        cases=[lambda:self.manifest['character'].update(sha256='0'*64),
               lambda:self.manifest['controls'][0]['frames'].pop(),
               lambda:self.manifest.update(width=33),lambda:self.manifest.update(approval='production'),
               lambda:self.config.update(seed=-1),lambda:self.config['controlnets'][0].update(type='wrong'),
               lambda:self.config.update(base_model='https://example.invalid/model'),
               lambda:self.config['ip_adapter'].update(weight_name='missing.safetensors'),
               lambda:self.config['ip_adapter'].update(image_encoder_folder='missing'),
               lambda:self.config['ip_adapter'].update(image_encoder_folder='../escape'),
               lambda:self.config['ip_adapter'].update(background_rgb=[0,0,256]),
               lambda:self.config['ip_adapter'].update(background_rgb=[True,0,0]),
               lambda:self.config.update(scheduler={'type':'unknown'}),
               lambda:self.config.update(scheduler={'timestep_spacing':'unknown'}),
               lambda:self.config.update(scheduler={'beta_schedule':'scaled_linear'})]
        original_manifest=copy.deepcopy(self.manifest);original_config=copy.deepcopy(self.config)
        for mutate in cases:
            with self.subTest(mutate=mutate):
                self.manifest=copy.deepcopy(original_manifest);self.config=copy.deepcopy(original_config);mutate();self.write()
                with self.dependencies(),self.assertRaises(ValueError):backend.run(self.manifest_path,self.config_path,self.out)
                self.diffusers.MotionAdapter.from_pretrained.assert_not_called();self.pipe.assert_not_called();self.assertFalse(self.out.exists())

    def test_control_image_size_is_verified_without_resizing(self):
        Image.new('RGB',(16,40),'black').save(self.root/'openpose-0.png');self.manifest['controls'][0]['frames'][0]=self.asset('openpose-0.png');self.write()
        with self.dependencies(),self.assertRaisesRegex(ValueError,'dimensions'):backend.run(self.manifest_path,self.config_path,self.out)
        self.pipe.assert_not_called();self.assertFalse(self.out.exists())

    def test_unavailable_device_is_rejected_before_loading_models(self):
        self.config['device']='cuda:0';self.write()
        with self.dependencies(),self.assertRaisesRegex(ValueError,'unavailable'):backend.run(self.manifest_path,self.config_path,self.out)
        self.diffusers.MotionAdapter.from_pretrained.assert_not_called();self.assertFalse(self.out.exists())

    def test_cuda_defaults_to_offload_on_the_requested_gpu(self):
        self.config['device']='cuda:1';self.write()
        with self.dependencies():
            self.torch.cuda=SimpleNamespace(is_available=lambda:True,device_count=lambda:2)
            result=backend.run(self.manifest_path,self.config_path,self.out)
        self.pipe.enable_model_cpu_offload.assert_called_once_with(gpu_id=1);self.pipe.to.assert_not_called()
        self.pipe.vae.enable_slicing.assert_called_once_with();self.assertTrue(result['settings']['cpu_offload'])

    def test_explicit_cuda_full_loading_and_noncuda_offload_rejection(self):
        self.config.update(device='cuda:1',cpu_offload=False);self.write()
        with self.dependencies():
            self.torch.cuda=SimpleNamespace(is_available=lambda:True,device_count=lambda:2)
            backend.run(self.manifest_path,self.config_path,self.out)
        self.pipe.to.assert_called_once_with('cuda:1');self.pipe.enable_model_cpu_offload.assert_not_called()
        self.config.update(device='cpu',cpu_offload=True);self.write()
        with self.dependencies(),self.assertRaisesRegex(ValueError,'only for CUDA'):
            backend.run(self.manifest_path,self.config_path,self.root/'other-output')
        self.pipe.assert_not_called();self.assertFalse((self.root/'other-output').exists())

    def test_unused_trailing_cells_and_original_phases_are_preserved(self):
        self.manifest.update(frame_count=3,columns=4,phases=[0,.1,.9])
        for control in self.manifest['controls']:control['frames']=control['frames'][:3]
        self.write()
        with self.dependencies():
            self.pipe.return_value=SimpleNamespace(frames=[self.frames[:3]])
            result=backend.run(self.manifest_path,self.config_path,self.out)
        self.assertEqual(result['phases'],[0,.1,.9]);self.assertEqual((result['columns'],result['rows']),(4,1))
        with Image.open(self.out/'generated-sheet.png') as atlas:
            self.assertEqual(atlas.size,(128,40));self.assertEqual(atlas.getpixel((120,20)),(255,0,255))
            for i,frame in enumerate(self.frames[:3]):self.assertEqual(atlas.crop((i*32,0,(i+1)*32,40)).tobytes(),frame.tobytes())
        self.assertFalse((self.out/'frame-003.png').exists());self.assertEqual(self.pipe.call_args.kwargs['num_frames'],3)

    def test_backend_error_is_not_retried_and_bad_output_is_not_repaired(self):
        with self.dependencies():
            self.pipe.side_effect=RuntimeError('model failure')
            with self.assertRaisesRegex(RuntimeError,'model failure'):backend.run(self.manifest_path,self.config_path,self.out)
        self.pipe.assert_called_once();self.assertFalse(self.out.exists())
        with self.dependencies():
            self.pipe.return_value=SimpleNamespace(frames=[[Image.new('RGB',(31,40),'black')]*4])
            with self.assertRaisesRegex(ValueError,'exact requested dimensions'):backend.run(self.manifest_path,self.config_path,self.out)
        self.pipe.assert_called_once();self.assertFalse(self.out.exists())

    def test_existing_output_prevents_model_loading_and_inference(self):
        self.out.mkdir()
        with self.dependencies(),self.assertRaisesRegex(ValueError,'new output'):backend.run(self.manifest_path,self.config_path,self.out)
        self.diffusers.MotionAdapter.from_pretrained.assert_not_called();self.pipe.assert_not_called()


    def test_appearance_composites_alpha_and_preserves_both_ends_at_original_scale(self):
        for size in ((147,245),(245,147)):
            with self.subTest(size=size):
                source=Image.new('RGBA',size,(255,0,255,0)); source.putpixel((0,0),(255,0,0,255))
                source.putpixel((size[0]-1,size[1]-1),(0,0,255,255));source.putpixel((1,1),(255,0,0,128))
                before=source.tobytes();prepared,record=backend.prepare_appearance(source,[128,128,128])
                x,y=record['offset'];self.assertEqual(prepared.size,(245,245));self.assertEqual(source.tobytes(),before)
                self.assertEqual(prepared.getpixel((x,y)),(255,0,0))
                self.assertEqual(prepared.getpixel((x+size[0]-1,y+size[1]-1)),(0,0,255))
                self.assertEqual(prepared.getpixel((x+1,y+1)),(192,64,64))
                self.assertEqual(prepared.getpixel((x+2,y+2)),(128,128,128))
                expected=Image.alpha_composite(Image.new('RGBA',size,(128,128,128,255)),source).convert('RGB')
                self.assertEqual(prepared.crop((x,y,x+size[0],y+size[1])).tobytes(),expected.tobytes())
                self.assertEqual(record['source_size'],list(size));self.assertEqual(record['scale'],1)

    def test_real_clip_preprocessing_keeps_portrait_top_and_bottom_when_available(self):
        try:from transformers import CLIPImageProcessor
        except ImportError:self.skipTest('Optional transformers not installed; no models or downloads required')
        source=Image.new('RGBA',(147,245),(0,0,0,0))
        source.paste((255,255,255,255),(12,12,135,233))
        source.paste((255,0,0,255),(12,12,135,32));source.paste((0,0,255,255),(12,213,135,233))
        prepared,_=backend.prepare_appearance(source,[128,128,128])
        processor=CLIPImageProcessor(size={'shortest_edge':224},crop_size={'height':224,'width':224})
        def color_rows(image):
            pixels=processor(image,return_tensors='np',do_normalize=False,do_rescale=False).pixel_values[0]
            red=(pixels[0]>240)&(pixels[1]<15)&(pixels[2]<15)
            blue=(pixels[2]>240)&(pixels[0]<15)&(pixels[1]<15)
            return red.any(axis=1).nonzero()[0],blue.any(axis=1).nonzero()[0]
        red,blue=color_rows(prepared)
        self.assertLessEqual(red[0],13);self.assertGreaterEqual(blue[-1],210)
        self.assertGreaterEqual(int(blue[-1]-red[0]+1),199)
        old_red,old_blue=color_rows(source.convert('RGB'))
        self.assertEqual((len(old_red),len(old_blue)),(0,0))

    def test_explicit_background_and_scheduler_override_are_used_and_reported(self):
        self.config['ip_adapter']['background_rgb']=[90,110,130]
        self.config['scheduler']={'type':'ddim','timestep_spacing':'trailing'};self.write()
        with self.dependencies():
            self.diffusers.DDIMScheduler.from_pretrained.return_value.config['timestep_spacing']='trailing'
            self.diffusers.DDIMScheduler.from_pretrained.return_value.timesteps=SimpleNamespace(tolist=lambda:[999,916,832])
            result=backend.run(self.manifest_path,self.config_path,self.out)
        self.assertEqual(self.pipe.call_args.kwargs['ip_adapter_image'].getpixel((0,0)),(90,110,130))
        self.assertEqual(result['appearance_transform']['background_rgb'],[90,110,130])
        self.assertEqual(result['scheduler']['timesteps'],[999,916,832])
        self.assertEqual(result['scheduler']['config']['timestep_spacing'],'trailing')
        self.assertEqual(result['settings']['scheduler'],self.config['scheduler'])
        self.assertEqual(self.diffusers.DDIMScheduler.from_pretrained.call_args.kwargs['timestep_spacing'],'trailing')
        self.assertEqual(self.diffusers.DDIMScheduler.from_pretrained.call_args.kwargs['beta_schedule'],'linear')


    def test_real_ddim_leading_matches_its_previous_step_calculation_when_available(self):
        try:from diffusers import DDIMScheduler
        except ImportError:self.skipTest('Optional diffusers not installed; no models or downloads required')
        settings=backend.load_config(self.config_path,self.manifest)
        scheduler=DDIMScheduler(num_train_timesteps=1000,beta_start=.00085,beta_end=.012,
                                beta_schedule='linear',clip_sample=False,steps_offset=1,
                                timestep_spacing=settings['scheduler']['timestep_spacing'])
        scheduler.set_timesteps(25);timesteps=scheduler.timesteps.tolist()
        self.assertEqual((timesteps[0],timesteps[-1]),(961,1))
        self.assertTrue(all(current-1000//25==following for current,following in zip(timesteps,timesteps[1:])))


if __name__=='__main__':unittest.main()
