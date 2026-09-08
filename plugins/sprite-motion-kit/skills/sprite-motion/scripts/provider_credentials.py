"""Resolve one explicitly selected MXAPI credential without network or writes.

Environment mode requires both MXAPI_API_KEY and MXAPI_BASE_URL. Passing a
MyPixelFlow root selects that project's SQLite account instead; the two sources
are never merged. SQLite is opened immutable/read-only, and an outstanding WAL
is rejected instead of silently reading an older account configuration.

Only Python's standard library is required. MyPixelFlow's AES-GCM envelope is
decrypted by an installed Node.js executable using its built-in crypto module.
Secrets travel through captured anonymous pipes in memory, never command-line
arguments, temporary files, inherited environment variables, or terminal output.
Callers must not serialize this credential object or log headers().
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


class ProviderCredentialError(ValueError):
    """A configuration error whose message contains no credential material."""


@dataclass(frozen=True, repr=False)
class MxapiCredentials:
    api_key: str = field(repr=False)
    base_url: str
    source: str
    credential_id: str | None = None
    auth_header_name: str = 'Authorization'
    auth_type: str = 'bearer'
    _extra_headers: tuple[tuple[str, str], ...] = field(default=(), repr=False)

    def __repr__(self) -> str:
        return '<MxapiCredentials configured; secrets redacted>'

    def headers(self) -> dict[str, str]:
        """Return request headers for this host only. Do not log the result."""
        headers = dict(self._extra_headers)
        headers['Content-Type'] = 'application/json'
        headers[self.auth_header_name] = (
            'Bearer ' + self.api_key if self.auth_type == 'bearer' else self.api_key
        )
        return headers


_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_FORBIDDEN_EXTRA_HEADERS = {
    'authorization', 'proxy-authorization', 'cookie', 'host', 'content-length',
    'transfer-encoding', 'connection',
}
_PLACEHOLDER_MASTER = 'replace-this-credential-master-key'
_NODE_DECRYPT = r'''
const {readFileSync} = require('node:fs');
const {createHash, createDecipheriv} = require('node:crypto');
try {
  const input = JSON.parse(readFileSync(0, 'utf8'));
  const p = input.envelope;
  const key = createHash('sha256').update(input.master, 'utf8').digest();
  const decipher = createDecipheriv('aes-256-gcm', key, Buffer.from(p.iv, 'base64url'));
  decipher.setAuthTag(Buffer.from(p.tag, 'base64url'));
  const plain = Buffer.concat([
    decipher.update(Buffer.from(p.value, 'base64url')), decipher.final()
  ]);
  process.stdout.write(plain);
  plain.fill(0);
  key.fill(0);
} catch (_) {
  process.exitCode = 1;
}
'''


def _base_url(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProviderCredentialError('An explicit HTTPS MXAPI base URL is required.')
    try:
        parsed = urlsplit(value)
        port = parsed.port
        valid = (
            parsed.scheme == 'https' and bool(parsed.hostname)
            and parsed.username is None and parsed.password is None
            and not parsed.query and not parsed.fragment
            and not any(c.isspace() or ord(c) < 32 for c in value)
            and '\\' not in value and (port is None or 1 <= port <= 65535)
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ProviderCredentialError('MXAPI base URL must use HTTPS without userinfo, query, or fragment.')
    return value.rstrip('/')


def _secret(value: object) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > 65536
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ProviderCredentialError('MXAPI credential is missing or invalid.')
    # The existing project trims an API key when saving it. Do not normalize a
    # manually supplied account value into a different credential here.
    if value != value.strip():
        raise ProviderCredentialError('MXAPI credential has surrounding whitespace.')
    return value


def _header_configuration(auth_type: object, header: object, raw_extra: object):
    if auth_type not in ('bearer', 'api-key'):
        raise ProviderCredentialError('The selected MXAPI account uses unsupported authentication.')
    if not isinstance(header, str) or not _HEADER_NAME.fullmatch(header):
        raise ProviderCredentialError('The selected MXAPI authentication header is invalid.')
    if header.lower() in _FORBIDDEN_EXTRA_HEADERS - {'authorization'}:
        raise ProviderCredentialError('The selected MXAPI authentication header is unsafe.')
    try:
        extra = json.loads(raw_extra) if raw_extra else {}
    except (TypeError, ValueError):
        raise ProviderCredentialError('The selected MXAPI extra headers are invalid.') from None
    if not isinstance(extra, dict):
        raise ProviderCredentialError('The selected MXAPI extra headers are invalid.')
    result = []
    seen = set()
    for name, value in extra.items():
        lower = name.lower()
        if (not _HEADER_NAME.fullmatch(name) or not isinstance(value, str)
                or any(ord(c) < 32 or ord(c) == 127 for c in value)
                or lower in _FORBIDDEN_EXTRA_HEADERS or lower == header.lower()
                or lower in seen):
            raise ProviderCredentialError('The selected MXAPI extra headers are unsafe or conflicting.')
        if lower == 'content-type':
            if value.lower() != 'application/json':
                raise ProviderCredentialError('The selected MXAPI content type is unsupported.')
        else:
            result.append((name, value))
        seen.add(lower)
    return tuple(result)


def _read_master(root: Path) -> str:
    env_file = root / '.env'
    configured = None
    try:
        if env_file.exists():
            if env_file.stat().st_size > 1024 * 1024:
                raise ProviderCredentialError('The selected project environment file is too large.')
            for line in env_file.read_text(encoding='utf-8-sig').splitlines():
                match = re.match(r'^\s*(?:export\s+)?CREDENTIAL_ENCRYPTION_MASTER_KEY\s*=\s*(.*?)\s*$', line)
                if not match:
                    continue
                if configured is not None:
                    raise ProviderCredentialError('The selected project has ambiguous master-key configuration.')
                value = match.group(1)
                if value.startswith(('"', "'")):
                    quote = value[0]
                    closing = value.find(quote, 1)
                    remainder = value[closing + 1:].strip() if closing >= 0 else ''
                    if closing < 0 or (remainder and not remainder.startswith('#')):
                        raise ProviderCredentialError('The selected project master-key configuration is invalid.')
                    value = value[1:closing]
                else:
                    value = value.split('#', 1)[0].strip()
                configured = value
        if configured and configured != _PLACEHOLDER_MASTER:
            return configured
        local = root / 'data' / '.credential-master-key'
        if not local.is_file() or local.stat().st_size > 65536:
            raise ProviderCredentialError('The selected project has no readable credential master key.')
        master = local.read_text(encoding='utf-8').strip()
        if not master:
            raise ProviderCredentialError('The selected project credential master key is empty.')
        return master
    except (OSError, UnicodeError):
        raise ProviderCredentialError('Cannot read the selected project credential master key.') from None


def _decrypt(encrypted: object, master: str, node_executable: str | None) -> str:
    try:
        envelope = json.loads(encrypted)
        if (not isinstance(envelope, dict) or set(envelope) != {'iv', 'tag', 'value'}
                or not all(isinstance(v, str) and 0 < len(v) <= 131072
                           and re.fullmatch(r'[A-Za-z0-9_-]+', v)
                           for v in envelope.values())):
            raise ValueError()
    except (TypeError, ValueError):
        raise ProviderCredentialError('The selected account encrypted credential is invalid.') from None
    node = node_executable or shutil.which('node')
    if not node:
        raise ProviderCredentialError('Node.js is required to read the selected project credential.')
    # Do not inherit NODE_OPTIONS hooks or unrelated API keys into this helper.
    child_env = {k: v for k, v in os.environ.items()
                 if k.upper() in {'SYSTEMROOT', 'WINDIR', 'PATH'}}
    try:
        result = subprocess.run(
            [str(node), '-e', _NODE_DECRYPT],
            input=json.dumps({'envelope': envelope, 'master': master}).encode('utf-8'),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
            check=False, env=child_env,
        )
    except (OSError, subprocess.SubprocessError):
        raise ProviderCredentialError('The credential decryption helper failed; no fallback account was selected.') from None
    if result.returncode:
        raise ProviderCredentialError('Cannot decrypt the selected account with its project master key.')
    try:
        return _secret(result.stdout.decode('utf-8'))
    except UnicodeError:
        raise ProviderCredentialError('The selected account credential is invalid.') from None


def _read_account(root: Path, credential_id: str | None) -> sqlite3.Row:
    db_path = root / 'data' / 'studio.db'
    wal_path = Path(str(db_path) + '-wal')
    try:
        if not root.is_dir() or not db_path.is_file():
            raise ProviderCredentialError('The explicitly selected MyPixelFlow database does not exist.')
        if wal_path.exists() and wal_path.stat().st_size:
            raise ProviderCredentialError('The selected database has an outstanding WAL; use explicit environment credentials or checkpoint it in MyPixelFlow first.')
        before = db_path.stat()
        connection = sqlite3.connect(db_path.as_uri() + '?mode=ro&immutable=1', uri=True)
        try:
            connection.row_factory = sqlite3.Row
            query = '''SELECT c.id, c.base_url, c.auth_type, c.auth_header_name,
                       c.extra_headers_json, c.encrypted_secret_payload
                       FROM provider_credentials c JOIN providers p ON p.id=c.provider_id
                       WHERE c.provider_id=? AND c.status=? AND p.status=?'''
            parameters = ['mxapi-v2', 'active', 'active']
            if credential_id is not None:
                query += ' AND c.id=?'
                parameters.append(credential_id)
            rows = connection.execute(query, parameters).fetchall()
        finally:
            connection.close()
        after = db_path.stat()
        if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
                or wal_path.exists() and wal_path.stat().st_size):
            raise ProviderCredentialError('The selected database changed while reading credentials; retry explicitly.')
    except (OSError, sqlite3.Error):
        raise ProviderCredentialError('Cannot read the selected MyPixelFlow account database.') from None
    if not rows:
        raise ProviderCredentialError('No matching active MXAPI account exists in the selected project.')
    if len(rows) != 1:
        raise ProviderCredentialError('Multiple active MXAPI accounts exist; select an explicit credential_id.')
    return rows[0]


def load_mxapi_credentials(*, mypixelflow_root: str | Path | None = None,
                           credential_id: str | None = None,
                           environ: Mapping[str, str] | None = None,
                           node_executable: str | None = None) -> MxapiCredentials:
    """Load one account. Any failure stops; there is no account/host fallback.

    mypixelflow_root, when provided, takes precedence as an explicit source
    selection and ignores MXAPI_* environment values entirely. An account id is
    mandatory when that project has more than one active MXAPI account.
    """
    if mypixelflow_root is None:
        if credential_id is not None:
            raise ProviderCredentialError('credential_id requires an explicit mypixelflow_root.')
        selected_env = os.environ if environ is None else environ
        url = _base_url(selected_env.get('MXAPI_BASE_URL'))
        key = _secret(selected_env.get('MXAPI_API_KEY'))
        return MxapiCredentials(api_key=key, base_url=url, source='environment')
    try:
        root = Path(mypixelflow_root).resolve(strict=True)
    except (OSError, ValueError):
        raise ProviderCredentialError('The explicitly selected MyPixelFlow root is invalid.') from None
    row = _read_account(root, credential_id)
    url = _base_url(row['base_url'])
    extra = _header_configuration(row['auth_type'], row['auth_header_name'], row['extra_headers_json'])
    key = _decrypt(row['encrypted_secret_payload'], _read_master(root), node_executable)
    return MxapiCredentials(api_key=key, base_url=url, source='mypixelflow',
                           credential_id=row['id'], auth_header_name=row['auth_header_name'],
                           auth_type=row['auth_type'], _extra_headers=extra)
