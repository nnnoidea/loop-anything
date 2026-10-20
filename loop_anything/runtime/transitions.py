"""Pure lifecycle decisions. No Timeline mutation, persistence, clock or dispatch.

The writer supplies facts and validates proposed retry parameters/notifications
against its contracts before applying effects in the existing transaction.
"""
import copy

from loop_anything.runtime.checks import evaluate
from loop_anything.runtime.timeline_model import expand


def decide_transition(lifecycle, state, event, context, parameters):
    candidates = [r for r in lifecycle['transitions'] if r['from'] == state and r['event'] == event]
    matches, issue = [], None
    try:
        matches = [r for r in candidates if 'when' not in r or evaluate(r['when'], context) is True]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        issue = 'Invalid transition condition: ' + str(exc)
    if len(matches) != 1 and issue is None:
        issue = ('Ambiguous transitions' if len(matches) > 1 else 'No matching transition' if candidates else 'Uncovered transition') + ': ' + state + ' + ' + event
    rule = matches[0] if len(matches) == 1 and issue is None else None
    parameters = copy.deepcopy(parameters)
    if rule and rule['to'] == 'retry':
        try:
            parameters.update(expand(rule.get('parameters', {}), context))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            issue = 'Invalid retry parameters: ' + str(exc)
    notices, notice_issue = [], None
    if rule and issue is None:
        try:
            notices = expand(rule.get('notify', []), context)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            notice_issue = 'Invalid notification parameters: ' + str(exc)
    # Keep notice expansion failure separate: retry contract failures take priority.
    return {'state': state, 'event': event, 'rule': copy.deepcopy(rule),
            'matches': copy.deepcopy(matches), 'issue': issue, 'parameters': parameters,
            'notices': notices, 'notice_issue': notice_issue}


def transition_effects(decision, report, kind, external_id, delay, now, issue=None):
    """Return state changes after the writer has validated all proposed actions.

    `now` is supplied by the caller. An accepted completion still requires the
    writer to commit its output envelope; this function never fabricates results.
    """
    issue = issue or decision['issue'] or decision['notice_issue']
    rule, event = decision['rule'], decision['event']
    accepted = rule is not None and issue is None
    target = rule['to'] if accepted else decision['state']
    execution, task, remove = {}, {}, []
    detail = report.get('detail', {})
    if event == 'check_error':
        execution['observation_error'] = str(detail.get('message') or 'Observation failed; external state is unknown')
    if accepted:
        if event != 'check_error':
            remove.append('observation_error')
        if target in ('fault', 'retry', 'agent'):
            execution.update(status='fault', error=str(detail.get('message') or event))
            task['status'] = 'retrying' if target == 'retry' else 'fault'
            if target == 'retry':
                execution['retry'] = {'status': 'pending', 'report_id': report['report_id'],
                                      'parameters': copy.deepcopy(decision['parameters'])}
                task['wait_reasons'] = [{'reason': 'retry_pending', 'detail': 'Waiting for process exit and operation scope before retry'}]
        elif target != 'completed' and kind == 'external' and external_id:
            execution.update(external_id=external_id, poll_after=delay, wake_at=now + delay, status='waiting')
            task['status'] = 'waiting'
        execution['lifecycle_state'] = target
    else:
        execution.update(status='fault', error=issue or 'Transition did not match')
        task['status'] = 'fault'
    return {'accepted': accepted, 'target': target, 'execution': execution, 'task': task,
            'remove_execution': remove, 'complete': accepted and target == 'completed'}
