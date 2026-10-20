"""Human-facing Base columns/views. Routing still uses the shared transport protocol."""
import json
import time
from urllib.parse import urlparse, urlencode

FIELDS={name:1 for name in ('名称','记录类型','主要任务','Agent ID','机器 ID','请求 ID','状态','请求内容','完整回复','更新时间')}
STATES={'pending':'等待接单','assigned':'已接单','starting':'启动中','running':'执行中','completed':'已完成',
        'failed':'失败','cancelled':'已取消','unavailable':'不可用','unknown':'执行状态待核实'}


def text(value, limit=90000):
    body=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2)
    if len(body.encode('utf-16-le'))//2<=limit:return body
    return '内容较长，请用 read / wait 按请求 ID 读取完整内容；如有附件，工具会自动下载。'


def columns(key, value):
    row={name:'' for name in FIELDS}
    row.update(名称=key.rsplit('/',1)[-1].removesuffix('.json'),记录类型='内部')
    data=value.get('payload',{}) if value.get('kind')=='dispatch' else value
    if key.startswith('agents/'):
        row.update(记录类型='Agent',名称=value.get('name',''),主要任务=text(value.get('description','')),
                   状态='暂停接单' if not value.get('enabled',True) else '忙碌' if value.get('busy') else '可接单（以机器心跳为准）')
    elif key.startswith('members/'):
        row.update(记录类型='机器',名称=value.get('machine_name') or value.get('name') or value.get('instance_id',''))
    elif key.startswith('results/') or value.get('kind')=='dispatch':
        row.update(记录类型='回复' if key.startswith('results/') else '请求',
                   名称=data.get('agent_label') or data.get('agent_id') or data.get('id',''),
                   状态=STATES.get(data.get('state'),data.get('state','')),
                   请求内容=text(data.get('message','')),
                   完整回复=text(data['result']) if data.get('result') is not None else data.get('error','') or '')
    row.update({'Agent ID':data.get('agent_id') or (value.get('id','') if key.startswith('agents/') else ''),
                '机器 ID':data.get('executor') or data.get('instance_id',''),
                '请求 ID':data.get('id','') if row['记录类型'] in ('请求','回复') else ''})
    row['更新时间']=time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime(value.get('updated_at',value.get('at',time.time()))))
    return row


def directory(media, member):
    """Readable per-Agent index; machine heartbeat remains one stable record."""
    instance=member['instance_id'];prefix='agents/'+instance
    existing={name:value for name,value in media.list(prefix)}
    for agent in member.get('agents',[]):
        name=agent['id']+'.json'
        value=dict(agent,instance_id=instance)
        if existing.pop(name,None)!=value:media.put(prefix+'/'+name,value)
    for name,value in existing.items():
        if value.get('enabled',True):media.put(prefix+'/'+name,dict(value,enabled=False))


def backfill(media):
    """One-time explicit join/upgrade: decorate existing rows without republishing work."""
    grouped={}
    for row in media.pages(media.path+'/'+media.table+'/records'):
        f=row['fields'];key=media.text(f.get('key',''))
        if key.startswith(('members/','results/','messages/')) and not media.text(f.get('记录类型')):
            grouped.setdefault(key,[]).append(row)
    for key,rows in grouped.items():
        try:value=media.decode(rows,heartbeat=key.startswith('members/'))
        except FileNotFoundError:continue
        if key.startswith('members/'):directory(media,value)
        visible=columns(key,value)
        for row in rows:
            if int(row['fields']['part'])==0:
                media.api('PUT',media.path+'/'+media.table+'/records/'+row['record_id'],{'fields':visible})


def views(media):
    common=['--base-token',media.app,'--table-id',media.table]
    def call(operation, **values):
        argv=['base',operation,*common]
        for k,v in values.items():argv+=['--'+k.replace('_','-'),v]
        body=media.shortcut(argv)
        return body.get('data',body)
    def listed():
        result=[];offset=0
        while True:
            page=call('+view-list',offset=str(offset),limit='100')
            part=page.get('views') or [];result.extend(part);offset+=len(part)
            if not part or offset>=page.get('total',offset):return result
    known={v.get('name',v.get('view_name')):v.get('id',v.get('view_id')) for v in listed()}
    if '请求与结果' not in known and '通信记录' in known:
        ident=known.pop('通信记录')
        call('+view-rename',view_id=ident,name='请求与结果');known['请求与结果']=ident
    specs={
        '请求与结果':(['请求','回复'],['名称','请求 ID','记录类型','Agent ID','机器 ID','状态','请求内容','完整回复','payload','更新时间']),
        'Agent 目录':(['Agent'],['名称','主要任务','Agent ID','机器 ID','状态','更新时间']),
        '机器心跳':(['机器'],['名称','机器 ID','更新时间']),
    }
    for name,(types,fields) in specs.items():
        if name not in known:
            call('+view-create',json=json.dumps({'name':name,'type':'grid'},ensure_ascii=False))
            known={v.get('name',v.get('view_name')):v.get('id',v.get('view_id')) for v in listed()}
        ident=known[name]
        call('+view-set-filter',view_id=ident,json=json.dumps({
            'logic':'or','conditions':[['记录类型','==',kind] for kind in types]},ensure_ascii=False))
        call('+view-set-visible-fields',view_id=ident,json=json.dumps({'visible_fields':fields},ensure_ascii=False))
    media.config['views']={name:known[name] for name in specs}
    if media.config.get('link'):
        parsed=urlparse(media.config['link'])
        media.config['display_url']=parsed._replace(path='/base/'+media.app,
            query=urlencode({'table':media.table,'view':known['请求与结果']}),fragment='').geturl()
