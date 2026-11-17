import tempfile
import unittest
from pathlib import Path
from knowledge import add, export, handoff, records

class KnowledgeTests(unittest.TestCase):
    def test_correction_trust_and_sharing(self):
        with tempfile.TemporaryDirectory() as d:
            r = dict(id='original', case='case', kind='hypothesis', title='test',
                     body='old', author='agent', source='test', trust='verified')
            self.assertEqual(add(d, r)['trust'], 'unverified')
            with self.assertRaises(ValueError): handoff(d, 'case', True)
            add(d, dict(r, id='correction', body='new', supersedes='original'))
            output = handoff(d, 'case')
            self.assertIn('"current": false', output)
            self.assertIn('"current": true', output)
            with self.assertRaises(ValueError):
                add(d, dict(r, id='fork', supersedes='original'))
            with self.assertRaises(ValueError):
                add(d, dict(r, id='cross', case='other', supersedes='correction'))
            with self.assertRaises(ValueError):
                add(d, dict(r, id='huge', body='x'*12001))

    def test_handoff_never_silently_truncates(self):
        with tempfile.TemporaryDirectory() as d:
            for n in range(4):
                add(d, dict(id='record-'+str(n), case='large', kind='hypothesis',
                            title='test', body='x'*8500, author='agent', source='test',
                            sensitivity='shareable'))
            with self.assertRaises(ValueError): handoff(d, 'large', True)

    def test_full_flow_and_protection(self):
        with tempfile.TemporaryDirectory() as d:
            r = dict(id='direction-1', case='agents', kind='direction', title='目的',
                     body='両AIが実作業する', author='user', source='conversation')
            add(d, r)
            with self.assertRaises(FileExistsError):
                add(d, r)
            proposal = dict(r, id='proposal-1', kind='proposal', refs=['direction-1'],
                            expected_effect='引き継ぎ可能', effort='1案件', acceptance='別AIが記録を参照',
                            status='approved')
            self.assertEqual(add(d, proposal)['status'], 'proposed')
            self.assertIn('両AIが実作業する', handoff(d, 'agents'))
            dest = Path(d) / 'vault'
            self.assertEqual(export(d, dest), 2)
            self.assertIn('[[direction-1]]', (dest/'proposal-1.md').read_text(encoding='utf-8'))
            with self.assertRaises(FileExistsError):
                export(d, dest)
            self.assertEqual(len(records(d)), 2)

    def test_reject_invalid_evidence_and_paths(self):
        with tempfile.TemporaryDirectory() as d:
            r = dict(id='../escape', case='agents', kind='decision', title='x', body='x', author='x', source='x')
            with self.assertRaises(ValueError): add(d, r)
            r['id'] = 'valid'
            r['refs'] = ['missing']
            with self.assertRaises(ValueError): add(d, r)
            with self.assertRaises(ValueError): handoff(d, 'unknown')
            r['refs'] = []
            r['kind'] = 'proposal'
            with self.assertRaises(ValueError): add(d, r)

if __name__ == '__main__': unittest.main()
