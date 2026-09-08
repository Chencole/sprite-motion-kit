"""Track user-requested character/action coverage; never infer completion from one clip."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys
import math
from PIL import Image
import motion

DISCOVERY_AREAS = ['state_machine', 'control_inputs', 'abilities', 'weapons', 'damage_death_revival', 'interactions']
VISUAL_CHECKS = ['appearance', 'whole_body_motion', 'timing_and_transition', 'transparency_and_crop', 'requested_action']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_scope(scope):
    """Validate the AI's recorded project inventory, not an invented fixed menu."""
    if not isinstance(scope, dict):
        raise ValueError('Coverage scope must be an object')
    motion.require_text(scope.get('request'), 'Record the user-requested scope')
    mode = scope.setdefault('scope_mode', 'full_character')
    if mode not in ['full_character', 'action_study']:
        raise ValueError('Scope mode must be full_character or action_study')
    if mode == 'action_study':
        motion.require_text(scope.get('study_reason'), 'An action study needs an explicit reason; it is not a complete character')
    characters = scope.get('characters')
    if not isinstance(characters, dict) or not characters:
        raise ValueError('Explicit character/action coverage is required')
    for name, entry in characters.items():
        motion.require_text(name, 'Character name required')
        if not isinstance(entry, dict):
            raise ValueError('Character coverage entry must be an object')
        discovery = entry.get('discovery', {})
        if not isinstance(discovery, dict):
            raise ValueError('Project discovery must be an object')
        motion.require_text(discovery.get('project'), 'AI must record the inspected project/request context')
        inspections = discovery.get('inspections', [])
        if not isinstance(inspections, list) or any(not isinstance(i, dict) or not isinstance(i.get('area'), str) for i in inspections) or sorted(i['area'] for i in inspections) != sorted(DISCOVERY_AREAS):
            raise ValueError('AI discovery must inspect state machine, control inputs, abilities, weapons, damage/death/revival and interactions')
        for inspection in inspections:
            if inspection.get('status') not in ['inspected', 'not_applicable']:
                raise ValueError('Discovery inspection status must be inspected or not_applicable')
            motion.require_text(inspection.get('source'), 'Every discovery area needs a concrete source/search reference')
            motion.require_text(inspection.get('notes'), 'Explain discovery findings or why an area is not applicable')
        requirements = entry.get('requirements')
        if not isinstance(requirements, list) or not requirements:
            raise ValueError('Record the discovered gameplay requirements before mapping actions')
        identifiers = set()
        applicable = []
        for requirement in requirements:
            if not isinstance(requirement, dict):
                raise ValueError('Gameplay requirement must be an object')
            for key in ['id', 'game_id', 'purpose', 'source']:
                motion.require_text(requirement.get(key), 'Every gameplay requirement needs ' + key)
            if requirement['id'] in identifiers:
                raise ValueError('Gameplay requirement IDs must be distinct')
            identifiers.add(requirement['id'])
            if requirement.get('kind') not in ['action', 'ability', 'weapon', 'interaction']:
                raise ValueError('Gameplay requirement kind must be action, ability, weapon or interaction')
            if type(requirement.get('applicable')) is not bool:
                raise ValueError('Each discovered requirement must explicitly record applicability')
            if requirement['applicable']:
                applicable.append(requirement['id'])
            else:
                motion.require_text(requirement.get('exclusion_reason'), 'Excluded requirements need an explicit reason')
        mapping = entry.get('action_map')
        if not isinstance(mapping, dict) or set(mapping) != set(applicable) or not applicable:
            raise ValueError('Action mapping must cover every applicable discovered requirement exactly')
        actions = list(mapping.values())
        if any(not isinstance(a, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', a) for a in actions):
            raise ValueError('Invalid action ID')
        if len(set(actions)) != len(actions):
            raise ValueError('Different gameplay requirements need independent action IDs; a generic action cannot replace multiple abilities')
        declared = entry.get('required_actions', actions)
        if not isinstance(declared, list) or any(not isinstance(a, str) for a in declared) or len(declared) != len(actions) or set(declared) != set(actions):
            raise ValueError('Required actions must exactly cover the discovered gameplay mapping')
        entry['required_actions'] = declared


def create(spec, out):
    spec = Path(spec).resolve()
    scope = motion.read(spec)
    validate_scope(scope)
    for entry in scope['characters'].values():
        motion.require_text(entry.get('character'), 'Character image path required')
        character = (spec.parent / entry['character']).resolve()
        verify_character_image(character)
        entry['character'] = str(character)
        entry['character_sha256'] = digest(character)
    out = Path(out).resolve()
    if out.exists():
        raise ValueError('Batch already exists; do not silently replace its scope')
    out.mkdir(parents=True)
    motion.write(out / 'scope.json', scope)
    motion.write(out / 'batch.json', {'schema': 2, 'scope_sha256': digest(out / 'scope.json'), 'jobs': {}, 'videos': {}, 'reviews': {}})
    return status(out)


def load(batch):
    root = Path(batch).resolve()
    data = motion.read(root / 'batch.json')
    if not isinstance(data, dict):
        raise ValueError('Batch metadata must be an object')
    if data.get('schema') not in [1, 2] or digest(root / 'scope.json') != data.get('scope_sha256'):
        raise ValueError('Scope changed; create an explicit revised batch instead of dropping requirements')
    scope = motion.read(root / 'scope.json')
    if not isinstance(scope, dict):
        raise ValueError('Coverage scope must be an object')
    for key in ['jobs', 'videos', 'reviews']:
        collection = data.setdefault(key, {})
        if not isinstance(collection, dict) or any(not isinstance(v, dict) for v in collection.values()):
            raise ValueError('Batch action registrations must be objects: ' + key)
    if data['schema'] == 2:
        validate_scope(scope)
    return root, data, scope


def binding(batch, character, action):
    _, data, scope = load(batch)
    if data['schema'] != 2:
        raise ValueError('Legacy batch has no project discovery inventory; create an explicitly revised schema-2 batch')
    entry = scope['characters'].get(character, {})
    if action not in entry.get('required_actions', []):
        raise ValueError('Action is not required for this character')
    requirement_id = next(key for key, value in entry['action_map'].items() if value == action)
    requirement = next(r for r in entry['requirements'] if r['id'] == requirement_id)
    return {'scope_sha256': data['scope_sha256'], 'character': character, 'action': action, 'requirement': requirement}


def attach(batch, character, job):
    root, data, scope = load(batch)
    if character not in scope['characters']:
        raise ValueError('Character is not in this batch')
    job, jd = motion.job_read(job)
    motion.verify_job_contract(job, jd)
    if digest(job / jd['character']) != scope['characters'][character]['character_sha256']:
        raise ValueError('Job uses a different character image')
    matches = set(jd['actions']) & set(scope['characters'][character]['required_actions'])
    if not matches:
        raise ValueError('Job has none of the required actions')
    for action in matches:
        data['jobs'].setdefault(character, {})[action] = str(job)
        data.get('videos', {}).get(character, {}).pop(action, None)
        data['reviews'].get(character, {}).pop(action, None)
    duplicates = duplicate_actions(data, scope)
    if duplicates:
        raise ValueError('Duplicate action evidence: ' + '; '.join(duplicates.values()))
    motion.write(root / 'batch.json', data)
    return status(root)


def sample_path(sample, relative):
    if not isinstance(relative, str) or not relative:
        raise ValueError('Video sample must name its local artifact files')
    path = (sample / relative).resolve()
    if not path.is_relative_to(sample) or not path.is_file():
        raise ValueError('Missing video artifact or path outside the sample: ' + relative)
    return path


def verify_character_image(path):
    try:
        with Image.open(path) as image:
            if getattr(image, 'n_frames', 1) != 1:
                raise ValueError('Character reference must be one still image')
            image.verify()
    except OSError as exc:
        raise ValueError('Character reference is not a readable image') from exc


def video_evidence(sample, character_hash, action, expected_binding):
    sample = Path(sample).resolve()
    manifest = motion.read(sample / 'sample.json')
    if not isinstance(manifest, dict):
        raise ValueError('Video sample manifest must be an object')
    if manifest.get('status') != 'video_review_sample' or manifest.get('scope_mode') != 'action_study':
        raise ValueError('Expected a bound single-action video review sample')
    if manifest.get('draft') or manifest.get('source_edge_frames'):
        raise ValueError('Diagnostic or source-clipped video samples cannot pass batch acceptance')
    if manifest.get('coverage_binding') != expected_binding:
        raise ValueError('Video sample does not match this character/action/gameplay requirement binding')
    reference = sample_path(sample, manifest.get('character_reference'))
    verify_character_image(reference)
    if digest(reference) != character_hash or manifest.get('character_sha256') != character_hash:
        raise ValueError('Video uses a different or changed character reference')
    source = sample_path(sample, manifest.get('source_video'))
    if digest(source) != manifest.get('source_video_sha256'):
        raise ValueError('Video source changed since extraction')
    clips = manifest.get('clips')
    if not isinstance(clips, list) or len(clips) != 1 or not isinstance(clips[0], dict) or clips[0].get('name') != action:
        raise ValueError('Video clip action does not match the required action')
    clip = clips[0]
    count = clip.get('count')
    if type(count) is not int or not 2 <= count <= 120 or type(clip.get('loop')) is not bool:
        raise ValueError('Invalid video clip frame count or loop contract')
    seconds = clip.get('seconds')
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('Invalid video clip duration')
    tile, origin = clip.get('tile', []), clip.get('origin', [])
    if not isinstance(tile, list) or len(tile) != 2 or any(type(v) is not int or v <= 0 for v in tile) or not isinstance(origin, list) or len(origin) != 2:
        raise ValueError('Invalid shared video canvas or origin')
    if any(type(v) is not int or not 0 <= v < tile[i] for i, v in enumerate(origin)):
        raise ValueError('Video origin is outside its shared canvas')
    indices = clip.get('source_frame_indices', [])
    times = clip.get('source_times_seconds', [])
    if not isinstance(indices, list) or len(indices) != count or any(type(v) is not int or v < 0 for v in indices) or any(a >= b for a, b in zip(indices, indices[1:])):
        raise ValueError('Video source frames must be distinct and ordered')
    if not isinstance(times, list) or len(times) != count or any(type(v) not in (int, float) or not math.isfinite(v) for v in times) or any(a >= b for a, b in zip(times, times[1:])):
        raise ValueError('Video source timestamps must be distinct and ordered')
    paths = clip.get('frames', [])
    if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths) or len(paths) != count or len(set(paths)) != count:
        raise ValueError('Video frame list does not match its count')
    frames = [sample_path(sample, p) for p in paths]
    atlas_path = sample_path(sample, clip.get('atlas', f'{action}/atlas.png'))
    with Image.open(atlas_path) as atlas:
        if atlas.format != 'PNG' or getattr(atlas, 'n_frames', 1) != 1 or atlas.mode != 'RGBA' or atlas.size != (tile[0] * count, tile[1]):
            raise ValueError('Video atlas does not match the shared canvas')
        for i, path in enumerate(frames):
            with Image.open(path) as frame:
                if frame.format != 'PNG' or getattr(frame, 'n_frames', 1) != 1 or frame.mode != 'RGBA' or list(frame.size) != tile:
                    raise ValueError('Video frames require real alpha, a body and one shared canvas')
                bounds = frame.getchannel('A').getbbox()
                if not bounds or bounds[0] == 0 or bounds[1] == 0 or bounds[2] == tile[0] or bounds[3] == tile[1]:
                    raise ValueError('Video body must retain transparent padding on every canvas edge')
                box = (i * tile[0], 0, (i + 1) * tile[0], tile[1])
                if atlas.crop(box).tobytes() != frame.tobytes():
                    raise ValueError('Video atlas pixels differ from the reviewed frame sequence')
    files = [sample / 'sample.json', reference, source, atlas_path] + frames
    return {str(p.relative_to(sample)).replace('\\', '/'): digest(p) for p in files}


def action_evidence(root, data, scope, character, action):
    entry = scope['characters'][character]
    if digest(entry['character']) != entry['character_sha256']:
        raise ValueError('Batch character reference changed')
    sample = data.get('videos', {}).get(character, {}).get(action)
    if sample:
        return video_evidence(sample, entry['character_sha256'], action, binding(root, character, action))
    return evidence(data['jobs'][character][action], entry['character_sha256'], action)


def duplicate_actions(data, scope):
    """Different requirements cannot be satisfied by copying one export under aliases."""
    duplicates = {}
    for character, entry in scope['characters'].items():
        sources, pixels = {}, {}
        for action in entry['required_actions']:
            sample = data.get('videos', {}).get(character, {}).get(action)
            job = data.get('jobs', {}).get(character, {}).get(action)
            try:
                if sample:
                    base = Path(sample).resolve()
                    report = motion.read(base / 'sample.json')
                    clip = report['clips'][0]
                    source_key = (digest(sample_path(base, report['source_video'])), tuple(clip['source_frame_indices']))
                    if source_key in sources:
                        duplicates[(character, action)] = 'Same source video interval is already assigned to ' + sources[source_key]
                    sources[source_key] = action
                    paths = [sample_path(base, p) for p in clip['frames']]
                elif job:
                    base = Path(job).resolve() / action
                    clip = motion.read(base / 'clip.json')
                    paths = [base / f'frame-{i:03}.png' for i in range(clip['count'])]
                else:
                    continue
                signature = []
                for path in paths:
                    with Image.open(path) as image:
                        signature.append(hashlib.sha256(str(image.size).encode() + image.convert('RGBA').tobytes()).hexdigest())
                pixel_key = tuple(signature)
                if pixel_key in pixels:
                    duplicates[(character, action)] = 'Same exported animation is already assigned to ' + pixels[pixel_key]
                pixels[pixel_key] = action
            except (ValueError, KeyError, OSError, TypeError, AttributeError, IndexError):
                continue  # action_evidence reports incomplete/corrupt artifacts separately.
    return duplicates


def attach_video(batch, character, action, sample):
    root, data, scope = load(batch)
    expected = binding(root, character, action)
    sample = Path(sample).resolve()
    video_evidence(sample, scope['characters'][character]['character_sha256'], action, expected)
    data.setdefault('videos', {}).setdefault(character, {})[action] = str(sample)
    data['jobs'].get(character, {}).pop(action, None)
    duplicates = duplicate_actions(data, scope)
    if duplicates:
        raise ValueError('Duplicate action evidence: ' + '; '.join(duplicates.values()))
    data['reviews'].get(character, {}).pop(action, None)
    motion.write(root / 'batch.json', data)
    return status(root)


def evidence(job, character_hash, action):
    job, jd = motion.job_read(job)
    motion.verify_job_contract(job, jd)
    if jd['schema'] in [2,3] and not jd.get('generation_preflight'):raise ValueError('Generation-time canvas controls were not verified; prepare and generate a new job before batch approval')
    if jd.get('generation_preflight',{}).get('diagnostic_only'):raise ValueError('Diagnostic generation is not an approved replacement batch')
    if digest(job / jd['character']) != character_hash:
        raise ValueError('Character image changed')
    if jd['schema'] in [2,3] and not jd.get('reference_review'):
        raise ValueError('Reference is not reviewed')
    if jd['actions'].get(action, {}).get('status') != 'packed':
        raise ValueError('Action has not been packed')
    dest = job / action
    clip = motion.read(dest / 'clip.json')
    if clip.get('draft',True) or not clip.get('sequence_check',{}):
        raise ValueError('Draft or legacy export lacks per-frame pose verification')
    observation_path=dest/'pose-observations.json'
    if clip.get('hold_from') is not None and clip['hold_from']<clip['count']-1:raise ValueError('Export changes the reviewed source motion with hold_from')
    rectangles=None;point_offsets=None;crop_path=dest/'crop-plan.json'
    if clip.get('crop_plan_sha256'):
        if digest(crop_path)!=clip['crop_plan_sha256'] or motion.read(observation_path).get('crop_plan_sha256')!=digest(crop_path):raise ValueError('Crop geometry changed after pose review')
        s=jd['actions'][action];crop_data,rectangles=motion.contract_module().load_crop(crop_path,dest/clip['source'],s['columns'],s['rows'],s['count'])
        if crop_data.get('schema')==2:point_offsets=motion.contract_module().cell_layout(crop_data,crop_data['image_size'])['frame_translations']
    elif jd['actions'][action].get('endpoints'):raise ValueError('Export is missing its reviewed crop geometry')
    result=motion.quality_module().check(job,jd,action,dest/clip['source'],motion.read(observation_path),motion.mannequin_module(),rectangles,point_offsets)
    if result!=clip['sequence_check']:raise ValueError('Pose verification changed; review this output again')
    if clip['action'] != action or clip.get('plan_sha256') != jd.get('plan_sha256'):
        raise ValueError('Clip does not belong to the current action/plan')
    files = [job / 'job.json', dest / 'clip.json', dest / clip['atlas'], dest / clip['source'], observation_path]
    files += [dest / f'frame-{i:03}.png' for i in range(clip['count'])]
    if clip.get('crop_plan_sha256'):files.append(crop_path)
    if jd['actions'][action].get('endpoint_reference'):files.append(job/jd['actions'][action]['endpoint_reference'])
    if digest(dest / clip['source']) != clip['source_sha256']:
        raise ValueError('Generated source changed')
    # job.json status changes when another action is packed; hash stable inputs instead.
    files = files[1:] + [job / jd['character']]
    if jd['schema'] == 2:
        files += [job / jd['motion_plan'], job / jd['actions'][action]['guide'], job / jd['actions'][action]['reference']]
    elif jd['schema'] == 3:
        files += [job / jd['reference_bundle']]
        files += [job / jd['actions'][action][k] for k in ['guide','reference','landmarks']]
    return {str(p.relative_to(job)): digest(p) for p in files}


def check_review(report, hashes, expected_binding, is_video):
    if not isinstance(report, dict) or not isinstance(report.get('checks'), dict):
        raise ValueError('Visual review and checks must be objects')
    if report.get('artifact_hashes') != hashes:
        raise ValueError('Review must identify the exact current exported artifacts')
    if expected_binding and report.get('coverage_binding') != expected_binding:
        raise ValueError('Review must identify the exact gameplay requirement binding')
    checks = VISUAL_CHECKS + (['source_video', 'ability_or_weapon_match'] if is_video else [])
    for check in checks:
        if report.get('checks', {}).get(check) is not True:
            raise ValueError('Visual check not passed: ' + check)
    motion.require_text(report.get('notes'), 'Actual visual observations required')


def review(batch, character, action, report):
    root, data, scope = load(batch)
    entry = scope['characters'].get(character, {})
    if action not in entry.get('required_actions', []):
        raise ValueError('Action is not required for this character')
    if not data['jobs'].get(character, {}).get(action) and not data.get('videos', {}).get(character, {}).get(action):
        raise ValueError('Attach this action job first')
    duplicates = duplicate_actions(data, scope)
    if duplicates:
        raise ValueError('Duplicate action evidence: ' + '; '.join(duplicates.values()))
    hashes = action_evidence(root, data, scope, character, action)
    report = motion.read(report)
    check_review(report, hashes, binding(root, character, action) if data['schema'] == 2 else None,
                 bool(data.get('videos', {}).get(character, {}).get(action)))
    data['reviews'].setdefault(character, {})[action] = report
    motion.write(root / 'batch.json', data)
    return status(root)


def status(batch):
    root, data, scope = load(batch)
    entries, current_evidence = [], {}
    duplicates = duplicate_actions(data, scope)
    for character, entry in scope['characters'].items():
        for action in entry['required_actions']:
            expected = binding(root, character, action) if data['schema'] == 2 else None
            item = {'character': character, 'action': action, 'state': 'missing_job',
                    'coverage_binding': expected, 'requirement': expected['requirement'] if expected else None}
            job = data['jobs'].get(character, {}).get(action)
            sample = data.get('videos', {}).get(character, {}).get(action)
            if job or sample:
                try:
                    if (character, action) in duplicates:
                        raise ValueError('Duplicate action evidence: ' + duplicates[(character, action)])
                    hashes = action_evidence(root, data, scope, character, action)
                    record = data['reviews'].get(character, {}).get(action)
                    item['state'] = 'awaiting_visual_review'
                    item['artifact_hashes'] = hashes
                    if record:
                        try:
                            check_review(record, hashes, expected, bool(sample))
                            item['state'] = 'reviewed'
                            current_evidence[character + '/' + action] = record
                        except ValueError as exc:
                            item['reason'] = str(exc)
                except (ValueError, KeyError, OSError) as exc:
                    item.update(state='incomplete', reason=str(exc))
            entries.append(item)
    ready = sum(e['state'] == 'reviewed' for e in entries)
    mode = scope.get('scope_mode', 'full_character')
    scope_complete = bool(entries) and ready == len(entries)
    full_complete = scope_complete and mode == 'full_character' and data['schema'] == 2
    evidence_hash = hashlib.sha256(json.dumps(current_evidence, sort_keys=True).encode()).hexdigest()
    try:
        snapshot = motion.read(root / 'completion.json') if (root / 'completion.json').is_file() else {}
    except (ValueError, OSError):
        snapshot = {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    return {'complete': full_complete, 'scope_complete': scope_complete, 'full_character_complete': full_complete,
            'study_complete': scope_complete and mode == 'action_study', 'scope_mode': mode,
            'delivery_kind': mode, 'coverage_schema': data['schema'], 'reviewed': ready,
            'required': len(entries), 'actions': entries, 'evidence_sha256': evidence_hash,
            'completion_current': scope_complete and snapshot.get('scope_sha256') == data['scope_sha256']
                                  and snapshot.get('evidence_sha256') == evidence_hash}


def finish(batch):
    result = status(batch)
    if not result['scope_complete']:
        missing = [f"{e['character']}/{e['action']}: {e['state']}" for e in result['actions'] if e['state'] != 'reviewed']
        raise ValueError('Batch incomplete: ' + '; '.join(missing))
    root, data, _ = load(batch)
    if data['schema'] != 2:
        raise ValueError('Legacy batch lacks project discovery; create an explicitly revised schema-2 batch')
    motion.write(root / 'completion.json', {'scope_sha256': data['scope_sha256'], **result})
    return status(root)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    c = commands.add_parser('create'); c.add_argument('--spec', required=True); c.add_argument('--out', required=True)
    for name in ['attach', 'attach-video', 'binding', 'review', 'status', 'finish']:
        c = commands.add_parser(name); c.add_argument('--batch', required=True)
        if name in ['attach', 'attach-video', 'binding', 'review']: c.add_argument('--character', required=True)
        if name == 'attach': c.add_argument('--job', required=True)
        if name in ['attach-video', 'binding']: c.add_argument('--action', required=True)
        if name == 'attach-video': c.add_argument('--sample', required=True)
        if name == 'review': c.add_argument('--action', required=True); c.add_argument('--report', required=True)
    args = vars(p.parse_args()); command = args.pop('command')
    try:
        print(json.dumps(globals()[command.replace('-', '_')](**args), ensure_ascii=False, indent=2))
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
