"""Small deterministic assertion vocabulary; never execute author code or prose."""
from loop_anything.runtime.model import Invalid, path


ARITY = {'eq': 2, 'le': 2, 'ge': 2, 'add': 2, 'len': 1, 'and': None, 'or': None}


def validate_expression(expr):
    if not isinstance(expr, dict):
        return
    if set(expr) == {'path'} and (isinstance(expr['path'], str) or
            isinstance(expr['path'], list) and all(isinstance(p, str) or type(p) is int for p in expr['path'])):
        return
    if set(expr) != {'op', 'args'} or expr['op'] not in ARITY or not isinstance(expr['args'], list):
        raise Invalid('Invalid deterministic assertion expression')
    arity = ARITY[expr['op']]
    if (arity is not None and len(expr['args']) != arity) or not expr['args']:
        raise Invalid('Invalid assertion argument count')
    for arg in expr['args']:
        validate_expression(arg)


def evaluate(expr, context):
    if not isinstance(expr, dict):
        return expr
    if 'path' in expr:
        return path(context, expr['path'])
    op = expr['op']
    if op == 'and':
        return all(evaluate(a, context) is True for a in expr['args'])
    if op == 'or':
        return any(evaluate(a, context) is True for a in expr['args'])
    args = [evaluate(a, context) for a in expr['args']]
    if op == 'eq':
        return args[0] == args[1]
    if op == 'le':
        return args[0] <= args[1]
    if op == 'ge':
        return args[0] >= args[1]
    if op == 'add':
        return args[0] + args[1]
    if op == 'len':
        return len(args[0])
    raise Invalid('Unknown assertion operation')


def check_assertions(node, context):
    for check in node.get('assertions', []):
        try:
            passed = evaluate(check['test'], context) is True
        except (KeyError, TypeError, ValueError, IndexError):
            passed = False
        if not passed:
            raise Invalid('Completion assertion failed: ' + check['message'])
