"""Durable process results; transport retries never run the process again."""
import base64
import hashlib
import json
import os
from loop_anything.runtime.team_transport import core

CHUNK_BYTES=524288
INLINE_BYTES=262144


def manifest(path):
    digest=hashlib.sha256();size=0
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(CHUNK_BYTES),b''):
            digest.update(chunk);size+=len(chunk)
    return {'bytes':size,'sha256':digest.hexdigest()}


def save(path, result):
    core.atomic_json(path,result)
    return manifest(path)


def read(path):
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict) or type(value.get('returncode')) is not int or not all(isinstance(value.get(k),str) for k in ('stdout','stderr')):
        raise ValueError('Invalid process result')
    return value


def chunk(path, offset):
    with path.open('rb') as stream:
        stream.seek(offset);data=stream.read(CHUNK_BYTES)
    return {'offset':offset,'data':base64.b64encode(data).decode('ascii')}


def receive(path, description, part=None):
    """Append or acknowledge the exact same bytes; a lost ACK is safe to retransmit."""
    size=description.get('bytes');digest=description.get('sha256')
    if type(size) is not int or size<=0 or not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Invalid process result manifest')
    if path.exists():
        if manifest(path)!=description:raise ValueError('Process result identity changed')
        return size
    pending=path.with_suffix('.part')
    if part is None:
        have=pending.stat().st_size if pending.exists() else 0
        if have==size:
            if manifest(pending)!=description:raise ValueError('Process result checksum mismatch')
            read(pending);os.replace(pending,path)
        return have
    offset=part.get('offset')
    if type(offset) is not int or offset<0 or not isinstance(part.get('data'),str):raise ValueError('Invalid result chunk')
    data=base64.b64decode(part['data'],validate=True)
    if not data or len(data)>CHUNK_BYTES or offset+len(data)>size:raise ValueError('Invalid result chunk size')
    pending.parent.mkdir(parents=True,exist_ok=True)
    with pending.open('r+b' if pending.exists() else 'w+b') as stream:
        stream.seek(0,2);have=stream.tell()
        if offset>have:return have
        if offset<have:
            stream.seek(offset)
            if stream.read(min(len(data),have-offset))!=data[:min(len(data),have-offset)]:raise ValueError('Result chunk changed')
        if offset+len(data)>have:
            stream.seek(have);stream.write(data[have-offset:]);stream.flush();os.fsync(stream.fileno())
        have=max(have,offset+len(data))
    if have==size:
        if manifest(pending)!=description:raise ValueError('Process result checksum mismatch')
        read(pending)
        os.replace(pending,path)
    return have
