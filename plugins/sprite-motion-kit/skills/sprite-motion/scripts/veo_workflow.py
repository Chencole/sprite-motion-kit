"""Prepare project-bound Veo videos from an existing image or reviewed start still.

The workflow is deliberately split into local preparation, explicit provider
submission, visual review, and extraction. This module never submits a paid
request. When the user chooses direct image reuse, verified existing artwork is
bound to the video without a new image task or still review. The optional
action-specific start-still route retains its own visual-review prerequisites.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

import batch as coverage
import motion
import mxapi


ACTION_KINDS = {'loop', 'one_shot'}
FACINGS = {'right_profile', 'left_profile'}
ROOT_MOTION = {'in_place', 'travel', 'stationary'}
BACKGROUND_MODES = {'green', 'magenta'}
EQUIPMENT_KINDS = {'none', 'handheld', 'shield', 'focus', 'natural_weapon'}
EQUIPMENT_STATES = {'none', 'sheathed', 'ready', 'attack', 'casting', 'natural', 'dropped', 'recovered'}
LEGAL_TRANSITIONS = {
    'none': {'none'},
    'sheathed': {'sheathed', 'ready'},
    'ready': {'ready', 'attack', 'casting', 'sheathed', 'dropped'},
    'attack': {'attack', 'ready', 'natural', 'dropped'},
    'casting': {'casting', 'ready', 'dropped'},
    'natural': {'natural', 'attack'},
    'dropped': {'dropped', 'recovered'},
    'recovered': {'ready', 'sheathed'},
}
STILL_CHECKS = [
    'identity', 'strict_side_profile', 'action_start_pose', 'equipment_start_state',
    'full_action_clearance', 'clean_key_background',
]


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + ' must be explicit text authored from the project')
    return value.strip()


def _texts(value, label, *, minimum=1):
    if not isinstance(value, list) or len(value) < minimum:
        raise ValueError(label + f' needs at least {minimum} explicit entries')
    return [_text(item, label) for item in value]


def _ratio(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f'{label} must be between {low:.2f} and {high:.2f}')
    return float(value)


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def image_digest(path):
    """Hash decoded pixels so a harmless PNG re-encode does not break identity."""
    try:
        with Image.open(path) as image:
            if getattr(image, 'n_frames', 1) != 1:
                raise ValueError('Identity reference must be one still image')
            rgba = image.convert('RGBA')
            return hashlib.sha256(f'{rgba.width}x{rgba.height}:RGBA'.encode() + rgba.tobytes()).hexdigest()
    except OSError as exc:
        raise ValueError('Identity reference is not a readable image') from exc


def design_digest(design):
    return hashlib.sha256(json.dumps(design, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _validate_equipment(design, phases):
    equipment = design.get('equipment_policy')
    if not isinstance(equipment, dict) or equipment.get('kind') not in EQUIPMENT_KINDS:
        raise ValueError('Explicit equipment_policy kind is required')
    for key in ['item', 'attachment', 'start_state', 'end_state', 'hands_at_start',
                'hands_during', 'hands_at_end', 'motion']:
        _text(equipment.get(key), 'equipment ' + key)
    start, end = equipment['start_state'], equipment['end_state']
    if start not in EQUIPMENT_STATES or end not in EQUIPMENT_STATES:
        raise ValueError('Unknown equipment start/end state')
    if equipment['kind'] == 'none' and (start != 'none' or end != 'none'):
        raise ValueError('Unarmed equipment must remain in the none state')
    if equipment['kind'] == 'natural_weapon' and (start != 'natural' or end != 'natural'):
        raise ValueError('Natural weapons must enter and leave in the natural state')
    states = [start] + [phase['equipment_state'] for phase in phases] + [end]
    for before, after in zip(states, states[1:]):
        if after not in LEGAL_TRANSITIONS[before]:
            raise ValueError(f'Illegal equipment transition: {before} -> {after}')
    if design['action_kind'] == 'loop' and start != end:
        raise ValueError('Loop equipment state must match at the seam')
    return equipment


def validate_design(design, expected_binding=None):
    if not isinstance(design, dict) or design.get('schema') != 1:
        raise ValueError('Veo action design must use schema 1')
    if design.get('design_status') != 'authored':
        raise ValueError('AI must author and inspect the action design before generation')
    binding = design.get('coverage_binding')
    if not isinstance(binding, dict):
        raise ValueError('Action design needs a project coverage binding')
    if expected_binding is not None and binding != expected_binding:
        raise ValueError('Action design must match the current project coverage binding')
    for key in ['character_id', 'action_id', 'visual_identity', 'gameplay_context',
                'anatomy_and_weight', 'start_pose', 'end_pose']:
        _text(design.get(key), key)
    if binding.get('character') != design['character_id'] or binding.get('action') != design['action_id']:
        raise ValueError('Design character/action differs from its coverage binding')
    if design.get('action_kind') not in ACTION_KINDS:
        raise ValueError('action_kind must be loop or one_shot')
    if design.get('facing') not in FACINGS:
        raise ValueError('Use a strict left or right side profile')
    if design.get('root_motion') not in ROOT_MOTION:
        raise ValueError('root_motion must be in_place, travel or stationary')
    if design.get('background_mode') not in BACKGROUND_MODES:
        raise ValueError('background_mode must explicitly select green or magenta keying')
    evidence = design.get('design_evidence')
    if not isinstance(evidence, list) or not evidence:
        raise ValueError('Record project evidence for this action and equipment state')
    for record in evidence:
        if not isinstance(record, dict):
            raise ValueError('Design evidence entries must be objects')
        _text(record.get('source'), 'design evidence source')
        _text(record.get('observation'), 'design evidence observation')
    phases = design.get('phases')
    if not isinstance(phases, list) or len(phases) < 3:
        raise ValueError('Action needs at least three ordered motion phases')
    previous = 0.0
    for phase in phases:
        if not isinstance(phase, dict):
            raise ValueError('Action phases must be objects')
        _text(phase.get('name'), 'phase name')
        _text(phase.get('body_motion'), 'phase body motion')
        _text(phase.get('equipment_motion'), 'phase equipment motion')
        _text(phase.get('game_event'), 'phase gameplay event; use none when there is no event')
        at = _ratio(phase.get('at'), 'phase time', 0.01, 0.99)
        if at <= previous:
            raise ValueError('Phase times must be strictly increasing')
        previous = at
        if phase.get('equipment_state') not in EQUIPMENT_STATES:
            raise ValueError('Every phase needs a recognized equipment_state')
    equipment = _validate_equipment(design, phases)
    effects = design.get('effects')
    if not isinstance(effects, dict) or effects.get('allow_unlisted') is not False:
        raise ValueError('Effects must explicitly forbid unlisted model inventions')
    if not isinstance(effects.get('allowed'), list) or not isinstance(effects.get('forbidden'), list):
        raise ValueError('Effects allowed/forbidden must be lists')
    _texts(effects.get('forbidden'), 'forbidden effects')
    framing = design.get('framing')
    if not isinstance(framing, dict):
        raise ValueError('Framing must describe the complete action envelope')
    _ratio(framing.get('character_height_ratio'), 'character height ratio', .25, .55)
    _ratio(framing.get('feet_y_ratio'), 'feet position ratio', .65, .90)
    safe = framing.get('safe_rect')
    if not isinstance(safe, list) or len(safe) != 4:
        raise ValueError('safe_rect must be [left, top, right, bottom]')
    left, top, right, bottom = [_ratio(value, 'safe rectangle coordinate', 0.0, 1.0) for value in safe]
    if not left < right or not top < bottom or left > .25 or top > .25 or right < .75 or bottom < .75:
        raise ValueError('safe_rect must preserve a useful central action area')
    _ratio(framing.get('minimum_clearance_ratio'), 'minimum clearance ratio', .02, .20)
    envelope = framing.get('motion_envelope')
    if not isinstance(envelope, dict):
        raise ValueError('motion_envelope must cover the complete body and action')
    for key in ['top', 'front', 'back', 'bottom']:
        _text(envelope.get(key), 'motion envelope ' + key)
    includes = framing.get('includes')
    if not isinstance(includes, list) or not {'body', 'equipment'}.issubset(set(includes)):
        raise ValueError('Framing must include at least body and equipment')
    _texts(design.get('identity_constraints'), 'identity constraints', minimum=3)
    if design['action_kind'] == 'loop':
        cycles = design.get('complete_cycles')
        if type(cycles) is not int or cycles < 2:
            raise ValueError('A generated loop needs at least two complete visible cycles')
        seam = design.get('loop_compatibility')
        if not isinstance(seam, dict):
            raise ValueError('Loop needs an explicit seam compatibility record')
        for key in ['equipment_state_matches', 'hand_occupancy_matches', 'facing_matches', 'scale_matches', 'velocity_matches']:
            if seam.get(key) is not True:
                raise ValueError('Loop seam check not satisfied: ' + key)
        _text(seam.get('notes'), 'loop seam notes')
        if equipment['start_state'] != equipment['end_state']:
            raise ValueError('Loop starts and ends with different equipment states')
    else:
        if design.get('complete_cycles') is not None:
            raise ValueError('One-shot actions do not declare repeated cycles')
        _text(design.get('recovery_or_hold'), 'one-shot recovery or final hold')
    return design


def load_bound_design(path, batch_path, character, action):
    design = motion.read(path)
    expected = coverage.binding(batch_path, character, action)
    validate_design(design, expected)
    return design


def scaffold(batch_path, character, action, out):
    expected = coverage.binding(batch_path, character, action)
    requirement = expected['requirement']
    data = {
        'schema': 1, 'design_status': 'needs_authoring', 'coverage_binding': expected,
        'character_id': character, 'action_id': action,
        'visual_identity': '', 'identity_constraints': [],
        'gameplay_context': requirement['purpose'], 'anatomy_and_weight': '',
        'design_evidence': [{'source': requirement['source'], 'observation': ''}],
        'action_kind': '', 'facing': '', 'root_motion': '', 'background_mode': '',
        'start_pose': '', 'phases': [], 'end_pose': '',
        'equipment_policy': {'kind': '', 'item': '', 'attachment': '', 'start_state': '',
                             'end_state': '', 'hands_at_start': '', 'hands_during': '',
                             'hands_at_end': '', 'motion': ''},
        'effects': {'allowed': [], 'forbidden': [], 'allow_unlisted': False},
        'framing': {'character_height_ratio': .45, 'feet_y_ratio': .82,
                    'safe_rect': [.06, .06, .94, .94], 'minimum_clearance_ratio': .04,
                    'includes': ['body', 'equipment'],
                    'motion_envelope': {'top': '', 'front': '', 'back': '', 'bottom': ''}},
        'complete_cycles': None, 'loop_compatibility': None, 'recovery_or_hold': '',
    }
    out = Path(out).resolve()
    if out.exists():
        raise ValueError('Design file already exists')
    motion.write(out, data)
    return {'design': str(out), 'status': 'needs_authoring', 'generation_submitted': False}


def _equipment_text(equipment):
    states = f"start={equipment['start_state']}, end={equipment['end_state']}"
    if equipment['kind'] == 'none':
        invariant = 'No weapon or focus appears in either hand; do not invent one.'
    elif equipment['start_state'] == equipment['end_state'] == 'sheathed':
        invariant = ('The item starts and ends fully stowed. It may leave its attachment only if an ordered phase '
                     'explicitly changes equipment_state; otherwise it is never drawn or held in a hand.')
    elif equipment['start_state'] == equipment['end_state'] == 'ready':
        invariant = 'The item begins and ends attached to the described ready hand or hands.'
    elif equipment['kind'] == 'natural_weapon':
        invariant = 'Use only the described natural body weapon; do not invent handheld equipment.'
    else:
        invariant = 'Follow only the explicit ordered state transitions; do not invent a draw or re-sheath.'
    return (f"Equipment kind={equipment['kind']}; item={equipment['item']}; attachment={equipment['attachment']}; "
            f"{states}. Hands: start={equipment['hands_at_start']}; during={equipment['hands_during']}; "
            f"end={equipment['hands_at_end']}. Motion: {equipment['motion']} {invariant}")


def prompts(design):
    validate_design(design)
    facing = 'screen right' if design['facing'] == 'right_profile' else 'screen left'
    phases = '\n'.join(
        f"{i + 1}. at {p['at']:.2f} — {p['name']}: body={p['body_motion']}; "
        f"equipment={p['equipment_motion']}; equipment_state={p['equipment_state']}; game_event={p['game_event']}"
        for i, p in enumerate(design['phases']))
    framing = design['framing']
    envelope = framing['motion_envelope']
    safe = framing['safe_rect']
    identity = '; '.join(design['identity_constraints'])
    allowed = ', '.join(design['effects']['allowed']) or 'none'
    forbidden = ', '.join(design['effects']['forbidden'])
    timing = (f"Show at least {design['complete_cycles']} complete cycles. Loop seam: {design['loop_compatibility']['notes']}"
              if design['action_kind'] == 'loop' else
              f"One complete action only. Preserve the final endpoint: {design['recovery_or_hold']}")
    key_color = 'bright green #00FF00' if design['background_mode'] == 'green' else 'bright magenta #FF00FF'
    common = (
        f"Character identity: {design['visual_identity']}. Identity constraints: {identity}. "
        f"Anatomy and weight: {design['anatomy_and_weight']}. Gameplay use: {design['gameplay_context']}. "
        f"Strict 90-degree side profile facing {facing}; fixed camera, fixed scale, no turn toward camera. "
        f"Place the standing character at about {framing['character_height_ratio']:.2f} of frame height, "
        f"with feet near {framing['feet_y_ratio']:.2f} of frame height. Keep the full action within normalized safe "
        f"rectangle left={safe[0]:.2f}, top={safe[1]:.2f}, right={safe[2]:.2f}, bottom={safe[3]:.2f}, "
        f"with at least {framing['minimum_clearance_ratio']:.2f} additional visual clearance. "
        f"Reserve above={envelope['top']}; in front={envelope['front']}; behind={envelope['back']}; below={envelope['bottom']}. "
        f"The envelope includes {', '.join(framing['includes'])}. Keep every limb, clothing part, weapon, cape and allowed effect inside it. "
        f'Use a flat uniform {key_color} chroma-key background, with no scenery, floor shadow, text, border or camera motion. '
    )
    still = (
        'Create one action-specific 2D pixel-art start-frame reference from the supplied identity image. ' + common +
        f"This still must show the exact true start pose: {design['start_pose']}. {_equipment_text(design['equipment_policy'])} "
        'Preserve the original art style, face, proportions, costume and equipment design. This is an action start frame, not a generic combat idle.'
    )
    video = (
        'Animate the supplied reviewed action-specific start still as one continuous game-character action. ' + common +
        f"Start pose: {design['start_pose']}. Ordered phases:\n{phases}\nEnd pose: {design['end_pose']}. "
        f"{_equipment_text(design['equipment_policy'])} Root motion: {design['root_motion']}. {timing}. "
        f"Allowed effects: {allowed}. Forbidden effects: {forbidden}. Do not invent any unlisted effect, prop, weapon, target or costume change. "
        'Preserve crisp pixel-art edges and temporal identity. No cuts, zoom, viewpoint turns, motion blur or perspective drift.'
    )
    return {'still_prompt': still, 'video_prompt': video}


def _job_local_results(job, state, suffix):
    results = state.get('local_results', [])
    if not isinstance(results, list) or len(results) != 1:
        raise ValueError('Job must have exactly one downloaded local result')
    path = Path(results[0])
    if not path.is_absolute():
        path = (Path(job) / path).resolve()
    if not path.is_file() or path.suffix.lower() != suffix:
        raise ValueError('Downloaded job result is missing or has the wrong media type')
    return path


def _contains_key_color(path, mode):
    with Image.open(path) as image:
        rgba = np.asarray(image.convert('RGBA'))
    visible = rgba[:, :, 3] > 128
    rgb = rgba[:, :, :3].astype(np.int16)
    if mode == 'green':
        keyed = (rgb[:, :, 1] >= 150) & (rgb[:, :, 1] - np.maximum(rgb[:, :, 0], rgb[:, :, 2]) >= 80)
    else:
        minimum = np.minimum(rgb[:, :, 0], rgb[:, :, 2])
        keyed = (minimum >= 150) & (minimum - rgb[:, :, 1] >= 80)
    return bool(np.any(visible & keyed))


def identity_source(batch_path, character, identity_job, background_mode=None, *, allow_action_still=False):
    _, _, scope = coverage.load(batch_path)
    entry = scope['characters'].get(character)
    if not entry:
        raise ValueError('Character is not in this coverage batch')
    if file_digest(entry['character']) != entry['character_sha256']:
        raise ValueError('Batch character changed; create an explicitly revised batch')
    identity_job = Path(identity_job).resolve()
    identity_packet = motion.read(identity_job / 'request.json')
    if isinstance(identity_packet, dict) and identity_packet.get('kind') == 'reference_upload':
        packet, state, local = mxapi.read_uploaded_reference(identity_job)
        if file_digest(local) != entry['character_sha256']:
            raise ValueError('Uploaded original does not match the batch character SHA256')
        if background_mode is not None and _contains_key_color(local, background_mode):
            raise ValueError('Character identity contains the selected key color; author the action with the other background mode')
        return {
            'kind': 'reference_upload', 'url': state['result_urls'][0], 'job': str(identity_job),
            'request_sha256': state['request_sha256'], 'local_sha256': file_digest(local),
            'character_sha256': entry['character_sha256'], 'character_pixel_sha256': image_digest(local),
            'provider_origin': packet['provider_origin'],
        }
    packet, state = mxapi.read_job(identity_job)
    if packet.get('kind') != 'image' or state.get('state') != 'succeeded' or len(state.get('result_urls', [])) != 1:
        raise ValueError('Identity source must be one successful image job')
    prior_workflow = packet.get('workflow')
    if (not allow_action_still and isinstance(prior_workflow, dict)
            and prior_workflow.get('kind') == 'project_bound_veo_action'):
        raise ValueError('An action-specific still cannot replace the character identity source')
    local = _job_local_results(identity_job, state, '.png')
    if image_digest(local) != image_digest(entry['character']):
        raise ValueError('Identity image job does not match the batch character pixels')
    if background_mode is not None and _contains_key_color(local, background_mode):
        raise ValueError('Character identity contains the selected key color; author the action with the other background mode')
    return {
        'url': state['result_urls'][0], 'job': str(identity_job),
        'request_sha256': state['request_sha256'], 'local_sha256': file_digest(local),
        'character_sha256': entry['character_sha256'], 'character_pixel_sha256': image_digest(local),
    }


def _stamp(job, design, phase, **parents):
    job = Path(job).resolve()
    packet, state = mxapi.read_job(job)
    packet['workflow'] = {
        'schema': 1, 'kind': 'project_bound_veo_action', 'phase': phase,
        'design_sha256': design_digest(design), 'coverage_binding': design['coverage_binding'],
        **parents,
    }
    state['request_sha256'] = mxapi.digest(packet)
    mxapi.write_json(job / 'request.json', packet)
    mxapi.write_json(job / 'job.json', state)
    motion.write(job / 'action-design.json', design)


def prepare_still(design_path, batch_path, character, action, identity_job, job):
    design = load_bound_design(design_path, batch_path, character, action)
    source = identity_source(batch_path, character, identity_job, design['background_mode'])
    prompt = prompts(design)['still_prompt']
    result = mxapi.prepare(Path(job), 'gpt-image-2', prompt, [source['url']], resolution='1K', ratio='16:9')
    _stamp(job, design, 'action_still', identity_source=source)
    return {**result, 'workflow': 'project_bound_veo_action', 'phase': 'action_still'}


def _still_inputs(still_job, design):
    still_job = Path(still_job).resolve()
    packet, state = mxapi.read_job(still_job)
    workflow = packet.get('workflow')
    if not isinstance(workflow, dict):
        raise ValueError('Action still is missing its workflow binding')
    snapshot = motion.read(still_job / 'action-design.json')
    if (packet.get('model') != 'gpt-image-2' or workflow.get('phase') != 'action_still'
            or workflow.get('kind') != 'project_bound_veo_action'
            or workflow.get('design_sha256') != design_digest(design)
            or design_digest(snapshot) != workflow.get('design_sha256')
            or workflow.get('coverage_binding') != design['coverage_binding']):
        raise ValueError('Action still belongs to another, changed, or unbound design')
    if state.get('state') != 'succeeded' or len(state.get('result_urls', [])) != 1:
        raise ValueError('Action-specific still must complete successfully')
    local = _job_local_results(still_job, state, '.png')
    return packet, state, local, {
        'request_sha256': state['request_sha256'], 'design_sha256': design_digest(design),
        'result_sha256': file_digest(local), 'result_pixel_sha256': image_digest(local),
        'result_urls_sha256': mxapi.digest(state['result_urls']),
    }


def review_still(design_path, batch_path, character, action, still_job, report_path):
    design = load_bound_design(design_path, batch_path, character, action)
    _, state, _, inputs = _still_inputs(still_job, design)
    report = motion.read(report_path)
    if not isinstance(report, dict) or report.get('schema') != 1 or report.get('input_hashes') != inputs:
        raise ValueError('Still review must bind the exact current design, request and downloaded image')
    if report.get('observed_equipment_start_state') != design['equipment_policy']['start_state']:
        raise ValueError('Observed equipment state does not match the action design')
    checks = report.get('checks')
    if not isinstance(checks, dict):
        raise ValueError('Still review checks must be an object')
    for check in STILL_CHECKS:
        if checks.get(check) is not True:
            raise ValueError('Still visual check not passed: ' + check)
    _text(report.get('notes'), 'Concrete action-still visual observations')
    destination = Path(still_job).resolve() / 'still-review.json'
    if destination.exists():
        raise ValueError('Still was already reviewed; prepare a new job to revise it')
    motion.write(destination, report)
    state['workflow_review'] = {'sha256': file_digest(destination), 'input_hashes': inputs}
    mxapi.write_json(Path(still_job).resolve() / 'job.json', state)
    return {'state': 'reviewed', 'still_job': str(Path(still_job).resolve()), 'checks': STILL_CHECKS}


def still_review_template(design_path, batch_path, character, action, still_job, out):
    """Create a source-bound checklist; it is never an automatic visual pass."""
    design = load_bound_design(design_path, batch_path, character, action)
    _, _, _, inputs = _still_inputs(still_job, design)
    out = Path(out).resolve()
    if out.exists():
        raise ValueError('Still review template already exists')
    motion.write(out, {
        'schema': 1,
        'input_hashes': inputs,
        'observed_equipment_start_state': '',
        'checks': {check: False for check in STILL_CHECKS},
        'notes': '',
    })
    return {'report': str(out), 'state': 'needs_visual_review', 'checks': STILL_CHECKS}


def _reviewed_still(still_job, design):
    packet, state, _, inputs = _still_inputs(still_job, design)
    record = state.get('workflow_review')
    path = Path(still_job).resolve() / 'still-review.json'
    if not isinstance(record, dict) or not path.is_file() or record.get('sha256') != file_digest(path):
        raise ValueError('Action-specific still needs a current visual review before Veo preparation')
    report = motion.read(path)
    if record.get('input_hashes') != inputs or report.get('input_hashes') != inputs:
        raise ValueError('Action-still review no longer matches the current inputs')
    if report.get('observed_equipment_start_state') != design['equipment_policy']['start_state']:
        raise ValueError('Reviewed still has the wrong equipment start state')
    for check in STILL_CHECKS:
        if report.get('checks', {}).get(check) is not True:
            raise ValueError('Action-still review is incomplete: ' + check)
    return packet, state, inputs, record


def prepare_video(design_path, batch_path, character, action, still_job, job, *,
                  existing_image_job=None, source_risk_notes=None):
    design = load_bound_design(design_path, batch_path, character, action)
    if existing_image_job is not None:
        if still_job is not None:
            raise ValueError('Choose an existing image job or a reviewed still job, not both')
        source = identity_source(batch_path, character, existing_image_job, allow_action_still=True)
        notes = ('Existing image reused as supplied. Its weapon state and start pose may differ '
                 'from the action design; no action-specific still review was required or recorded.')
        if source_risk_notes is not None:
            notes = _text(source_risk_notes, 'Existing-image source risk notes')
        prompt = prompts(design)['video_prompt'].replace(
            'Animate the supplied reviewed action-specific start still as one continuous game-character action.',
            'Animate the supplied existing character image as one continuous game-character action. '
            'Use this image as provided; its initial weapon state or pose may differ from the authored action. '
            'Transition visibly into the requested action without changing character identity.')
        result = mxapi.prepare(Path(job), 'veo-3.1-fast', prompt, [source['url']], ratio='16:9')
        _stamp(job, design, 'action_video', source_mode='existing_image',
               identity_source=source, source_risk_notes=notes,
               identity_character_sha256=source['character_sha256'],
               identity_provider_origin=source.get('provider_origin'))
        return {**result, 'workflow': 'project_bound_veo_action', 'phase': 'action_video',
                'source_mode': 'existing_image', 'source_risk_notes': notes}
    still_packet, still_state, still_inputs, review = _reviewed_still(still_job, design)
    prompt = prompts(design)['video_prompt']
    result = mxapi.prepare(Path(job), 'veo-3.1-fast', prompt, still_state['result_urls'], ratio='16:9')
    _stamp(
        job, design, 'action_video',
        action_still_request_sha256=still_state['request_sha256'],
        action_still_result_sha256=still_inputs['result_sha256'],
        action_still_review_sha256=review['sha256'],
        identity_character_sha256=still_packet['workflow']['identity_source']['character_sha256'],
        identity_provider_origin=still_packet['workflow']['identity_source'].get('provider_origin'),
    )
    return {**result, 'workflow': 'project_bound_veo_action', 'phase': 'action_video'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    base = argparse.ArgumentParser(add_help=False)
    base.add_argument('--batch', required=True)
    base.add_argument('--character', required=True)
    base.add_argument('--action', required=True)
    scaffold_parser = commands.add_parser('scaffold', parents=[base])
    scaffold_parser.add_argument('--out', required=True)
    prompt_parser = commands.add_parser('prompts', parents=[base])
    prompt_parser.add_argument('--design', required=True)
    still = commands.add_parser('prepare-still', parents=[base])
    still.add_argument('--design', required=True)
    still.add_argument('--identity-job', required=True,
                       help='Verified upload-reference job for local original art, or a downloaded identity image job')
    still.add_argument('--job', required=True)
    review = commands.add_parser('review-still', parents=[base])
    review.add_argument('--design', required=True)
    review.add_argument('--still-job', required=True)
    review.add_argument('--report', required=True)
    review_template = commands.add_parser('still-review-template', parents=[base])
    review_template.add_argument('--design', required=True)
    review_template.add_argument('--still-job', required=True)
    review_template.add_argument('--out', required=True)
    video = commands.add_parser('prepare-video', parents=[base])
    video.add_argument('--design', required=True)
    image_source = video.add_mutually_exclusive_group(required=True)
    image_source.add_argument('--still-job')
    image_source.add_argument('--existing-image-job',
                              help='Reuse a verified upload or existing identity image job without generating or reviewing a new still')
    video.add_argument('--source-risk-notes', help='Record known weapon/start-pose conflicts without blocking direct image reuse')
    video.add_argument('--job', required=True)
    args = vars(parser.parse_args())
    command = args.pop('command')
    try:
        if command == 'scaffold':
            result = scaffold(args.pop('batch'), args.pop('character'), args.pop('action'), args.pop('out'))
        elif command == 'prompts':
            design = load_bound_design(args['design'], args['batch'], args['character'], args['action'])
            result = prompts(design)
        elif command == 'prepare-still':
            result = prepare_still(args.pop('design'), args.pop('batch'), args.pop('character'),
                                   args.pop('action'), args.pop('identity_job'), args.pop('job'))
        elif command == 'review-still':
            result = review_still(args.pop('design'), args.pop('batch'), args.pop('character'),
                                  args.pop('action'), args.pop('still_job'), args.pop('report'))
        elif command == 'still-review-template':
            result = still_review_template(args.pop('design'), args.pop('batch'), args.pop('character'),
                                           args.pop('action'), args.pop('still_job'), args.pop('out'))
        else:
            result = prepare_video(args.pop('design'), args.pop('batch'), args.pop('character'),
                                   args.pop('action'), args.pop('still_job'), args.pop('job'),
                                   existing_image_job=args.pop('existing_image_job'),
                                   source_risk_notes=args.pop('source_risk_notes'))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, mxapi.ProviderError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
