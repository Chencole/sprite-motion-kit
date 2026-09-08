# Video-first samples

Use this route when the user chooses video generation instead of whole-sheet
image generation. Keep that choice; do not silently return to image sheets or
substitute a playback of old sprite frames as a newly generated video.

The host needs an available video-generation service or a video supplied by the
user. For an existing MXAPI/MyPixelFlow account, the plugin includes a real
[image and Seedance connection](mxapi-generation.md); inspect that route before
claiming that no video tool is available. This plugin does not bundle a video
model, credentials or credits. If no service is connected, ask which existing
service to use and continue local extraction work while waiting. Do not purchase
credits, upload character art to an unrelated provider, or claim generation is
running without a real call.

Use the approved character appearance as the image-to-video input. Request a
fixed right-profile camera, full body/weapon in frame, stable scale, simple keyed
background, no camera movement or motion blur, and several complete consecutive
steps. Character appearance comes from the input; the motion description should
focus on the actual action. A video model may still change limbs, equipment or
camera: inspect its output before choosing the extraction interval.

For walk/run, choose one full two-step cycle with the same anatomical support
foot and compatible velocity at its two boundaries. Do not mistake two similar
silhouettes for a complete loop. Attack/fall/jump intervals include anticipation
and settling as required. Death holds a full-size final body. Different actions
normally use separate clips; choose the set from the game's actual requirements.

```sh
python scripts/video_sample.py --video character-walk.mp4 --ffmpeg /path/to/ffmpeg \
  --out NEW_OUTPUT --character "Character" --action walk --start 1.0 \
  --duration 1.0 --count 8 --loop --background magenta --origin 512 850 \
  --review-notes "Inspected one complete two-step cycle; source camera and floor stay fixed."
```

Coordinates and timing above are examples, not inferred facts about an input.
Supply the actual video-canvas origin. Source alpha or an opaque green/magenta key is
supported; opaque arbitrary scenery requires a separate matte workflow and is
rejected. The importer does not download FFmpeg or remove arbitrary backgrounds.

The command uses an existing FFmpeg executable to inspect actual source timestamps
and select the nearest unique source frame to each uniform target time.
It keeps the original canvas and source order, without frame-wise recentering,
floor alignment, body stretching or optical-flow interpolation. It records output
target and actual sampling times plus original frame indices. A short interval cannot be silently
padded. Loop playback omits the duplicate endpoint; one-shot playback holds its
last extracted frame.

This is a single-action review artifact, not completion of a character's full
action set. Importer tests prove extraction behavior, not natural animation.
Real generated video is required before claiming the new route improves quality.
Keep repository visibility private while that quality remains unverified. Fixed
chroma thresholds remove edge-connected key background without eroding the body.
Compressed video may retain slight color spill; inspect it rather than treating
a successful alpha export as proof of a clean or natural animation.

When a plain key background is trapped in a closed gap between limbs, cloak or
weapon, first check that the character itself contains none of that key color.
Then explicitly use `--key-scope all` to remove those enclosed key pixels with
the same fixed threshold. This must not silently erase matching clothes or eyes;
default `edge-connected` preserves isolated internal colors. The review records
the chosen scope and includes a local copy of the unmodified source video.
