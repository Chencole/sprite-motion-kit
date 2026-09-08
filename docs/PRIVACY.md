# Privacy

Sprite Motion Kit's authoring, extraction and review helpers run locally without telemetry or analytics. They read the selected artwork, videos and job paths and write the requested output. There is no plugin-hosted backend.

The optional MXAPI connection makes authenticated image/video generation and quota requests to the account endpoint the user selects. With an explicitly selected MyPixelFlow installation, it reads that project's encrypted credential database and encryption configuration locally and decrypts the selected credential in process memory. Alternatively it reads the user's MXAPI environment configuration. It does not copy credentials into this repository, jobs or logs, modify MyPixelFlow, or include an account in the distributed plugin. Provider redirects are refused and account headers are not forwarded to media download hosts.

Submitting a generation sends the requested prompt and reference image URLs to the chosen provider and may consume its credits. Generated results are downloaded from provider-returned media URLs. The request, task identifier and result URLs are recorded locally for recovery; treat these job files as private because they can contain prompts, reference locations and signed media links. There are no automatic billable retries. A quota check alone does not submit a generation.

The host AI's image-generation tool receives the character and pose references when the user requests generation. That service's privacy policy, retention, pricing and permissions apply. This plugin does not replace or bypass them.

The experimental local-model route is opt-in. Its separate setup helper downloads only explicitly requested model files from the documented upstream sources and verifies their hashes. No model weights or generation quotas are bundled.

Generated requests and source images are saved in the local job for inspection. The offline review page embeds the images and makes no external requests. Sharing that page shares those images; only share artwork you intend to disclose. Jobs are excluded from this repository by default.

Support: https://github.com/Chencole/sprite-motion-kit/issues
