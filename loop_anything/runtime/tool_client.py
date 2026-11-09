"""Use the installed portable client for either team transport."""
import importlib.util
import json
from loop_anything.paths import platform_skill_directory


def module(name):
    path=platform_skill_directory()/'scripts'/(name+'.py')
    spec=importlib.util.spec_from_file_location('_loop_'+name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def request(url, tool, arguments=None, request_id=None, wait=30):
    if url.startswith('nas:'):return module('platform_transport').invoke(url,tool,arguments,request_id,wait)
    return module('call').fetch(url.rstrip('/')+'/api/tools',json.dumps({'tool':tool,'arguments':arguments or {}}).encode())


def scoped_url(base,ident,token):return module('platform_transport').scoped_url(base,ident,token)
