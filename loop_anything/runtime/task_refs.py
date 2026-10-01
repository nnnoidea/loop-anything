"""Resolve author references once into the existing immutable Task/record identities."""
import copy
from loop_anything.runtime.model import Invalid


def reference_index(specs):
    index = {}
    for spec in specs:
        ref = spec.get('ref')
        if ref is None:
            continue
        if not isinstance(ref, str) or not ref.strip():
            raise Invalid('Task ref must be nonempty text')
        if ref in index and index[ref]['id'] != spec['id']:
            raise Invalid('Duplicate Task ref: ' + ref)
        index[ref] = spec
    return index


def resolve_task_references(specs, existing=()):
    """Forward references within the submitted set are allowed; missing refs fail closed."""
    specs = copy.deepcopy(specs)
    index = reference_index(list(existing) + specs)
    def find(ref):
        if not isinstance(ref, str) or ref not in index:
            raise Invalid('Unknown Task ref: ' + str(ref))
        return index[ref]
    for spec in specs:
        refs = spec.pop('after_refs', [])
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise Invalid('after_refs must resolve to an array of Task refs')
        spec['after'] = list(dict.fromkeys(spec.get('after', []) + [find(ref)['id'] for ref in refs]))
        for port, source in list(spec.get('inputs', {}).items()):
            if not isinstance(source, dict) or not ({'task_ref', 'task_refs'} & source.keys()):
                continue
            if len(set(source) & {'task_ref', 'task_refs'}) != 1 or set(source) - {'task_ref', 'task_refs', 'port', 'path', 'revision'}:
                raise Invalid('Task reference input accepts task_ref/task_refs, port and optional path/revision')
            many = 'task_refs' in source
            refs = source['task_refs'] if many else [source['task_ref']]
            if not isinstance(refs, list):raise Invalid('task_refs must resolve to an array')
            records, revisions = [], []
            for ref in refs:
                task = find(ref)
                if source.get('port') not in task['outputs']:
                    raise Invalid('Unknown output port for Task ref ' + ref + ': ' + str(source.get('port')))
                destination = task['outputs'][source['port']]
                records.append(destination['id'])
                revisions.append(destination.get('expected_revision', 0) + 1)
            spec['inputs'][port] = dict({k:v for k,v in source.items() if k in ('path','revision')},
                                       **({'records': records} if many else {'record': records[0]}))
            if 'revision' not in source and revisions:
                if len(set(revisions)) == 1:spec['inputs'][port]['revision'] = revisions[0]
                else:spec['inputs'][port]['revisions'] = revisions
    return specs


def describe_references(specs, refs=None):
    index = reference_index(specs)
    refs = list(index) if refs is None else refs
    missing = [ref for ref in refs if ref not in index]
    if missing:raise Invalid('Unknown Task refs: ' + ', '.join(missing))
    return {ref: {'task_id': index[ref]['id'], 'node': index[ref]['node'],
                  'outputs': {port: {'record': value['id'], 'revision': value.get('expected_revision', 0) + 1}
                              for port, value in index[ref]['outputs'].items()}} for ref in refs}
