"""Send a platform notification to an explicit existing cc-connect chat."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def sender_command(executable=None, data_dir=None, config_path=None):
    project, session = (os.environ.get(key, '').strip() for key in ('CC_PROJECT', 'CC_SESSION_KEY'))
    if not project or not session:
        raise ValueError('CC_PROJECT and CC_SESSION_KEY are required; configure notifications from the intended cc-connect chat')
    executable = shutil.which(executable or 'cc-connect')
    if not executable:
        raise ValueError('cc-connect is not installed; use the existing bridge setup first')
    directory = data_dir or os.environ.get('CC_DATA_DIR', '').strip()
    command = [sys.executable, str(Path(__file__).resolve()), '--project', project, '--session', session,
               '--executable', str(Path(executable).absolute())]
    if directory:command += ['--data-dir', str(Path(directory).expanduser().resolve())]
    config_path=config_path or os.environ.get('CC_CONFIG_PATH')
    if config_path:command.extend(['--config',str(Path(config_path).expanduser().resolve())])
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--print-command', action='store_true', help='Print sender argv for the current cc-connect chat without sending a message')
    for name in ('project', 'session', 'data-dir'):
        parser.add_argument('--' + name)
    parser.add_argument('--platform', help='Platform of the selected Bot; must match the conversation channel')
    parser.add_argument('--config', help='Config of the running cc-connect; used for topic resolution and alternate Bot selection')
    parser.add_argument('--conversation', action='store_true', help='Preserve the original conversation; resolve topic roots and verify alternate Bot selection')
    parser.add_argument('--executable', default='cc-connect')
    args = parser.parse_args()
    if args.print_command:
        try:
            print(json.dumps(sender_command(args.executable,args.data_dir,args.config), ensure_ascii=False))
        except ValueError as exc:
            parser.error(str(exc))
        return
    send_attempted=False
    checked=None
    try:
        notice = json.load(sys.stdin)
        outlet=notice.get('outlet',{})
        project=outlet.get('identity') or args.project
        session=outlet.get('destination') or args.session
        conversation=notice.get('conversation')
        if conversation:session=conversation['session_key']
        if args.platform and conversation and conversation.get('platform')!=args.platform:
            raise ValueError('Selected Bot platform does not match the notification destination')
        directory=args.data_dir
        if not all(isinstance(v,str) and v.strip() for v in (project,session)):
            raise ValueError('The project/identity and session/destination must be explicit')
        executable=shutil.which(args.executable)
        if not executable:raise ValueError('cc-connect executable is unavailable on the sending machine')
        config_path=args.config
        if not directory and config_path:
            from cc_connect_context import helper
            directory=helper(['--catalog',config_path]).get('data_dir')
            if directory:
                path=Path(directory).expanduser()
                if not path.is_absolute():raise ValueError('Supply the actual absolute --data-dir for a relative cc-connect data_dir')
                directory=str(path)
        if args.conversation or conversation:
            from cc_connect_context import inspect_compatible as inspect
            session=conversation['session_key'] if conversation else session
            try:
                checked=inspect(project,session,directory,config_path,expected=conversation,**({'alternate':True} if notice.get('alternate_bot') else {}))
            except Exception as exc:
                # A probe failure is definitely before send. Even an unfamiliar
                # channel response must permit the platform's entry-Bot fallback.
                raise ValueError('Could not select this notification Bot: '+str(exc)) from None
            if conversation:checked['entry_project']=conversation['entry_project']
        from cc_connect_context import prepare_compatible
        prepared=prepare_compatible(project,session,config_path,checked or conversation)
        session,checked=prepared['session'],prepared['conversation']
        title=str(notice.get('title') or '协作通知')
        if notice.get('run_id'):title+=' · '+str(notice['run_id'])
        lines = [title, str(notice['message'])]
        if notice.get('task_label'):
            labels = {'completed': '已完成', 'executing': '执行中', 'fault': '失败', 'ready': '就绪', 'held': '暂停等待'}
            lines.append('任务：' + notice['task_label'] + ' · ' + labels.get(notice.get('task_status'), notice.get('task_status', '')))
        if notice.get('reason'):
            lines.append(str(notice['reason']))
        if notice.get('reply'):lines.append('需要回复：可以在平台回答，或让当前会话的 Agent 提交回复。')
        if notice.get('request_id'):
            if str(notice['request_id']) not in str(notice['message']):lines.append('请求：' + str(notice['request_id']))
        else:lines.append('通知：' + str(notice['id']))
        send_attempted=True
        result = subprocess.run([executable, 'send', '--project', project, '--session', session,
                                 *(['--data-dir', directory] if directory else []), '--stdin'], input='\n'.join(lines), text=True,
                                encoding='utf-8', capture_output=True, timeout=25)
        if result.returncode:
            raise ValueError('cc-connect send failed: ' + (result.stderr.strip() or str(result.returncode)))
        print(json.dumps({'delivered': True, 'channel': 'cc-connect', 'reference': notice['id'], 'delivery_session_key':session, **({'conversation':checked} if checked else {})}, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'delivered': False, 'not_sent':not send_attempted, 'error': str(exc)}, ensure_ascii=False))
        raise SystemExit(2)


if __name__ == '__main__':
    main()
