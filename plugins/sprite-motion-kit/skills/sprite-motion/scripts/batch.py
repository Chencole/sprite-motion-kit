"""Track user-requested character/action coverage; never infer completion from one clip."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys
import motion


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def create(spec, out):
    spec = Path(spec).resolve()
    scope = motion.read(spec)
    motion.require_text(scope.get('request'), 'Record the user-requested scope')
    characters = scope.get('characters')
    if not isinstance(characters, dict) or not characters:
        raise ValueError('Explicit character/action coverage is required')
    for name, entry in characters.items():
        motion.require_text(name, 'Character name required')
        actions = entry.get('required_actions')
        if not isinstance(actions, list) or not actions or len(set(actions)) != len(actions):
            raise ValueError('Each character needs distinct required actions')
        if any(not isinstance(a, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', a) for a in actions):
            raise ValueError('Invalid action ID')
        character = (spec.parent / entry['character']).resolve()
        entry['character'] = str(character)
        entry['character_sha256'] = digest(character)
    out = Path(out).resolve()
    if out.exists():
        raise ValueError('Batch already exists; do not silently replace its scope')
    out.mkdir(parents=True)
    motion.write(out / 'scope.json', scope)
    motion.write(out / 'batch.json', {'schema': 1, 'scope_sha256': digest(out / 'scope.json'), 'jobs': {}, 'reviews': {}})
    return status(out)


def load(batch):
    root = Path(batch).resolve()
    data = motion.read(root / 'batch.json')
    if data.get('schema') != 1 or digest(root / 'scope.json') != data.get('scope_sha256'):
        raise ValueError('Scope changed; create an explicit revised batch instead of dropping requirements')
    return root, data, motion.read(root / 'scope.json')


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
        data['reviews'].get(character, {}).pop(action, None)
    motion.write(root / 'batch.json', data)
    return status(root)


def evidence(job, character_hash, action):
    job, jd = motion.job_read(job)
    motion.verify_job_contract(job, jd)
    if digest(job / jd['character']) != character_hash:
        raise ValueError('Character image changed')
    if jd['schema'] == 2 and not jd.get('reference_review'):
        raise ValueError('Reference is not reviewed')
    if jd['actions'].get(action, {}).get('status') != 'packed':
        raise ValueError('Action has not been packed')
    dest = job / action
    clip = motion.read(dest / 'clip.json')
    if clip['action'] != action or clip.get('plan_sha256') != jd.get('plan_sha256'):
        raise ValueError('Clip does not belong to the current action/plan')
    files = [job / 'job.json', dest / 'clip.json', dest / clip['atlas'], dest / clip['source']]
    files += [dest / f'frame-{i:03}.png' for i in range(clip['count'])]
    if digest(dest / clip['source']) != clip['source_sha256']:
        raise ValueError('Generated source changed')
    # job.json status changes when another action is packed; hash stable inputs instead.
    files = files[1:] + [job / jd['character']]
    if jd['schema'] == 2:
        files += [job / jd['motion_plan'], job / jd['actions'][action]['guide']]
    return {str(p.relative_to(job)): digest(p) for p in files}


def review(batch, character, action, report):
    root, data, scope = load(batch)
    entry = scope['characters'].get(character, {})
    if action not in entry.get('required_actions', []):
        raise ValueError('Action is not required for this character')
    job = data['jobs'].get(character, {}).get(action)
    if not job:
        raise ValueError('Attach this action job first')
    hashes = evidence(job, entry['character_sha256'], action)
    report = motion.read(report)
    if report.get('artifact_hashes') != hashes:
        raise ValueError('Review must identify the exact current exported artifacts')
    for check in ['appearance', 'whole_body_motion', 'timing_and_transition', 'transparency_and_crop', 'requested_action']:
        if report.get('checks', {}).get(check) is not True:
            raise ValueError('Visual check not passed: ' + check)
    motion.require_text(report.get('notes'), 'Actual visual observations required')
    data['reviews'].setdefault(character, {})[action] = report
    motion.write(root / 'batch.json', data)
    return status(root)


def status(batch):
    root, data, scope = load(batch)
    entries = []
    for character, entry in scope['characters'].items():
        for action in entry['required_actions']:
            item = {'character': character, 'action': action, 'state': 'missing_job'}
            job = data['jobs'].get(character, {}).get(action)
            if job:
                try:
                    hashes = evidence(job, entry['character_sha256'], action)
                    record = data['reviews'].get(character, {}).get(action)
                    item['state'] = 'reviewed' if record and record.get('artifact_hashes') == hashes else 'awaiting_visual_review'
                    if item['state'] != 'reviewed':
                        item['artifact_hashes'] = hashes
                except (ValueError, KeyError, OSError) as exc:
                    item.update(state='incomplete', reason=str(exc))
            entries.append(item)
    ready = sum(e['state'] == 'reviewed' for e in entries)
    return {'complete': ready == len(entries), 'reviewed': ready, 'required': len(entries), 'actions': entries}


def finish(batch):
    result = status(batch)
    if not result['complete']:
        missing = [f"{e['character']}/{e['action']}: {e['state']}" for e in result['actions'] if e['state'] != 'reviewed']
        raise ValueError('Batch incomplete: ' + '; '.join(missing))
    root, data, _ = load(batch)
    motion.write(root / 'completion.json', {'scope_sha256': data['scope_sha256'], **result})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    c = commands.add_parser('create'); c.add_argument('--spec', required=True); c.add_argument('--out', required=True)
    for name in ['attach', 'review', 'status', 'finish']:
        c = commands.add_parser(name); c.add_argument('--batch', required=True)
        if name in ['attach', 'review']: c.add_argument('--character', required=True)
        if name == 'attach': c.add_argument('--job', required=True)
        if name == 'review': c.add_argument('--action', required=True); c.add_argument('--report', required=True)
    args = vars(p.parse_args()); command = args.pop('command')
    try:
        print(json.dumps(globals()[command](**args), ensure_ascii=False, indent=2))
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
