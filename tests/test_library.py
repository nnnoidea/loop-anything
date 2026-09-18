"""Optional user documentation is portable metadata, not executable policy."""
import copy
import unittest

from loop_anything.runtime.model import validate
from loop_anything.runtime.timeline_model import validate_v2
from loop_anything.packaging.packages import make_archive, read_archive
from test_packages import document
from test_loop_definition_authoring import definition


class LibraryGuideTests(unittest.TestCase):
    def test_guide_survives_package_round_trip_without_changing_tasks(self):
        doc = document()
        before = copy.deepcopy(doc['loop_definition']['seed'])
        doc['loop_definition']['guide'] = {
            'purpose': 'For people receiving this loop', 'effects': 'Scripts execute locally',
            'parameters': {'request': {'label': '研究目标', 'description': 'What to investigate'}}}
        unpacked, _, _, _ = read_archive(make_archive(doc))
        self.assertEqual(unpacked['loop_definition']['guide'], doc['loop_definition']['guide'])
        self.assertEqual(unpacked['loop_definition']['seed'], before)

    def test_old_loop_definitions_need_no_guide(self):
        doc = document()
        self.assertTrue(validate_v2(doc['loop_definition'], doc['implementations'])['valid'])
        bp = definition()
        self.assertTrue(validate(bp, {n: {'kind': 'agent'} for n in bp['nodes']})['valid'])

    def test_malformed_guides_rejected_in_both_versions(self):
        for guide in [None, [], {'purpose': {}}, {'parameters': []},
                      {'parameters': {'x': {'type': 'string'}}}, {'execute': 'command'}]:
            with self.subTest(guide=guide):
                doc = document(); doc['loop_definition']['guide'] = guide
                self.assertFalse(validate_v2(doc['loop_definition'], doc['implementations'])['valid'])
                bp = definition(); bp['guide'] = guide
                self.assertFalse(validate(bp, {n: {'kind': 'agent'} for n in bp['nodes']})['valid'])
