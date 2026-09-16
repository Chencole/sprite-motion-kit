"""Explicit MXAPI image/video jobs. No credentials on disk, no submit retries."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

from provider_credentials import load_mxapi_credentials, ProviderCredentialError


MODELS = {
    "gpt-image-2": {"kind": "image", "submit": "/api/v2/gpt-image-2", "poll": "/api/v2/gpt-image/task", "sizes": ["1K", "2K", "4K"], "refs": 8},
    "seedream-4.5": {"kind": "image", "submit": "/api/v2/draw-4-5", "poll": "/api/v2/draw/task", "sizes": ["2K", "4K"], "refs": 8, "code": "doubao-seedream-4-5-251128"},
    "seedream-5.0": {"kind": "image", "submit": "/api/v2/draw-5-0", "poll": "/api/v2/draw/task", "sizes": ["2K", "3K"], "refs": 8, "code": "doubao-seedream-5-0-260128"},
    "nano2": {"kind": "image", "submit": "/api/v2/nano2", "poll": "/api/v2/nano/task", "sizes": ["1K", "2K", "4K"], "refs": 8},
    "seedance-2.0": {"kind": "video", "submit": "/api/v2/video/seedance2", "poll": "/api/v2/video/task", "sizes": ["480p", "720p", "1080p"], "refs": 9, "duration": [4, 15]},
    # This fixed route selects doubao-seedance-2-0-fast-260128; omit model.
    # A single image anchors the first frame unless reference mode is explicit.
    "seedance-2.0-fast": {"kind": "video", "submit": "/api/v2/video/seedance2-fast", "poll": "/api/v2/video/task", "sizes": ["480p", "720p"], "refs": 9, "duration": [4, 15], "reference_roles": ["first_frame", "reference_image"]},
    # MXAPI /api/docs?id=v2-video-seedance2-mini fixes the upstream model to
    # doubao-seedance-2-0-mini-260615. Two references is this adapter's supported
    # subset, not an inferred upstream limit or a copy of Fast's capabilities.
    "seedance-2.0-mini": {"kind": "video", "submit": "/api/v2/video/seedance2-mini", "poll": "/api/v2/video/task", "sizes": ["480p", "720p"], "refs": 2, "duration": [4, 15], "endpoints": True, "reference_roles": ["first_frame", "reference_image"], "ratios": ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"]},
    "seedance-1.0-fast": {"kind": "video", "submit": "/api/v2/video/generate", "poll": "/api/v2/video/task", "sizes": ["480p", "720p", "1080p"], "refs": 1, "duration": [2, 12], "code": "doubao-seedance-1-0-pro-fast-251015"},
    "seedance-1.0-lite-i2v": {"kind": "video", "submit": "/api/v2/video/generate", "poll": "/api/v2/video/task", "sizes": ["480p", "720p", "1080p"], "refs": 2, "duration": [2, 12], "code": "doubao-seedance-1-0-lite-i2v-250428", "endpoints": True, "i2v_only": True},
    # Veo's documented API exposes neither resolution nor duration controls.
    "veo-3.1-fast": {"kind": "video", "submit": "/api/v2/veo/generate", "poll": "/api/v2/veo/task", "sizes": [], "refs": 2, "duration": None, "code": "veo31-fast", "endpoints": True, "ratios": ["16:9", "9:16"], "default_ratio": "16:9"},
}
RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"}


class ProviderError(ValueError):
    pass


def write_json(path: Path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def reference_image(source: str):
    if source.startswith("https://"):
        parsed = urllib.parse.urlsplit(source)
        if parsed.username or parsed.password or not parsed.hostname or parsed.fragment:
            raise ProviderError("Invalid reference URL")
        return source
    # MyPixelFlow's verified transport publishes local/inline art before passing
    # it to MXAPI. Do not invent base64 support or silently omit the reference.
    raise ProviderError("Reference requires a provider-reachable HTTPS image URL; use the image job result URL or explicitly publish the local image with your existing media service")


def build_payload(model, prompt, references=(), *, resolution=None, ratio=None, duration=None, first_last=False, reference_role=None):
    if model not in MODELS:
        raise ProviderError("Unknown model; run models to see supported adapters")
    spec = MODELS[model]
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 10000:
        raise ProviderError("Prompt must contain 1–10000 characters")
    ratio = spec.get("default_ratio", "1:1") if ratio is None else ratio
    if ratio not in spec.get("ratios", RATIOS):
        raise ProviderError("Unsupported aspect ratio")
    if reference_role is not None:
        if reference_role not in spec.get("reference_roles", []):
            raise ProviderError("This model adapter does not support the selected reference role")
        if first_last or not references or (reference_role == "first_frame" and len(references) != 1):
            raise ProviderError("Reference role requires matching images and cannot be combined with first/last mode")
    if model in {"seedance-2.0-mini", "seedance-2.0-fast"} and re.search(r"(?:^|\s)--(?:dur|rs|ratio)(?:\s|=|$)", prompt):
        raise ProviderError("Seedance 2.0 Mini/Fast use top-level duration, resolution and ratio; legacy inline parameters are unsupported")
    if len(references) > spec["refs"]:
        raise ProviderError("Too many reference images; none may be silently dropped")
    if model == "seedance-2.0-fast" and len(references) > 1 and reference_role != "reference_image":
        raise ProviderError("Multiple Fast images require explicit reference_image mode; first_frame accepts one image")
    if first_last and (not spec.get("endpoints") or len(references) != 2):
        raise ProviderError("First/last-frame mode requires a documented endpoint adapter and exactly two images")
    if model == "veo-3.1-fast":
        if resolution is not None or duration is not None:
            raise ProviderError("Veo does not document resolution or duration controls; omit both options")
        if len(references) == 2 and not first_last:
            raise ProviderError("Two Veo images require explicit first/last-frame mode")
        return {"model": spec["code"], "prompt": prompt.strip(), "aspectRatio": ratio,
                "images": list(references), "enableExtendImg": False, "enableTranslation": False}
    resolution = resolution or spec["sizes"][0]
    if resolution not in spec["sizes"]:
        raise ProviderError("Unsupported model resolution")
    if spec["kind"] == "image":
        if first_last:
            raise ProviderError("Image jobs do not have video endpoints")
        body = {"prompt": prompt.strip(), "reference_images": list(references)}
        if model == "gpt-image-2":
            body.update(aspect_ratio=ratio, quality="auto", resolution=resolution)
        elif model == "nano2":
            body.update(aspect_ratio=ratio, image_size=resolution)
        else:
            body.update(prompt=f"{prompt.strip()}\nImage aspect ratio: {ratio}.", size=resolution, model=spec["code"])
            if model == "seedream-5.0":
                body.update(output_format="png", web_search=False)
        return body
    duration = spec['duration'][0] if duration is None else duration
    if isinstance(duration, bool) or not isinstance(duration, int) or not spec["duration"][0] <= duration <= spec["duration"][1]:
        raise ProviderError("Duration is outside this model's supported range")
    if ratio in {"3:2", "2:3"} or (model.startswith("seedance-1") and ratio == "21:9"):
        raise ProviderError("Unsupported video aspect ratio")
    if spec.get("i2v_only") and not references:
        raise ProviderError("I2V requires a character image")
    if spec.get("endpoints") and len(references) == 2 and not first_last and reference_role != "reference_image":
        raise ProviderError("Two endpoint images require explicit first/last mode or a supported reference_image role")
    content = []
    text = prompt.strip()
    if model.startswith("seedance-1"):
        text += f" --ratio {'adaptive' if references else ratio} --rs {resolution} --dur {duration}"
    content.append({"type": "text", "text": text})
    for index, ref in enumerate(references):
        role = ("first_frame" if index == 0 else "last_frame") if first_last else (reference_role or ("first_frame" if model.startswith("seedance-1") or model in {"seedance-2.0-mini", "seedance-2.0-fast"} else "reference_image"))
        content.append({"type": "image_url", "image_url": {"url": ref}, "role": role})
    if model.startswith("seedance-1"):
        return {"model": spec["code"], "content": content}
    if model in {"seedance-2.0-mini", "seedance-2.0-fast"}:
        return {"content": content, "ratio": ratio, "resolution": resolution, "duration": duration, "generate_audio": False}
    return {"content": content, "ratio": ratio, "resolution": resolution, "duration": duration, "generate_audio": False, "watermark": False, "tools": []}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError("API redirect refused; verify configured provider URL")


class Client:
    def __init__(self, credentials, timeout=55):
        self.credentials = credentials
        self.timeout = timeout

    def request(self, path, *, body=None, query=None, multipart=None):
        if not path.startswith("/api/v2/") or ".." in path or "?" in path:
            raise ProviderError("Unsupported provider path")
        url = self.credentials.base_url.rstrip("/") + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = self.credentials.headers()
        data = None if body is None else json.dumps(body).encode("utf-8")
        if multipart is not None:
            if body is not None or path != '/api/v2/upload/temp-image':
                raise ProviderError('Multipart is only supported for reference image upload')
            data, content_type = multipart
            headers = {key: value for key, value in headers.items()
                       if key.lower() not in {'content-type', 'content-length'}}
            headers['Content-Type'] = content_type
        req = urllib.request.Request(url, data=data, headers=headers, method="GET" if data is None else "POST")
        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=self.timeout) as response:
                raw = response.read(24 * 1024 * 1024 + 1)
                if len(raw) > 24 * 1024 * 1024:
                    raise ProviderError("Provider JSON response is too large")
                payload = json.loads(raw)
        except urllib.error.HTTPError as exc:
            # Provider errors may echo inputs, headers or signed URLs; never print them.
            raise ProviderError(f"Provider returned HTTP {exc.code}; request was not retried") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError("Provider connection/response failed; request was not retried") from None
        if not isinstance(payload, dict) or payload.get("success") is False or ("code" in payload and str(payload["code"]) not in {"0", "200"}):
            raise ProviderError("Provider rejected the request; request was not retried")
        return payload

    def check(self):
        data = unwrap(self.request("/api/v2/points/balance"))
        try:
            balance = float(data["remaining_points"])
            if not math.isfinite(balance):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ProviderError("Balance response is missing remaining_points") from None
        return {"connected": True, "remaining_points": balance, "generation_submitted": False, "source": self.credentials.source}


def unwrap(value):
    value = value.get("data", value) if isinstance(value, dict) else value
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def task_id(payload):
    data = unwrap(payload)
    for key in ("task_ids", "taskIds"):
        values = data.get(key)
        if isinstance(values, list):
            for value in values:
                if value is not None and str(value).strip():
                    return str(value).strip()
    for record in (data, unwrap(data.get("task", {})), unwrap(data.get("result", {}))):
        for key in ("task_id", "taskId", "id"):
            if record.get(key) is not None and str(record[key]).strip():
                return str(record[key]).strip()
    return None


def result_urls(payload):
    urls = []
    def visit(value, depth=0):
        if depth > 8:
            return
        if isinstance(value, str):
            if value.startswith(("https://", "data:image/", "data:video/")):
                urls.append(value)
            elif value.startswith(("{", "[")):
                try:
                    visit(json.loads(value), depth + 1)
                except ValueError:
                    pass
        elif isinstance(value, list):
            for item in value:
                visit(item, depth + 1)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key in {"content", "prompt", "reference_images", "reference_image", "input", "request"}:
                    continue
                if key == "b64_json" and isinstance(item, str):
                    urls.append("data:image/png;base64," + item)
                elif re.fullmatch(r"(?:data|result|results|output|outputs|files?|media|images?|videos?|(?:image|video|media|file)_urls?|urls?)", key):
                    visit(item, depth + 1)
    visit(payload)
    return list(dict.fromkeys(urls))


def status_of(payload):
    statuses = []
    def visit(value, depth=0):
        if depth > 8:
            return
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                return
        if isinstance(value, list):
            for item in value:
                visit(item, depth + 1)
            return
        if not isinstance(value, dict):
            return
        for key, val in value.items():
            if key in {"status", "state", "task_status", "taskStatus"}:
                statuses.append(str(val).lower())
            elif key in {"data", "result", "results", "output", "outputs", "task", "job"}:
                visit(val, depth + 1)
    visit(payload)
    # An explicit failure wins, even if the response contains a preview URL.
    if any(s in {"4", "failed", "fail", "failure", "cancelled", "canceled", "error"} for s in statuses):
        return "failed"
    if any(s in {"3", "completed", "succeeded", "success", "complete", "finished", "done", "ok"} for s in statuses):
        return "succeeded"
    return "succeeded" if result_urls(payload) else "submitted"


def prepare(job: Path, model, prompt, references=(), **options):
    refs = [reference_image(str(ref)) for ref in references]
    payload = build_payload(model, prompt, refs, **options)
    job.mkdir(parents=True, exist_ok=False)
    packet = {"schema_version": 1, "model": model, "body": payload, "options": options,
              "reference_count": len(refs), "kind": MODELS[model]["kind"]}
    write_json(job / "request.json", packet)
    write_json(job / "job.json", {"schema_version": 1, "state": "prepared", "request_sha256": digest(packet)})
    return {"state": "prepared", "job": str(job), "model": model, "reference_count": len(refs), "generation_submitted": False}


def read_job(job):
    packet = json.loads((job / "request.json").read_text(encoding="utf-8"))
    state = json.loads((job / "job.json").read_text(encoding="utf-8"))
    if packet.get("model") not in MODELS or digest(packet) != state.get("request_sha256"):
        raise ProviderError("Prepared request changed; create a new job")
    return packet, state


def submit(job: Path, client):
    # Exclusive marker survives crashes/timeouts: a POST is never repeated by rerun.
    packet, state = read_job(job)
    workflow = packet.get('workflow')
    if isinstance(workflow, dict):
        source = workflow.get('identity_source')
        origin = (source.get('provider_origin') if isinstance(source, dict) else None)
        origin = origin or workflow.get('identity_provider_origin')
        if origin:
            same_origin_reference(client.credentials.base_url, origin)
    if state["state"] != "prepared":
        raise ProviderError("Job has already been submitted or needs reconciliation; no repeat submit")
    try:
        with (job / "submit.lock").open("x") as lock:
            lock.write("One generation submission attempted. Do not delete to retry.")
    except FileExistsError:
        raise ProviderError("Submission already attempted; reconcile the existing job") from None
    state.update(state="submission_unknown", provider_url=client.credentials.base_url, credential_source=client.credentials.source)
    write_json(job / "job.json", state)
    payload = client.request(MODELS[packet["model"]]["submit"], body=packet["body"])
    state.update(state=status_of(payload), external_job_id=task_id(payload), result_urls=result_urls(payload))
    if state["state"] != "failed" and not state["external_job_id"] and state["result_urls"]:
        state["state"] = "succeeded"
    if state["state"] == "submitted" and not state["external_job_id"]:
        state["state"] = "submission_unknown"
    write_json(job / "job.json", state)
    return summary(job, state)


def poll(job: Path, client):
    packet, state = read_job(job)
    if state.get("provider_url") != client.credentials.base_url:
        raise ProviderError("Job belongs to another provider URL")
    if not state.get("external_job_id"):
        raise ProviderError("No task ID recorded; cannot resubmit or invent one")
    payload = client.request(MODELS[packet["model"]]["poll"], query={"task_id": state["external_job_id"]})
    state.update(state=status_of(payload), result_urls=result_urls(payload))
    data = unwrap(payload)
    if isinstance(data.get("points_cost"), (int, float)):
        state["provider_points_cost"] = data["points_cost"]
        state["points_refunded"] = str(data.get("points_refunded", False)).lower() in {"true", "1"}
        state["points_cost"] = 0 if state["points_refunded"] else data["points_cost"]
    write_json(job / "job.json", state)
    return summary(job, state)


def summary(job, state):
    return {"job": str(job), "state": state["state"], "has_task_id": bool(state.get("external_job_id")),
            "result_count": len(state.get("result_urls", [])), "points_cost": state.get("points_cost")}


def public_https(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise ProviderError("Result must use a public HTTPS URL")
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise ProviderError("Non-public result URL refused")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443)
    except OSError:
        raise ProviderError("Result host cannot be resolved safely") from None
    # Desktop TUN proxies resolve normal HTTPS domain names into the RFC 2544
    # fake-IP pool, then route by the original host. Keep TLS verification and
    # block literal/private/loopback/link-local targets, while allowing this
    # specific domain-only proxy transport (also used by the authenticated API).
    fake_dns = ipaddress.ip_network("198.18.0.0/15")
    if not addresses or any(not (ipaddress.ip_address(item[4][0]).is_global or
                                (literal is None and ipaddress.ip_address(item[4][0]) in fake_dns))
                            for item in addresses):
        raise ProviderError("Non-public result URL refused")


class DownloadRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(job: Path):
    packet, state = read_job(job)
    if state["state"] != "succeeded" or not state.get("result_urls"):
        raise ProviderError("No successful media result to download")
    media_paths = []
    for index, url in enumerate(state["result_urls"]):
        suffix = ".png" if packet["kind"] == "image" else ".mp4"
        dest = job / f"result-{index:02d}{suffix}"
        if dest.exists():
            raise ProviderError("Result file already exists; refusing to overwrite")
        temporary = dest.with_suffix(".download")
        try:
            if url.startswith("data:"):
                header, encoded = url.split(",", 1)
                if ";base64" not in header:
                    raise ProviderError("Only base64 media results are supported")
                temporary.write_bytes(base64.b64decode(encoded, validate=True))
            else:
                public_https(url)
                # No provider headers go to media/CDN hosts.
                req = urllib.request.Request(url, headers={"User-Agent": "SpriteMotionKit/0.5"})
                with urllib.request.build_opener(DownloadRedirect()).open(req, timeout=55) as response, temporary.open("xb") as stream:
                    size = 0
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > 256 * 1024 * 1024:
                            raise ProviderError("Media result exceeds 256 MiB")
                        stream.write(chunk)
            if packet["kind"] == "image":
                from PIL import Image
                with Image.open(temporary) as im:
                    im.verify()
                with Image.open(temporary) as im:
                    im.save(dest, format="PNG")
                temporary.unlink()
            else:
                with temporary.open("rb") as stream:
                    head = stream.read(16)
                if head[4:8] != b"ftyp" and head[:4] != b"\x1aE\xdf\xa3":
                    raise ProviderError("Result does not contain recognizable video data")
                os.replace(temporary, dest)
            media_paths.append(str(dest))
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError("Media download or decoding failed; generation was not retried") from None
    state["local_results"] = media_paths
    write_json(job / "job.json", state)
    return {"state": "downloaded", "files": media_paths, "art_approved": False}


REFERENCE_MAX_BYTES = 10 * 1024 * 1024
REFERENCE_FORMATS = {'PNG': ('png', 'image/png'), 'JPEG': ('jpg', 'image/jpeg'),
                     'GIF': ('gif', 'image/gif'), 'WEBP': ('webp', 'image/webp')}


def same_origin_reference(base_url, value):
    """Resolve a provider upload result without permitting another origin."""
    try:
        base = urllib.parse.urlsplit(base_url)
        if (base.scheme != 'https' or not base.hostname or base.username or base.password
                or base.port not in (None, 443) or base.query or base.fragment):
            raise ValueError()
        origin = urllib.parse.urlunsplit(('https', base.netloc, '', '', ''))
        if not isinstance(value, str) or not value or any(ord(c) < 33 for c in value) or '\\' in value:
            raise ValueError()
        url = urllib.parse.urljoin(origin + '/', value)
        parsed = urllib.parse.urlsplit(reference_image(url))
        if (parsed.hostname.lower() != base.hostname.lower()
                or parsed.port not in (None, 443)):
            raise ValueError()
        return url
    except (ValueError, AttributeError):
        raise ProviderError('Reference upload URL must stay on the selected HTTPS provider origin') from None


class ReferenceRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin):
        super().__init__()
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = same_origin_reference(self.origin, newurl)
        public_https(url)
        return super().redirect_request(req, fp, code, msg, headers, url)


def _download_reference(url, origin):
    url = same_origin_reference(origin, url)
    public_https(url)
    request = urllib.request.Request(url, headers={'User-Agent': 'SpriteMotionKit/0.5'})
    try:
        with urllib.request.build_opener(ReferenceRedirect(origin)).open(request, timeout=55) as response:
            same_origin_reference(origin, response.geturl())
            raw = response.read(REFERENCE_MAX_BYTES + 1)
        if len(raw) > REFERENCE_MAX_BYTES:
            raise ProviderError('Reference download exceeds 10 MiB')
        return raw
    except ProviderError:
        raise
    except (OSError, ValueError):
        raise ProviderError('Reference verification download failed; no generation was submitted') from None


def upload_reference(image, job, client):
    """Publish original bytes to the selected account; never generate an image."""
    from PIL import Image
    image, job = Path(image).resolve(), Path(job).resolve()
    if not image.is_file() or not 0 < image.stat().st_size <= REFERENCE_MAX_BYTES:
        raise ProviderError('Reference image must be an existing file of at most 10 MiB')
    raw = image.read_bytes()
    try:
        with Image.open(io.BytesIO(raw)) as source:
            extension, mime = REFERENCE_FORMATS[source.format]
            if getattr(source, 'n_frames', 1) != 1:
                raise ProviderError('Reference identity must be a single still image')
            source.verify()
    except ProviderError:
        raise
    except (OSError, ValueError, KeyError):
        raise ProviderError('Reference must be a readable JPEG, PNG, GIF or WebP still') from None
    if len(raw) > REFERENCE_MAX_BYTES:
        raise ProviderError('Reference image exceeds 10 MiB')
    origin = same_origin_reference(client.credentials.base_url, '/')[:-1]
    source_sha = hashlib.sha256(raw).hexdigest()
    packet = {'schema_version': 1, 'kind': 'reference_upload',
              'endpoint': '/api/v2/upload/temp-image', 'provider_origin': origin,
              'source_sha256': source_sha, 'source_size': len(raw), 'source_mime': mime,
              'source_file': 'source.' + extension}
    job.mkdir(parents=True, exist_ok=False)
    (job / packet['source_file']).write_bytes(raw)
    write_json(job / 'request.json', packet)
    state = {'schema_version': 1, 'kind': 'reference_upload', 'state': 'uploading',
             'request_sha256': digest(packet), 'generation_submitted': False}
    write_json(job / 'job.json', state)
    boundary = 'SpriteMotionKit' + uuid.uuid4().hex
    multipart = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
                 f'filename="reference.{extension}"\r\nContent-Type: {mime}\r\n\r\n').encode('ascii')
    multipart += raw + f'\r\n--{boundary}--\r\n'.encode('ascii')
    response = client.request(packet['endpoint'], multipart=(multipart, 'multipart/form-data; boundary=' + boundary))
    data = unwrap(response)
    if type(data.get('size')) is not int or data['size'] != len(raw) or data.get('type') != mime:
        raise ProviderError('Reference upload metadata does not match the source image')
    url = same_origin_reference(origin, data.get('url'))
    downloaded = _download_reference(url, origin)
    if hashlib.sha256(downloaded).hexdigest() != source_sha:
        raise ProviderError('Uploaded reference bytes differ from the original source SHA256')
    verified = job / ('verified.' + extension)
    verified.write_bytes(downloaded)
    state.update(state='verified', source_sha256=source_sha, remote_sha256=source_sha,
                 result_urls=[url], local_results=[str(verified)])
    state['verification_sha256'] = digest({'source_sha256': source_sha, 'result_urls': [url]})
    write_json(job / 'job.json', state)
    return {'state': 'verified', 'kind': 'reference_upload', 'job': str(job),
            'source_sha256': source_sha, 'remote_sha256': source_sha,
            'generation_submitted': False}


def read_uploaded_reference(job):
    """Check a real upload receipt and immutable local copies, without a request."""
    job = Path(job).resolve()
    packet = json.loads((job / 'request.json').read_text(encoding='utf-8'))
    state = json.loads((job / 'job.json').read_text(encoding='utf-8'))
    if (not isinstance(packet, dict) or not isinstance(state, dict)
            or packet.get('kind') != 'reference_upload' or state.get('kind') != 'reference_upload'
            or state.get('state') != 'verified' or state.get('generation_submitted') is not False
            or packet.get('endpoint') != '/api/v2/upload/temp-image'
            or digest(packet) != state.get('request_sha256')):
        raise ProviderError('Reference upload receipt is incomplete or changed')
    source = job / str(packet.get('source_file', ''))
    results, urls = state.get('local_results'), state.get('result_urls')
    if (not source.resolve().is_relative_to(job) or not source.is_file()
            or not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], str)
            or not isinstance(urls, list) or len(urls) != 1):
        raise ProviderError('Reference upload receipt needs its source and verified download')
    local = Path(results[0]).resolve()
    if not local.is_relative_to(job) or not local.is_file():
        raise ProviderError('Verified reference download is missing or outside the upload job')
    same_origin_reference(packet.get('provider_origin'), urls[0])
    expected = packet.get('source_sha256')
    if (state.get('verification_sha256') != digest({'source_sha256': expected, 'result_urls': urls})
            or state.get('source_sha256') != expected or state.get('remote_sha256') != expected
            or hashlib.sha256(source.read_bytes()).hexdigest() != expected
            or hashlib.sha256(local.read_bytes()).hexdigest() != expected):
        raise ProviderError('Reference upload source or verified download SHA256 changed')
    return packet, state, local


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mypixelflow-root", type=Path)
    parser.add_argument("--credential-id")
    parser.add_argument("--node")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("models")
    commands.add_parser("check")
    upload = commands.add_parser('upload-reference')
    upload.add_argument('--image', type=Path, required=True)
    upload.add_argument('--job', type=Path, required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--model", choices=MODELS, required=True)
    prep.add_argument("--prompt-file", type=Path, required=True)
    prep.add_argument("--reference", action="append", default=[])
    prep.add_argument("--resolution")
    prep.add_argument("--ratio", help="Default: 16:9 for Veo, 1:1 for other profiles")
    prep.add_argument("--duration", type=int)
    prep.add_argument("--first-last", action="store_true")
    prep.add_argument("--reference-role", choices=["first_frame", "reference_image"],
                      help="Seedance 2.0 Mini/Fast: one first frame by default, or explicit reference-image conditioning")
    prep.add_argument("--job", type=Path, required=True)
    for cmd in ("submit", "poll", "download"):
        p = commands.add_parser(cmd)
        p.add_argument("--job", type=Path, required=True)
        if cmd == "submit":
            p.add_argument("--confirm-submit", action="store_true", help="Submit exactly one authorized, billable request")
    args = parser.parse_args()
    try:
        if args.command == "models":
            result = MODELS
        elif args.command == "prepare":
            result = prepare(args.job, args.model, args.prompt_file.read_text(encoding="utf-8-sig"), args.reference,
                             resolution=args.resolution, ratio=args.ratio, duration=args.duration, first_last=args.first_last,
                             reference_role=args.reference_role)
        elif args.command == "download":
            result = download(args.job)
        else:
            credentials = load_mxapi_credentials(mypixelflow_root=args.mypixelflow_root, credential_id=args.credential_id, node_executable=args.node)
            client = Client(credentials)
            if args.command == "check":
                result = client.check()
            elif args.command == 'upload-reference':
                result = upload_reference(args.image, args.job, client)
            elif args.command == "submit":
                if not args.confirm_submit:
                    raise ProviderError("Use --confirm-submit only for a generation already authorized by the user")
                result = submit(args.job, client)
            else:
                result = poll(args.job, client)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ProviderError, ProviderCredentialError, OSError, ValueError, KeyError):
        # Never print unexpected exceptions: they can contain provider payloads.
        exc = sys.exc_info()[1]
        message = str(exc) if isinstance(exc, (ProviderError, ProviderCredentialError)) else "Invalid local job/configuration; no automatic generation retry"
        print(json.dumps({"error": message}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
