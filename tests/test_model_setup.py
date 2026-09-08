"""Mock HTTP only: no external download, environment install or model execution."""
import copy
import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.request
import sys
from pathlib import Path
from unittest.mock import Mock,patch

S=Path(__file__).resolve().parents[1]/'plugins/sprite-motion-kit/skills/sprite-motion/scripts'
sys.path.insert(0,str(S))
import model_setup


class Response(io.BytesIO):
    def geturl(self):return 'https://us.aws.cdn.hf.co/model?signature=never-print-this'


class ModelSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.output=self.root/'models';self.lock_path=self.root/'models.lock.json'
        self.payloads={'config.json':b'{"fixture":true}','weights.safetensors':b'fake test bytes only'}
        self.lock={'schema':1,'repositories':[{'repo':'example/model','commit':'a'*40,'license':None}],
                   'files':[{'repo':'example/model','commit':'a'*40,'source_path':name,'destination':'model/'+name,
                             'size':len(payload),'sha256':hashlib.sha256(payload).hexdigest()} for name,payload in self.payloads.items()]}
        self.write()

    def write(self):self.lock_path.write_text(json.dumps(self.lock),encoding='utf-8')
    def opener(self):
        self.http=Mock()
        def respond(request,timeout):return Response(self.payloads[request.full_url.rsplit('/',1)[1]])
        self.http.open.side_effect=respond
        return patch.object(model_setup,'_opener',return_value=self.http)

    def test_plan_is_read_only_and_reports_unknown_license_without_MIT_claim(self):
        with patch.object(model_setup,'_opener',side_effect=AssertionError('Network is forbidden')):
            result=model_setup.plan(self.lock_path)
        self.assertEqual(result['file_count'],2);self.assertEqual(result['total_bytes'],sum(map(len,self.payloads.values())))
        self.assertEqual(result['downloads_started'],0);self.assertFalse(self.output.exists())
        self.assertIsNone(result['repositories'][0]['declared_license']);self.assertIn('undeclared',result['repositories'][0]['notice'])
        self.assertIn('does not cover',result['notice'])

    def test_distributable_lock_has_complete_pins_and_portable_destinations(self):
        lock=S.parent/'assets/conditioned-models.lock.json'
        with patch.object(model_setup,'_opener',side_effect=AssertionError('No network for shipped-lock validation')):
            result=model_setup.plan(lock)
        self.assertEqual((result['file_count'],result['total_bytes']),(24,8021271853))
        self.assertEqual(len(result['repositories']),4)
        data=json.loads(lock.read_text(encoding='utf-8'))
        self.assertEqual(set(data),{'schema','repositories','files'})
        for entry in data['files']:
            self.assertEqual(set(entry),{'repo','commit','source_path','destination','size','sha256'})
            self.assertNotIn(':',entry['destination']);self.assertNotIn('\\',entry['destination'])
        for repo in data['repositories']:
            self.assertEqual(repo['card_url'],'https://huggingface.co/'+repo['repo']+'/blob/'+repo['commit']+'/README.md')

    def test_explicit_fetch_verifies_bytes_then_reuses_exact_hash_without_network(self):
        with self.opener():result=model_setup.fetch(self.lock_path,self.output)
        self.assertEqual(result['status'],'complete');self.assertFalse(result['models_executed']);self.assertFalse(result['uploaded'])
        for call in self.http.open.call_args_list:
            request=call.args[0]
            self.assertTrue(request.full_url.startswith('https://huggingface.co/example/model/resolve/'+'a'*40+'/'))
            self.assertEqual(request.get_method(),'GET')
        for name,payload in self.payloads.items():self.assertEqual((self.output/'model'/name).read_bytes(),payload)
        self.assertFalse(list(self.output.rglob('*.part')));self.assertNotIn('signature',json.dumps(result))
        with patch.object(model_setup,'_opener',side_effect=AssertionError('Verified reuse must not use network')):
            reused=model_setup.fetch(self.lock_path,self.output)
        self.assertTrue(all(file['status']=='reused_verified' for file in reused['files']))

    def test_conflicting_existing_file_stops_entire_batch_without_overwrite(self):
        target=self.output/'model/weights.safetensors';target.parent.mkdir(parents=True);target.write_bytes(b'user-owned')
        with self.opener(),self.assertRaisesRegex(ValueError,'Existing file differs'):model_setup.fetch(self.lock_path,self.output)
        self.http.open.assert_not_called();self.assertEqual(target.read_bytes(),b'user-owned')
        self.assertFalse((self.output/'model/config.json').exists())

    def test_bad_size_or_hash_never_publishes_and_stale_part_is_not_overwritten(self):
        for payload in (b'longer than locked size by a lot'*4,b'x'*len(self.payloads['config.json'])):
            output=self.root/('bad-'+hashlib.sha256(payload).hexdigest()[:8])
            with self.opener():
                self.http.open.side_effect=lambda *a,**k:Response(payload)
                with self.assertRaises(RuntimeError):model_setup.fetch(self.lock_path,output)
            self.assertFalse((output/'model/config.json').exists());part=output/'model/config.json.part';self.assertTrue(part.exists())
            before=part.read_bytes()
            with self.opener(),self.assertRaisesRegex(ValueError,'Existing .part'):model_setup.fetch(self.lock_path,output)
            self.http.open.assert_not_called();self.assertEqual(part.read_bytes(),before)

    def test_paths_missing_hashes_unpinned_commits_and_collisions_are_rejected(self):
        original=copy.deepcopy(self.lock)
        invalid=[('destination','../escape'),('destination','C:/escape'),('destination','a\\..\\escape'),
                 ('destination','/escape'),('destination','CON.bin'),('destination','model/weights.PART'),
                 ('sha256',None),('commit','main'),('repo','https://example.invalid/model'),('source_path','../weights')]
        for field,value in invalid:
            self.lock=copy.deepcopy(original);self.lock['files'][0][field]=value;self.write()
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):model_setup.plan(self.lock_path)
        self.lock=copy.deepcopy(original);self.lock['files'][1]['destination']=self.lock['files'][0]['destination'].upper();self.write()
        with self.assertRaisesRegex(ValueError,'Duplicate'):model_setup.plan(self.lock_path)
        self.assertFalse(self.output.exists())

    def test_redirect_policy_and_network_errors_never_expose_signed_queries(self):
        handler=model_setup.OfficialRedirects();request=urllib.request.Request('https://huggingface.co/example/model/resolve/'+'a'*40+'/weights')
        accepted=handler.redirect_request(request,None,302,'Found',{},'https://us.aws.cdn.hf.co/file?signature=secret')
        self.assertEqual(accepted.host,'us.aws.cdn.hf.co')
        for url in ('http://huggingface.co/file','https://localhost/file','https://evil-hf.co/file',
                    'https://hf.co.evil.example/file','https://huggingface.co@localhost/file','https://huggingface.co:8443/file'):
            with self.subTest(url=url),self.assertRaises(ValueError):handler.redirect_request(request,None,302,'Found',{},url)
        with self.assertRaises(ValueError):model_setup.allowed_url('https://us.aws.cdn.hf.co/file',initial=True)
        with self.opener():
            self.http.open.side_effect=urllib.error.HTTPError('https://us.aws.cdn.hf.co/x?signature=secret',403,'secret URL',{},None)
            with self.assertRaises(RuntimeError) as error:model_setup.fetch(self.lock_path,self.output)
        self.assertIn('HTTP 403',str(error.exception));self.assertNotIn('secret',str(error.exception));self.assertNotIn('signature',str(error.exception))

    def test_publication_race_preserves_new_existing_file(self):
        original=model_setup._publish
        def race(part,target):
            target.write_bytes(b'arrived concurrently');original(part,target)
        with self.opener(),patch.object(model_setup,'_publish',side_effect=race),self.assertRaises(RuntimeError):
            model_setup.fetch(self.lock_path,self.output)
        self.assertEqual((self.output/'model/config.json').read_bytes(),b'arrived concurrently')
        self.assertTrue((self.output/'model/config.json.part').exists())

    def test_symlink_escape_is_rejected_before_network(self):
        outside=self.root/'outside';outside.mkdir();self.output.mkdir()
        try:(self.output/'model').symlink_to(outside,target_is_directory=True)
        except OSError:self.skipTest('This platform does not permit directory symlinks for this user')
        with self.opener(),self.assertRaisesRegex(ValueError,'escapes'):model_setup.fetch(self.lock_path,self.output)
        self.http.open.assert_not_called();self.assertEqual(list(outside.iterdir()),[])


if __name__=='__main__':unittest.main()
