"""Send a platform notification to an explicit existing cc-connect chat."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def definitely_not_sent(error):
    """Known CLI connection failures and explicit rejections, never generic failures."""
    return bool(re.fullmatch(r'Error: cc-connect is not running \(socket not found: [^\n]+\)', error) or
                re.fullmatch(r'Error: failed to connect: Post "http://unix/send": dial unix [^\n]+: connect: (?:no such file or directory|connection refused|permission denied)', error) or
                re.fullmatch(r'Error: project "[^\n]+" not found', error) or
                # Feishu 230002: the bot is outside the chat; the API rejected delivery.
                re.fullmatch(r'Error: (?:feishu|lark): (?:reply|send) failed code=230002 msg=[^\n]*', error))


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
    parser.add_argument('--platform', help='Legacy metadata; session routing is handled by cc-connect')
    parser.add_argument('--config', help='Legacy setup option; delivery does not read bridge configuration')
    parser.add_argument('--conversation', action='store_true', help='Legacy flag; conversation metadata is always preserved')
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
        directory=args.data_dir
        if not all(isinstance(v,str) and v.strip() for v in (project,session)):
            raise ValueError('The project/identity and session/destination must be explicit')
        executable=args.executable
        from cc_connect_context import prepare_delivery
        prepared=prepare_delivery(session,conversation)
        session,checked=prepared['session'],prepared['conversation']
        title=str(notice.get('title') or '协作通知')
        if notice.get('run_id') and not notice.get('request_id'):title+=' · '+str(notice['run_id'])
        lines = [title, str(notice['message'])]
        if notice.get('task_label') and not notice.get('request_id'):
            labels = {'completed': '已完成', 'executing': '执行中', 'fault': '失败', 'ready': '就绪', 'held': '暂停等待'}
            lines.append('任务：' + notice['task_label'] + ' · ' + labels.get(notice.get('task_status'), notice.get('task_status', '')))
        if notice.get('reason'):
            lines.append(str(notice['reason']))
        if notice.get('reply'):lines.append('需要回复：可以在平台回答，或让当前会话的 Agent 提交回复。')
        if notice.get('request_id'):
            if str(notice['request_id']) not in str(notice['message']):lines.append('请求：' + str(notice['request_id']))
        else:lines.append('通知：' + str(notice['id']))
        send_attempted=True
        try:
            result = subprocess.run([executable, 'send', '--project', project, '--session', session,
                                     *(['--data-dir', directory] if directory else []), '--stdin'], input='\n'.join(lines), text=True,
                                    encoding='utf-8', capture_output=True, timeout=25)
        except (FileNotFoundError, PermissionError):
            send_attempted=False
            raise
        if result.returncode:
            error=result.stderr.strip()
            if definitely_not_sent(error):send_attempted=False
            raise ValueError('cc-connect send failed: ' + (error or str(result.returncode)))
        print(json.dumps({'delivered': True, 'channel': 'cc-connect', 'reference': notice['id'], 'delivery_session_key':session, **({'conversation':checked} if checked else {})}, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'delivered': False, 'not_sent':not send_attempted, 'error': str(exc)}, ensure_ascii=False))
        raise SystemExit(2)


if __name__ == '__main__':
    main()
