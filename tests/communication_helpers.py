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
