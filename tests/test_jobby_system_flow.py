"""Static explainer contract only; never reads the live application ledger."""
import re
import stat
import unittest
from tempfile import TemporaryDirectory
from html.parser import HTMLParser
from pathlib import Path
from fastapi.testclient import TestClient
from personal_jobby.app import create_app

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / 'personal_jobby/static/system-flow.html'
CSS = ROOT / 'personal_jobby/static/system-flow.css'


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.text = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


class SystemFlowTests(unittest.TestCase):
    def setUp(self):
        self.html = HTML.read_text()
        self.css = CSS.read_text()
        self.doc = Document(self.html)
        self.text = ' '.join(' '.join(self.doc.text).split())

    def test_thirteen_expandable_stages_and_actor_boundaries(self):
        stages = [a for t, a in self.doc.tags if t == 'details' and a.get('id', '').startswith('stage-')]
        self.assertEqual({a['id'] for a in stages}, {f'stage-{n}' for n in range(1, 14)})
        for phrase in ['Actor', 'Stored evidence', 'Stop', 'CLI never clicks forms', 'not a universal ATS adapter', 'ONLY HERMES BROWSER', 'Codex ChatGPT subscription auth', 'No extra MCP server']:
            self.assertIn(phrase, self.text)

    def stage_text(self, number):
        source = re.search(rf'<details id="stage-{number}">(.*?)</details>', self.html, re.S).group(1)
        return ' '.join(' '.join(Document(source).text).split())

    def test_scheduler_and_browser_have_stage_specific_roles(self):
        self.assertIn('scheduler only starts a fresh Hermes session; it never submits', self.stage_text(2))
        self.assertIn('Hermes browser reads genuine employer evidence; CLI stores it afterward', self.stage_text(5))
        self.assertIn('Only Hermes browser clicks real Submit once; cron only triggers the session', self.stage_text(11))
        self.assertNotIn('browser tools or the configured external scheduler', self.text)
        for number in (3, 10):
            self.assertNotIn('External cron', self.stage_text(number))

    def test_history_is_inspected_before_discovery_and_lease_start(self):
        stage = self.stage_text(3)
        for phrase in ['global holds', 'previous/latest safe ledger', 'pending/uncertain prior reservations before discovery',
                       'never recreate or retry locked postings', 'do not replace history inspection']:
            self.assertIn(phrase, stage)
        commands = re.search(r'<pre><code>(.*?)</code></pre>', re.search(
            r'<details id="stage-3">(.*?)</details>', self.html, re.S).group(1), re.S).group(1).splitlines()
        self.assertEqual(commands, ['jobby daily status', 'jobby daily summary',
                                    'jobby daily start --owner OPAQUE_OWNER', 'jobby daily heartbeat RUN_ID'])
        self.assertIn('Kill-switch example only', stage)

    def test_commands_are_copyable_and_have_valid_spaces(self):
        for command in [
            'jobby status --brief', 'jobby profile', 'jobby show JOB_ID',
            "jobby search 'AI Engineer' --location Canada --remote --hours-old 72 --limit 5",
            'jobby daily verify-job JOB_ID --evidence PRIVATE_JSON',
            'jobby fit JOB_ID --evidence PRIVATE_JSON', 'jobby prepare JOB_ID',
            'jobby approve JOB_ID --review PRIVATE_JSON', 'jobby attempt JOB_ID --manifest PRIVATE_JSON',
            'jobby screenshot ATTEMPT_ID PATH --kind filled_form --phone-redacted --qa-note NOTE',
            'jobby daily begin-submit RUN_ID ATTEMPT_ID --phone-not-required',
            'jobby daily begin-submit RUN_ID ATTEMPT_ID --phone-required',
            'jobby daily configure --enabled false',
            'jobby daily uncertain RUN_ID ATTEMPT_ID --reason SAFE_REASON',
            'jobby daily summary RUN_ID',
        ]:
            self.assertIn(command, self.text)
        self.assertIn('placeholders', self.text)
        self.assertIn('not actions', self.text)

    def test_truthfulness_and_persistent_uncertainty(self):
        for phrase in ['ILLUSTRATIVE EXAMPLES NOT LIVE JOB RESULTS', 'never automatic retry or unlock',
                       'across days and reruns', 'same-attempt employer confirmation',
                       '10 attempted submissions', 'includes uncertain', 'approval stale',
                       'CAD 120000 annual BASE', 'dated candidate facts', 'NOT live state',
                       'Disabled until manually configured', 'not proof of execution',
                       'HTTP 200', 'not encrypted at rest', 'human investigation']:
            self.assertIn(phrase, self.text)
        self.assertNotRegex(self.text, r'\b\d+ applications (submitted|successful)\b')

    def test_evidence_boundary_has_no_unsupported_test_metric(self):
        self.assertNotRegex(self.text, r'\b\d+ (?:control/CLI|control-layer|tests? passed|checks)')
        for phrase in ['Control-layer tests do not prove ATS completion', 'only a real receipt confirms',
                       'Configured cron is not proof of execution', 'not already shipped or product-ready', 'Evidence boundary']:
            self.assertIn(phrase, self.text)

    def test_served_csp_and_link_scope(self):
        for tag, attrs in self.doc.tags:
            self.assertNotIn(tag, ['script', 'style', 'iframe', 'form', 'img'])
            self.assertNotIn('style', attrs)
            self.assertFalse(any(k.startswith('on') for k in attrs))
            if tag == 'link':
                self.assertEqual(attrs.get('href'), '/static/system-flow.css')
            if tag == 'a':
                self.assertTrue(attrs['href'].startswith(('#', '/')))
        self.assertNotRegex(self.css, r'@import|url\s*\(')
        self.assertIn('href="/"', self.html)

    def test_accessible_native_controls_and_responsive_print(self):
        ids = [a['id'] for _, a in self.doc.tags if 'id' in a]
        self.assertEqual(len(ids), len(set(ids)))
        radios = [a for t, a in self.doc.tags if t == 'input']
        self.assertEqual(len(radios), 3)
        labels = {a.get('for') for t, a in self.doc.tags if t == 'label'}
        for radio in radios:
            self.assertEqual(radio['type'], 'radio')
            self.assertIn(radio['id'], labels)
        self.assertTrue(any(t == 'svg' and a.get('role') == 'img' and a.get('aria-labelledby') for t, a in self.doc.tags))
        for tag in ['main', 'header', 'footer', 'title', 'desc', 'fieldset', 'legend']:
            self.assertTrue(any(t == tag for t, _ in self.doc.tags), tag)
        for rule in ['max-width: 759px', '@media print', '12pt', ':focus-visible', '44px']:
            self.assertIn(rule, self.css)
        self.assertNotRegex(self.css, r'overflow(?:-x)?\s*:\s*hidden')

    def assert_export_equivalent(self, output):
        offline = output.read_text()
        embedded = re.search(r'<style>\n(.*?)</style>', offline, re.S)
        self.assertIsNotNone(embedded)
        self.assertEqual(embedded.group(1), CSS.read_text())
        self.assertEqual(offline.replace(embedded.group(0), '<link rel="stylesheet" href="/static/system-flow.css">'), HTML.read_text())
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(output.parent.stat().st_mode), 0o700)

    def test_offline_is_equivalent_and_private(self):
        from personal_jobby.export_system_flow import export_system_flow
        with TemporaryDirectory() as temp:
            output = Path(temp) / 'exports/flow.html'
            export_system_flow(output)
            self.assert_export_equivalent(output)

    def test_offline_refresh_replaces_stale_content_and_css(self):
        from personal_jobby.export_system_flow import export_system_flow
        with TemporaryDirectory() as temp:
            output = Path(temp) / 'exports/flow.html'
            output.parent.mkdir(mode=0o755)
            output.write_text('<style>stale CSS</style>stale HTML')
            output.chmod(0o644)
            export_system_flow(output)
            self.assert_export_equivalent(output)

    def test_offline_rejects_symlink_file_and_parent(self):
        from personal_jobby.export_system_flow import export_system_flow
        with TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / 'target.html'
            target.write_text('untouched')
            output = root / 'flow.html'
            output.symlink_to(target)
            with self.assertRaises(ValueError):
                export_system_flow(output)
            self.assertEqual(target.read_text(), 'untouched')
            folder = root / 'linked'
            folder.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                export_system_flow(folder / 'other.html')
            self.assertFalse((root / 'other.html').exists())


class SystemFlowRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = TestClient(create_app(Path(self.temp.name)), base_url='http://localhost')
        self.addCleanup(self.client.close)

    def test_document_assets_are_served_with_private_security_headers(self):
        for asset, mime in [(HTML, 'text/html'), (CSS, 'text/css')]:
            with self.subTest(asset=asset.name):
                response = self.client.get('/static/' + asset.name)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['content-type'].split(';')[0], mime)
                self.assertEqual(response.content, asset.read_bytes())
                self.assertEqual(response.headers['cache-control'], 'no-store')
                self.assertEqual(response.headers['x-robots-tag'], 'noindex, nofollow')
                csp = response.headers['content-security-policy']
                self.assertIn("style-src 'self'", csp)
                self.assertIn("script-src 'self'", csp)
                self.assertNotIn('unsafe-inline', csp)

    def test_unlisted_files_and_traversal_are_refused(self):
        for path in [
            '/static/unknown.html', '/static/index.html',
            '/static/candidate.json', '/static/metadata.json',
            '/static/%2E%2E%2Fcandidate.json',
            '/static/%2E%2E%2Fmetadata.json',
            '/static/..%2Fstatic%2Fsystem-flow.html',
            '/static/system-flow.html/metadata.json',
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_document_assets_reject_foreign_host(self):
        for name in ['system-flow.html', 'system-flow.css']:
            with self.subTest(name=name):
                response = self.client.get('/static/' + name, headers={'host': 'evil.example'})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {'detail': 'Host rejected'})


if __name__ == '__main__':
    unittest.main()
