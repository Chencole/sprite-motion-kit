"""Install a pinned model lock directly from official Hugging Face hosting.

plan --lock models.lock.json                 (read-only; no network)
fetch --lock models.lock.json --root models  (explicit download)

Lock schema: {schema:1, files:[{repo,commit,source_path,destination,size,sha256}],
repositories:[{repo,commit,license,license_note}]}. All file hashes are required;
do not invent missing hashes from an unfinished download ledger. Destination
paths are portable relative POSIX paths. Weights retain their upstream terms;
the plugin's MIT license is not a license for model weights. No upload, model
execution, dependency installation, automatic retry or partial-file resume.
"""
import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

CHUNK=8*1024*1024


def relative_path(value):
    if not isinstance(value,str) or not value or any(ord(c)<32 or c in '\\:*?<>|"' for c in value):
        raise ValueError('Expected a portable relative POSIX path')
    parts=PurePosixPath(value).parts
    if not parts or value.startswith('/') or any(p in ('.','..') or p.endswith((' ','.')) for p in value.split('/')):
        raise ValueError('Path traversal or ambiguous path component')
    if value!=PurePosixPath(value).as_posix():raise ValueError('Path must be normalized')
    for part in parts:
        if re.fullmatch(r'CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]',part.split('.')[0],re.I):raise ValueError('Reserved filename')
    return value


def identity(repo,commit):
    if not isinstance(repo,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*',repo):
        raise ValueError('Expected a Hugging Face owner/repository identity')
    if not isinstance(commit,str) or not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('A full pinned repository commit is required')


def load_lock(path):
    data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if data.get('schema')!=1 or not isinstance(data.get('files'),list) or not data['files']:raise ValueError('Expected model lock schema 1 with files')
    files=[]; destinations=set()
    for record in data['files']:
        if not isinstance(record,dict):raise ValueError('Every locked file must be an object')
        identity(record.get('repo'),record.get('commit'))
        source=relative_path(record.get('source_path')); destination=relative_path(record.get('destination'))
        if destination.casefold().endswith('.part') or destination.casefold() in destinations:raise ValueError('Duplicate destination or reserved .part suffix')
        destinations.add(destination.casefold())
        if type(record.get('size')) is not int or record['size']<0:raise ValueError('Every file needs an exact nonnegative byte size')
        if not isinstance(record.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',record['sha256']):raise ValueError('Every file needs a complete SHA-256 before fetch')
        files.append({key:record[key] for key in ('repo','commit','source_path','destination','size','sha256')})
    for destination in destinations:
        if any(str(parent) in destinations for parent in PurePosixPath(destination).parents if str(parent)!='.'):
            raise ValueError('A destination file cannot also be another destination directory')
    repositories={}
    for entry in data.get('repositories',[]):
        identity(entry.get('repo'),entry.get('commit')); repositories[(entry['repo'],entry['commit'])]=entry
    return files,repositories


def plan(lock):
    files,metadata=load_lock(lock); repositories=[]
    for repo,commit in sorted({(f['repo'],f['commit']) for f in files}):
        entry=metadata.get((repo,commit),{}); license_tag=entry.get('license',entry.get('license_tag'))
        repositories.append({'repo':repo,'commit':commit,'declared_license':license_tag,
                             'license_note':entry.get('license_note',''),
                             'notice':None if license_tag else 'License is undeclared in this lock; review upstream terms and obtain files directly from official hosting.',
                             'model_card':'https://huggingface.co/'+repo+'/blob/'+commit+'/README.md'})
    return {'status':'planned','files':files,'file_count':len(files),'total_bytes':sum(f['size'] for f in files),
            'repositories':repositories,'notice':'Model weights retain upstream terms; the plugin MIT license does not cover these weights.',
            'downloads_started':0,'models_executed':False}


def allowed_url(url,initial=False):
    try:
        parsed=urllib.parse.urlsplit(url); host=parsed.hostname or ''
        valid_host=host=='huggingface.co' or (not initial and host.endswith('.hf.co'))
        valid=parsed.scheme=='https' and valid_host and parsed.port in (None,443) and parsed.username is None and parsed.password is None
    except ValueError:valid=False
    if not valid:raise ValueError('Only HTTPS Hugging Face hosting and its official hf.co CDN redirects are allowed')


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        allowed_url(newurl)
        return super().redirect_request(request,fp,code,msg,headers,newurl)


def _opener():
    return urllib.request.build_opener(OfficialRedirects())


def target_path(root,destination):
    target=(root/relative_path(destination)).resolve()
    if not target.is_relative_to(root):raise ValueError('Resolved destination escapes the requested model directory')
    return target


def matches(path,entry):
    if not path.is_file() or path.stat().st_size!=entry['size']:return False
    sha=hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda:file.read(CHUNK),b''):sha.update(chunk)
    return sha.hexdigest()==entry['sha256']


def _publish(part,target):
    # Windows rename refuses an existing destination. POSIX rename overwrites,
    # so use atomic exclusive hard-link publication there instead.
    if os.name=='nt':part.rename(target)
    else:os.link(part,target); part.unlink()


def fetch(lock,root):
    summary=plan(lock); root=Path(root).resolve(); pending=[]; result=[]
    # Check the entire batch for existing conflicts before any download/write.
    for entry in summary['files']:
        target=target_path(root,entry['destination']); part=target_path(root,entry['destination']+'.part')
        if target.exists():
            if not matches(target,entry):raise ValueError('Existing file differs; preserved: '+entry['destination'])
            result.append({'destination':entry['destination'],'status':'reused_verified','sha256':entry['sha256']})
        elif part.exists():raise ValueError('Existing .part file preserved; inspect it before an explicit retry: '+entry['destination'])
        else:pending.append(entry)
    opener=_opener() if pending else None
    for entry in pending:
        target=target_path(root,entry['destination']); part=target_path(root,entry['destination']+'.part')
        target.parent.mkdir(parents=True,exist_ok=True)
        if target!=target_path(root,entry['destination']) or part!=target_path(root,entry['destination']+'.part'):
            raise ValueError('Destination changed during setup')
        url='https://huggingface.co/'+entry['repo']+'/resolve/'+entry['commit']+'/'+urllib.parse.quote(entry['source_path'],safe='/')
        allowed_url(url,initial=True); request=urllib.request.Request(url,headers={'User-Agent':'SpriteMotionKit-model-setup','Accept-Encoding':'identity'},method='GET')
        received=0; sha=hashlib.sha256()
        try:
            with opener.open(request,timeout=60) as response:
                allowed_url(response.geturl())
                with part.open('xb') as file:
                    for chunk in iter(lambda:response.read(CHUNK),b''):
                        received+=len(chunk)
                        if received>entry['size']:raise ValueError('Response exceeds locked size')
                        file.write(chunk);sha.update(chunk)
                    file.flush();os.fsync(file.fileno())
            if received!=entry['size'] or sha.hexdigest()!=entry['sha256']:raise ValueError('Response differs from locked size/SHA-256')
            _publish(part,target)
        except Exception as error:
            # Network exceptions may contain signed CDN URLs. Never print them.
            reason='HTTP '+str(error.code) if isinstance(error,urllib.error.HTTPError) else type(error).__name__
            raise RuntimeError('Model fetch failed for '+entry['destination']+' ('+reason+'); existing files and any .part are preserved') from None
        result.append({'destination':entry['destination'],'status':'downloaded_verified','sha256':entry['sha256']})
    return {'status':'complete','file_count':len(result),'total_bytes':summary['total_bytes'],'files':result,
            'repositories':summary['repositories'],'notice':summary['notice'],'models_executed':False,'uploaded':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); commands=parser.add_subparsers(dest='command',required=True)
    for name in ('plan','fetch'):
        command=commands.add_parser(name);command.add_argument('--lock',required=True)
        if name=='fetch':command.add_argument('--root',required=True)
    args=vars(parser.parse_args()); name=args.pop('command')
    print(json.dumps((fetch if name=='fetch' else plan)(**args),indent=2,ensure_ascii=False))
