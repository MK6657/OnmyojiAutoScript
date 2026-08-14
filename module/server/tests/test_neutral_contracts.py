import json
import re
import unittest
from pathlib import Path


CONTRACT_ROOT = Path(__file__).resolve().parents[3] / 'handoff' / 'contracts' / 'v1'


class NeutralContractTest(unittest.TestCase):
    def test_contract_definitions_and_examples_are_complete(self):
        schema = json.loads((CONTRACT_ROOT / 'contracts.schema.json').read_text(encoding='utf-8'))
        examples = json.loads((CONTRACT_ROOT / 'examples.json').read_text(encoding='utf-8'))
        expected = {
            'DeviceIdentity',
            'FrameEnvelope',
            'CandidateEnvelope',
            'EvidenceManifest',
            'BattlePreparationResult',
        }

        self.assertEqual(set(schema['$defs']), expected)
        self.assertEqual(set(examples), expected)
        for name in expected:
            required = set(schema['$defs'][name]['required'])
            self.assertTrue(required.issubset(examples[name]), name)

    def test_examples_preserve_read_only_and_hash_boundaries(self):
        examples = json.loads((CONTRACT_ROOT / 'examples.json').read_text(encoding='utf-8'))
        sha256 = re.compile(r'^[0-9a-f]{64}$')

        frame = examples['FrameEnvelope']
        candidate = examples['CandidateEnvelope']
        self.assertRegex(frame['sha256'], sha256)
        self.assertEqual(candidate['source_frame_sha256'], frame['sha256'])
        self.assertEqual(candidate['source_frame_id'], frame['frame_id'])
        self.assertEqual(candidate['apply_state'], 'candidate_only')
        self.assertNotIn('absolute_path', candidate)
        self.assertNotIn('oas_write_path', candidate)
        self.assertTrue(frame['artifact_ref'].startswith('artifact://'))

    def test_device_aliases_do_not_claim_stable_identity(self):
        device = json.loads((CONTRACT_ROOT / 'examples.json').read_text(encoding='utf-8'))['DeviceIdentity']

        self.assertGreaterEqual(len(device['serial_aliases']), 2)
        self.assertNotEqual(device['stability'], 'stable')
        self.assertTrue(device['claims'])


if __name__ == '__main__':
    unittest.main()
