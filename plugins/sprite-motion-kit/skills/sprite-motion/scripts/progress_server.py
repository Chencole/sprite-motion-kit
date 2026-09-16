"""Read-only, loopback-only live view of persisted sprite production evidence.

No provider calls, credentials, database access, writes to jobs, or raw JSON serving.
Python 3.10+, standard library only. See references/progress-view.md.
"""
import argparse
import hashlib
import json
import mimetypes
import os
import re
import socket
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

VIEW_VERSION = '5.5'
CURRENT_ACTIONS = {'body_attack', 'walk', 'death'}
RETIRED_SCOPES = {'body-motion-v3', 'body-motion-v3-r2', 'body-motion-v4-three-actions', 'body-motion-v4-pilot-six'}
MEDIA = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.mp4', '.webm'}
NAMES = {'job.json', 'sample.json', 'batch.json', 'scope.json', 'motion-coverage.json', 'action-design.json', 'comparison.json', 'production-status.json', 'queue.json', 'body-motion-v3-fullqueue.json', 'body-motion-v3-r2-fullqueue.json'}
SKIP = {'.git', 'node_modules', '__pycache__', '.venv', 'config', 'configs', 'db', 'database', 'secrets'}
LABELS = ['原画设计', '首帧提交', '首帧审核', '视频生成', '透明抽帧', 'Review', '游戏接入']


def safe(value, limit=180):
    if not isinstance(value, (str, int, float)):
        return ''
    value = str(value)
    if re.search(r'https?[:/]|data:|bearer\s|api.?key|token[=:]|secret[=:]|signature[=:]|sk-[a-zA-Z0-9]', value, re.I):
        return '[敏感或远程内容已隐藏]'
    return ''.join(c for c in value if c >= ' ' or c == '\n')[:limit]


def read(path):
    try:
        if os.name == 'nt':
            import ctypes
            import msvcrt
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            create = kernel.CreateFileW
            create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            create.restype = wintypes.HANDLE
            # Share READ, WRITE and DELETE, so atomic producer renames remain legal.
            handle = create(str(path), 0x80000000, 7, None, 3, 0x80, None)
            if handle == ctypes.c_void_p(-1).value:
                return None
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            stream = os.fdopen(fd, 'r', encoding='utf-8-sig')
        else:
            stream = path.open('r', encoding='utf-8-sig')
        with stream:
            if os.fstat(stream.fileno()).st_size > 12_000_000:
                return None
            result = json.load(stream)
        return result if isinstance(result, dict) else None
    except (OSError, ValueError):
        return None


def mapping(value):
    if isinstance(value, dict):
        return value.items()
    if isinstance(value, list):
        return [(v.get('id', v.get('character_id', str(i))), v) for i, v in enumerate(value) if isinstance(v, dict)]
    return []


class Evidence:
    def __init__(self, roots, coverage, media_roots, scope_policy=None, scope_spec=None):
        self.roots, self.coverage = roots, coverage
        self.scope_policy = scope_policy
        self.scope_spec = scope_spec
        self.source_name = scope_spec.stem.removesuffix('-spec') if scope_spec else scope_policy
        self.source_parents = list(dict.fromkeys([p.parent for p in coverage] + [r.parent for r in roots if scope_policy and r.name == scope_policy + '-batch']))
        self.allowed = list(dict.fromkeys(roots + media_roots + [p.parent for p in coverage]))
        self.lock = threading.Lock()
        self.files, self.digests = {}, {}
        self.snapshot = {'schema_version': 1, 'ui_version': VIEW_VERSION, 'items': [], 'sources': [], 'warnings': [], 'updated_at': None}

    def permitted(self, p):
        return any(p.is_relative_to(r) for r in self.allowed)

    def local(self, value, owner):
        if not isinstance(value, str) or re.search(r'^[a-z]+://|^\\\\|^//|^data:', value, re.I):
            return None
        path = Path(value)
        candidates = [path] if path.is_absolute() else [owner.parent / path] + [r / path for r in self.roots] + [r.parent.parent / path for r in self.roots]
        for candidate in candidates:
            try:
                p = candidate.resolve()
                if self.permitted(p) and p.suffix.lower() in MEDIA and p.is_file():
                    return p
            except (OSError, ValueError):
                pass
        return None

    def media(self, value, owner, registry):
        p = self.local(value, owner)
        if p is None:
            return None
        token = hashlib.sha256(str(p).encode()).hexdigest()[:32]
        registry[token] = p
        return '/media/' + token

    def digest(self, p):
        stat = p.stat()
        key = (str(p), stat.st_mtime_ns, stat.st_size)
        if key not in self.digests:
            with p.open('rb') as stream:
                h = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(chunk)
                self.digests[key] = h.hexdigest()
        return self.digests[key]

    def scan(self):
        registry, docs, warnings, sources = {}, {}, [], []
        for root in self.roots:
            sources.append({'name': safe(root.name), 'exists': root.is_dir(), 'kind': '任务目录'})
            count = 0
            if not root.is_dir():
                continue
            for parent, dirs, files in os.walk(root, followlinks=False):
                count += 1
                dirs[:] = [d for d in dirs if d.lower() not in SKIP and not (Path(parent) / d).is_symlink()]
                if len(Path(parent).relative_to(root).parts) >= 10:
                    dirs[:] = []
                if count > 6000 or len(docs) >= 4000:
                    warnings.append('扫描达到有界上限；请缩小任务目录。')
                    break
                for name in files:
                    if name in NAMES or name in {'ledger.json', 'fullqueue.json'} or name.endswith('-fullqueue.json') or name.endswith('-still-review.json') or name.endswith('-design.json'):
                        p = Path(parent) / name
                        if not self.permitted(p.resolve()):
                            continue
                        d = read(p)
                        if d is not None:
                            docs[p] = d
                        else:
                            warnings.append(safe(name) + ' 暂不可读，等待下一次刷新。')
        for p in self.coverage:
            exists = p.is_file()
            sources.append({'name': safe(p.name), 'exists': exists, 'kind': '全角色覆盖'})
            if exists:
                d = read(p)
                if d is not None:
                    docs[p] = d
                else:
                    warnings.append('覆盖清单写入中或不可读；未据此声明全覆盖。')
        current_scopes = {}
        current_scope_hashes = set()
        if self.scope_policy and (self.scope_spec or self.scope_policy not in RETIRED_SCOPES):
            for parent in self.source_parents:
                for candidate in parent.iterdir():
                    if candidate.name not in {self.source_name + '-spec.json', self.source_name + '-scope.json', self.source_name + '-batch'}:
                        continue
                    paths = [candidate] if candidate.is_file() else [candidate / 'scope.json', candidate / 'batch.json']
                    for source in paths:
                        if source.suffix.lower() != '.json' or not self.permitted(source.resolve()):
                            continue
                        definition = read(source)
                        if definition is None:
                            continue
                        current_scopes[source] = definition
                        if source.name in {'scope.json', self.source_name + '-scope.json'}:
                            current_scope_hashes.add(self.digest(source))
                        if isinstance(definition.get('scope_sha256'), str):
                            current_scope_hashes.add(definition['scope_sha256'])
            sources = [s for s in sources if s['kind'] != '全角色覆盖']
            sources.append({'name': self.scope_policy, 'exists': bool(current_scopes), 'kind': '当前全目标'})
            if not current_scopes:
                warnings.append(self.scope_policy + ' 新目标清单尚未落地；旧未提交队列已被替代，不再计作待办。')
            docs.update(current_scopes)
        items = {}
        coverage_summary = {}

        def row(character, action, group='production'):
            key = (group, str(character), str(action))
            if key not in items:
                items[key] = {'id': hashlib.sha256(repr(key).encode()).hexdigest()[:20], 'character': safe(character), 'action': safe(action), 'group': group,
                              'stages': [{'state': 'pending', 'text': '未提交 / 无记录'} for _ in LABELS],
                              'media': {}, 'evidence': [], 'notes': [], 'updated_at': 0}
            return items[key]

        def evidence(item, p):
            name = next((str(p.relative_to(r)).replace('\\', '/') for r in self.allowed if p.is_relative_to(r)), p.name)
            name = safe(name, 240)
            if name not in item['evidence']:
                item['evidence'].append(name)
            try:
                item['updated_at'] = max(item['updated_at'], p.stat().st_mtime)
            except OSError:
                pass

        def stage(item, index, state, text):
            item['stages'][index] = {'state': state, 'text': text}

        def bound(d):
            b = d.get('coverage_binding') or {}
            if not isinstance(b, dict):
                b = {}
            return b.get('character_id', b.get('character', d.get('character_id'))), b.get('action_id', b.get('action', d.get('action_id')))

        # Coverage is an inventory, never proof that anything was submitted.
        for p, d in docs.items():
            if p.name not in {'scope.json', 'motion-coverage.json'}:
                continue
            if isinstance(d.get('summary'), dict):
                coverage_summary = {k: v for k, v in d['summary'].items() if k in {'batch_action_tasks', 'batch_characters', 'role_form_profiles', 'profile_action_requirements', 'profile_actions_missing'} and isinstance(v, int)}
            profiles = {v.get('id'): v for v in d.get('profiles', []) if isinstance(v, dict)}
            for requirement in d.get('requirements', []):
                if not isinstance(requirement, dict) or requirement.get('applicable') is False:
                    continue
                profile = profiles.get(requirement.get('profile_id'), {})
                cid = profile.get('batch_character') or requirement.get('character_id')
                aid = requirement.get('action_id')
                if not cid or not aid:
                    continue
                item = row(cid, aid)
                evidence(item, p)
                aliases = item.setdefault('aliases', [])
                alias = safe(profile.get('display_name', profile.get('id', '')))
                if alias and alias not in aliases:
                    aliases.append(alias)
                detail = safe(requirement.get('purpose', ''), 180)
                if detail and detail not in item['notes']:
                    item['notes'].append(detail)
                if (requirement.get('coverage') or {}).get('status') in {'published_exact', 'published'}:
                    stage(item, 6, 'recorded', '覆盖清单记录现有发布 · 非本轮新生成')
            for cid, character in mapping(d.get('characters', {})):
                if not isinstance(character, dict):
                    continue
                actions = character.get('required_actions') or list((character.get('action_map') or {}).values()) or character.get('actions', [])
                if isinstance(actions, dict):
                    actions = list(actions)
                for action in actions:
                    aid = action.get('id', action.get('action_id', action.get('name'))) if isinstance(action, dict) else action
                    if not aid:
                        continue
                    item = row(cid, aid)
                    evidence(item, p)
                    item['name'] = safe(character.get('name', cid))
                    ref = character.get('character', character.get('identity_image', character.get('reference_image')))
                    media = self.media(ref, p, registry)
                    if media:
                        item['media']['art'] = media
                        stage(item, 0, 'recorded', '已有本地角色原画')
                    if isinstance(action, dict) and action.get('purpose'):
                        item['notes'].append(safe(action['purpose'], 400))

        for p, d in docs.items():
            if p.name != 'production-status.json':
                continue
            reference = d.get('character_reference')
            cid = d.get('character_id') or (Path(reference).parent.name if isinstance(reference, str) else '待绑定角色')
            aid = d.get('current_action') or '准备阶段'
            item = row(cid, aid)
            item['active'] = True
            evidence(item, p)
            media = self.media(d.get('character_reference'), p, registry)
            if media:
                item['media']['art'] = media
                stage(item, 0, 'recorded', '当前角色原画可看')
            if d.get('new_generation_submitted') is False:
                stage(item, 1, 'pending', '准备阶段 · 尚未提交首帧')
                stage(item, 3, 'pending', 'Veo 视频尚未提交')
            if d.get('phase') == 'first_frame_review_failed':
                stage(item, 2, 'failed', '首帧审核失败 · 待修复')
            item['notes'].append('生产状态：' + safe(d.get('phase', 'unknown')))
            item['notes'].extend(safe(n, 450) for n in (d.get('notes') or [])[:6])

        queued_jobs, reuse_samples, provider_bindings, integration_records = {}, {}, set(), {}
        canonical_jobs, execution = {}, {}
        for p, d in sorted(docs.items(), key=lambda pair: ({'ledger.json': 1, 'production-status.json': 2}.get(pair[0].name, 0), str(pair[0]))):
            if p.name not in {'queue.json', 'fullqueue.json', 'ledger.json', 'production-status.json'} and not p.name.endswith('-fullqueue.json'):
                continue
            queue_scope = d.get('scope_sha256')
            if queue_scope not in current_scope_hashes and p.name in {'ledger.json', 'production-status.json'} and isinstance(d.get('queue'), str):
                queue_path = Path(d['queue']).resolve()
                queue_doc = docs.get(queue_path)
                if queue_doc and self.permitted(queue_path) and d.get('queue_sha256') == self.digest(queue_path):
                    queue_scope = queue_doc.get('scope_sha256')
            if queue_scope not in current_scope_hashes:
                continue
            if p.name in {'ledger.json', 'production-status.json'} and 'halt' in d:
                halt = d.get('halt')
                reason = halt.get('reason') if isinstance(halt, dict) else halt
                execution = {'paused': bool(halt), 'reason': reason if isinstance(reason, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,120}', reason) else ''}
            entries = d.get('items', d.get('jobs', d.get('tasks', d.get('queue', []))))
            if isinstance(entries, dict):
                entries = list(entries.values())
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                cid, aid = bound(entry)
                cid = cid or entry.get('character', entry.get('batch_character'))
                aid = aid or entry.get('action')
                if (not cid or not aid) and isinstance(entry.get('id'), str) and '/' in entry['id']:
                    cid, aid = entry['id'].split('/', 1)
                if not isinstance(cid, str) or not isinstance(aid, str):
                    continue
                item = row(cid, aid)
                item['mode'] = 'existing_image'
                item['queued'] = True
                item['current_queue'] = True
                item['queue_state'] = safe(entry.get('state', 'planned'))
                item['failure_reason'] = safe(entry.get('blocked_reason') or entry.get('hold_reason') or entry.get('failure_reason') or '', 400)
                item['blocked'] = entry.get('blocked') is True or any(tag in item['queue_state'].lower() for tag in ('hold', 'blocked', 'keycollision'))
                if isinstance(entry.get('integration_json'), str) and isinstance(entry.get('integration_sha256'), str):
                    integration_records[(cid, aid)] = (entry['integration_json'], entry['integration_sha256'])
                binding = entry.get('provider_coverage_binding')
                if isinstance(binding, dict) and isinstance(binding.get('scope_sha256'), str):
                    provider_bindings.add((binding['scope_sha256'], cid, aid))
                reuse = entry.get('reuse')
                if isinstance(entry.get('sample_json'), str):
                    reuse = {**(reuse if isinstance(reuse, dict) else {}),
                             'sample_json': entry['sample_json'], 'sample_json_sha256': entry.get('sample_sha256'),
                             'review_json': entry.get('review_json'), 'review_json_sha256': entry.get('review_sha256'),
                             'reuse_decision_json': entry.get('reuse_decision_json'), 'reuse_decision_sha256': entry.get('reuse_decision_sha256')}
                if isinstance(reuse, dict) and isinstance(reuse.get('sample_json'), str) and isinstance(reuse.get('sample_json_sha256'), str):
                    candidate = Path(reuse['sample_json']).resolve()
                    if self.permitted(candidate) and candidate.suffix == '.json':
                        reuse_samples[candidate] = (item, reuse)
                evidence(item, p)
                for field in ('character_png', 'canonical_character_png', 'original_character_png', 'character_reference', 'existing_image', 'reference_image', 'image', 'source_image'):
                    url = self.media(entry.get(field), p, registry)
                    if url:
                        item['media']['art'] = url
                        stage(item, 0, 'recorded', '已有游戏角色原画')
                        break
                stage(item, 3, 'pending', '已排入本轮队列 · 尚无提交证据')
                if item['current_queue']:
                    queue_state = entry.get('state')
                    if queue_state == 'reconciliation_hold':
                        stage(item, 3, 'waiting', '历史回执待核对 · 暂停新提交')
                    elif queue_state == 'reuse_candidate_review_before_generation':
                        stage(item, 3, 'pending', '候选视频待无 VFX 审核 · 未新提交')
                        stage(item, 5, 'waiting', '本体复用审核未完成')
                    elif queue_state == 'reuse_completed_local_rebind':
                        item['notes'].append('v3 队列：已有完成视频，保留活动预览；新 scope 本地绑定待核验。')
                    item['notes'].append('当前队列状态：' + item['queue_state'])
                for field in ('job', 'job_dir', 'job_path', 'generation_job', 'video_job'):
                    value = entry.get(field)
                    if isinstance(value, str) and not re.search(r'://|^\\\\|^//', value):
                        job_path = Path(value)
                        candidates = [job_path] if job_path.is_absolute() else [p.parent / job_path] + [r / job_path for r in self.roots]
                        for candidate in candidates:
                            target = candidate.resolve()
                            if self.permitted(target):
                                queued_jobs[target.parent if target.name == 'job.json' else target] = (cid, aid)
                                if p.name in {'ledger.json', 'production-status.json'}:
                                    canonical_jobs[(cid, aid)] = target.parent if target.name == 'job.json' else target

        jobs_by_digest = {}
        stills_by_digest = {}
        job_docs = sorted(((p, d) for p, d in docs.items() if p.name == 'job.json'), key=lambda pair: (pair[0].parent.stat().st_ctime_ns, str(pair[0])))
        for p, d in job_docs:
            # Read only this job's known request packet; never forward its body.
            packet = read(p.parent / 'request.json') or {}
            workflow = packet.get('workflow') or {}
            if not isinstance(workflow, dict):
                workflow = {}
            if packet.get('kind', d.get('kind')) == 'reference_upload':
                source_hash, remote_hash = d.get('source_sha256'), d.get('remote_sha256')
                source_path = self.local(packet.get('source_file'), p)
                matches = []
                for candidate in items.values():
                    art = candidate['media'].get('art')
                    local_art = registry.get(art.rsplit('/', 1)[-1]) if art else None
                    if local_art and (local_art == source_path or (source_hash and self.digest(local_art) == source_hash)):
                        matches.append(candidate['character'])
                targets = [v for v in items.values() if v['group'] == 'production' and v['character'] in matches]
                if not targets:
                    targets = [row('未绑定身份上传', p.parent.name, 'unbound')]
                results = d.get('local_results') or []
                verified_file = self.local(results[0], p) if isinstance(results, list) and results else None
                valid = d.get('state') == 'verified' and bool(source_hash) and source_hash == remote_hash and verified_file is not None and self.digest(verified_file) == source_hash
                for item in targets:
                    evidence(item, p)
                    stage(item, 0, 'done' if valid else 'recorded', '身份原画已上传 · SHA256 一致' if valid else '身份上传已有回执 · 校验待完成')
                    item['receipt'] = {'kind': 'reference_upload', 'state': safe(d.get('state', 'unknown')), 'hash_match': valid, 'generation_submitted': d.get('generation_submitted') is True}
                    if verified_file:
                        item['media']['art'] = self.media(str(verified_file), p, registry)
                    if d.get('generation_submitted') is False:
                        item['notes'].append('身份原画上传回执：原文件与下载校验件 SHA256 一致；上传不代表首帧或视频生成已提交。' if valid else '身份原画上传尚待校验；没有新生成提交记录。')
                continue
            design = docs.get(p.parent / 'action-design.json', {})
            cid, aid = bound(design or workflow or d)
            if not (cid and aid) and p.parent.resolve() in queued_jobs:
                cid, aid = queued_jobs[p.parent.resolve()]
            # An archived request copy can retain valid binding and newer ctime.
            # The execution ledger, not directory age, selects the current job.
            if (cid, aid) in canonical_jobs and p.parent.resolve() != canonical_jobs[(cid, aid)]:
                continue
            group = 'production' if cid and aid else 'unbound'
            binding = (design or workflow or d).get('coverage_binding') or {}
            if self.scope_policy and cid and aid and binding.get('scope_sha256') not in current_scope_hashes and (binding.get('scope_sha256'), cid, aid) not in provider_bindings and queued_jobs.get(p.parent.resolve()) != (cid, aid):
                group = 'unbound'
            if not (cid and aid):
                cid, aid = '未绑定试样', p.parent.name
            item = row(cid, aid, group)
            if workflow.get('mode') == 'existing_image' or packet.get('mode') == 'existing_image':
                item['mode'] = 'existing_image'
            evidence(item, p)
            cost = d.get('provider_points_cost', d.get('points_cost'))
            if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                item['cost_points'] = cost
                item['notes'].append('任务实际记录费用：' + str(cost) + ' points')
            state = str(d.get('state', d.get('status', 'unknown'))).lower()
            phase = workflow.get('phase', '')
            kind = packet.get('kind', d.get('kind', ''))
            attempt = None
            if phase in {'action_still', 'action_video'}:
                attempt = {'name': safe(p.parent.name), 'phase': phase, 'state': safe(state), 'updated_at': p.stat().st_mtime}
                item.setdefault('attempts', []).append(attempt)
                if phase == 'action_still':
                    item['current_still_attempt'] = attempt['name']
                    item['media'].pop('still', None)
                    stage(item, 2, 'pending', '当前尝试尚未审核')
                else:
                    item['current_video_attempt'] = attempt['name']
                    item['current_video_sha256'] = None
                    item['media'].pop('video', None)
            results = d.get('local_results') or []
            if not isinstance(results, list):
                results = []
            local = [(self.local(v, p), v) for v in results]
            local = [(x, v) for x, v in local if x]
            is_video = kind == 'video' or phase == 'action_video' or any(x.suffix.lower() in {'.mp4', '.webm'} for x, _ in local) or 'video' in p.parent.name.lower()
            index = 3 if is_video else (1 if phase == 'action_still' else 0)
            if is_video:
                item['video_job'] = {'state': safe(state), 'has_external_job_id': bool(d.get('external_job_id')), 'submission_in_progress': (p.parent / 'submit.lock').is_file(), 'name': safe(p.parent.name)}
            model = packet.get('model')
            if isinstance(model, str):
                item['model'] = safe(model)
            if state in {'succeeded', 'completed', 'complete', 'success'}:
                stage(item, index, 'done' if local else 'recorded', '已完成 · 本地媒体可看' if local else '任务记录完成 · 本地文件未就绪')
            elif state in {'failed', 'error', 'cancelled', 'canceled', 'rejected'}:
                stage(item, index, 'failed', '任务失败 / 已取消')
                item['notes'].append('失败详情保留在本地任务记录；页面不转发供应商错误正文。')
            elif state == 'submission_unknown':
                stage(item, index, 'waiting', '提交结果待确认 · 不代表可重试')
            elif state in {'prepared', 'created', 'draft'} and not d.get('external_job_id'):
                in_flight = is_video and item['video_job']['submission_in_progress']
                stage(item, index, 'waiting' if in_flight else 'pending', '存在提交锁 · 尚待回执' if in_flight else '已准备 · 尚无提交回执')
            elif state in {'submitted', 'pending', 'queued', 'processing', 'running', 'polling', 'waiting'} or d.get('external_job_id'):
                stage(item, index, 'waiting', '首帧生成中 · 已提交' if index == 1 else '已提交 · 等待任务写入新状态')
            else:
                stage(item, index, 'recorded', '状态待识别 · ' + safe(state, 40))
            if design:
                evidence(item, p.parent / 'action-design.json')
                if item['stages'][0]['state'] == 'pending':
                    stage(item, 0, 'recorded', '已有动作设计记录')
            for path, value in local:
                media = self.media(value, p, registry)
                if path.suffix.lower() in {'.mp4', '.webm'}:
                    item['media']['video'] = media
                    try:
                        digest = self.digest(path)
                        jobs_by_digest[digest] = item
                        if attempt:
                            attempt['video'] = media
                            item['current_video_sha256'] = digest
                    except OSError:
                        pass
                else:
                    item['media']['still' if phase == 'action_still' else 'art'] = media
                    if phase == 'action_still':
                        attempt['image'] = media
                        stills_by_digest[self.digest(path)] = (item, attempt)
            if phase == 'action_still':
                report_path = p.parent / 'still-review.json'
                report = read(report_path)
                record = d.get('workflow_review')
                if report and isinstance(record, dict):
                    checks = report.get('checks') or {}
                    if checks and all(v is True for v in checks.values()):
                        stage(item, 2, 'recorded', '已有首帧审核记录 · 时效待工作流核验')
                    else:
                        stage(item, 2, 'failed', '首帧审核未全通过')
                    evidence(item, report_path)

        for p, report in docs.items():
            if not p.name.endswith('-still-review.json'):
                continue
            hashes = report.get('input_hashes') or {}
            result_hash = hashes.get('result_sha256') if isinstance(hashes, dict) else None
            match = stills_by_digest.get(result_hash)
            if match is None and not result_hash:
                match = next(((v, a) for v in items.values() for a in v.get('attempts', []) if p.stem == a['name'] + '-review'), None)
            if match is None:
                continue
            item, attempt = match
            current = item.get('current_still_attempt') == attempt['name']
            evidence(item, p)
            checks = report.get('checks') or {}
            failures = [safe(k, 80) for k, v in checks.items() if v is False] if isinstance(checks, dict) else []
            if failures:
                attempt['review'] = '审核失败 · ' + ', '.join(failures)
                if current:
                    stage(item, 2, 'failed', '首帧审核失败 · ' + ', '.join(failures))
            elif current and item['stages'][2]['state'] == 'pending':
                stage(item, 2, 'recorded', '存在目视报告 · 工作流审核登记待核验')
            notes = report.get('notes')
            if isinstance(notes, str):
                attempt['review_notes'] = safe(notes, 1000)
                if current:
                    item['notes'].append('首帧审核：' + safe(notes, 1000))

        # Prefer the explicit comparison copies over duplicate historical exports.
        samples = sorted([(p, d) for p, d in docs.items() if p.name == 'sample.json'], key=lambda pair: ('review-veo-comparison' not in str(pair[0]), len(str(pair[0]))))
        seen = set()
        for p, d in samples:
            reuse_match = reuse_samples.get(p.resolve())
            if reuse_match and self.digest(p) != reuse_match[1]['sample_json_sha256']:
                reuse_match = None
            for clip in d.get('clips', []):
                if not isinstance(clip, dict):
                    continue
                cid, aid = bound(d)
                aid = aid or clip.get('name', 'unknown')
                source_hash = d.get('source_video_sha256')
                identity = (source_hash or str(p), aid, tuple(d.get('interval', [])))
                if reuse_match:
                    identity += ('current-reuse', reuse_match[0]['character'], reuse_match[0]['action'])
                if identity in seen:
                    continue
                seen.add(identity)
                item = reuse_match[0] if reuse_match else jobs_by_digest.get(source_hash)
                if reuse_match:
                    item['current_video_sha256'] = source_hash
                if item is None and cid:
                    sample_group = 'production'
                    if self.scope_policy and (d.get('coverage_binding') or {}).get('scope_sha256') not in current_scope_hashes:
                        sample_group = 'unbound'
                    item = row(cid, aid, sample_group)
                if item is None:
                    item = row(d.get('character', '未绑定试样'), aid, 'unbound')
                if item.get('current_video_attempt') and item.get('current_video_sha256') != source_hash:
                    evidence(item, p)
                    item['notes'].append('存在早前视频抽帧记录；不计作当前视频尝试的结果。')
                    continue
                item['display_action'] = safe(aid)
                if not cid:
                    item['notes'].append('独立试样，无全角色覆盖绑定。')
                evidence(item, p)
                for field, key in [('character_reference', 'art'), ('source_video', 'video')]:
                    media = self.media(d.get(field), p, registry)
                    if media:
                        item['media'][key] = media
                frames = clip.get('frames') or []
                frame_urls = [self.media(f, p, registry) for f in frames[:500]]
                if frame_urls and all(frame_urls) and len(frames) == len(frame_urls):
                    item['media']['frames'] = frame_urls
                    item['seconds'] = clip.get('seconds', 1)
                    item['loop'] = clip.get('loop', False) is True
                    item['times'] = clip.get('source_times_seconds', [])
                    stage(item, 4, 'done', str(len(frame_urls)) + ' 帧本地序列可看')
                elif frames:
                    stage(item, 4, 'waiting', '抽帧记录存在 · 本地帧不齐')
                for candidate in (clip.get('preview_gif'), clip.get('gif'), d.get('preview_gif'), d.get('gif')):
                    preview = self.media(candidate, p, registry)
                    if preview:
                        item['media']['gif'] = preview
                        break
                draft = d.get('draft') is True or 'draft' in str(d.get('status', ''))
                if draft:
                    stage(item, 5, 'failed', '诊断草稿 · 待修复 / 审核')
                elif clip.get('accepted_by_user') is True:
                    stage(item, 5, 'recorded', '记录用户已验收 · 时效待核验')
                else:
                    stage(item, 5, 'waiting', '待视觉审核 / 用户验收')
                stage(item, 6, 'recorded' if d.get('game_assets_replaced') is True else 'pending', '记录已替换游戏素材' if d.get('game_assets_replaced') is True else '未接入 / 无接入记录')
                if reuse_match:
                    item['reuse_sample_verified'] = True
                    reuse = reuse_match[1]
                    item['reuse_sample_sha256'] = reuse['sample_json_sha256']
                    item['reuse_review_sha256'] = reuse.get('review_json_sha256')
                    stage(item, 5, 'waiting', '当前范围复用待最终审核，不新投')
                    review_path = Path(reuse['review_json']).resolve() if isinstance(reuse.get('review_json'), str) else None
                    if review_path and self.permitted(review_path) and review_path.is_file() and self.digest(review_path) == reuse.get('review_json_sha256'):
                        report = read(review_path) or {}
                        if report.get('status') == 'approved_for_integration' and report.get('sample_sha256') == reuse['sample_json_sha256']:
                            stage(item, 5, 'done', '当前复用审核通过 · sample / review 指纹匹配')
                            evidence(item, review_path)
                        decision_path = Path(reuse['reuse_decision_json']).resolve() if isinstance(reuse.get('reuse_decision_json'), str) else None
                        if decision_path and self.permitted(decision_path) and decision_path.is_file() and self.digest(decision_path) == reuse.get('reuse_decision_sha256'):
                            decision = read(decision_path) or {}
                            criteria = decision.get('criteria') or {}
                            decision_sample = Path(decision['sample']).resolve() if isinstance(decision.get('sample'), str) else None
                            if (decision.get('status') == 'approved_for_reuse'
                                    and (decision.get('character'), decision.get('action')) == (item['character'], item['action'])
                                    and decision.get('evidence_review_sha256') == reuse.get('review_json_sha256')
                                    and report.get('sample_sha256') == reuse['sample_json_sha256']
                                    and decision_sample == p.resolve()
                                    and decision.get('count') == len(item['media'].get('frames', []))
                                    and isinstance(criteria, dict) and criteria and all(v is True for v in criteria.values())):
                                stage(item, 5, 'done', '技术复用判定通过 · 非逐帧用户批准；游戏接入另列')
                                item['reuse_approval_kind'] = 'technical'
                                evidence(item, review_path)
                                evidence(item, decision_path)
                item['notes'].extend(safe(n, 500) for n in (d.get('notes') or [])[:4])

        for p, d in docs.items():
            if p.name == 'action-design.json' or p.name.endswith('-design.json'):
                cid, aid = bound(d)
                if cid and aid:
                    item = row(cid, aid)
                    evidence(item, p)
                    if item['stages'][0]['state'] == 'pending':
                        stage(item, 0, 'recorded', '已有动作设计记录')
                    status = d.get('design_status', d.get('status'))
                    if status:
                        item['notes'].append('动作设计状态：' + safe(status, 80))
            if p.name != 'batch.json':
                continue
            if self.scope_policy and d.get('scope_sha256') not in current_scope_hashes:
                continue
            for cid, actions in mapping(d.get('reviews', {})):
                for aid, report in mapping(actions):
                    if not isinstance(report, dict):
                        continue
                    item = row(cid, aid)
                    checks = report.get('checks') or {}
                    stage(item, 5, 'recorded' if checks and all(v is True for v in checks.values()) else 'failed', 'Batch 审核记录通过 · 时效待核验' if checks and all(v is True for v in checks.values()) else 'Batch 审核未全通过')
                    evidence(item, p)

        values = list(items.values())
        if self.scope_policy:
            old_art = {v['character']: v['media']['art'] for v in values if v['media'].get('art')}
            old_aliases = {v['character']: v.get('aliases', []) for v in values if v.get('aliases')}
            wanted = {}
            coverage_summary = {}
            for p, definition in current_scopes.items():
                scope = definition.get('batch_spec') if isinstance(definition.get('batch_spec'), dict) else definition
                for cid, character in mapping(scope.get('characters', {})):
                    if not isinstance(character, dict):
                        continue
                    actions = character.get('required_actions') or list((character.get('action_map') or {}).values()) or character.get('actions', [])
                    if isinstance(actions, dict):
                        actions = list(actions)
                    for action in actions:
                        aid = action.get('id', action.get('action_id', action.get('name'))) if isinstance(action, dict) else action
                        if not aid:
                            continue
                        item = row(cid, aid)
                        if not item.get('video_job') and not item.get('current_queue') and (str(cid), str(aid)) != ('human-0', 'walk'):
                            item['notes'] = []
                            item['evidence'] = []
                            item['stages'] = [{'state': 'pending', 'text': '未提交 / 无记录'} for _ in LABELS]
                        item['scope_revision'] = self.scope_policy
                        item['mode'] = 'existing_image'
                        item['name'] = safe(character.get('name', cid))
                        item['aliases'] = old_aliases.get(cid, [])
                        evidence(item, p)
                        art = self.media(character.get('character', character.get('reference_image')), p, registry) or old_art.get(cid)
                        if art:
                            item['media']['art'] = art
                            stage(item, 0, 'recorded', '复用已有角色原画')
                        wanted[(str(cid), str(aid))] = item
            retained = []
            for item in values:
                pair = (item['character'], item['action'])
                if pair == ('human-0', 'walk') and item['media'].get('frames'):
                    item['active'] = True
                    item['accepted_baseline'] = True
                    item['notes'].append('用户已认可并保留的原 human walk 透明动画。')
                    if pair not in wanted:
                        item['group'] = 'unbound'
                        item['active'] = False
                        item['scope_revision'] = 'superseded-history'
                        retained.append(item)
                    continue
                if item['group'] == 'production':
                    continue
                if not (item['media'].get('video') or item['media'].get('frames') or (item.get('video_job') or {}).get('state') == 'submission_unknown'):
                    continue
                item['scope_revision'] = 'superseded-history'
                if old_art.get(item['character']):
                    item['media'].setdefault('art', old_art[item['character']])
                item['active'] = False
                item['queued'] = False
                item['notes'].append('历史素材 / 待独立复用审核：不计当前新目标；技能 VFX 由游戏运行时实现。')
                retained.append(item)
            values = list(wanted.values()) + retained
            coverage_summary = {'batch_action_tasks': len(wanted), 'batch_characters': len({cid for cid, _ in wanted})}
        # Read the explicit integration receipt, not the game's config or registry.
        for parent in self.source_parents:
            receipt_path = parent / 'human-0-walk-integration.json'
            if not self.permitted(receipt_path.resolve()):
                continue
            receipt = read(receipt_path)
            if not receipt or receipt.get('character') != 'human-0' or receipt.get('action') != 'walk':
                continue
            for item in values:
                if (item['character'], item['action']) != ('human-0', 'walk'):
                    continue
                if (receipt.get('user_source_accepted') is True
                        and receipt.get('source_video_sha256') == item.get('current_video_sha256')
                        and receipt.get('count') == len(item['media'].get('frames', []))
                        and receipt.get('count', 0) > 0
                        and receipt.get('lossless_pixels') is True
                        and receipt.get('registry') and receipt.get('atlas_sha256')):
                    item['integration'] = {'accepted': True, 'recorded': True, 'frames': receipt['count'], 'lossless_pixels': True}
                    item['completed_baseline'] = True
                    stage(item, 5, 'done', '用户已批准原视频与透明动画')
                    stage(item, 6, 'done', '接入凭据记录已写入 motion.json · 无损共享裁剪')
                    evidence(item, receipt_path)
        for item in values:
            receipt_ref = integration_records.get((item['character'], item['action']))
            if receipt_ref and item['group'] == 'production' and item.get('reuse_sample_verified'):
                receipt_path = Path(receipt_ref[0]).resolve()
                if self.permitted(receipt_path) and receipt_path.is_file() and self.digest(receipt_path) == receipt_ref[1]:
                    receipt = read(receipt_path) or {}
                    action_record = next((a for a in receipt.get('actions', []) if isinstance(a, dict) and a.get('action') == item['action']), None)
                    if (receipt.get('character') == item['character'] and receipt.get('status') in {'integrated_pending_engine_test', 'integrated', 'integrated_and_targeted_engine_tests_passed'}
                            and action_record and action_record.get('sample_sha256') == item.get('reuse_sample_sha256')
                            and action_record.get('review_sha256') == item.get('reuse_review_sha256')
                            and action_record.get('count') == len(item['media'].get('frames', []))
                            and re.fullmatch(r'[a-f0-9]{64}', str(action_record.get('atlas_sha256', '')))
                            and re.fullmatch(r'[a-f0-9]{64}', str(receipt.get('motion_sha256', '')))):
                        stage(item, 6, 'recorded', '已接入 · 接入凭据与当前 sample/review 匹配；引擎验证待核对')
                        evidence(item, receipt_path)
                        item['integration'] = {'recorded': True, 'receipt_sha256': receipt_ref[1], 'engine_validation': 'pending'}
                        validation_path = receipt_path.parent / 'validation.json'
                        validation = read(validation_path) or {}
                        if (validation.get('character') == item['character'] and validation.get('status') == 'integrated_and_targeted_engine_tests_passed'
                                and validation.get('resource_import_exit_code') == 0 and validation.get('routing_failures') == 0
                                and validation.get('combat_geometry_failures') == 0):
                            stage(item, 6, 'done', '已接入 · 导入及引擎定向检查通过（非全游戏目视通关）')
                            item['integration']['engine_validation'] = 'passed'
                            evidence(item, validation_path)
                            map_path = receipt_path.parent / 'validation-v5-map.json'
                            map_report = read(map_path) or {}
                            map_source = Path(map_report['source_map']).resolve() if isinstance(map_report.get('source_map'), str) else None
                            if (map_report.get('status') == 'published_full_v5_map_and_targeted_tests_passed'
                                    and item['character'] + '/' + item['action'] in map_report.get('real_new_clips_integrated', [])
                                    and map_report.get('godot_failures') == 0 and isinstance(map_report.get('godot_checks'), int)
                                    and map_report['godot_checks'] > 0 and map_source and self.permitted(map_source)
                                    and map_source.is_file() and self.digest(map_source) == map_report.get('map_sha256')):
                                count = map_report['godot_checks']
                                stage(item, 6, 'done', '已接入 · 导入/引擎验证通过 · v5 映射 ' + str(count) + ' 项检查通过')
                                item['integration']['map_checks'] = count
                                evidence(item, map_path)
            if item['group'] == 'production' and not item.get('current_still_attempt'):
                item.setdefault('mode', 'existing_image')
            item['notes'] = list(dict.fromkeys(item['notes']))
            states = [s['state'] for s in item['stages']]
            item['status'] = 'completed' if item.get('completed_baseline') else ('failed' if 'failed' in states else ('waiting' if 'waiting' in states else 'pending'))
        values = [v for v in values if v['group'] == 'production' and v.get('scope_revision') == self.scope_policy and v['action'] in CURRENT_ACTIONS]
        for item in values:
            item.pop('attempts', None)
            item['mode'] = 'existing_image'
        # Publication links supplement receipts, never create jobs or old rows.
        for parent in self.source_parents:
            links_path = parent / 'seedance-v5' / 'registry-links.json'
            if not self.permitted(links_path.resolve()):
                continue
            links = read(links_path) or {}
            if links.get('kind') != 'canonical_motion_integration_links' or not isinstance(links.get('entries'), dict):
                continue
            for item in values:
                entry = links['entries'].get(item['character'] + '/' + item['action'])
                if not isinstance(entry, dict) or entry.get('status') != 'integrated_tested':
                    continue
                if (entry.get('character'), entry.get('action')) != (item['character'], item['action']):
                    continue
                if not item.get('current_video_sha256') or entry.get('source_video_sha256') != item['current_video_sha256']:
                    continue
                if entry.get('count', 0) <= 0 or entry['count'] != len(item['media'].get('frames', [])):
                    continue
                paths = {}
                for key in ('sample', 'review', 'integration_receipt', 'validation'):
                    value = entry.get(key)
                    if not isinstance(value, str) or re.search(r'^[a-z]+://|^\\\\|^//', value, re.I):
                        break
                    path = Path(value)
                    path = (path if path.is_absolute() else links_path.parent / path).resolve()
                    if path.suffix.lower() != '.json' or not self.permitted(path) or not path.is_file():
                        break
                    paths[key] = path
                if len(paths) != 4 or any(self.digest(path) != entry.get(key + '_sha256') for key, path in paths.items()):
                    continue
                receipt = read(paths['integration_receipt']) or {}
                action_record = next((a for a in receipt.get('actions', []) if isinstance(a, dict) and a.get('action') == item['action']), {})
                metadata = action_record.get('metadata') or {}
                if (receipt.get('character') != item['character'] or receipt.get('status') not in {'integrated_pending_engine_test', 'integrated', 'integrated_and_targeted_engine_tests_passed'}
                        or action_record.get('sample_sha256', metadata.get('sample_sha256')) != entry['sample_sha256']
                        or action_record.get('review_sha256') != entry['review_sha256']
                        or action_record.get('count') != entry['count']
                        or not re.fullmatch(r'[a-f0-9]{64}', str(entry.get('atlas_sha256', '')))
                        or action_record.get('atlas_sha256') != entry['atlas_sha256']):
                    continue
                report = read(paths['review']) or {}
                approved = (report.get('character') == item['character'] and report.get('action') == item['action']
                            and report.get('status') in {'approved', 'approved_for_integration'}
                            and report.get('sample_sha256') == entry['sample_sha256'])
                technical_reuse = (item.get('reuse_approval_kind') == 'technical' and report.get('status') == 'approved_for_reuse'
                                   and entry.get('reuse_decision_sha256') == entry['review_sha256'])
                if not approved and not technical_reuse and item['stages'][5]['state'] != 'done':
                    continue
                gif = self.media(entry.get('gif'), links_path, registry)
                if gif:
                    item['media']['gif'] = gif
                evidence(item, links_path)
                for path in paths.values():
                    evidence(item, path)
                if item['stages'][6]['state'] == 'done':
                    continue
                stage(item, 5, 'done', '技术复核通过 · 非逐帧用户批准')
                stage(item, 6, 'recorded', '已接入 · canonical sample/review/atlas 凭据匹配')
                item['integration'] = {'recorded': True, 'receipt_sha256': entry['integration_receipt_sha256'], 'engine_validation': 'pending'}
                validation = read(paths['validation']) or {}
                if (validation.get('character') == item['character'] and validation.get('status') == 'passed'
                        and validation.get('integration_receipt_sha256') == entry['integration_receipt_sha256']
                        and validation.get('import_exit_code') == 0 and validation.get('publication_failures') == 0
                        and validation.get('runtime_routing_failures') == 0
                        and isinstance(validation.get('publication_checks'), int) and validation['publication_checks'] > 0
                        and isinstance(validation.get('runtime_routing_checks'), int) and validation['runtime_routing_checks'] > 0):
                    stage(item, 6, 'done', '已接入 · 发布 ' + str(validation['publication_checks']) + ' / 路由 ' + str(validation['runtime_routing_checks']) + ' 项检查通过（非全游戏目视通关）')
                    item['integration']['engine_validation'] = 'passed'
        values.sort(key=lambda v: (v['character'], v['action']))
        coverage_summary = {'batch_action_tasks': len(values), 'batch_characters': len({v['character'] for v in values})}
        sources = [s for s in sources if s['kind'] == '当前全目标']
        if not values:
            warnings.append('当前全角色三动作 scope 尚未接入；不使用已停止范围代替，不声明任何任务已提交。')
        used = set()
        for item in values:
            for value in item['media'].values():
                for url in value if isinstance(value, list) else [value]:
                    if isinstance(url, str) and url.startswith('/media/'):
                        used.add(url.rsplit('/', 1)[-1])
        registry = {key: path for key, path in registry.items() if key in used}
        snapshot = {'schema_version': 1, 'ui_version': VIEW_VERSION, 'scope_revision': self.scope_policy, 'items': values, 'sources': sources, 'warnings': list(dict.fromkeys(warnings)), 'labels': LABELS,
                    'updated_at': datetime.now(timezone.utc).isoformat(), 'poll_seconds': 3, 'coverage_summary': coverage_summary, 'execution': execution,
                    'counts': {'actions': len(values), 'production': sum(v['group'] == 'production' and (not v.get('accepted_baseline') or v.get('scope_revision') == self.scope_policy) for v in values), 'failed': sum(v['status'] == 'failed' for v in values)}}
        with self.lock:
            self.files, self.snapshot = registry, snapshot

    def run(self):
        while True:
            try:
                self.scan()
            except Exception:
                with self.lock:
                    self.snapshot = {**self.snapshot, 'warnings': ['本轮读取未完成，保留上次证据；正在重试。']}
            time.sleep(3)


PAGE = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="progress-view-version" content="3.4"><title>实时原画与生成预览 · v3.4</title>
<style>
:root{color-scheme:dark;font:14px/1.5 "Microsoft YaHei",sans-serif;background:#10161d;color:#e5ecf1}*{box-sizing:border-box}body{margin:0}main{max-width:1320px;margin:auto;padding:10px 16px}header{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}h1{font-size:16px;margin:0}h2{font-size:17px;margin:0}h3{font-size:14px;margin:0}p{margin:6px 0}.muted{font-size:12px;color:#a5b9c5}.version{font:11px monospace;color:#a5cfbd}button,select,input{font:inherit;color:#e5ecf1;background:#213440;border:1px solid #4b626e;border-radius:6px;padding:7px 10px;min-width:0}button{cursor:pointer}button:hover{border-color:#a0d5b7}:focus-visible{outline:2px solid #9bd7be;outline-offset:2px}a{color:#ddcb99}.hero{background:#17232d;border:1px solid #3b505d;border-radius:9px;overflow:hidden}.herohead{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:9px 12px}.herohead select{max-width:50%;font-size:12px}.media{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:2px;background:#344651}.panel{min-width:0;background:#17232d}.label{display:flex;align-items:center;justify-content:space-between;font-size:12px;padding:5px 9px;color:#c3d3df}.stage{height:250px;display:grid;place-items:center;position:relative;overflow:hidden;background-color:#253139;background-image:linear-gradient(45deg,#35434b 25%,transparent 25%),linear-gradient(-45deg,#35434b 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#35434b 75%),linear-gradient(-45deg,transparent 75%,#35434b 75%);background-size:20px 20px;background-position:0 0,0 10px,10px -10px,-10px 0}.stage img,.stage video{width:100%;height:100%;object-fit:contain;position:absolute}.stage img{image-rendering:auto}.empty{color:#a1b5bf;font-size:13px;text-align:center;padding:18px}.compact{display:flex;gap:6px;flex-wrap:wrap;padding:10px}.tag{font-size:11px;padding:4px 7px;background:#111d25;border:1px solid #3f5663;border-radius:5px}.done{color:#a8dfc1;border-color:#447b61}.waiting{color:#e7cd92;border-color:#887a50}.failed{color:#efb1a6;border-color:#9c675f}.recorded{color:#bbd5ec}.controls{display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:7px;font-size:11px}.controls button,.controls select{font-size:11px;padding:4px 7px}.controls input{flex:1;min-width:70px;max-width:200px}.evidence{padding:0 12px 10px;font-size:12px;color:#b9c9d3;overflow-wrap:anywhere}details{margin:5px 0}summary{cursor:pointer;color:#cfddd9}.history-entry{padding:8px 0;border-top:1px solid #344651}.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:14px 0 8px}.toolbar input{flex:1;min-width:150px}.summary{font-size:12px;color:#adccbd;margin:8px 0}.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}.character{padding:0;overflow:hidden;text-align:left;background:#18242e;border:1px solid #3b4f5c;border-radius:8px}.character[aria-expanded=true]{border:2px solid #92d0b1}.portrait{height:160px;position:relative;background:radial-gradient(ellipse at 50% 70%,#365348,#15232c 75%)}.portrait img{width:100%;height:100%;object-fit:contain}.character .caption{display:block;padding:8px 10px}.caption strong,.caption small{display:block}.caption small{font-size:11px;color:#a4b9c5}.character-actions{margin:12px 0;border:1px solid #38515e;border-radius:8px;padding:12px;background:#17242e}.actions-head{display:flex;align-items:center;justify-content:space-between;gap:8px}.actions-list{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin-top:10px}.action-button{text-align:left;font-size:12px;overflow-wrap:anywhere}.action-button small{display:block;color:#adc2ce;font-size:11px}.action-detail{margin-top:10px}.alert{font-size:12px;color:#e3bf96}footer{margin-top:18px;border-top:1px solid #324651;padding:10px 0;font-size:11px;color:#8fa8b7}.statusline{font-size:11px;color:#b3cabf}.lightbox{background:#111b23;color:#e5ecf1;border:1px solid #698274;border-radius:9px;max-width:96vw;width:1000px;padding:10px}.lightbox::backdrop{background:#000b}.lightbox img{display:block;width:100%;max-height:80vh;object-fit:contain}.lightbox button{float:right}.notice{padding:6px 10px;font-size:12px;color:#adc0cd}#more{margin-top:8px}@media(max-width:650px){main{padding:7px 9px}h1{font-size:14px}.herohead{padding:6px 9px}h2{font-size:15px}.herohead select{max-width:47%}.media{grid-template-columns:1fr 1fr}.stage{height:185px}.hero .media>.panel:first-child:nth-last-child(2),.hero .media>.panel:first-child:nth-last-child(2)~.panel{min-width:0}.gallery{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.portrait{height:150px}.actions-list{grid-template-columns:repeat(2,minmax(0,1fr))}.statusline{max-width:45%;text-align:right;font-size:10px}.compact{padding:7px;gap:4px}.tag{font-size:10px}.toolbar{gap:6px}.toolbar select{max-width:52%;font-size:12px}}@media(max-width:430px){.media{grid-template-columns:1fr}.stage{height:170px}.herohead select{font-size:10px;padding:5px}.label{padding:3px 8px}.hero .media>.panel:nth-child(n+3) .stage{height:190px}}
#live-jobs{margin-bottom:8px}.live-count{font-size:12px;color:#b9dfc9;margin:4px 0}.live-strip{display:flex;gap:6px;overflow-x:auto;padding-bottom:5px}.live-task{flex:0 0 170px;display:flex;gap:7px;align-items:center;text-align:left;padding:5px;font-size:11px}.live-task img{width:35px;height:48px;object-fit:contain}.live-task strong,.live-task small{display:block}.live-task small{font-size:10px}.ready-title{font-size:14px;margin:9px 0 5px;color:#bce4d0}#ready-result .media{border:1px solid #456657;border-radius:7px;overflow:hidden}
</style><main><header><h1>实时角色预览 <span class="version">v3.4</span></h1><span id="live" class="statusline">读取本地记录…</span></header><section id="live-jobs" aria-label="本轮真实任务状态"></section><section id="hero" aria-label="本轮活动任务大预览"><div class="empty">正在载入已有角色原画与最新生成结果…</div></section><section id="ready-result" aria-label="本轮可播放透明动画"></section><div id="warnings" role="status"></div><div class="toolbar"><input id="search" aria-label="搜索全部角色和动作" placeholder="搜索角色名称 / action"><select id="scope" aria-label="覆盖范围"><option value="production">本轮角色画廊</option><option value="unbound">历史素材（待本体复用）</option></select><button id="refresh">刷新</button></div><div id="summary" class="summary"></div><section id="gallery" class="gallery" aria-label="全角色原画画廊"></section><section id="character-actions" hidden class="character-actions" aria-label="所选角色全部动作"></section><footer><details><summary>本地证据与刷新说明</summary><p>每 3 秒读取真实 job / batch / sample / queue。已有原画可直接进入 Veo；图片生成成功不等于审核通过。未审产物仍可看，历史试样不计入本轮完成。</p><div id="sources"></div><p>界面版本 v3.4 · no-store · 仅安全本地媒体 · 新版本出现时自动更新页面。</p></details></footer></main><dialog id="lightbox" class="lightbox"><button id="close-image">关闭</button><img id="large-image" alt="完整原图预览"></dialog>
<script>
const VIEW_VERSION='3.4',$=id=>document.getElementById(id);let data={items:[],labels:[]},busy=false,selectedCharacter=null,selectedAction=null,heroChoice=null,actionLimit=24,heroSignature='',detailSignature='',gallerySignature='',liveSignature='',readySignature='';const players=new Set();
$('character-actions').after($('ready-result'));
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function enlarge(url){$('large-image').src=url;$('lightbox').showModal()}$('close-image').onclick=()=>$('lightbox').close();
function panel(label,url,kind='image',eager=false){const p=el('div',undefined,'panel'),head=el('div',undefined,'label');head.append(el('span',label));p.append(head);const stage=el('div',undefined,'stage');p.append(stage);if(url){const media=el(kind==='video'?'video':'img');media.src=url;if(kind==='video'){media.controls=true;media.muted=true;media.playsInline=true;media.preload='metadata'}else{media.alt=label;media.loading=eager?'eager':'lazy';const open=el('a','放大');open.href=url;open.onclick=e=>{e.preventDefault();enlarge(url)};head.append(open);media.onclick=()=>enlarge(url)}media.onerror=()=>{stage.replaceChildren(el('div','本地文件暂不可读，稍后刷新。','empty'))};stage.append(media)}else stage.append(el('div','等待本地结果 · 尚无可预览文件','empty'));return p}
function framePanel(item,eager){const frames=item.media.frames;if(!frames?.length)return panel('透明动画 · 待抽帧',null);const p=panel('透明动画 · '+frames.length+' 帧',frames[0],'image',eager),image=p.querySelector('img'),controls=el('div',undefined,'controls'),play=el('button','播放'),prev=el('button','上一帧'),next=el('button','下一帧'),rate=el('select'),range=el('input'),info=el('span');let index=0,timer=null;for(const x of [.5,1,2]){const o=el('option',x+'×');o.value=x;o.selected=x===1;rate.append(o)}range.type='range';range.min=0;range.max=frames.length-1;range.value=0;range.setAttribute('aria-label','透明动画帧');rate.setAttribute('aria-label','播放速度');function draw(){image.src=frames[index];range.value=index;info.textContent=(index+1)+' / '+frames.length}function stop(){clearTimeout(timer);timer=null;play.textContent='播放'}function tick(){if(index===frames.length-1){if(!item.loop){stop();return}index=0}else index++;draw();timer=setTimeout(tick,1000*(Number(item.seconds)||1)/frames.length/Number(rate.value))}play.onclick=()=>{if(timer!==null)stop();else{if(index===frames.length-1)index=0;draw();play.textContent='暂停';timer=setTimeout(tick,1000*(Number(item.seconds)||1)/frames.length/Number(rate.value))}};for(const [b,delta] of [[prev,-1],[next,1]])b.onclick=()=>{stop();index=Math.max(0,Math.min(frames.length-1,index+delta));draw()};range.oninput=()=>{stop();index=+range.value;draw()};controls.append(play,prev,next,rate,range,info);p.append(controls);draw();p.stop=stop;players.add(p);return p}
function stopInside(root){for(const p of players){if(root.contains(p)){p.stop();players.delete(p)}}root.querySelectorAll('video').forEach(v=>v.pause())}
function displayName(item){return item.aliases?.[0]||item.name||item.character}
function makePreview(item,isHero=false){const root=el('article',undefined,'hero'),head=el('div',undefined,'herohead');head.append(el('h2',displayName(item)+' · '+(item.display_action||item.action)));if(isHero){const chooser=el('select');chooser.setAttribute('aria-label','选择活动任务');const candidates=data.items.filter(i=>i.group==='production'&&(i.active||i.attempts?.length||i.queued));for(const i of candidates){const o=el('option',i.character+' / '+i.action);o.value=i.id;o.selected=i.id===item.id;chooser.append(o)}chooser.onchange=()=>{heroChoice=chooser.value;heroSignature='';renderHero()};if(candidates.length>1)head.append(chooser)}root.append(head);const media=el('div',undefined,'media');media.append(panel('已有角色原画',item.media.art,'image',isHero));if(item.mode!=='existing_image'&&item.media.still)media.append(panel('最新首帧 · '+(item.current_still_attempt?.endsWith('-v2')?'v2':'已生成'),item.media.still,'image',isHero));if(item.media.video)media.append(panel('真实 Veo 原视频',item.media.video,'video',isHero));else media.append(panel(item.stages[3]?.state==='waiting'?'Veo 已提交 · 等待结果':'Veo 视频 · 尚无本地结果',null));if(item.media.frames?.length)media.append(framePanel(item,isHero));root.append(media);const strip=el('div',undefined,'compact');const indices=item.mode==='existing_image'?[0,3,4,5,6]:[0,1,2,3,4,5,6];for(const i of indices){const s=item.stages[i];strip.append(el('span',(data.labels[i]||'状态')+'：'+s.text,'tag '+s.state))}root.append(strip);const details=el('div',undefined,'evidence');if(item.mode==='existing_image')details.append(el('p','已有原画直接用于视频生成，无需另做首帧。','muted'));if(item.attempts?.length){const history=el('details');history.append(el('summary','尝试历史与审核（'+item.attempts.length+'）'));for(const a of item.attempts){const e=el('div',undefined,'history-entry');e.append(el('p',a.name+' · '+a.state+(a.review?' · '+a.review:'')));if(a.review_notes)e.append(el('p',a.review_notes));for(const [key,label]of [['image','查看这次首帧'],['video','查看这次视频']])if(a[key]){const link=el('a',label);link.href=a[key];link.target='_blank';link.rel='noopener';e.append(link)}history.append(e)}details.append(history)}const facts=el('details');facts.append(el('summary','动作说明与持久化证据'));for(const n of item.notes||[])facts.append(el('p',n));for(const p of item.evidence||[])facts.append(el('p',p,'muted'));details.append(facts);root.append(details);return root}
function rank(i){return (i.group==='production'?100:0)+(i.stages[3]?.state==='waiting'?60:0)+(i.active?30:0)+(i.media.video?20:0)+(i.queued?10:0)}
function renderHero(){const candidates=data.items.filter(i=>i.group==='production'&&!i.accepted_baseline&&!i.completed_baseline&&i.video_job&&(['submitted','pending','queued','processing','running','polling','waiting'].includes(i.video_job.state)||(i.video_job.submission_in_progress&&i.video_job.state!=='submission_unknown')));const chosen=data.items.find(i=>i.id===heroChoice)||candidates.slice().sort((a,b)=>b.updated_at-a.updated_at)[0];$('hero').hidden=!chosen;if(!chosen){stopInside($('hero'));$('hero').replaceChildren();heroSignature='';return}const signature=JSON.stringify(chosen);if(signature!==heroSignature){stopInside($('hero'));$('hero').replaceChildren(makePreview(chosen,true));heroSignature=signature}}
function groups(){const q=$('search').value.toLowerCase().replace(/human0/g,'human-0'),scope=$('scope').value,result=new Map();for(const item of data.items){if(item.group!==scope)continue;const text=JSON.stringify([item.character,item.name,item.aliases,item.action,item.display_action]).toLowerCase();if(q&&!text.includes(q))continue;const key=scope==='production'?item.character:item.id;if(!result.has(key))result.set(key,[]);result.get(key).push(item)}return result}
function renderGallery(){const all=groups(),signature=JSON.stringify([...all].map(([key,items])=>[key,items.length,items.map(i=>i.media.art).find(Boolean),items[0].aliases]));if(signature!==gallerySignature){$('gallery').replaceChildren();for(const [key,items]of all){const reference=items.find(i=>i.media.art)||items[0],button=el('button',undefined,'character');button.type='button';button.dataset.character=key;button.setAttribute('aria-expanded',String(selectedCharacter===key));const portrait=el('div',undefined,'portrait');if(reference.media.art){const img=el('img');img.src=reference.media.art;img.alt=displayName(reference);img.loading='lazy';img.onerror=()=>portrait.replaceChildren(el('div','原画暂不可读','empty'));portrait.append(img)}else portrait.append(el('div','暂无本地原画','empty'));const caption=el('span',undefined,'caption');caption.append(el('strong',displayName(reference)),el('small',reference.character+' · '+items.length+' 个动作'));button.append(portrait,caption);button.onclick=()=>{selectedCharacter=selectedCharacter===key?null:key;selectedAction=null;actionLimit=24;detailSignature='';renderActions();for(const b of $('gallery').children)b.setAttribute('aria-expanded',String(b.dataset.character===selectedCharacter));if(selectedCharacter)$('character-actions').scrollIntoView({block:'start',behavior:'smooth'})};$('gallery').append(button)}gallerySignature=signature}const c=data.coverage_summary||{};const existing=[...all.values()].filter(items=>items.some(i=>i.media.art)).length;$('summary').textContent=`${all.size} 个角色 · ${existing} 张已有原画 · 本轮完整覆盖 ${data.counts?.production||0} 个动作`+(c.role_form_profiles?` / ${c.role_form_profiles} 个角色形态`:'')+' · 点击角色展开动作';renderActions()}
function renderActions(){const all=groups(),items=all.get(selectedCharacter);const target=$('character-actions');if(!items){stopInside(target);target.hidden=true;return}target.hidden=false;const signature=JSON.stringify([items,selectedAction,actionLimit]);if(signature===detailSignature)return;detailSignature=signature;stopInside(target);target.replaceChildren();const head=el('div',undefined,'actions-head');head.append(el('h2',displayName(items[0])+' · '+items.length+' 个动作'));const close=el('button','收起');close.onclick=()=>{selectedCharacter=null;detailSignature='';renderGallery()};head.append(close);target.append(head);const list=el('div',undefined,'actions-list');for(const item of items.slice(0,actionLimit)){const b=el('button',undefined,'action-button');b.append(el('span',item.display_action||item.action),el('small',item.media.video?'原视频可看':item.stages[3]?.text));b.onclick=()=>{selectedAction=item.id;detailSignature='';renderActions()};list.append(b)}target.append(list);if(items.length>actionLimit){const more=el('button','更多动作（'+(items.length-actionLimit)+'）');more.id='more';more.onclick=()=>{actionLimit+=24;detailSignature='';renderActions()};target.append(more)}const selected=items.find(i=>i.id===selectedAction);if(selected){const d=el('div',undefined,'action-detail');d.append(makePreview(selected));target.append(d)}}
function renderLive(){const production=data.items.filter(i=>i.group==='production'),current=production.filter(i=>!i.accepted_baseline),jobs=current.filter(i=>i.video_job),history=data.items.filter(i=>i.group!=='production'&&i.evidence.some(p=>p.startsWith('batch-01/'))&&i.video_job),done=history.filter(i=>['succeeded','completed'].includes(i.video_job.state)).length,unknown=history.filter(i=>i.video_job.state==='submission_unknown').length,submitted=jobs.filter(i=>i.video_job.has_external_job_id).length,planned=current.filter(i=>i.queue_state==='planned'&&!i.video_job).length,reuse=production.filter(i=>i.completed_baseline).length,candidates=current.filter(i=>i.queue_state==='reuse_candidate_review_before_generation').length,holds=current.filter(i=>i.queue_state==='reconciliation_hold').length;const signature=JSON.stringify([data.scope_revision,data.counts?.production,jobs.map(i=>[i.id,i.video_job]),planned,reuse,candidates,holds,done,unknown]);if(signature===liveSignature)return;liveSignature=signature;$('live-jobs').replaceChildren(el('p',`${data.scope_revision||'本轮'}：${data.counts?.production||0} 个目标 · ${planned} planned 尚未提交 · ${submitted} 个本轮真实回执；另含 ${reuse} 个已接入复用、${candidates} 个待审候选、${holds} 个查账锁定。历史批 01：${done} completed + ${unknown} unknown，媒体与费用保留。`,'live-count'));const strip=el('div',undefined,'live-strip');for(const i of jobs.sort((a,b)=>b.updated_at-a.updated_at)){const b=el('button',undefined,'live-task');if(i.media.art){const image=el('img');image.src=i.media.art;image.alt=i.character;b.append(image)}b.append(el('span',i.character+' / '+i.action+' · '+i.video_job.state));b.onclick=()=>{heroChoice=i.id;heroSignature='';renderHero()};strip.append(b)}$('live-jobs').append(strip)}
function renderReady(){const item=data.items.find(i=>i.group==='production'&&i.accepted_baseline&&i.media.frames?.length);if(!item)return;const signature=JSON.stringify([item.id,item.media,item.seconds,item.loop,item.integration]);if(signature===readySignature)return;readySignature=signature;stopInside($('ready-result'));const section=el('details');section.append(el('summary','已完成 / 已接入：'+item.character+' / '+item.action+' · '+item.media.frames.length+' 帧透明动画'));section.append(makePreview(item));$('ready-result').replaceChildren(section)}
async function refresh(){if(busy)return;busy=true;try{const response=await fetch('/api/progress',{cache:'no-store'});if(!response.ok)throw Error();const next=await response.json();if(next.ui_version&&next.ui_version!==VIEW_VERSION){$('live').textContent='检测到新版，正在更新界面…';const url=new URL(location.href);url.searchParams.set('v',next.ui_version);location.replace(url);return}data=next;$('live').textContent='v'+VIEW_VERSION+' · '+(data.updated_at?new Date(data.updated_at).toLocaleTimeString():'读取中');$('warnings').replaceChildren(...(data.warnings||[]).map(w=>el('p',w,'alert')));$('sources').replaceChildren(...(data.sources||[]).map(s=>el('p',s.name+' · '+(s.exists?'已发现':'尚未出现'))));renderLive();renderHero();renderReady();renderGallery()}catch(e){$('live').textContent='连接暂断 · 保留已读结果'}finally{busy=false}}
$('search').oninput=()=>{gallerySignature='';detailSignature='';renderGallery()};$('scope').onchange=()=>{selectedCharacter=null;gallerySignature='';detailSignature='';renderGallery()};$('refresh').onclick=refresh;refresh();setInterval(refresh,3000);document.addEventListener('visibilitychange',()=>{if(document.hidden){for(const p of players)p.stop();document.querySelectorAll('video').forEach(v=>v.pause())}else refresh()});
</script></html>
'''


PAGE = (PAGE.replace('3.4', VIEW_VERSION)
        .replace('真实 Veo 原视频', '真实原视频')
        .replace('Veo 已提交 · 等待结果', '视频已提交 · 等待结果')
        .replace('Veo 视频 · 尚无本地结果', '视频 · 尚无本地结果')
        .replace('已有原画可直接进入 Veo', '已有原画可直接进入视频生成')
        .replace("i.group==='production'&&i.accepted_baseline&&i.media.frames?.length", "i.accepted_baseline&&i.media.frames?.length")
        .replace('function renderLive(){', 'function renderLegacyLive(){')
        .replace('</script>', r'''
function renderLive(){
 const pilot=data.scope_revision==='body-motion-v4-pilot-six';
 if(!pilot){renderLegacyLive();return}
 const current=data.items.filter(i=>i.group==='production'),jobs=current.filter(i=>i.video_job);
 const historical=prefix=>data.items.filter(i=>i.group!=='production'&&i.video_job&&i.evidence.some(p=>p.startsWith(prefix)));
 const first=historical('batch-01/'),second=historical('body-motion-v3-driver/');
 const completed=list=>list.filter(i=>['succeeded','completed'].includes(i.video_job.state)).length;
 const submitted=jobs.filter(i=>i.video_job.has_external_job_id).length;
 const unknown=first.filter(i=>i.video_job.state==='submission_unknown').length;
 const signature=JSON.stringify([current.map(i=>[i.id,i.queue_state,i.video_job,i.model,i.cost_points,i.media.video]),completed(first),unknown,completed(second)]);
 if(signature===liveSignature)return;
 liveSignature=signature;
 const models=[...new Set(jobs.map(i=>i.model).filter(Boolean))];
 const costs=jobs.filter(i=>typeof i.cost_points==='number');
 const price=costs.length?`实际费用已记录 ${costs.length} 条，合计 ${costs.reduce((sum,i)=>sum+i.cost_points,0)} points`:'实际价格待任务凭据确认';
 $('live-jobs').replaceChildren(el('p',`${models.join(' / ')||'Seedance2.0Fast（请求模型）'} 六试样（2角色） · 已载入 ${current.length}/6 个目标${current.length?'':' · 清单尚未就绪'} · ${submitted} 个真实回执 · ${completed(jobs)} 已完成 · ${jobs.filter(i=>i.media.video).length} 个本地视频可看 · ${price}。历史 Veo 批01：${completed(first)} completed + ${unknown} unknown；旧 v3 批：${completed(second)} completed，不计当前进度。`,'live-count'));
 const strip=el('div',undefined,'live-strip');
 for(const i of jobs.sort((a,b)=>b.updated_at-a.updated_at)){
  const button=el('button',undefined,'live-task');
  if(i.media.art){const img=el('img');img.src=i.media.art;img.alt=i.character;button.append(img)}
  button.append(el('span',i.character+' / '+i.action+' · '+i.video_job.state+(i.media.video?' · 查看原视频':'')+(i.model?' · '+i.model:'')));
  button.onclick=()=>{heroChoice=i.id;heroSignature='';renderHero()};strip.append(button);
 }
 $('live-jobs').append(strip);
}
</script>'''))


# Build the served page from the established visual styles and media controls,
# not the retired navigation/renderers. No archived rows or routes enter this UI.
_style = re.search(r'<style>(.*?)</style>', PAGE, re.S).group(1)
_helpers = '\n'.join(line for line in re.search(r'<script>(.*?)</script>', PAGE, re.S).group(1).splitlines()
                     if line.startswith(('function el(', 'function enlarge(', 'function panel(', 'function framePanel(', 'function stopInside(', 'function displayName(')))
_helpers = _helpers.replace("info.textContent=(index+1)+' / '+frames.length", "info.textContent=(index+1)+' / '+frames.length;p.dispatchEvent(new CustomEvent('framechange',{detail:index}))")
PAGE = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>全角色三动作实时队列 · v' + VIEW_VERSION + '</title><style>' + _style + r'''
.gallery{display:block}.matrix-role{margin:10px 0;padding:10px;background:#17242e;border:1px solid #38515e;border-radius:8px}.matrix-head{display:flex;align-items:center;gap:12px;margin-bottom:9px}.matrix-head img{width:70px;height:90px;object-fit:contain}.matrix-actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.matrix-cell{min-width:0;padding:9px;border:1px solid #344b58;border-radius:6px}.matrix-cell p{font-size:11px;overflow-wrap:anywhere}.matrix-cell .stage{height:160px}.matrix-cell button{width:100%;margin-top:6px;font-size:12px}.matrix-cell .controls button{width:auto}.pipeline{color:#b2c7d2}.matrix-cell .panel{margin-top:8px}@media(max-width:560px){.matrix-actions{grid-template-columns:1fr}.matrix-cell .stage{height:180px}}
</style><main><header><h1>全角色三动作实时队列 <span class="version">v''' + VIEW_VERSION + r'''</span></h1><span id="live">读取当前范围…</span></header>
<div id="warnings" role="status"></div><div id="summary" class="summary"></div><section id="live-jobs" aria-label="本轮真实提交"></section><section id="hero" hidden aria-label="当前产物与同步复核"></section>
<div class="toolbar"><input id="search" placeholder="搜索角色 / 攻击起手 / 行走 / 死亡" aria-label="搜索当前队列"><button id="refresh">刷新</button></div>
<section id="gallery" class="gallery" aria-label="全角色三动作矩阵"></section><footer>只读当前范围的 job / queue / sample。供应商完成、下载、抽帧、复核、入库分别计数；缺证据不视为完成。每 3 秒更新。</footer></main>
<dialog id="lightbox" class="lightbox"><button id="close-image">关闭</button><img id="large-image" alt="本地产物预览"></dialog><script>
const VIEW_VERSION=__CURRENT_VIEW_VERSION_JSON__,$=id=>document.getElementById(id),players=new Set();
const ACTIONS=[['body_attack','攻击起手'],['walk','行走'],['death','死亡']];
let data={items:[],labels:[]},busy=false,matrixSignature='',heroSignature='',chosen=null,syncReview=false;
''' + _helpers + r'''
function provider(item){const job=item.video_job;if(!job){const q=item.queue_state||'';if(/reuse/.test(q))return '复用待审';if(/hold|blocked|failed/.test(q))return '受阻 · '+q;if(/ready_for_submit|prepared/.test(q))return '待提交（尚无供应商回执）';return '未准备 / 尚无提交证据'}const labels={prepared:'待提交',created:'待提交',draft:'未准备',submitted:'已提交 / 排队',queued:'已提交 / 排队',pending:'供应商排队',processing:'生成中',running:'生成中',polling:'等待供应商结果',waiting:'等待供应商结果',succeeded:'供应商已完成',completed:'供应商已完成',failed:'失败',error:'失败',cancelled:'已取消',submission_unknown:'提交结果待确认，不能据此重试'};return labels[job.state]||job.state}
function stage(item,index){return item.stages?.[index]?.text||'未记录'}
function review(item,sync=false){chosen=item.id;syncReview=sync;heroSignature='';renderHero();$('hero').scrollIntoView({block:'start',behavior:'smooth'})}
function makePreview(item){const root=el('article',undefined,'hero'),head=el('div',undefined,'herohead');head.append(el('h2',displayName(item)+' / '+(ACTIONS.find(a=>a[0]===item.action)?.[1]||item.action)));root.append(head);const media=el('div',undefined,'media');let frames=null,video=null;if(item.media.frames?.length&&(syncReview||!item.media.gif)){frames=framePanel(item,true);media.append(frames)}else if(item.media.gif)media.append(panel('实际透明 GIF',item.media.gif,'image',true));if(item.media.video){const p=panel('实际原视频',item.media.video,'video',true);video=p.querySelector('video');media.append(p)}if(item.media.art)media.append(panel('当前角色原画',item.media.art,'image',true));if(frames&&video&&item.times?.length===item.media.frames.length){frames.addEventListener('framechange',event=>{const time=Number(item.times[event.detail]);if(Number.isFinite(time)){video.pause();video.currentTime=time}});root.append(el('p','同步复核：播放或逐帧操作透明序列，原视频同步定位到记录时间。','notice'))}root.append(media);root.append(el('p',provider(item)+' · '+stage(item,4)+' · '+stage(item,5)+' · '+stage(item,6),'compact'));return root}
function renderLiveJobs(){const root=$('live-jobs'),jobs=data.items.filter(i=>i.video_job?.has_external_job_id).sort((a,b)=>Number(/succeeded|completed/.test(a.video_job.state))-Number(/succeeded|completed/.test(b.video_job.state))||b.updated_at-a.updated_at);root.replaceChildren(el('h2','本轮真实提交 · '+jobs.length+' 条（不含复用）'));if(data.execution?.paused)root.append(el('p','执行已暂停：'+(data.execution.reason||'原因未记录')+'；已付任务状态如下，未提交项不算完成。','alert'));if(!jobs.length)root.append(el('p','当前尚无真实视频提交回执。','muted'));for(const item of jobs){const line=el('div',undefined,'compact'),label=ACTIONS.find(a=>a[0]===item.action)?.[1]||item.action;line.append(el('strong',displayName(item)+' / '+label),el('span',provider(item),'tag'),el('span',item.media.video?'下载完成':'尚未下载','tag'),el('span',stage(item,4),'tag'));if(item.media.video||item.media.frames?.length||item.media.gif){const button=el('button','看产物');button.onclick=()=>review(item,true);line.append(button)}root.append(line)}}
function renderHero(){renderLiveJobs();const candidates=data.items.filter(i=>i.video_job?.has_external_job_id&&(i.media.video||i.media.gif||i.media.frames?.length));const item=data.items.find(i=>i.id===chosen)||candidates.sort((a,b)=>b.updated_at-a.updated_at)[0];$('hero').hidden=!item;if(!item){stopInside($('hero'));$('hero').replaceChildren();heroSignature='';return}const signature=JSON.stringify([item,syncReview]);if(signature===heroSignature)return;heroSignature=signature;stopInside($('hero'));$('hero').replaceChildren(makePreview(item))}
function renderMatrix(){const query=$('search').value.trim().toLowerCase(),groups=new Map();for(const item of data.items){if(!groups.has(item.character))groups.set(item.character,[]);groups.get(item.character).push(item)}const visible=[...groups].filter(([id,items])=>!query||JSON.stringify([id,items.map(i=>[i.name,i.aliases,i.action,ACTIONS.find(a=>a[0]===i.action)?.[1]])]).toLowerCase().includes(query));const signature=JSON.stringify(visible);if(signature===matrixSignature)return;matrixSignature=signature;stopInside($('gallery'));$('gallery').replaceChildren();for(const [id,items]of visible){const card=el('article',undefined,'matrix-role'),head=el('div',undefined,'matrix-head'),reference=items.find(i=>i.media.art)||items[0];if(reference.media.art){const img=el('img');img.src=reference.media.art;img.alt=displayName(reference);img.loading='lazy';head.append(img)}head.append(el('h2',displayName(reference)+' · '+id));card.append(head);const columns=el('div',undefined,'matrix-actions');for(const [action,label]of ACTIONS){const cell=el('section',undefined,'matrix-cell'),item=items.find(i=>i.action===action);cell.append(el('h3',label+' / '+action));if(!item){cell.append(el('p','当前 scope 未列出此项，未创建任务'));columns.append(cell);continue}cell.append(el('p','供应商：'+provider(item),'pipeline'));cell.append(el('p','下载：'+(item.media.video?'下载完成，本地原片可看':'尚无本地原片'),'pipeline'));cell.append(el('p','透明：'+stage(item,4),'pipeline'));cell.append(el('p','复核：'+stage(item,5),'pipeline'));cell.append(el('p','游戏：'+stage(item,6),'pipeline'));if(item.failure_reason)cell.append(el('p','受阻原因：'+item.failure_reason,'alert'));if(item.video_job&&/failed|error/.test(item.video_job.state)&&!item.failure_reason)cell.append(el('p','任务失败；安全摘要未记录，具体原因保留在本地 job。','alert'));if(item.model)cell.append(el('p','模型：'+item.model,'muted'));if(typeof item.cost_points==='number')cell.append(el('p','实际费用：'+item.cost_points+' points','muted'));if(item.media.gif)cell.append(panel('实际透明 GIF',item.media.gif));else if(item.media.frames?.length)cell.append(framePanel(item,false));else if(item.media.video){const p=panel('实际原片',item.media.video,'video');p.querySelector('video').preload='none';cell.append(p)}if(item.media.art||item.media.video||item.media.gif||item.media.frames?.length){const button=el('button',item.times?.length&&item.media.frames?.length?'原画 / 原片 / 同步复核':'查看原画 / 原片 / 透明产物');button.onclick=()=>review(item,true);cell.append(button)}columns.append(cell)}card.append(columns);$('gallery').append(card)}if(!data.items.length)$('gallery').append(el('p','全角色 37 × 3 = 111 的请求计划等待当前 scope。不会用旧范围或旧任务填充进度。','empty'))}
function renderSummary(){const items=data.items,total=items.length,characters=new Set(items.map(i=>i.character)).size,jobs=items.filter(i=>i.video_job),downloaded=items.filter(i=>i.media.video).length,transparent=items.filter(i=>i.media.frames?.length||i.media.gif).length,integrated=items.filter(i=>['done','recorded'].includes(i.stages?.[6]?.state)).length,failed=items.filter(i=>i.status==='failed'||/hold|blocked/.test(i.queue_state||'')).length;$('summary').textContent=`当前范围：${characters} 角色 / ${total} 目标 · 真实提交回执 ${jobs.filter(i=>i.video_job.has_external_job_id).length} · 下载 ${downloaded}/${total} · 透明产物 ${transparent}/${total} · 接入记录 ${integrated}/${total} · 失败/受阻 ${failed}。${data.scope_revision||'等待范围'}`}
async function refresh(){if(busy)return;busy=true;try{const response=await fetch('/api/progress',{cache:'no-store'});if(!response.ok)throw Error('HTTP '+response.status);const next=await response.json();if(next.ui_version!==VIEW_VERSION){if(parseFloat(next.ui_version)<parseFloat(VIEW_VERSION))throw Error('响应来自不匹配的旧进程，请主任务核对监听 PID');const url=new URL(location.href);url.searchParams.set('v',next.ui_version);location.replace(url);return}data=next;$('live').textContent='v'+VIEW_VERSION+' · PID '+(response.headers.get('X-Progress-Process-Id')||'?')+' · '+(data.updated_at?new Date(data.updated_at).toLocaleTimeString():'读取中');$('warnings').replaceChildren(...(data.warnings||[]).map(w=>el('p',w,'alert')));renderSummary();renderHero();renderMatrix()}catch(error){$('live').textContent='连接待恢复 · '+error.message}finally{busy=false}}
$('search').oninput=()=>{matrixSignature='';renderMatrix()};$('refresh').onclick=refresh;refresh();setInterval(refresh,3000);document.addEventListener('visibilitychange',()=>{if(document.hidden){for(const p of players)p.stop();document.querySelectorAll('video').forEach(v=>v.pause())}else refresh()});
</script></html>''')


PAGE = re.sub(r'^function provider\(item\).*$', r'''function localStage(item){if(item.reuse_sample_verified&&item.stages?.[5]?.state==='done')return '已确认复用，不新投';const names={needs_prepared_reference:'待准备参考图',needs_side_reference:'待主角侧面参考图',needs_reference:'待参考图',needs_frozen_design_binding:'待冻结设计/输入绑定',needs_reference_upload:'待身份上传',ready_to_prepare:'可本地准备',ready_for_prepare:'可本地准备',prepared:'已准备，待提交',reused:'复用记录待凭据核验',reuse_accepted_verified:'复用记录待凭据核验',candidate_reuse:'复用待审，不重投',reuse_pending_final_review:'复用待最终审查，不重投',planned:'未准备',failed:'本地失败/受阻'};return names[item.queue_state]||item.queue_state||'未准备'}
function provider(item){const job=item.video_job;if(!job){if(item.reuse_sample_verified&&item.stages?.[5]?.state==='done')return '本轮不提交 · 复用已完成素材';if(item.queue_state==='reused')return '本轮不提交 · 复用凭据待核验';return '未提交（无供应商 job 回执）'}const labels={prepared:'待提交',created:'待提交',draft:'未准备',submitted:'已提交 / 排队',queued:'已提交 / 排队',pending:'供应商排队',processing:'生成中',running:'生成中',polling:'等待供应商结果',waiting:'等待供应商结果',succeeded:'供应商已完成',completed:'供应商已完成',failed:'失败',error:'失败',cancelled:'已取消',submission_unknown:'提交结果待确认，不能据此重试'};return labels[job.state]||job.state}''', PAGE, flags=re.M)
PAGE = PAGE.replace("cell.append(el('p','供应商：'+provider(item),'pipeline'));", "cell.append(el('p','准备/复用：'+localStage(item),'pipeline'));cell.append(el('p','供应商：'+provider(item),'pipeline'));")


PAGE = PAGE.replace('__CURRENT_VIEW_VERSION_JSON__', json.dumps(VIEW_VERSION))
PAGE = PAGE.replace("i.status==='failed'||/hold|blocked/.test(i.queue_state||'')", "i.status==='failed'||i.blocked===true||/hold|blocked|keycollision/.test(i.queue_state||'')")


class ProgressHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if os.name == 'nt' and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def send_headers(self, code, content_type, size, extra=None):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(size))
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.send_header('X-Progress-View-Version', VIEW_VERSION)
        self.send_header('X-Progress-Process-Id', str(os.getpid()))
        self.send_header('X-Progress-Scope', self.server.evidence.scope_policy or 'unspecified')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self'; media-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def send_data(self, code, body, mime):
        self.send_headers(code, mime, len(body))
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            # Reject DNS rebinding, foreign origins, and arbitrary file routes.
            expected = {'127.0.0.1:' + str(self.server.server_port), 'localhost:' + str(self.server.server_port)}
            if self.headers.get('Host', '') not in expected:
                return self.send_data(403, b'Forbidden', 'text/plain')
            origin = self.headers.get('Origin')
            if origin and origin not in {'http://' + h for h in expected}:
                return self.send_data(403, b'Forbidden', 'text/plain')
            route = urlsplit(self.path).path
            if route == '/':
                return self.send_data(200, PAGE.encode('utf-8'), 'text/html; charset=utf-8')
            if route == '/api/progress':
                with self.server.evidence.lock:
                    body = json.dumps(self.server.evidence.snapshot, ensure_ascii=False).encode('utf-8')
                return self.send_data(200, body, 'application/json; charset=utf-8')
            if not re.fullmatch(r'/media/[a-f0-9]{32}', route):
                return self.send_data(404, b'Not found', 'text/plain')
            with self.server.evidence.lock:
                p = self.server.evidence.files.get(route.rsplit('/', 1)[-1])
            if not p or not self.server.evidence.permitted(p.resolve()) or p.suffix.lower() not in MEDIA:
                return self.send_data(404, b'Not found', 'text/plain')
            with p.open('rb') as stream:
                size = os.fstat(stream.fileno()).st_size
                start, end, code = 0, size - 1, 200
                requested = self.headers.get('Range')
                if requested:
                    match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
                    valid = bool(match and any(match.groups()))
                    if valid:
                        left, right = match.groups()
                        start = int(left) if left else max(0, size - int(right))
                        end = min(int(right), size - 1) if left and right else size - 1
                        valid = 0 <= start <= end < size
                    if not valid:
                        self.send_headers(416, 'text/plain', 0, {'Content-Range': 'bytes */' + str(size)})
                        return
                    code = 206
                extra = {'Accept-Ranges': 'bytes'}
                if code == 206:
                    extra['Content-Range'] = f'bytes {start}-{end}/{size}'
                remaining = max(0, end - start + 1)
                self.send_headers(code, mimetypes.guess_type(str(p))[0] or 'application/octet-stream', remaining, extra)
                if self.command == 'HEAD':
                    return
                stream.seek(start)
                while remaining:
                    chunk = stream.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError:
            self.close_connection = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', action='append', required=True, help='Repeat for each task root; missing roots are watched.')
    parser.add_argument('--coverage', action='append', default=[], help='Explicit coverage JSON; may appear later.')
    parser.add_argument('--media-root', action='append', default=[], help='Additional explicitly allowed local media root.')
    parser.add_argument('--port', type=int, default=8805)
    parser.add_argument('--scope-policy', default='current-three-actions', help='Current revision name. Superseded revisions are not displayed.')
    parser.add_argument('--scope-spec', help='Exact current spec JSON; its sibling PREFIX-batch is watched automatically.')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,100}', args.scope_policy):
        parser.error('Scope policy must be a simple lowercase revision name.')
    scope_spec = Path(args.scope_spec).resolve() if args.scope_spec else None
    if scope_spec:
        args.coverage.append(str(scope_spec))
        args.root.append(str(scope_spec.parent / (scope_spec.stem.removesuffix('-spec') + '-batch')))
    roots, coverage, allowed = ([Path(v).resolve() for v in values] for values in (args.root, args.coverage, args.media_root))
    if any(str(p).startswith('\\\\') for p in roots + coverage + allowed):
        parser.error('Network shares are not allowed.')
    server = ProgressHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    server.evidence = Evidence(roots, coverage, allowed, args.scope_policy, scope_spec)
    threading.Thread(target=server.evidence.run, daemon=True).start()
    print(f'Progress view: http://127.0.0.1:{args.port}/ pid={os.getpid()} version={VIEW_VERSION} scope={args.scope_policy}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
