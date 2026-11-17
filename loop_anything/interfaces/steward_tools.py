"""Client delegation and management controls over the existing Run runtime."""
from loop_anything.interfaces.agent_tasks import object_schema
from loop_anything.runtime.model import Invalid


def definitions():
    text = {'type': 'string', 'minLength': 1}
    obj = {'type': 'object'}
    request = {'request_id': text, 'operation': text, 'run_id': text, 'key': text, 'title': text,
               'message': {'type': 'string'}, 'arguments': obj, 'inputs': obj,
               'created_by': {'type': 'string'}, 'bindings': obj,
               'notification_route': text, 'notification_command': {'type': 'array', 'items': text},
               'conversation_id': text, 'chat_context': obj}
    entries = [
        ('submit_run_request', 'Persist a complete user delegation. Reuse request_id on retry. Use start_run for startup in the current session; subsequent requests need run_id. Goal/constraint changes use update_timeline and its inspect-and-report notice. message/modify/explain and other substantive operations awaken the current steward with arguments and original intent. command (pause/resume/terminate/release_gate/retry_notification), update_run (metadata_revision, optional title/created_by/archived) and delete_run (metadata_revision) execute deterministically with durable receipts. Read tools are called directly and do not persist snapshots. Delete receipts remain readable after the Run is deleted. Receipt pending/processing is acceptance; completed means the request is resolved. No caller-owned entry token is returned.', request, ['request_id', 'operation'], False),
        ('read_run_request', 'Read a persisted delegation receipt, complete answer and current steward. Use after disconnect or pending; do not create another startup request.', {'request_id': text}, ['request_id'], True),
        ('reply_run_request', 'Reply to a question or cancel a pending delegation. Stable reply_id deduplicates. A reply starts a fresh steward turn with the saved request and history. Cancellation preserves already committed effects. An explicitly withdrawn progression decision may be reopened by a new reply while its Run is running or paused; its dependent work waits for the new review.', {'request_id': text, 'reply_id': text, 'message': {'type': 'string'}, 'cancel': {'type': 'boolean'}}, ['request_id', 'reply_id', 'message'], False),
        ('answer_run_request', 'Managed steward only. Persist a full question, mark the assigned request waiting_user, then finish. Complete answers are submitted as the management Task outputs.decision through report_task.', {'run_id': text, 'token': text, 'request_id': text, 'status': {'const': 'waiting_user'}, 'result': {}}, ['run_id', 'token', 'request_id', 'status', 'result'], False),
    ]
    return [{'name': name, 'description': description, 'inputSchema': object_schema(properties, required),
             'annotations': {'readOnlyHint': readonly}} for name, description, properties, required, readonly in entries]


def call(store, name, a):
    from loop_anything.runtime import steward
    if name == 'submit_run_request':
        if a['operation']=='start':raise Invalid('Use start_run from the actual registered caller session')
        required = ('run_id',)
        if any(key not in a for key in required):
            raise Invalid('Request needs ' + ', '.join(required))
        return steward.submit(store, a)
    if name == 'read_run_request':
        return steward.read_request(store, a['request_id'])
    if name == 'reply_run_request':
        return steward.follow_up(store, a['request_id'], a['reply_id'], a['message'], a.get('cancel', False))
    return steward.answer(store, a['run_id'], a['token'], a['request_id'], a['status'], a['result'])
