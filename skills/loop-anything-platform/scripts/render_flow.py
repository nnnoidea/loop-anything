"""Render an Agent-authored Loop overview with the bundled Answer me with HTML CLI."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

from call import fetch


def render(source, output):
    renderer = Path(__file__).parent / 'vendor/answer-me-with-html/am.mjs'
    with tempfile.TemporaryDirectory(prefix='loop-flow-') as home:
        result = subprocess.run(['node', str(renderer), 'render', str(source), '-o', str(output), '--no-open'],
                                env={**os.environ, 'AM_HOME': home, 'AM_NO_UPDATE_CHECK': '1'},
                                capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stderr or result.stdout)
    return result.stderr.strip()


def upload(source, output, draft_id, revision, url):
    # Use ordinary revision-protected package writes; never publish or start a Run.
    for path, file in [('docs/flow.md', source), ('docs/flow.html', output)]:
        response = fetch(url.rstrip('/') + '/api/tools', json.dumps({'tool': 'put_asset', 'arguments': {
            'draft_id': draft_id, 'revision': revision, 'path': path,
            'content': file.read_text(encoding='utf-8'), 'executable': False,
        }}, ensure_ascii=False).encode('utf-8'))
        if not response.get('ok'):
            raise ValueError(json.dumps({'failed_asset': path, 'revision': revision, 'response': response}, ensure_ascii=False))
        revision = response['revision']
    return revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Agent-authored Markdown, including flow blocks')
    parser.add_argument('--output', type=Path, help='HTML output; defaults to source with .html suffix')
    parser.add_argument('--draft-id', help='Also save docs/flow.md and docs/flow.html in this existing draft')
    parser.add_argument('--revision', type=int, help='Current draft revision, required when saving')
    parser.add_argument('--url', help='Platform URL override (otherwise connection.json)')
    args = parser.parse_args()
    if args.draft_id and args.revision is None:
        parser.error('--draft-id requires --revision from read_loop')
    source = args.source.resolve()
    output = (args.output or source.with_suffix('.html')).resolve()
    if source == output:
        parser.error('Source and HTML output must be different files')
    try:
        warnings = render(source, output)
        result = {'ok': True, 'source': str(source), 'html': str(output)}
        if warnings:
            result['warnings'] = warnings
        if args.draft_id:
            connection = Path(__file__).resolve().parent.parent / 'connection.json'
            settings = json.loads(connection.read_text()) if connection.exists() else {}
            url = args.url or settings.get('url')
            if not url:
                raise ValueError('Specify --url for the running platform')
            result['revision'] = upload(source, output, args.draft_id, args.revision, url)
            result['draft_id'] = args.draft_id
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError) as exc:
        parser.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
