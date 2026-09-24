"""Send a platform notification to an explicit existing cc-connect chat."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def sender_command():
    project, session = (os.environ.get(key, '').strip() for key in ('CC_PROJECT', 'CC_SESSION_KEY'))
    if not project or not session:
        raise ValueError('CC_PROJECT and CC_SESSION_KEY are required; configure notifications from the intended cc-connect chat')
    executable = shutil.which('cc-connect')
    if not executable:
        raise ValueError('cc-connect is not installed; use the existing bridge setup first')
    directory = Path(os.environ.get('CC_DATA_DIR', '').strip() or Path.home() / '.cc-connect').expanduser().resolve()
    return [sys.executable, str(Path(__file__).resolve()), '--project', project, '--session', session,
            '--data-dir', str(directory), '--executable', str(Path(executable).absolute())]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--print-command', action='store_true', help='Print sender argv for the current cc-connect chat without sending a message')
    for name in ('project', 'session', 'data-dir'):
        parser.add_argument('--' + name)
    parser.add_argument('--executable', default='cc-connect')
    args = parser.parse_args()
    if args.print_command:
        try:
            print(json.dumps(sender_command(), ensure_ascii=False))
        except ValueError as exc:
            parser.error(str(exc))
        return
    try:
        notice = json.load(sys.stdin)
        outlet=notice.get('outlet',{})
        project=outlet.get('identity') or args.project
        session=outlet.get('destination') or args.session
        directory=args.data_dir or str(Path.home()/'.cc-connect')
        if not all(isinstance(v,str) and v.strip() for v in (project,session,directory)):
            raise ValueError('The project/identity and session/destination must be explicit')
        lines = [str(notice['title']) + ' · ' + str(notice['run_id']), str(notice['message'])]
        if notice.get('task_label'):
            labels = {'completed': '已完成', 'executing': '执行中', 'fault': '失败', 'ready': '就绪', 'held': '暂停等待'}
            lines.append('任务：' + notice['task_label'] + ' · ' + labels.get(notice.get('task_status'), notice.get('task_status', '')))
        if notice.get('reason'):
            lines.append(str(notice['reason']))
        if notice.get('reply'):lines.append('需要回复：可以在平台回答，或让当前会话的 Agent 提交回复。')
        lines.append('通知：' + str(notice['id']))
        result = subprocess.run([args.executable, 'send', '--project', project, '--session', session,
                                 '--data-dir', directory, '--stdin'], input='\n'.join(lines), text=True,
                                encoding='utf-8', capture_output=True, timeout=25)
        if result.returncode:
            raise ValueError('cc-connect send failed: ' + (result.stderr.strip() or str(result.returncode)))
        print(json.dumps({'delivered': True, 'channel': 'cc-connect', 'reference': notice['id']}, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'delivered': False, 'error': str(exc)}, ensure_ascii=False))
        raise SystemExit(2)


if __name__ == '__main__':
    main()
