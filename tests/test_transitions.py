"""Lifecycle calculations accept data only and leave the caller's state untouched."""
import copy
import unittest

from loop_anything.runtime.lifecycle import template
from loop_anything.runtime.transitions import decide_transition, transition_effects


class TransitionTests(unittest.TestCase):
    def calculate(self, lifecycle, state, event, *, kind='external', external_id='job-1',
                  context=None, parameters=None, issue=None):
        context = context or {'inputs': {}, 'parameters': {}, 'settings': {}, 'detail': {},
                              'outputs': {}, 'attempt': 1, 'task_revision': 1}
        parameters = parameters or {'batch': 4}
        report = {'event': event, 'report_id': 'report-1', 'detail': context['detail']}
        before = copy.deepcopy((lifecycle, context, parameters, report))
        decision = decide_transition(lifecycle, state, event, context, parameters)
        effects = transition_effects(decision, report, kind, external_id, 60, 1000, issue=issue)
        self.assertEqual((lifecycle, context, parameters, report), before)
        self.assertEqual(decision, decide_transition(lifecycle, state, event, context, parameters))
        return decision, effects

    def test_wait_completion_and_observation_failure_have_distinct_effects(self):
        for event, state in [('submitted', 'submitting'), ('progress', 'waiting'), ('check_error', 'waiting')]:
            _, effects = self.calculate(template('external'), state, event)
            self.assertTrue(effects['accepted'])
            self.assertEqual(effects['execution']['wake_at'], 1060)
            self.assertEqual(effects['execution']['external_id'], 'job-1')
            self.assertEqual(effects['task']['status'], 'waiting')
            if event == 'check_error':
                self.assertIn('observation_error', effects['execution'])
                self.assertEqual(effects['remove_execution'], [])
            else:
                self.assertEqual(effects['remove_execution'], ['observation_error'])
        _, done = self.calculate(template('command'), 'executing', 'completed', kind='command', external_id=None)
        self.assertTrue(done['complete'])
        self.assertEqual(done['execution'], {'lifecycle_state': 'completed'})
        self.assertEqual(done['task'], {})  # Only the writer can validate and commit the result.

    def test_retry_and_agent_handoff_do_not_dispatch_or_modify_parameters(self):
        matrix = {'initial': 'waiting', 'transitions': [
            {'from':'waiting','event':'failed','to':'retry',
             'when':{'op':'le','args':[{'path':'attempt'},2]}, 'parameters':{'batch':{'$':'detail.batch'}},
             'notify':[{'message':'Attempt {attempt} failed'}]},
            {'from':'waiting','event':'failed','to':'agent',
             'when':{'op':'ge','args':[{'path':'attempt'},3]}}]}
        context = {'attempt':1,'detail':{'batch':2}}
        decision, retry = self.calculate(matrix, 'waiting', 'failed', context=context)
        self.assertEqual(decision['parameters'], {'batch':2})
        self.assertEqual(decision['notices'], [{'message':'Attempt 1 failed'}])
        self.assertEqual(retry['execution']['retry'], {'status':'pending','report_id':'report-1','parameters':{'batch':2}})
        self.assertEqual(retry['task']['status'], 'retrying')
        context['attempt'] = 3
        _, handoff = self.calculate(matrix, 'waiting', 'failed', context=context)
        self.assertEqual(handoff['execution']['lifecycle_state'], 'agent')
        self.assertEqual(handoff['task']['status'], 'fault')
        self.assertNotIn('retry', handoff['execution'])

    def test_uncovered_ambiguous_and_invalid_conditions_keep_original_lifecycle(self):
        row = {'from':'review','event':'reply','to':'approved'}
        for rows, event, message in [([], 'reply', 'Uncovered'), ([row,row], 'reply', 'Ambiguous'),
                ([dict(row, when={'path':'absent'})], 'reply', 'Invalid transition condition'),
                ([dict(row, when={'op':'eq','args':[1,2]})], 'reply', 'No matching')]:
            decision, effects = self.calculate({'transitions':rows}, 'review', event, kind='event', external_id=None)
            self.assertIn(message, decision['issue'])
            self.assertFalse(effects['accepted'])
            self.assertEqual(effects['target'], 'review')
            self.assertNotIn('lifecycle_state', effects['execution'])
            self.assertEqual(effects['task']['status'], 'fault')

    def test_same_evaluator_handles_other_business_states_and_writer_rejections(self):
        matrix = {'transitions':[{'from':'review','event':'reply','to':'approved'}]}
        _, effects = self.calculate(matrix, 'review', 'reply', kind='event', external_id=None)
        self.assertEqual(effects['execution'], {'lifecycle_state':'approved'})
        self.assertFalse(effects['complete'])
        matrix = {'transitions':[{'from':'waiting','event':'failed','to':'retry',
                                 'notify':[{'message':{'$':'missing'}}]}]}
        decision, effects = self.calculate(matrix, 'waiting', 'failed', issue='Invalid retry parameters: batch')
        self.assertIn('Invalid notification parameters', decision['notice_issue'])
        self.assertEqual(effects['execution']['error'], 'Invalid retry parameters: batch')
        self.assertNotIn('retry', effects['execution'])
