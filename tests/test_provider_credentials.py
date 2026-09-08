import contextlib
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/sprite-motion-kit/skills/sprite-motion/scripts'))
from provider_credentials import ProviderCredentialError, load_mxapi_credentials


TEST_KEY = 'test-only-mxapi-secret-never-a-real-key'
TEST_MASTER = 'test-only-local-master-key'
NODE = shutil.which('node')
ENCRYPT = r'''
const {readFileSync} = require('node:fs');
const {createHash, createCipheriv, randomBytes} = require('node:crypto');
const x = JSON.parse(readFileSync(0, 'utf8'));
const iv = randomBytes(12);
const cipher = createCipheriv('aes-256-gcm', createHash('sha256').update(x.master).digest(), iv);
const value = Buffer.concat([cipher.update(x.key, 'utf8'), cipher.final()]);
process.stdout.write(JSON.stringify({iv:iv.toString('base64url'),
    tag:cipher.getAuthTag().toString('base64url'),value:value.toString('base64url')}));
'''


class EnvironmentCredentialTests(unittest.TestCase):
    def test_explicit_environment_works_without_node_or_database(self):
        with patch('provider_credentials.subprocess.run', side_effect=AssertionError('No helper needed')):
            result = load_mxapi_credentials(environ={
                'MXAPI_API_KEY': TEST_KEY, 'MXAPI_BASE_URL': 'https://relay.example/api/'})
        self.assertEqual(result.base_url, 'https://relay.example/api')
        self.assertEqual(result.headers()['Authorization'], 'Bearer ' + TEST_KEY)
        self.assertNotIn(TEST_KEY, repr(result))
        self.assertEqual(result.source, 'environment')

    def test_partial_environment_never_defaults_account_or_host(self):
        for env in ({}, {'MXAPI_API_KEY': TEST_KEY}, {'MXAPI_BASE_URL': 'https://relay.example'},
                    {'MXAPI_TOKEN': TEST_KEY, 'MXAPI_BASE_URL': 'https://relay.example'}):
            with self.subTest(keys=list(env)), self.assertRaises(ProviderCredentialError):
                load_mxapi_credentials(environ=env)

    def test_unsafe_urls_rejected_without_echo(self):
        for url in ('http://relay.example', 'https://user:' + TEST_KEY + '@relay.example',
                    'https://relay.example/?key=' + TEST_KEY, 'https://relay.example/#' + TEST_KEY,
                    'https://relay.example:bad', 'https://', 'https://relay.example\\other',
                    'https://relay.example\nother'):
            with self.subTest(url=url):
                with self.assertRaises(ProviderCredentialError) as raised:
                    load_mxapi_credentials(environ={'MXAPI_API_KEY': TEST_KEY, 'MXAPI_BASE_URL': url})
                self.assertNotIn(TEST_KEY, str(raised.exception))

    def test_header_injection_and_empty_secrets_rejected(self):
        for key in ('', '   ', TEST_KEY + '\nInjected: header', TEST_KEY + '\x00', ' ' + TEST_KEY):
            with self.assertRaises(ProviderCredentialError) as raised:
                load_mxapi_credentials(environ={'MXAPI_API_KEY': key, 'MXAPI_BASE_URL': 'https://relay.example'})
            self.assertNotIn(TEST_KEY, str(raised.exception))

    def test_credential_id_requires_project_source(self):
        with self.assertRaises(ProviderCredentialError):
            load_mxapi_credentials(credential_id='account-a', environ={})


@unittest.skipUnless(NODE, 'Node.js is required for the actual AES-GCM fixture')
class ProjectCredentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([NODE, '-e', ENCRYPT],
                                input=json.dumps({'master': TEST_MASTER, 'key': TEST_KEY}).encode(),
                                capture_output=True, check=True, timeout=15)
        cls.envelope = result.stdout.decode()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.db = self.data / 'studio.db'
        (self.root / '.env').write_text('CREDENTIAL_ENCRYPTION_MASTER_KEY="' + TEST_MASTER + '"\n', encoding='utf-8')
        connection = sqlite3.connect(self.db)
        connection.executescript('''
            CREATE TABLE providers (id TEXT PRIMARY KEY, status TEXT);
            CREATE TABLE provider_credentials (
                id TEXT PRIMARY KEY, provider_id TEXT, status TEXT, base_url TEXT,
                auth_type TEXT, auth_header_name TEXT, extra_headers_json TEXT,
                encrypted_secret_payload TEXT);
            INSERT INTO providers VALUES ('mxapi-v2', 'active');
        ''')
        connection.close()
        self.add_account('account-a')

    def tearDown(self):
        self.temp.cleanup()

    def add_account(self, account_id, status='active'):
        # sqlite3's context manager ends the transaction but does not close the
        # handle. Close explicitly so Windows can remove the fixture database.
        with contextlib.closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute('INSERT INTO provider_credentials VALUES (?,?,?,?,?,?,?,?)',
                               (account_id, 'mxapi-v2', status, 'https://selected.example',
                                'bearer', 'Authorization', '{"X-Channel":"configured"}', self.envelope))

    def update(self, field, value):
        # Field names in this helper are test constants, never caller input.
        with contextlib.closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute(f'UPDATE provider_credentials SET {field}=? WHERE id=?', (value, 'account-a'))

    def load(self, **kwargs):
        return load_mxapi_credentials(mypixelflow_root=self.root, node_executable=NODE, **kwargs)

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def test_real_decryption_is_silent_and_does_not_change_source(self):
        before = self.snapshot()
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            credentials = self.load()
        self.assertEqual(credentials.api_key, TEST_KEY)
        self.assertEqual(credentials.headers()['X-Channel'], 'configured')
        self.assertEqual(credentials.credential_id, 'account-a')
        self.assertEqual(credentials.source, 'mypixelflow')
        self.assertNotIn(TEST_KEY, repr(credentials))
        self.assertEqual(stdout.getvalue() + stderr.getvalue(), '')
        self.assertEqual(before, self.snapshot())

    def test_explicit_project_ignores_environment_account_and_host(self):
        credentials = self.load(environ={'MXAPI_API_KEY': 'other-account', 'MXAPI_BASE_URL': 'https://other.example'})
        self.assertEqual(credentials.base_url, 'https://selected.example')
        self.assertEqual(credentials.api_key, TEST_KEY)

    def test_multiple_active_accounts_require_exact_selection(self):
        self.add_account('account-b')
        with self.assertRaisesRegex(ProviderCredentialError, 'Multiple active'):
            self.load()
        self.assertEqual(self.load(credential_id='account-b').credential_id, 'account-b')
        for account in ('missing', 'account-b\' OR 1=1 --'):
            with self.assertRaisesRegex(ProviderCredentialError, 'No matching active'):
                self.load(credential_id=account)

    def test_inactive_accounts_and_provider_are_not_reused(self):
        self.update('status', 'disabled')
        with self.assertRaisesRegex(ProviderCredentialError, 'No matching active'):
            self.load(credential_id='account-a')
        self.update('status', 'active')
        with contextlib.closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute('UPDATE providers SET status=?', ('disabled',))
        with self.assertRaisesRegex(ProviderCredentialError, 'No matching active'):
            self.load()

    def test_missing_database_is_not_created_or_replaced_by_environment(self):
        other = self.root / 'missing'
        with self.assertRaises(ProviderCredentialError):
            load_mxapi_credentials(mypixelflow_root=other, environ={
                'MXAPI_API_KEY': TEST_KEY, 'MXAPI_BASE_URL': 'https://other.example'})
        self.assertFalse(other.exists())

    def test_pending_wal_is_rejected_without_reading_stale_account(self):
        Path(str(self.db) + '-wal').write_bytes(b'pending-writes')
        before = self.snapshot()
        with self.assertRaisesRegex(ProviderCredentialError, 'outstanding WAL'):
            self.load()
        self.assertEqual(before, self.snapshot())

    def test_local_master_key_fallback_only_when_project_env_unconfigured(self):
        (self.root / '.env').unlink()
        (self.data / '.credential-master-key').write_text(TEST_MASTER + '\n', encoding='utf-8')
        self.assertEqual(self.load().api_key, TEST_KEY)
        (self.root / '.env').write_text('CREDENTIAL_ENCRYPTION_MASTER_KEY=wrong-key\n', encoding='utf-8')
        with self.assertRaisesRegex(ProviderCredentialError, 'Cannot decrypt'):
            self.load(environ={'MXAPI_API_KEY': TEST_KEY, 'MXAPI_BASE_URL': 'https://other.example'})

    def test_dotenv_comments_and_duplicate_master_configuration(self):
        (self.root / '.env').write_text('export CREDENTIAL_ENCRYPTION_MASTER_KEY="' + TEST_MASTER + '" # comment\n', encoding='utf-8')
        self.assertEqual(self.load().api_key, TEST_KEY)
        (self.root / '.env').write_text('CREDENTIAL_ENCRYPTION_MASTER_KEY=' + TEST_MASTER + '\n' * 1
                                      + 'CREDENTIAL_ENCRYPTION_MASTER_KEY=other\n', encoding='utf-8')
        with self.assertRaisesRegex(ProviderCredentialError, 'ambiguous'):
            self.load()

    def test_corrupted_ciphertext_is_redacted_and_does_not_fallback(self):
        for envelope in ('not-json-' + TEST_KEY, '{}', '{"iv":1,"tag":2,"value":3}'):
            self.update('encrypted_secret_payload', envelope)
            with self.assertRaises(ProviderCredentialError) as raised:
                self.load()
            self.assertNotIn(TEST_KEY, str(raised.exception))
        corrupted = json.loads(self.envelope)
        corrupted['tag'] = 'A' * 22
        self.update('encrypted_secret_payload', json.dumps(corrupted))
        with self.assertRaisesRegex(ProviderCredentialError, 'Cannot decrypt'):
            self.load()

    def test_unsafe_stored_auth_and_host_are_rejected(self):
        for field, invalid in [('base_url', 'http://selected.example'),
                               ('auth_type', 'custom'), ('auth_header_name', 'Host')]:
            with self.subTest(field=field):
                original = {'base_url': 'https://selected.example', 'auth_type': 'bearer',
                            'auth_header_name': 'Authorization'}[field]
                self.update(field, invalid)
                with self.assertRaises(ProviderCredentialError):
                    self.load()
                self.update(field, original)

    def test_extra_headers_cannot_replace_selected_account_or_host(self):
        for extra in ({'Authorization': TEST_KEY}, {'Host': 'other.example'},
                      {'X-Test': 'value\r\nAuthorization: ' + TEST_KEY},
                      {'X-Channel': 'a', 'x-channel': 'b'}, ['invalid']):
            self.update('extra_headers_json', json.dumps(extra))
            with self.assertRaises(ProviderCredentialError) as raised:
                self.load()
            self.assertNotIn(TEST_KEY, str(raised.exception))

    def test_helper_errors_never_expose_stderr_or_exception_payloads(self):
        with patch('provider_credentials.subprocess.run', return_value=subprocess.CompletedProcess(
                args=[], returncode=1, stdout=TEST_KEY.encode(), stderr=TEST_KEY.encode())):
            with self.assertRaises(ProviderCredentialError) as raised:
                self.load()
            self.assertNotIn(TEST_KEY, str(raised.exception))
        with patch('provider_credentials.subprocess.run', side_effect=subprocess.TimeoutExpired(
                cmd=TEST_KEY, timeout=15, output=TEST_KEY.encode(), stderr=TEST_KEY.encode())):
            with self.assertRaises(ProviderCredentialError) as raised:
                self.load()
            self.assertNotIn(TEST_KEY, str(raised.exception))
            self.assertTrue(raised.exception.__suppress_context__)

    def test_helper_receives_secrets_only_in_captured_pipe(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=TEST_KEY.encode(), stderr=b'')
        with patch.dict(os.environ, {'NODE_OPTIONS': '--require unsafe-hook', 'UNRELATED_API_KEY': TEST_KEY}):
            with patch('provider_credentials.subprocess.run', return_value=completed) as run:
                self.load()
        args, kwargs = run.call_args
        self.assertNotIn(TEST_MASTER, repr(args))
        self.assertNotIn(TEST_KEY, repr(args))
        self.assertNotIn('NODE_OPTIONS', kwargs['env'])
        self.assertNotIn('UNRELATED_API_KEY', kwargs['env'])
        self.assertEqual(kwargs['stdout'], subprocess.PIPE)
        self.assertEqual(kwargs['stderr'], subprocess.PIPE)
        self.assertEqual(json.loads(kwargs['input'])['master'], TEST_MASTER)


if __name__ == '__main__':
    unittest.main()
