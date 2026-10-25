from __future__ import annotations

from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / 'skills/package-design-handoff/scripts/package_index.py'
CHECKPOINT = ROOT / 'skills/package-design-checkpoint/scripts/package_index.py'
SPEC = importlib.util.spec_from_file_location('package_index_tested', HANDOFF)
assert SPEC and SPEC.loader
INDEX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INDEX)


class PackageIndexTests(unittest.TestCase):
    def build(self, **changes):
        args = dict(project_name='Example Design', slug='example-design',
                    artifact_type='checkpoint', version='0.10.0',
                    change='Added the compact navigation and error states.',
                    payload_paths=['index.html', 'assets/logo.svg', 'notes.md'],
                    primary={'path': 'index.html', 'label': 'Review the website'},
                    created_at='2026-10-25T09:00:00+00:00',
                    docs=[{'path': '_checkpoint/CHANGELOG.md', 'label': 'Checkpoint changelog'}])
        args.update(changes)
        return INDEX.build_index(**args)

    def test_independent_skill_copies_are_identical(self):
        self.assertEqual(HANDOFF.read_bytes(), CHECKPOINT.read_bytes())

    def test_both_variants_have_the_same_sections_and_safe_defaults(self):
        sections = ['Start here', 'What changed', 'What to review', 'Current decisions / blockers',
                    'Package map', 'Verification summary', 'Documentation links']
        for kind in ['checkpoint', 'handoff']:
            with self.subTest(kind=kind):
                files = self.build(artifact_type=kind)
                self.assertEqual(set(files), INDEX.GENERATED_PATHS)
                html = files['index.html'].decode()
                offsets = [html.index(text) for text in sections]
                self.assertEqual(offsets, sorted(offsets))
                self.assertIn(kind.upper(), html)
                self.assertIn('REVIEW ONLY — DO NOT DEPLOY', html)
                self.assertEqual(html.count('<p class="empty">None</p>'), 3)
                self.assertIn('Project verification: Not run / not reported', html)
                self.assertTrue(files['README.md'].startswith(b'Open `index.html` first.\n'))
                data = json.loads(files['artifact-manifest.json'])
                self.assertEqual(data['primary']['path'], 'project/index.html')
                self.assertIsNone(data['deployment']['path'])
                self.assertEqual(data['verification']['source'], 'caller-reported')

    def test_title_does_not_append_duplicate_design_word(self):
        html = self.build(project_name='AzimuthSuborbital.com - Design')['index.html'].decode()
        self.assertIn('<title>AzimuthSuborbital.com - Design — Checkpoint 0.10.0</title>', html)
        self.assertNotIn('Design design', html)

    def test_existing_source_index_and_readme_are_separate_from_generated_guide(self):
        files = self.build(payload_paths=['index.html', 'README.md', 'assets/app.css'])
        data = json.loads(files['artifact-manifest.json'])
        paths = {row['path'] for row in data['package_map']}
        self.assertTrue({'index.html', 'README.md', 'project/', 'project/index.html', 'project/README.md', 'project/assets/', '_package/', '_checkpoint/'} <= paths)
        self.assertIn('project/README.md', {row['path'] for row in data['documentation']})
        self.assertIn('href="project/index.html"', files['index.html'].decode())

    def test_metadata_enriches_cli_targets_and_adds_evidence(self):
        files = self.build(payload_paths=['index.html', 'mobile.html', 'qa.txt'],
                           review_targets=[{'path': 'mobile.html', 'label': 'Mobile menu'}],
                           metadata={'primary': {'path': 'index.html', 'description': 'Open the responsive primary preview.'},
                                     'review_targets': [{'path': 'mobile.html', 'description': 'Compare the compact menu.'},
                                                        {'path': 'qa.txt', 'label': 'Keyboard results', 'role': 'evidence'}],
                                     'decisions': ['Choose the menu label.']})
        data = json.loads(files['artifact-manifest.json'])
        self.assertEqual(data['primary']['label'], 'Review the website')
        self.assertEqual(data['primary']['description'], 'Open the responsive primary preview.')
        self.assertEqual(data['review_targets'][0]['description'], 'Compare the compact menu.')
        self.assertEqual(data['review_targets'][1]['role'], 'evidence')
        self.assertIn('Choose the menu label.', files['index.html'].decode())

    def test_missing_primary_and_conflicting_primary_fail(self):
        for changes in [dict(primary=None), dict(primary={'path': 'missing.html', 'label': 'Missing'}),
                        dict(metadata={'primary': {'path': 'notes.md', 'label': 'Notes'}})]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.build(**changes)
        files = self.build(primary=None, metadata={'primary': {'path': 'notes.md', 'label': 'Review design notes'}})
        self.assertEqual(json.loads(files['artifact-manifest.json'])['primary']['path'], 'project/notes.md')

    def test_broken_or_escaping_declared_links_are_rejected(self):
        for path in ['missing.html', '../index.html', '/index.html', 'https://evil.test/index.html', '//evil.test/index.html', 'a\\b.html']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.build(metadata={'review_targets': [{'path': path, 'label': 'Review target'}]})
        with self.assertRaises(ValueError):
            self.build(metadata={'package_map': [{'path': 'absent', 'role': 'source', 'description': 'No such file'}]})

    def test_filename_characters_are_encoded_and_text_is_escaped(self):
        name = 'preview #1 & café.html'
        files = self.build(project_name='<script>alert(1)</script> Design',
                           payload_paths=[name], primary={'path': name, 'label': '<img src=x onerror=alert(1)>'},
                           metadata={'decisions': ['<script>no</script>']})
        html = files['index.html'].decode()
        self.assertIn('href="project/preview%20%231%20%26%20caf%C3%A9.html"', html)
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img ', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('&lt;img', html)

    def test_guide_has_accessible_offline_responsive_styling(self):
        html = self.build()['index.html'].decode()
        for marker in ['<html lang="en">', 'name="viewport"', ':focus-visible', 'a:visited', 'a:hover',
                       '@media(max-width:680px)', 'Skip to package guide', '<main id="main"', 'aria-labelledby=']:
            self.assertIn(marker, html)
        for forbidden in ['<script', '<iframe', '@import', 'url(', '<link', 'http://', 'https://']:
            self.assertNotIn(forbidden, html)

    def test_verification_is_reported_and_requires_real_evidence(self):
        for verification in [{'status': 'passed'}, {'status': 'failed', 'evidence': 'absent.txt'}, {'status': 'unknown'}]:
            with self.subTest(verification=verification), self.assertRaises(ValueError):
                self.build(metadata={'verification': verification})
        files = self.build(metadata={'verification': {'status': 'failed', 'evidence': 'notes.md', 'summary': 'Two checks failed.'}})
        html = files['index.html'].decode()
        self.assertIn('Failed (caller-reported)', html)
        self.assertIn('Two checks failed.', html)
        self.assertIn('href="project/notes.md"', html)
        report = json.loads(files['_package/verification.json'])
        self.assertEqual(report['scope'], 'packaging')
        self.assertIn('does not claim project design tests', report['publication_condition'])

    def test_deployment_requires_handoff_scoped_directory_and_passed_evidence(self):
        metadata = {'deployment': {'posture': 'deployable', 'path': 'assets'},
                    'verification': {'status': 'passed', 'evidence': 'notes.md'}}
        files = self.build(artifact_type='handoff', metadata=metadata)
        data = json.loads(files['artifact-manifest.json'])
        self.assertEqual(data['deployment']['path'], 'project/assets/')
        self.assertIn('Never deploy the package root.', files['index.html'].decode())
        for changes in [{}, {'artifact_type': 'handoff', 'metadata': {'deployment': {'posture': 'deployable', 'path': 'assets'}}},
                        {'artifact_type': 'handoff', 'metadata': {**metadata, 'decisions': ['Pick one.']}},
                        {'artifact_type': 'handoff', 'metadata': {**metadata, 'deployment': {'posture': 'deployable', 'path': 'notes.md'}}}]:
            values = {'metadata': metadata, **changes}
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.build(**values)

    def test_implementation_ready_is_not_deployment_approval(self):
        files = self.build(artifact_type='handoff', metadata={'deployment': {'posture': 'implementation-ready'}})
        html = files['index.html'].decode()
        self.assertIn('ACCEPTED — IMPLEMENTATION READY', html)
        self.assertIn('No subtree is cleared for deployment', html)

    def test_readme_keeps_caller_markdown_and_html_literal(self):
        files = self.build(project_name='[Injected](https://evil.test) <script>x</script>',
                           primary={'path': 'index.html', 'label': '[Visit](https://evil.test)'},
                           change='Changed [this](https://evil.test).')
        readme = files['README.md'].decode()
        self.assertIn(r'\[Injected\]\(https://evil.test\)', readme)
        self.assertIn(r'\[Visit\]\(https://evil.test\)', readme)
        self.assertIn('&lt;script&gt;', readme)
        self.assertNotIn('<script>', readme)

    def test_custom_documentation_and_evidence_map_entries_feed_documentation_links(self):
        files = self.build(payload_paths=['index.html', 'notes/copy-options.txt', 'reports/checks.txt'],
                           metadata={'package_map': [
                               {'path': 'notes/copy-options.txt', 'role': 'documentation', 'description': 'Wording choices for approval.'},
                               {'path': 'reports/checks.txt', 'role': 'evidence', 'description': 'Keyboard test results.'}]})
        data = json.loads(files['artifact-manifest.json'])
        docs = {row['path']: row for row in data['documentation']}
        self.assertEqual(docs['project/notes/copy-options.txt']['description'], 'Wording choices for approval.')
        self.assertIn('project/reports/checks.txt', docs)

    def test_explicit_deployment_is_annotated_without_a_map_override(self):
        files = self.build(artifact_type='handoff', payload_paths=['index.html', 'dist/site/index.html', 'qa.txt'],
                           metadata={'deployment': {'posture': 'deployable', 'path': 'dist/site'},
                                     'verification': {'status': 'passed', 'evidence': 'qa.txt'}})
        data = json.loads(files['artifact-manifest.json'])
        rows = {row['path']: row for row in data['package_map']}
        self.assertEqual(rows['project/dist/site/']['role'], 'deployable')
        self.assertEqual(rows['project/dist/']['role'], 'source')

    def test_package_map_cannot_claim_unapproved_deployable_files(self):
        with self.assertRaises(ValueError):
            self.build(metadata={'package_map': [{'path': 'assets', 'role': 'deployable', 'description': 'Ship this.'}]})
        files = self.build(metadata={'package_map': [{'path': 'assets', 'role': 'review-only', 'description': 'Visual review assets.'}]})
        self.assertIn('Visual review assets.', files['index.html'].decode())

    def test_review_only_rows_cannot_overlap_approved_deployment_subtree(self):
        for deployment_path, review_path in [('assets', 'assets'), ('assets', 'assets/logo.svg'),
                                             ('.', 'notes.md')]:
            metadata = {'deployment': {'posture': 'deployable', 'path': deployment_path},
                        'verification': {'status': 'passed', 'evidence': 'notes.md'},
                        'package_map': [{'path': review_path, 'role': 'review-only',
                                         'description': 'For review only.'}]}
            with self.subTest(deployment_path=deployment_path, review_path=review_path), self.assertRaisesRegex(ValueError, 'review-only'):
                self.build(artifact_type='handoff', metadata=metadata)
        for role in ['source', 'documentation', 'evidence']:
            metadata = {'deployment': {'posture': 'deployable', 'path': 'assets'},
                        'verification': {'status': 'passed', 'evidence': 'notes.md'},
                        'package_map': [{'path': 'assets/logo.svg', 'role': role,
                                         'description': 'Part of the approved subtree.'},
                                        {'path': 'notes.md', 'role': 'review-only',
                                         'description': 'Review-only material outside the approved subtree.'}]}
            with self.subTest(role=role):
                self.build(artifact_type='handoff', metadata=metadata)

    def test_unknown_fields_duplicates_and_invalid_types_fail(self):
        for metadata in [{'surprise': True}, {'decisions': 'None'}, {'review_checklist': []},
                         {'verification': {'status': 'not-run', 'passed': True}},
                         {'review_targets': [{'path': 'notes.md', 'label': 'Notes'}, {'path': 'notes.md', 'label': 'Other'}]}]:
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                self.build(metadata=metadata)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'metadata.json'
            source.write_text('{"decisions": [], "decisions": []}')
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                INDEX.load_metadata(source)
            source.write_text('[]')
            with self.assertRaises(ValueError):
                INDEX.load_metadata(source)
        self.assertEqual(INDEX.load_metadata(None), {})

    def test_nonstring_enums_fail_with_controlled_validation_errors(self):
        for value in [[], {}, False, 1]:
            metadata_cases = [
                {'verification': {'status': value}},
                {'verification': {'evidence': value}},
                {'deployment': {'posture': value}},
                {'review_targets': [{'path': 'notes.md', 'label': 'Review notes', 'role': value}]},
                {'package_map': [{'path': 'notes.md', 'role': value, 'description': 'Review notes.'}]},
            ]
            for metadata in metadata_cases:
                with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                    self.build(metadata=metadata)

    def test_validate_rejects_missing_files_unmapped_entries_and_remote_html(self):
        generated = self.build()
        names = set(generated) | {'project/index.html', 'project/assets/logo.svg', 'project/notes.md', '_checkpoint/CHANGELOG.md'}
        INDEX.validate_index(generated, names)
        with self.assertRaises(ValueError):
            INDEX.validate_index(generated, names - {'project/index.html'})
        with self.assertRaises(ValueError):
            INDEX.validate_index(generated, names | {'surprise.txt'})
        bad = dict(generated)
        bad['index.html'] = generated['index.html'].replace(b'href="project/index.html"', b'href="https://evil.test/"')
        with self.assertRaises(ValueError):
            INDEX.validate_index(bad, names)


if __name__ == '__main__':
    unittest.main()
