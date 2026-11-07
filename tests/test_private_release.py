"""Check the private dependency route and publication barrier in release validation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/private-release.yml'


class PrivateReleaseTests(unittest.TestCase):
    def setUp(self):
        self.data = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)

    def test_every_source_job_fetches_private_dependency_without_public_caches(self):
        for name in ('git-sources', 'macos', 'windows', 'linux', 'freebsd', 'web', 'linux-riscv64', 'server'):
            with self.subTest(job=name):
                steps = self.data['jobs'][name]['steps']
                fetch = [step for step in steps if step.get('uses') == './.github/actions/fetch-eridu-style']
                self.assertEqual(len(fetch), 1)
                self.assertEqual(fetch[0]['with']['ssh-key'], '${{ secrets.ERIDU_STYLE_DEPLOY_KEY }}')
                self.assertFalse(any('rust-cache' in step.get('uses', '') or 'freebsd-cargo-cache' in step.get('uses', '') for step in steps))
        freebsd = self.data['jobs']['freebsd']['steps']
        vm = next(step for step in freebsd if step.get('name') == 'Start the FreeBSD VM')
        self.assertEqual(vm['with']['sync'], 'rsync')
        build = next(step for step in freebsd if step.get('name') == 'Build and package')
        self.assertIn('GIT_CONFIG_KEY_0="url.file://$PWD/.git/ci-eridu-style.insteadOf"', build['run'])

    def test_validation_blocks_release_version_and_publication(self):
        self.assertEqual(self.data['jobs']['version']['if'], '${{ !inputs.validate-only }}')
        self.assertIn('!inputs.validate-only', self.data['jobs']['release']['if'])
        jobs = self.data['jobs']
        for name in ('macos', 'windows', 'linux', 'flatpak', 'arch', 'freebsd', 'web', 'linux-riscv64', 'server'):
            self.assertIn('version', jobs[name]['needs'])
        for name in ('validate-native', 'validate-freebsd'):
            self.assertIn('inputs.validate-only', jobs[name]['if'])
            uses = [step.get('uses', '') for step in jobs[name]['steps']]
            self.assertFalse(any('upload-artifact' in action or 'draft-release' in action for action in uses))

    def test_only_exact_reviewed_package_sources_pass(self):
        step = next(step for step in self.data['jobs']['git-sources']['steps'] if 'run' in step)
        script = step['run'].split("<<'PYTHON'\n", 1)[1].split('\nPYTHON', 1)[0]
        source = 'git+https://github.com/tomblanchard312/eridu-style?rev=abc#abc'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Cargo.lock').write_text(f'[[package]]\nname="eridu-style"\nsource="{source}"\n')
            environment = {**os.environ, 'ALLOWED_GIT_PACKAGES': json.dumps([['eridu-style', source]])}
            def check():
                return subprocess.run([sys.executable, '-c', script], cwd=root, env=environment, capture_output=True)
            self.assertEqual(check().returncode, 0)
            environment['ALLOWED_GIT_PACKAGES'] = json.dumps([['other-package', source]])
            self.assertNotEqual(check().returncode, 0)
            environment['ALLOWED_GIT_PACKAGES'] = json.dumps([['eridu-style', source + 'different']])
            self.assertNotEqual(check().returncode, 0)
            environment['ALLOWED_GIT_PACKAGES'] = json.dumps([['eridu-style', source]])
            (root / '.cargo').mkdir()
            (root / '.cargo/config.toml').write_text('[source.crates-io]\nreplace-with="other"\n')
            self.assertNotEqual(check().returncode, 0)


if __name__ == '__main__':
    unittest.main()
