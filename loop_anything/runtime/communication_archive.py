"""Retire delivered transport files without discarding communication history."""
import json
import time


def enqueue(db, message):
    db.execute('INSERT OR IGNORE INTO communication_archive_queue VALUES (?,?)',
               (message['id'], json.dumps(message)))


def retire(db, where, parameters):
    # Callers supply only internal SQL predicates. Journal before removing retries.
    rows = db.execute('SELECT document FROM communication_outbox WHERE ' + where, parameters).fetchall()
    for row in rows:
        enqueue(db, json.loads(row[0]))
    db.execute('DELETE FROM communication_outbox WHERE ' + where, parameters)


def acknowledge(db, receipt):
    row = db.execute('SELECT document FROM communication_outbox WHERE id=?',
                     (receipt['payload']['message_id'],)).fetchone()
    if not row:return
    message = json.loads(row[0])
    expected = dict(sender=message['target'], target=message['sender'],
                    group_id=message['group_id'], request_id=message['request_id'],
                    assignment_id=message.get('assignment_id'))
    if any(receipt.get(key) != value for key, value in expected.items()):
        from loop_anything.runtime.model import Conflict
        raise Conflict('Receipt does not match the pending publication')
    retire(db, 'id=?', (message['id'],))


def reconcile_legacy(comm, root, group_id, instance):
    """Once per mount/process, retire old publications already settled in SQLite."""
    from loop_anything.runtime.communication import read_message
    key = (group_id, str(root))
    if key in comm.archive_scanned_groups:
        return
    for path in (root / 'messages').glob('*/*.json'):
        try:
            message = read_message(path)
        except (OSError, ValueError):
            continue
        if not isinstance(message, dict) or message.get('group_id') != group_id:
            continue
        if path.stem != message.get('id') or path.parent.name != message.get('target'):
            continue
        with comm.transaction() as db:
            if message.get('sender') == instance and message.get('kind') != 'ack':
                pending = db.execute('SELECT 1 FROM communication_outbox WHERE id=?', (message['id'],)).fetchone()
                if not pending:
                    enqueue(db, message)
            elif message.get('target') == instance and message.get('kind') == 'ack':
                received = db.execute('SELECT document FROM communication_inbox WHERE id=?', (message['id'],)).fetchone()
                if received and json.loads(received[0]) == message:
                    enqueue(db, message)
    comm.archive_scanned_groups.add(key)


def drain(comm, root, group_id):
    """Archive from durable content first, then remove the hot copy, then the journal."""
    from loop_anything.runtime.communication import identifier, read_message
    with comm.store.connection() as db:
        instance = comm.settings(db)['instance_id']
        messages = [json.loads(r[0]) for r in db.execute(
            """SELECT document FROM communication_archive_queue WHERE json_extract(document,'$.group_id')=?
            AND ((json_extract(document,'$.kind')='ack' AND json_extract(document,'$.target')=?)
              OR (json_extract(document,'$.kind')!='ack' AND json_extract(document,'$.sender')=?))""", (group_id, instance, instance))]
    for message in messages:
        try:
            if message['kind'] == 'ack':
                # A delayed duplicate publication may outlive the source outbox row.
                # Its receipt still authorizes retiring that exact source-owned file.
                original = root / 'messages' / identifier(message['sender']) / (identifier(message['payload']['message_id']) + '.json')
                try:
                    duplicate = read_message(original)
                except FileNotFoundError:
                    duplicate = None
                if duplicate is not None:
                    if any(duplicate.get(k) != v for k, v in {
                            'id': message['payload']['message_id'], 'sender': message['target'],
                            'target': message['sender'], 'group_id': group_id,
                            'request_id': message['request_id'], 'assignment_id': message.get('assignment_id')}.items()):
                        from loop_anything.runtime.model import Conflict
                        raise Conflict('Receipt does not match the pending publication')
                    archive(root, duplicate)
            archive(root, message)
            with comm.transaction() as db:
                db.execute('DELETE FROM communication_archive_queue WHERE id=?', (message['id'],))
        except (OSError, ValueError) as exc:
            comm.transport_error = "Message archive pending: " + str(exc)


def archive(root, message):
    from loop_anything.runtime.communication import identifier, publish_message
    ident, target = identifier(message['id']), identifier(message['target'])
    day = time.strftime('%Y-%m-%d', time.gmtime(message.get('at', 0)))
    destination = root / 'archive' / day / target / (ident + '.json')
    publish_message(destination, message)
    source = root / 'messages' / target / (ident + '.json')
    # A reader racing removal retries from its durable sender; the business
    # effect was committed before this journal entry could be created.
    source.unlink(missing_ok=True)
    size = len(json.dumps(message, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    if size > 1_000_000:
        for index in range((size + 524287) // 524288):
            source.with_name(ident + '-part-' + str(index) + '.bin').unlink(missing_ok=True)
