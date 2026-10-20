from communication_helpers import legacy_offer
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from loop_anything.runtime.communication import Communication, publish_message, read_message
from loop_anything.runtime.communication_archive import drain
from loop_anything.runtime.store import Store
from loop_anything.runtime.model import Conflict


class CommunicationArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.a, self.b = [Communication(Store(self.root / (name + '.db'))) for name in ('a', 'b')]
        config = self.a.config('group', path=str(self.root / 'nas'), create=True)['configuration']
        self.gid = next(iter(config['groups']))
        self.b.config('group', path=str(self.root / 'nas'))
        self.aid, self.bid = [c.settings()['instance_id'] for c in (self.a, self.b)]
        self.row = dict(id='request-test', origin=self.aid, executor=self.bid,
                        group_id=self.gid, assignment_id='assignment-test', state='assigned')
        with self.a.transaction() as db:
            self.a.save(db, self.row)
        # Complete initial legacy reconciliation before measuring ordinary scans.
        self.scan(self.a, self.b)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def scan(*instances):
        for comm in instances:
            comm.last_scan = 0
            comm.scan()
            if getattr(comm, 'transport_error', None):
                raise AssertionError(comm.transport_error)

    def progress(self, text='working', sequence=1):
        with self.b.transaction() as db:
            ident = self.b.emit(db, self.row, self.aid, 'progress',
                               dict(sequence=sequence, state='running', progress={'text': text}))
            message = json.loads(db.execute('SELECT document FROM communication_outbox WHERE id=?', (ident,)).fetchone()[0])
        return message

    def hot(self, message):
        return self.root / 'nas' / 'messages' / message['target'] / (message['id'] + '.json')

    def archived(self, message):
        files = list((self.root / 'nas' / 'archive').glob('*/*/' + message['id'] + '.json'))
        self.assertEqual(len(files), 1)
        self.assertEqual(read_message(files[0]), message)

    def receipt(self, message):
        with self.a.store.connection() as db:
            return json.loads(db.execute("SELECT document FROM communication_outbox WHERE json_extract(document,'$.payload.message_id')=?", (message['id'],)).fetchone()[0])

    def test_confirmed_messages_and_receipts_leave_hot_scan_without_reexecution(self):
        messages = [self.progress(sequence=i) for i in range(1, 21)]
        message = messages[-1]
        self.scan(self.b, self.a, self.a, self.b, self.a, self.b)
        for delivered in messages:
            self.archived(delivered)
            self.archived(self.receipt(delivered))
        self.assertFalse(list((self.root / 'nas' / 'messages').glob('*/*.json')))
        with patch('loop_anything.runtime.communication.read_message', wraps=read_message) as reads:
            self.scan(self.a, self.b, self.a, self.b)
            self.assertEqual(reads.call_count, 0)
        before = self.a.get(self.row['id'])
        # A delayed duplicate still gets a receipt and cannot repeat its effect.
        publish_message(self.hot(message), message)
        self.scan(self.a, self.a, self.b)
        self.assertEqual(self.a.get(self.row['id']), before)

    def test_lost_receipt_is_republished_identically_after_receiver_restart(self):
        message = self.progress()
        self.scan(self.b, self.a, self.a)
        ack = self.receipt(message)
        self.hot(ack).unlink()
        self.a = Communication(Store(self.a.store.filename))
        before = self.a.get(self.row['id'])
        self.scan(self.a, self.a, self.b)
        self.archived(message)
        self.archived(ack)
        self.assertEqual(self.a.get(self.row['id']), before)

    def test_wrong_receipt_scope_cannot_retire_a_pending_message(self):
        message = self.progress()
        self.scan(self.b, self.a)
        ack = self.receipt(message)
        for field in ('group_id', 'request_id', 'assignment_id', 'sender', 'target'):
            with self.subTest(field=field), self.assertRaises(Conflict):
                self.b.receive(dict(ack, **{field: 'wrong-identity'}))
            with self.b.store.connection() as db:
                self.assertIsNotNone(db.execute('SELECT 1 FROM communication_outbox WHERE id=?', (message['id'],)).fetchone())
                self.assertEqual(db.execute('SELECT count(*) FROM communication_archive_queue').fetchone()[0], 0)
            self.assertTrue(self.hot(message).exists())
        self.b.receive(ack)
        self.scan(self.b)
        self.archived(message)

    def test_archive_failure_and_multipart_cleanup_resume_after_restart(self):
        message = self.progress('large' * 300000)
        self.scan(self.b, self.a, self.a)
        ack = self.receipt(message)
        self.b.receive(ack)
        with patch('loop_anything.runtime.communication.publish_message', side_effect=OSError('NAS unavailable')):
            drain(self.b, self.root / 'nas', self.gid)
        self.assertIn('NAS unavailable', self.b.transport_error)
        self.assertTrue(self.hot(message).exists())
        unlink = Path.unlink
        def interrupted(path, *args, **kwargs):
            if path == self.hot(message):raise OSError('Stopped after archive publication')
            return unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', interrupted):
            drain(self.b, self.root / 'nas', self.gid)
        self.archived(message)
        self.assertTrue(self.hot(message).exists())
        self.b = Communication(Store(self.b.store.filename))
        self.scan(self.b)
        self.archived(message)
        self.assertFalse(self.hot(message).exists())
        self.assertFalse(list(self.hot(message).parent.glob(message['id'] + '-part-*.bin')))
        with self.b.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM communication_archive_queue').fetchone()[0], 0)

    def test_archive_error_does_not_block_new_delivery(self):
        message = self.progress()
        self.scan(self.b, self.a, self.a)
        self.b.receive(self.receipt(message))
        following = self.progress('next update', sequence=2)
        with patch('loop_anything.runtime.communication_archive.archive', side_effect=OSError('Archive read-only')):
            self.b.last_scan = 0
            self.b.scan()
        self.assertTrue(self.hot(following).exists())
        self.assertIn('Archive read-only', self.b.transport_error)
        self.scan(self.a)
        self.assertEqual(self.a.get(self.row['id'])['progress']['text'], 'next update')

    def test_active_broadcast_remains_until_source_cancels_and_old_files_are_retired(self):
        request = legacy_offer(self.a,location='group', group_id=self.gid, agent_id='missing', message='wait')['request']
        self.scan(self.a, self.b)
        with self.a.store.connection() as db:
            message = json.loads(db.execute("SELECT document FROM communication_outbox WHERE json_extract(document,'$.kind')='offer'").fetchone()[0])
        self.assertTrue(self.hot(message).exists())
        self.a.control(request['id'], 'cancel', reason='Withdrawn by user')
        self.scan(self.a)
        self.assertFalse(self.hot(message).exists())
        self.archived(message)
        # Simulate an old release leaving a settled broadcast in the active folder.
        publish_message(self.hot(message), message)
        self.a = Communication(Store(self.a.store.filename))
        self.scan(self.a)
        self.assertFalse(self.hot(message).exists())
        self.assertEqual(self.a.get(request['id'])['state'], 'cancelled')

    def test_source_archives_granted_and_expired_announcements(self):
        from loop_anything.runtime.engine import Engine
        # This case uses real requests; discard the packet-only fixture row.
        with self.a.transaction() as db:
            db.execute('DELETE FROM communication_requests WHERE id=?', (self.row['id'],))
        engine = Engine(self.a.store)
        engine.communication = self.a
        self.a.engine = engine
        try:
            granted, expired = [legacy_offer(self.a,location='group', group_id=self.gid,
                agent_id='papers', message=label)['request'] for label in ('assign', 'expire')]
            self.scan(self.a)
            with self.a.store.connection() as db:
                offers = [json.loads(row[0]) for row in db.execute("SELECT document FROM communication_outbox WHERE json_extract(document,'$.kind')='offer'")]
            self.a.receive(dict(id='claim-test', sender=self.bid, target=self.aid,
                request_id=granted['id'], group_id=self.gid, assignment_id=None,
                kind='claim', payload={'agent_id': 'papers'}))
            with patch('loop_anything.runtime.communication.time.time', return_value=expired['deadline'] + 1):
                self.a.tick()
            self.scan(self.a)
            self.assertIsNotNone(self.a.get(granted['id']).get('assignment_id'))
            self.assertEqual(self.a.get(expired['id'])['state'], 'unavailable')
            for offer in offers:
                self.archived(offer)
                self.assertFalse(self.hot(offer).exists())
        finally:
            engine.close()

    def test_sent_receipts_do_not_periodically_republish_and_unsent_survives_restart(self):
        message = self.progress()
        self.scan(self.b, self.a)
        ack = self.receipt(message)
        self.a = Communication(Store(self.a.store.filename))
        self.scan(self.a)
        self.assertTrue(self.hot(ack).exists())
        # Source consumes the ACK without another receive of the original message.
        self.scan(self.b, self.a, self.b)
        with patch('loop_anything.runtime.communication.time.time', return_value=time.time() + 10), \
             patch('loop_anything.runtime.communication.publish_message', wraps=publish_message) as writes:
            self.scan(self.a)
        self.assertFalse(any(call.args[1].get('kind') == 'ack' for call in writes.call_args_list))


if __name__ == '__main__':
    unittest.main()
