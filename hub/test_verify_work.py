import json
from pathlib import Path
import tempfile
import unittest
from verify_work import verify, EXPECTED

class ArtifactTests(unittest.TestCase):
    def test_waiting_then_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(verify(folder)['status'], 'waiting')
            p = Path(folder) / 'relay-proof.json'
            p.write_text(json.dumps(EXPECTED), encoding='utf-8')
            self.assertEqual(verify(folder)['status'], 'passed')

    def test_reject_bad_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'relay-proof.json'
            for body in ['x'*4097, '{"revision":1,"revision":2}',
                         json.dumps(dict(EXPECTED, revision=True)),
                         json.dumps(dict(EXPECTED, command='execute'))]:
                p.write_text(body, encoding='utf-8')
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    verify(folder)
