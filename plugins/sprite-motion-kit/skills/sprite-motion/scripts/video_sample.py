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


def _select_source_frames(video, ffmpeg, start, duration, count):
    """Inspect decoded timestamps before selecting unique frames in [start, end)."""
    begin, span = Fraction(str(start)), Fraction(str(duration))
    end = begin + span
    result = _run_ffmpeg([
        str(ffmpeg), '-hide_banner', '-nostdin', '-nostats', '-loglevel', 'info',
        '-i', str(video), '-map', '0:v:0', '-an', '-vf', 'showinfo=checksum=0',
        '-t', f'{float(end):.9f}', '-fps_mode', 'passthrough', '-f', 'null', '-'])
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
    candidates = [frame for frame in decoded if begin <= frame['time'] < end]
    if len(candidates) < count:
        raise ValueError(f'Interval contains {len(candidates)} source frames, expected at least {count}; no silent padding')
    times = [begin + i * span / count for i in range(count)]
    # Fraction comparisons keep exact midpoint ties deterministic (earlier frame).
    selected = [min(candidates, key=lambda frame: (abs(frame['time'] - t), frame['time'])) for t in times]
    if len({frame['index'] for frame in selected}) != count:
        raise ValueError('Uniform sampling would repeat source frames; choose fewer frames or a longer interval')
    dimensions = selected[0]['size']
    if any(frame['size'] != dimensions for frame in candidates):
        raise ValueError('Decoded frame dimensions changed')
    if dimensions[0] * dimensions[1] * count > 120_000_000:
        raise ValueError('Atlas too large; choose fewer frames or a smaller source video')
    return selected, [float(t) for t in times]


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


def _remove_background(image, mode, key_scope='edge-connected'):
    rgba = np.array(image.convert('RGBA'))
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
                 character_image=None, batch=None, batch_character=None):
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
    selected, sampling_times = _select_source_frames(video, ffmpeg, start, duration, count)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.video-sample-', dir=out.parent) as temporary:
        staging = Path(temporary) / 'sample'
        rawdir = staging / 'decoded'
        rawdir.mkdir(parents=True)
        # Select source indices directly; output synchronization must not invent
        # repeats. Both passes explicitly use the same first video stream.
        vf = 'select=' + '+'.join(f'eq(n\\,{frame["index"]})' for frame in selected)
        command = [str(ffmpeg), '-hide_banner', '-nostdin', '-loglevel', 'error',
                   '-i', str(video), '-map', '0:v:0', '-an', '-vf', vf,
                   '-fps_mode', 'passthrough', '-frames:v', str(count),
                   '-pix_fmt', 'rgba', '-start_number', '0', str(rawdir / 'frame-%03d.png')]
        _run_ffmpeg(command)
        paths = sorted(rawdir.glob('frame-*.png'))
        if len(paths) != count:
            raise ValueError(f'Interval yielded {len(paths)} frames, expected {count}; no silent padding')
        frames, bounds, dimensions = [], [], None
        for path in paths:
            with Image.open(path) as raw:
                if dimensions is None:
                    dimensions = raw.size
                if raw.size != dimensions:
                    raise ValueError('Decoded frame dimensions changed')
                clean = _remove_background(raw, background, key_scope)
            b = clean.getchannel('A').getbbox()
            if not b or b[0] == 0 or b[1] == 0 or b[2] == clean.width or b[3] == clean.height:
                raise ValueError('A video frame is empty or touches the canvas edge; retain the full character in source video')
            frames.append(clean)
            bounds.append(list(b))
        shutil.rmtree(rawdir)
        width, height = dimensions
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
        report = {'character': character, 'status': 'video_review_sample', 'clips': [clip],
                  'scope_mode': 'action_study', 'full_character_complete': False,
                  'coverage_binding': coverage_binding, 'character_reference': character_copy,
                  'character_sha256': character_hash,
                  'source_video_sha256': hashlib.sha256(video.read_bytes()).hexdigest(),
                  'source_video_name': video.name, 'source_video': source_copy,
                  'interval': [start, start + duration],
                  'sampling': 'Nearest unique source frame within [start, end) for each uniform target time; midpoint ties use the earlier frame; no optical flow or padding',
                  'background': background,
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
        template = template.replace('<a href="source-partitions.png" target="_blank" rel="noopener">原图与人物边界 ↗</a>', '')
        template = template.replace('<a href="source-transparent.png" target="_blank" rel="noopener">透明原图 ↗</a>', '')
        comparison = ('<details class="details"><summary>原始视频对照（保留背景）</summary>'
                      f'<video controls preload="metadata" playsinline src="{source_copy}" '
                      'style="display:block;max-width:100%;width:480px;margin-top:12px"></video>'
                      f'<a href="{source_copy}" target="_blank" rel="noopener">打开原始视频 ↗</a></details>')
        template = template.replace('  <footer>', '  ' + comparison + '\n  <footer>')
        (staging / 'index.html').write_text(template, encoding='utf-8')
        staging.rename(out)
    return {'preview': str(out / 'index.html'), 'status': 'video_review_sample', 'count': count,
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
    parser.add_argument('--origin', type=int, nargs=2, required=True)
    parser.add_argument('--character-image', help='Approved source appearance; bound batches supply this automatically')
    parser.add_argument('--batch', help='Existing project-discovery coverage batch')
    parser.add_argument('--batch-character', help='Character ID in that batch; action comes from --action')
    print(json.dumps(export_video(**vars(parser.parse_args())), ensure_ascii=False))
