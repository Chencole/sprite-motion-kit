"""Extract a reviewed video interval into sprite frames; never generates video.

Requires an existing FFmpeg executable. Keeps the full input canvas and source
order, samples time uniformly, and does not infer a complete gait from a loop.
"""
import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

SKILL = Path(__file__).resolve().parents[1]


def _run_ffmpeg(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180,
                                encoding='utf-8', errors='replace')
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('Video decoding failed: ' + str(exc)) from exc
    if result.returncode:
        raise ValueError('Video decoding failed: ' + result.stderr[-1000:])
    return result


def _select_source_frames(video, ffmpeg, start, duration, count, loop):
    """Inspect timestamps and select a loop half-open or one-shot closed interval."""
    begin, span = Fraction(str(start)), Fraction(str(duration))
    end = begin + span
    result = _run_ffmpeg([
        str(ffmpeg), '-hide_banner', '-nostdin', '-nostats', '-loglevel', 'info',
        '-i', str(video), '-map', '0:v:0', '-an', '-vf', 'showinfo=checksum=0',
        '-fps_mode', 'passthrough', '-f', 'null', '-'])
    time_base, decoded = None, []
    for line in result.stderr.splitlines():
        if 'showinfo' not in line:
            continue
        config = re.search(r'config in time_base:\s*(\d+/\d+)', line)
        if config:
            time_base = Fraction(config.group(1))
        frame = re.search(r'\bn:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:', line)
        size = re.search(r'\bs:(\d+)x(\d+)', line)
        if frame and time_base and size:
            frame_duration = re.search(r'\bduration:\s*(\d+)', line)
            decoded.append({'index': int(frame.group(1)),
                            'time': int(frame.group(2)) * time_base,
                            'duration': int(frame_duration.group(1)) * time_base if frame_duration else Fraction(0),
                            'size': (int(size.group(1)), int(size.group(2)))})
    if not decoded:
        raise ValueError('No decoded video timestamps; use FFmpeg with showinfo support')
    if any(b['time'] <= a['time'] for a, b in zip(decoded, decoded[1:])):
        raise ValueError('Source video timestamps must be strictly increasing')
    if decoded[0]['time'] > begin or decoded[-1]['time'] + decoded[-1]['duration'] < end:
        raise ValueError('Requested interval exceeds decoded video coverage; no silent padding')
    candidates = [frame for frame in decoded
                  if begin <= frame['time'] and (frame['time'] < end if loop else frame['time'] <= end)]
    if len(candidates) < count:
        raise ValueError(f'Interval contains {len(candidates)} source frames, expected at least {count}; no silent padding')
    divisor = count if loop else count - 1
    times = [begin + i * span / divisor for i in range(count)]
    # Fraction comparisons keep exact midpoint ties deterministic (earlier frame).
    selected = [min(candidates, key=lambda frame: (abs(frame['time'] - t), frame['time'])) for t in times]
    if len({frame['index'] for frame in selected}) != count:
        raise ValueError('Uniform sampling would repeat source frames; choose fewer frames or a longer interval')
    dimensions = selected[0]['size']
    if any(frame['size'] != dimensions for frame in candidates):
        raise ValueError('Decoded frame dimensions changed')
    if dimensions[0] * dimensions[1] * count > 120_000_000:
        raise ValueError('Atlas too large; choose fewer frames or a smaller source video')
    return selected, [float(t) for t in times], candidates


def _json_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _read_json(path, label):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError(label + ' is missing or invalid') from exc
    if not isinstance(value, dict):
        raise ValueError(label + ' must be an object')
    return value


def _local_result(job, state):
    results = state.get('local_results')
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], str):
        raise ValueError('Veo action job must have exactly one downloaded local result')
    result = Path(results[0])
    if not result.is_absolute():
        result = (job / result).resolve()
    else:
        result = result.resolve()
    if not result.is_file() or result.suffix.lower() != '.mp4':
        raise ValueError('Veo action job local result is missing or is not MP4 video')
    return result


def validate_generation_job(generation_job, video, expected_binding=None):
    """Bind an input video to one downloaded project-bound Veo action job."""
    if not isinstance(generation_job, (str, Path)):
        raise ValueError('Generation job path is required')
    job = Path(generation_job).resolve()
    if not job.is_dir():
        raise ValueError('Generation job directory does not exist')
    packet = _read_json(job / 'request.json', 'Generation request')
    state = _read_json(job / 'job.json', 'Generation job state')
    if _json_digest(packet) != state.get('request_sha256'):
        raise ValueError('Generation request changed after preparation')
    workflow = packet.get('workflow')
    if (packet.get('kind') != 'video' or packet.get('model') != 'veo-3.1-fast'
            or not isinstance(workflow, dict)
            or workflow.get('kind') != 'project_bound_veo_action'
            or workflow.get('phase') != 'action_video'):
        raise ValueError('Generation job is not a project-bound Veo action-video job')
    if (state.get('state') != 'succeeded' or not isinstance(state.get('result_urls'), list)
            or len(state['result_urls']) != 1 or not isinstance(state['result_urls'][0], str)):
        raise ValueError('Veo action job has not completed successfully')
    binding = workflow.get('coverage_binding')
    if not isinstance(binding, dict) or (expected_binding is not None and binding != expected_binding):
        raise ValueError('Veo action job has the wrong gameplay coverage binding')
    design = _read_json(job / 'action-design.json', 'Veo action design snapshot')
    design_sha = _json_digest(design)
    if (workflow.get('design_sha256') != design_sha or design.get('coverage_binding') != binding
            or design.get('character_id') != binding.get('character')
            or design.get('action_id') != binding.get('action')):
        raise ValueError('Veo action design changed or does not match its gameplay binding')
    if design.get('action_kind') not in ('loop', 'one_shot'):
        raise ValueError('Veo action design must specify loop or one_shot')
    if binding.get('motion_strategy') == 'body_actions_with_runtime_vfx':
        import batch as coverage_module
        coverage_module.validate_body_effects(design.get('effects'))
    result = _local_result(job, state)
    source_sha = hashlib.sha256(Path(video).read_bytes()).hexdigest()
    if hashlib.sha256(result.read_bytes()).hexdigest() != source_sha:
        raise ValueError('Input video is not the downloaded result of this Veo action job')
    framing = design.get('framing')
    if not isinstance(framing, dict):
        raise ValueError('Veo action design is missing its framing contract')
    safe_rect, clearance = framing.get('safe_rect'), framing.get('minimum_clearance_ratio')
    if (not isinstance(safe_rect, list) or len(safe_rect) != 4
            or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in safe_rect)
            or not 0 <= safe_rect[0] < safe_rect[2] <= 1
            or not 0 <= safe_rect[1] < safe_rect[3] <= 1
            or isinstance(clearance, bool) or not isinstance(clearance, (int, float))
            or not 0 <= clearance < .5):
        raise ValueError('Veo action design has an invalid safe rectangle or clearance')
    if (safe_rect[0] + clearance >= safe_rect[2] - clearance
            or safe_rect[1] + clearance >= safe_rect[3] - clearance):
        raise ValueError('Veo action design safe rectangle collapses after its required clearance')
    background_mode = design.get('background_mode')
    if background_mode not in ('green', 'magenta'):
        raise ValueError('Veo action design needs an explicit supported background_mode')
    source_mode = workflow.get('source_mode')
    if source_mode is not None and source_mode not in ('existing_image', 'reviewed_still'):
        raise ValueError('Unknown Veo image source mode')
    if source_mode == 'existing_image':
        source = workflow.get('identity_source')
        if (not isinstance(source, dict)
                or any(not isinstance(source.get(key), str) or not re.fullmatch(r'[0-9a-f]{64}', source[key])
                       for key in ('request_sha256', 'local_sha256', 'character_sha256', 'character_pixel_sha256'))
                or source.get('character_sha256') != workflow.get('identity_character_sha256')
                or not isinstance(packet.get('body'), dict)
                or packet['body'].get('images') != [source.get('url')]
                or not isinstance(workflow.get('source_risk_notes'), str)
                or not workflow['source_risk_notes'].strip()
                or any(key.startswith('action_still_review') for key in workflow)):
            raise ValueError('Existing-image Veo job has invalid source evidence or a fabricated still review')
    evidence = {
        'schema': 1, 'kind': workflow['kind'], 'phase': workflow['phase'],
        'job': str(job), 'model': packet['model'],
        'request_sha256': state['request_sha256'], 'design_sha256': design_sha,
        'coverage_binding': binding, 'source_video_sha256': source_sha,
        'safe_rect': [float(value) for value in safe_rect],
        'minimum_clearance_ratio': float(clearance),
        'background_mode': background_mode,
        'action_kind': design['action_kind'],
    }
    if source_mode is not None:
        evidence['source_mode'] = source_mode
    if source_mode == 'existing_image':
        evidence['identity_character_sha256'] = workflow['identity_character_sha256']
        evidence['source_risk_notes'] = workflow['source_risk_notes']
    return evidence, design


def _decode_frames(video, ffmpeg, frames, destination, *, prefix='frame'):
    indices = [frame['index'] for frame in frames]
    if not indices:
        raise ValueError('No source frames selected')
    if indices == list(range(indices[0], indices[-1] + 1)):
        select = f'between(n\\,{indices[0]}\\,{indices[-1]})'
    else:
        select = '+'.join(f'eq(n\\,{index})' for index in indices)
    command = [str(ffmpeg), '-hide_banner', '-nostdin', '-loglevel', 'error',
               '-i', str(video), '-map', '0:v:0', '-an', '-vf', 'select=' + select,
               '-fps_mode', 'passthrough', '-frames:v', str(len(indices)),
               '-pix_fmt', 'rgba', '-start_number', '0', str(destination / f'{prefix}-%05d.png')]
    _run_ffmpeg(command)
    paths = sorted(destination.glob(f'{prefix}-*.png'))
    if len(paths) != len(indices):
        raise ValueError(f'Video decode yielded {len(paths)} frames, expected {len(indices)}')
    return paths


def _check_workflow_interval(paths, source_frames, dimensions, *, background, key_scope,
                             black_sidebars, safe_rect, clearance, sampled_indices,
                             sidebar_black_threshold=24):
    if not source_frames or len(paths) != len(source_frames):
        raise ValueError('Full-interval inspection requires every source frame')
    width, height = dimensions
    allowed = [safe_rect[0] + clearance, safe_rect[1] + clearance,
               safe_rect[2] - clearance, safe_rect[3] - clearance]
    minimum = [1.0, 1.0, 1.0, 1.0]
    failures = []
    for path, source in zip(paths, source_frames):
        with Image.open(path) as raw:
            if raw.size != dimensions:
                raise ValueError('Decoded frame dimensions changed during full-interval review')
            clean = _remove_background(raw, background, key_scope, black_sidebars, sidebar_black_threshold)
        bounds = clean.getchannel('A').getbbox()
        if not bounds:
            failures.append(source['index'])
            continue
        normalized = [bounds[0] / width, bounds[1] / height,
                      bounds[2] / width, bounds[3] / height]
        margins = [normalized[0], normalized[1], 1 - normalized[2], 1 - normalized[3]]
        minimum = [min(before, value) for before, value in zip(minimum, margins)]
        if (normalized[0] < allowed[0] - 1e-12 or normalized[1] < allowed[1] - 1e-12
                or normalized[2] > allowed[2] + 1e-12 or normalized[3] > allowed[3] + 1e-12):
            failures.append(source['index'])
    if failures:
        preview = ', '.join(str(value) for value in failures[:8])
        raise ValueError('Veo action leaves its designed safe frame or clearance at source frame(s): ' + preview)
    indices = [frame['index'] for frame in source_frames]
    return {
        'checked_all_interval_frames': True,
        'source_frame_count': len(indices),
        'source_frame_indices': indices,
        'included_unsampled_frames': bool(set(indices) - set(sampled_indices)),
        'safe_rect': list(safe_rect), 'minimum_clearance_ratio': clearance,
        'minimum_observed_canvas_clearance': minimum,
        'all_foreground_inside_contract': True,
    }


def _edge_connected(mask):
    """Flood row spans instead of pixels; retain enclosed costume key colors."""
    height, width = mask.shape
    visited = np.zeros_like(mask)
    seeds = [(0, x) for x in np.flatnonzero(mask[0])]
    seeds += [(height - 1, x) for x in np.flatnonzero(mask[-1])]
    seeds += [(y, 0) for y in np.flatnonzero(mask[:, 0])]
    seeds += [(y, width - 1) for y in np.flatnonzero(mask[:, -1])]
    while seeds:
        y, x = seeds.pop()
        if visited[y, x] or not mask[y, x]:
            continue
        left_stops = np.flatnonzero(~mask[y, :x])
        right_stops = np.flatnonzero(~mask[y, x:])
        left = int(left_stops[-1]) + 1 if len(left_stops) else 0
        right = x + int(right_stops[0]) if len(right_stops) else width
        visited[y, left:right] = True
        for adjacent in (y - 1, y + 1):
            if 0 <= adjacent < height:
                available = mask[adjacent, left:right] & ~visited[adjacent, left:right]
                starts = np.flatnonzero(available & ~np.concatenate(([False], available[:-1])))
                seeds.extend((adjacent, left + int(offset)) for offset in starts)
    return visited


def _remove_background(image, mode, key_scope='edge-connected', black_sidebars=None,
                       sidebar_black_threshold=24):
    if type(sidebar_black_threshold) is not int or not 0 <= sidebar_black_threshold <= 64:
        raise ValueError('Sidebar black threshold must be an integer between 0 and 64')
    if black_sidebars is None and sidebar_black_threshold != 24:
        raise ValueError('A custom sidebar black threshold requires explicit black sidebars')
    rgba = np.array(image.convert('RGBA'))
    if black_sidebars is not None:
        if (len(black_sidebars) != 2 or any(type(v) is not int or v < 0 for v in black_sidebars)
                or sum(black_sidebars) <= 0 or sum(black_sidebars) >= image.width or mode == 'alpha'):
            raise ValueError('Black sidebars require two fixed widths leaving a keyed center region')
        left, right = black_sidebars
        region = np.zeros(rgba.shape[:2], dtype=bool)
        region[:, :left] = True
        if right:
            region[:, -right:] = True
        # Only inspected fixed sidebars, never dark armor in the center. Keep
        # nonblack foreground extending into the bars on the original canvas.
        near_black = (rgba[:, :, :3].max(axis=2) <= sidebar_black_threshold) & region
        rgba[_edge_connected(near_black)] = 0
    if mode != 'alpha':
        rgb = rgba[:, :, :3].astype(np.int16)
        # Fixed thresholds for the whole clip: no per-frame fitting, erosion or
        # despill that can eat costume colors or cause a changing silhouette.
        if mode == 'green':
            candidate = (rgb[:, :, 1] >= 150) & (rgb[:, :, 1] - np.maximum(rgb[:, :, 0], rgb[:, :, 2]) >= 80)
        else:
            minimum = np.minimum(rgb[:, :, 0], rgb[:, :, 2])
            candidate = (minimum >= 150) & (minimum - rgb[:, :, 1] >= 80)
        mask = _edge_connected(candidate) if key_scope == 'edge-connected' else candidate
        if float(mask.mean()) < .01:
            raise ValueError(f'No usable edge-connected {mode} background')
        rgba[mask] = 0
    if int(rgba[:, :, 3].min()) == 255:
        raise ValueError('Image is fully opaque; provide alpha or a supported keyed background')
    edge = np.concatenate([rgba[0, :, 3], rgba[-1, :, 3], rgba[:, 0, 3], rgba[:, -1, 3]])
    if float((edge <= 8).mean()) < .98:
        raise ValueError('Video background is not transparent around its perimeter')
    rgba[rgba[:, :, 3] == 0] = 0
    return Image.fromarray(rgba)


def export_video(video, ffmpeg, out, *, character, action, start, duration, count,
                 loop, background, origin, review_notes, key_scope='edge-connected',
                 character_image=None, batch=None, batch_character=None,
                 black_sidebars=None, draft=False, generation_job=None,
                 sidebar_black_threshold=24):
    video, ffmpeg, out = Path(video).resolve(), Path(ffmpeg).resolve(), Path(out).resolve()
    if not video.is_file() or not ffmpeg.is_file():
        raise ValueError('Provide an existing video and FFmpeg executable')
    if out.exists():
        raise ValueError('Use a new output directory; existing samples are preserved')
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', action):
        raise ValueError('Invalid action name')
    if any(not math.isfinite(v) for v in (start, duration)) or start < 0 or duration <= 0 or duration > 60:
        raise ValueError('Choose a finite interval between zero and sixty seconds')
    if type(count) is not int or not 2 <= count <= 120 or type(loop) is not bool:
        raise ValueError('Invalid frame count or loop contract')
    if background not in ('magenta', 'green', 'alpha') or not str(review_notes).strip():
        raise ValueError('Choose explicit alpha/key extraction and describe the inspected interval')
    if key_scope not in ('edge-connected', 'all'):
        raise ValueError('Key scope must be edge-connected or all')
    if type(draft) is not bool:
        raise ValueError('Draft must be an explicit boolean')
    if type(sidebar_black_threshold) is not int or not 0 <= sidebar_black_threshold <= 64:
        raise ValueError('Sidebar black threshold must be an integer between 0 and 64')
    if black_sidebars is None and sidebar_black_threshold != 24:
        raise ValueError('A custom sidebar black threshold requires explicit black sidebars')
    if black_sidebars is not None and (len(black_sidebars) != 2 or any(type(v) is not int or v < 0 for v in black_sidebars)):
        raise ValueError('Black sidebars require two fixed nonnegative widths')
    if background == 'alpha' and key_scope != 'edge-connected':
        raise ValueError('Key scope only applies to a keyed background')
    if len(origin) != 2 or any(type(v) is not int or v < 0 for v in origin):
        raise ValueError('Origin must contain two nonnegative input-canvas coordinates')
    coverage_binding = None
    if bool(batch) != bool(batch_character):
        raise ValueError('Provide both batch and batch-character to bind a gameplay requirement')
    if batch:
        import batch as coverage_module
        coverage_binding = coverage_module.binding(batch, batch_character, action)
        entry = coverage_module.load(batch)[2]['characters'][batch_character]
        character_image = Path(character_image or entry['character']).resolve()
        if coverage_module.digest(character_image) != entry['character_sha256']:
            raise ValueError('Character reference differs from the coverage batch')
    generation_evidence, action_design = None, None
    if generation_job:
        if not coverage_binding:
            raise ValueError('A project-bound Veo generation job requires batch and batch-character')
        generation_evidence, action_design = validate_generation_job(
            generation_job, video, coverage_binding)
        if background != generation_evidence['background_mode']:
            raise ValueError('Background extraction mode differs from the Veo action design')
        if loop != (action_design['action_kind'] == 'loop'):
            raise ValueError('Extraction loop flag differs from the Veo action design')
    if character_image:
        character_image = Path(character_image).resolve()
        if not character_image.is_file():
            raise ValueError('Provide an existing character reference image')
        try:
            with Image.open(character_image) as appearance:
                if getattr(appearance, 'n_frames', 1) != 1:
                    raise ValueError('Character reference must be one still image')
                appearance.verify()
        except OSError as exc:
            raise ValueError('Character reference is not a readable image') from exc
    selected, sampling_times, interval_frames = _select_source_frames(
        video, ffmpeg, start, duration, count, loop)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.video-sample-', dir=out.parent) as temporary:
        staging = Path(temporary) / 'sample'
        rawdir = staging / 'decoded'
        rawdir.mkdir(parents=True)
        # Select source indices directly; output synchronization must not invent
        # repeats. Both passes explicitly use the same first video stream.
        paths = _decode_frames(video, ffmpeg, selected, rawdir)
        frames, bounds, dimensions, edge_frames = [], [], None, []
        for path in paths:
            with Image.open(path) as raw:
                if dimensions is None:
                    dimensions = raw.size
                if raw.size != dimensions:
                    raise ValueError('Decoded frame dimensions changed')
                clean = _remove_background(raw, background, key_scope, black_sidebars, sidebar_black_threshold)
            b = clean.getchannel('A').getbbox()
            touches_edge = b and (b[0] == 0 or b[1] == 0 or b[2] == clean.width or b[3] == clean.height)
            if not b or (touches_edge and not draft):
                raise ValueError('A video frame is empty or touches the canvas edge; retain the full character in source video')
            if touches_edge:
                edge_frames.append(selected[len(frames)]['index'])
            frames.append(clean)
            bounds.append(list(b))
        width, height = dimensions
        interval_review = None
        if generation_evidence:
            inspection = staging / 'full-interval'
            inspection.mkdir()
            inspection_paths = _decode_frames(video, ffmpeg, interval_frames, inspection, prefix='source')
            framing = action_design['framing']
            interval_review = _check_workflow_interval(
                inspection_paths, interval_frames, dimensions, background=background,
                key_scope=key_scope, black_sidebars=black_sidebars,
                safe_rect=framing['safe_rect'], clearance=framing['minimum_clearance_ratio'],
                sampled_indices=[frame['index'] for frame in selected],
                sidebar_black_threshold=sidebar_black_threshold)
            shutil.rmtree(inspection)
        shutil.rmtree(rawdir)
        if origin[0] >= width or origin[1] >= height:
            raise ValueError('Origin is outside video canvas')
        if width * height * count > 120_000_000:
            raise ValueError('Atlas too large; choose fewer frames or a smaller source video')
        folder = staging / action
        folder.mkdir()
        atlas = Image.new('RGBA', (width * count, height))
        contact = Image.new('RGB', (width * min(4, count), (height + 24) * math.ceil(count / 4)), '#1d2934')
        for i, frame in enumerate(frames):
            frame.save(folder / f'frame-{i:03}.png')
            atlas.alpha_composite(frame, (i * width, 0))
            contact.paste(frame, ((i % 4) * width, (i // 4) * (height + 24)), frame)
            ImageDraw.Draw(contact).text(((i % 4) * width + 8, (i // 4) * (height + 24) + height), str(i + 1), fill='white')
        atlas.save(folder / 'atlas.png')
        contact.save(folder / 'contact.png')
        extension = video.suffix.lower()
        if not re.fullmatch(r'\.[a-z0-9]{1,8}', extension):
            extension = '.video'
        source_copy = 'source-video' + extension
        shutil.copyfile(video, staging / source_copy)
        character_copy, character_hash = None, None
        if character_image:
            extension = character_image.suffix.lower()
            character_copy = 'character-reference' + (extension if re.fullmatch(r'\.[a-z0-9]{1,8}', extension) else '.image')
            shutil.copyfile(character_image, staging / character_copy)
            character_hash = hashlib.sha256((staging / character_copy).read_bytes()).hexdigest()
        clip = {'name': action, 'count': count, 'seconds': duration, 'loop': loop,
                'tile': [width, height], 'origin': list(origin),
                'frames': [f'{action}/frame-{i:03}.png' for i in range(count)],
                'sampling_times_seconds': sampling_times,
                'source_frame_indices': [frame['index'] for frame in selected],
                'source_times_seconds': [float(frame['time']) for frame in selected],
                'bounds': bounds, 'accepted_by_user': False}
        sample_status = 'video_draft_sample' if draft else 'video_review_sample'
        report = {'character': character, 'status': sample_status, 'clips': [clip],
                  'draft': draft, 'source_edge_frames': edge_frames,
                  'scope_mode': 'action_study', 'full_character_complete': False,
                  'coverage_binding': coverage_binding, 'character_reference': character_copy,
                  'character_sha256': character_hash,
                  'source_video_sha256': hashlib.sha256(video.read_bytes()).hexdigest(),
                  'source_video_name': video.name, 'source_video': source_copy,
                  'generation_job': generation_evidence,
                  'generation_interval_review': interval_review,
                  'interval': [start, start + duration],
                  'sampling': ('Nearest unique source frame within [start, end) for each uniform target time; '
                               'loop endpoint excluded; midpoint ties use the earlier frame; no optical flow or padding'
                               if loop else
                               'Nearest unique source frame within [start, end] including the true one-shot endpoint; '
                               'midpoint ties use the earlier frame; no optical flow or padding'),
                  'background': background,
                  'black_sidebars': list(black_sidebars) if black_sidebars is not None else None,
                  'sidebar_black_threshold': sidebar_black_threshold if black_sidebars is not None else None,
                  'sidebar_processing': 'Remove edge-connected near-black pixels only inside fixed left/right sidebar widths; preserve canvas and nonblack extensions' if black_sidebars is not None else None,
                  'key_scope': key_scope if background != 'alpha' else None,
                  'background_removal': 'preserved source alpha' if background == 'alpha' else f'fixed chroma thresholds, {key_scope} key pixels; no per-frame erosion or despill',
                  'pose_correspondence_verified': False, 'game_assets_replaced': False,
                  'notes': [str(review_notes), '视频抽帧单动作样例；整段统一画布，未自动贴地、补帧或修改动作。尚需审核角色一致性、完整步态和首尾衔接。']}
        (staging / 'sample.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        template = (SKILL / 'assets/sheet-sample-review.html').read_text(encoding='utf-8')
        template = template.replace('角色动作小样 · 五动作小样', '视频抽帧 · 单动作试样')
        template = template.replace('正在加载五种动作。', '正在加载视频抽帧。')
        template = template.replace('CHARACTER SAMPLE 02 / MOTION STUDY', 'VIDEO SAMPLE / ONE ACTION REVIEW')
        template = template.replace('完整图集 · 透明帧 · 连续播放', '视频抽帧 · 透明帧 · 单动作对照')
        template = template.replace('data.character+" · 动作小样"', 'data.character+" · 视频抽帧单动作试样"')
        template = template.replace('整张图集导出的独立小样。', '连续视频抽帧样例。')
        if draft:
            template = template.replace('视频抽帧 · 透明帧 · 单动作对照', '诊断草稿 · 原片可能缺损 · 不可作为合格素材')
        template = template.replace('<a href="source-partitions.png" target="_blank" rel="noopener">原图与人物边界 ↗</a>', '')
        template = template.replace('<a href="source-transparent.png" target="_blank" rel="noopener">透明原图 ↗</a>', '')
        comparison = ('<details class="details"><summary>原始视频对照（保留背景）</summary>'
                      f'<video controls preload="metadata" playsinline src="{source_copy}" '
                      'style="display:block;max-width:100%;width:480px;margin-top:12px"></video>'
                      f'<a href="{source_copy}" target="_blank" rel="noopener">打开原始视频 ↗</a></details>')
        template = template.replace('  <footer>', '  ' + comparison + '\n  <footer>')
        (staging / 'index.html').write_text(template, encoding='utf-8')
        staging.rename(out)
    return {'preview': str(out / 'index.html'), 'status': sample_status, 'count': count,
            'scope_mode': 'action_study', 'full_character_complete': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('video', 'ffmpeg', 'out', 'character', 'action', 'review-notes'):
        parser.add_argument('--' + arg, required=True)
    parser.add_argument('--start', type=float, required=True)
    parser.add_argument('--duration', type=float, required=True)
    parser.add_argument('--count', type=int, default=8)
    parser.add_argument('--loop', action='store_true')
    parser.add_argument('--background', choices=['alpha', 'magenta', 'green'], required=True)
    parser.add_argument('--key-scope', choices=['edge-connected', 'all'], default='edge-connected',
                        help='Use all only after checking that the character has no key color; also removes enclosed background gaps')
    parser.add_argument('--black-sidebars', type=int, nargs=2, metavar=('LEFT', 'RIGHT'),
                        help='Explicit fixed black pillarbox widths; remove edge-connected black there without cropping the canvas')
    parser.add_argument('--draft', action='store_true',
                        help='Allow source-edge clipping for diagnostic viewing only; the output cannot pass batch acceptance')
    parser.add_argument('--sidebar-black-threshold', type=int, default=24,
                        help='Explicit sidebar-only near-black RGB maximum, 0-64 (default 24); requires --black-sidebars when changed')
    parser.add_argument('--origin', type=int, nargs=2, required=True)
    parser.add_argument('--character-image', help='Approved source appearance; bound batches supply this automatically')
    parser.add_argument('--batch', help='Existing project-discovery coverage batch')
    parser.add_argument('--batch-character', help='Character ID in that batch; action comes from --action')
    parser.add_argument('--generation-job', help='Downloaded project-bound Veo action-video job that produced --video')
    print(json.dumps(export_video(**vars(parser.parse_args())), ensure_ascii=False))
