"""Persist a pre-upgrade offer to test the legacy protocol without publishing new ones."""
import json
from unittest.mock import patch
from loop_anything.runtime.communication import clean


def legacy_offer(comm, **arguments):
    # Build a pre-directory-protocol fixture, not a new production dispatch.
    with patch('loop_anything.runtime.dispatch.choose',return_value={'id':arguments.get('agent_id','papers'),'instance_id':'legacy-unselected'}):
        created=comm.request(dict(arguments,instance_id='legacy-unselected'))
    ident=created['request']['id']
    with comm.transaction() as db:
        row=comm.get(ident,db)
        for key in ('protocol','executor','assignment_id','target_instance'):row.pop(key,None)
        row['state']='pending'
        db.execute("DELETE FROM communication_outbox WHERE json_extract(document,'$.request_id')=?",(ident,))
        comm.emit(db,row,'broadcast','offer',clean(row))
        comm.save(db,row)
    return dict(comm.read(ident),request_token=created['request_token'])


def notification_groups(self):
    from test_communication import CommunicationTests
    from loop_anything.runtime.team_transport import connect
    gid=CommunicationTests.groups(self)
    group=self.a.settings()['groups'][gid]
    connect(group).put('members/notification-fixture.json',{
        'instance_id':'notification-fixture','revision':'fixture','updated_at':0,
        'agents':[{'id':'papers','instance_id':'notification-fixture','name':'Notification fixture',
                   'description':'Return the notification test result','enabled':True}]})
    return gid
