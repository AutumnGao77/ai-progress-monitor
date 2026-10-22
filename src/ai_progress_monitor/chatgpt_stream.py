"""Read-only, version-gated desktop IPC request observation.

The desktop stream is an internal protocol, not the public app-server API.
Only request lifecycle fields survive decoding; conversation contents are never
stored or logged. Connection/revision failures preserve the last known pending
requests until a fresh snapshot or confirmed process exit resolves them.
"""
import copy
import json
import os
import select
import socket
import stat
import struct
import time
import uuid
from pathlib import Path
from typing import Optional

_MAX_FRAME = 32 * 1024 * 1024
_POLL_BYTES = 8 * 1024 * 1024
_MAX_REQUESTS = 512


def _request(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid request')
    params = value.get('params') or {}
    if not isinstance(params, dict):
        raise ValueError('Invalid request params')
    result = {}
    for key in ('id', 'method', 'completed'):
        field = value.get(key)
        if field is not None and not isinstance(field, (str, int, bool)):
            raise ValueError('Invalid lifecycle field')
        if isinstance(field, str) and len(field) > 512:
            raise ValueError('Oversized lifecycle field')
        result[key] = field
    result['params'] = {}
    for key in ('threadId', 'turnId'):
        field = params.get(key)
        if field is not None and (not isinstance(field, str) or len(field) > 512):
            raise ValueError('Invalid lifecycle identifier')
        result['params'][key] = field
    return result


def _requests(value):
    if not isinstance(value, list) or len(value) > _MAX_REQUESTS:
        raise ValueError('Unsupported request list')
    return [_request(item) for item in value]


class RequestState:
    def __init__(self):
        self.revision = None
        self.requests = []

    @property
    def pending_turns(self):
        return tuple(item['params'].get('turnId') for item in self.requests
                     if item.get('method') == 'mcpServer/elicitation/request'
                     and item.get('completed') is not True)

    def apply(self, change):
        try:
            revision = change['revision']
            if type(revision) is not int:
                return False
            if change.get('type') == 'snapshot':
                requests = _requests(change['conversationState']['requests'])
            elif change.get('type') == 'patches' and self.revision is not None:
                if change.get('baseRevision') != self.revision or revision <= self.revision:
                    return False
                requests = copy.deepcopy(self.requests)
                patches = change['patches']
                if not isinstance(patches, list):
                    return False
                for patch in patches:
                    path, op = patch['path'], patch['op']
                    if not isinstance(path, list) or not path:
                        return False
                    if path[0] != 'requests':
                        continue
                    value = patch.get('value')
                    if len(path) == 1:
                        if op not in ('add', 'replace'):
                            return False
                        requests = _requests(value)
                        continue
                    index = path[1]
                    if type(index) is not int or index < 0:
                        return False
                    if len(path) == 2:
                        if op == 'add' and index <= len(requests):
                            requests.insert(index, _request(value))
                        elif op == 'replace':
                            requests[index] = _request(value)
                        elif op == 'remove':
                            requests.pop(index)
                        else:
                            return False
                    else:
                        item = requests[index]
                        key = path[2]
                        if key not in ('id', 'method', 'completed', 'params'):
                            continue
                        if key == 'params' and len(path) > 3:
                            if path[3] not in ('threadId', 'turnId'):
                                continue
                            if len(path) != 4:
                                return False
                            target, key = item['params'], path[3]
                        else:
                            if len(path) != 3:
                                return False
                            target = item
                        if op == 'remove':
                            target.pop(key, None)
                        elif op in ('add', 'replace'):
                            target[key] = value
                        else:
                            return False
                        requests[index] = _request(item)
                    if len(requests) > _MAX_REQUESTS:
                        return False
            else:
                return False
        except (KeyError, TypeError, ValueError, IndexError):
            return False
        self.requests, self.revision = requests, revision
        return True


class DesktopRequestStream:
    def __init__(self, path: Optional[Path] = None, clock=time.monotonic):
        self.path = path or Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'ipc/ipc.sock'
        self.clock = clock
        self.states = {}
        self._processes = frozenset()
        self._socket = None
        self._buffer = bytearray()
        self._out = bytearray()
        self._client = None
        self._owners = {}
        self._owner_checked = {}
        self._snapshot_due = {}
        self._requests = {}
        self._retry = {}
        self._resync = set()
        self._connect_after = 0.0

    @property
    def pending(self):
        result = {}
        for thread, state in self.states.items():
            turns = tuple(item['params'].get('turnId') for item in state.requests
                          if item.get('method') == 'mcpServer/elicitation/request'
                          and item.get('completed') is not True
                          and item['params'].get('threadId') in (None, thread))
            if turns:
                result[thread] = turns
        return result

    def close(self):
        if self._socket is not None:
            self._socket.close()
        self._socket = None
        self._buffer.clear()
        self._out.clear()
        self._client = None
        self._owners.clear()
        self._owner_checked.clear()
        self._snapshot_due.clear()
        self._requests.clear()
        self._resync.clear()
        # Never accept patches after a disconnect without a fresh snapshot.
        for state in self.states.values():
            state.revision = None

    def _queue(self, message):
        data = json.dumps(message, separators=(',', ':')).encode()
        self._out.extend(struct.pack('<I', len(data)))
        self._out.extend(data)

    def _send_request(self, method, params, version, thread=None):
        ident = str(uuid.uuid4())
        self._requests[ident] = (method, thread, self.clock())
        self._queue({'type': 'request', 'requestId': ident,
                     'sourceClientId': self._client or 'initializing-client',
                     'version': version, 'method': method, 'params': params, 'timeoutMs': 2000})

    def _follow(self, thread, value=True):
        self._queue({'type': 'broadcast', 'method': 'thread-stream-following-changed',
                     'sourceClientId': self._client, 'targetClientIds': [self._owners[thread]],
                     'version': 1, 'params': {'conversationId': thread, 'hostId': 'local', 'following': value}})

    def _connect(self):
        for path in (self.path.parent, self.path):
            info = path.lstat()
            if info.st_uid != os.getuid() or info.st_mode & 0o077 or stat.S_ISLNK(info.st_mode):
                raise OSError('Untrusted local IPC endpoint')
        if not stat.S_ISSOCK(self.path.lstat().st_mode):
            raise OSError('Not an IPC socket')
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(0.1)
            connection.connect(str(self.path))
            connection.setblocking(False)
        except OSError:
            connection.close()
            raise
        self._socket = connection
        self._send_request('initialize', {'clientType': 'ai-progress-monitor'}, 0)

    def _message(self, message, wanted):
        kind = message.get('type')
        if kind == 'client-discovery-request':
            self._queue({'type': 'client-discovery-response', 'requestId': message.get('requestId'),
                         'response': {'canHandle': False}})
        elif kind == 'response':
            request = self._requests.pop(message.get('requestId'), None)
            if request is None:
                return
            method, thread, _ = request
            if message.get('resultType') != 'success':
                if method == 'initialize':
                    raise OSError('Initialization rejected')
                if thread:
                    self._retry[thread] = self.clock() + 30
                    self._owners.pop(thread, None)
                return
            if method == 'initialize':
                result = message.get('result')
                if not isinstance(result, dict):
                    raise ValueError('Invalid initialization result')
                client = result.get('clientId')
                if not isinstance(client, str):
                    raise ValueError('Invalid client')
                self._client = client
            elif thread in wanted:
                owner = message.get('handledByClientId')
                if isinstance(owner, str):
                    changed = self._owners.get(thread) != owner
                    self._owners[thread] = owner
                    self._owner_checked[thread] = self.clock()
                    if changed:
                        self.states.setdefault(thread, RequestState()).revision = None
                        self._follow(thread)
                        self._snapshot_due[thread] = self.clock() + 30
        elif kind == 'broadcast' and message.get('method') == 'thread-stream-state-changed':
            params = message.get('params')
            if not isinstance(params, dict):
                raise ValueError('Invalid stream parameters')
            thread = params.get('conversationId')
            if (thread not in wanted or thread not in self._owners or params.get('hostId') != 'local'
                    or message.get('sourceClientId') != self._owners[thread]):
                return
            state = self.states.setdefault(thread, RequestState())
            if message.get('version') != 11 or not state.apply(params.get('change', {})):
                state.revision = None
                if thread not in self._resync:
                    self._resync.add(thread)
                    self._follow(thread)
                    self._snapshot_due[thread] = self.clock() + 30
            else:
                self._resync.discard(thread)
                self._snapshot_due.pop(thread, None)

    def poll(self, threads, live_processes):
        """Bound work per poll; unknown liveness must be handled by the caller."""
        processes = frozenset(live_processes)
        if processes != self._processes:
            self.close()
            self.states.clear()
            self._retry.clear()
            self._processes = processes
            self._connect_after = 0
        if not processes:
            return self.pending
        # Previously pending requests remain subscribed even outside the scan cap.
        priority = {thread: index for index, thread in enumerate(threads)}
        wanted = set(priority) | set(self.pending)
        now = self.clock()
        try:
            if self._socket is None:
                if now < self._connect_after:
                    return self.pending
                self._connect()
            for thread in list(self._owners):
                if thread not in wanted:
                    self._follow(thread, False)
                    self._owners.pop(thread)
                    self.states.pop(thread, None)
            for ident, (method, thread, sent) in list(self._requests.items()):
                if now - sent > 3:
                    self._requests.pop(ident)
                    if method == 'initialize':
                        raise OSError('Initialization timeout')
                    self._retry[thread] = now + 30
            for thread, due in list(self._snapshot_due.items()):
                if now > due:
                    self._owners.pop(thread, None)
                    self._snapshot_due.pop(thread, None)
                    self._retry[thread] = now + 30
            if self._client:
                discovering = {entry[1] for entry in self._requests.values()}
                refresh = {thread for thread in self._owners
                           if now - self._owner_checked.get(thread, now) > 30}
                available = sorted((wanted - set(self._owners) | refresh) - discovering,
                                   key=lambda thread: (self._retry.get(thread, 0), priority.get(thread, -1)))
                for thread in [item for item in available if self._retry.get(item, 0) <= now][:4]:
                    self._send_request('thread-owner-discovery', {'hostId': 'local', 'conversationId': thread}, 1, thread)
            deadline = self.clock() + 0.15
            budget = _POLL_BYTES
            while budget > 0 and self.clock() < deadline:
                if self._out:
                    try:
                        sent = self._socket.send(self._out)
                        del self._out[:sent]
                    except BlockingIOError:
                        pass
                try:
                    data = self._socket.recv(min(65536, budget))
                except BlockingIOError:
                    remaining = min(0.005, max(0, deadline - self.clock()))
                    if remaining and select.select([self._socket], [], [], remaining)[0]:
                        continue
                    break
                if not data:
                    raise OSError('IPC disconnected')
                budget -= len(data)
                self._buffer.extend(data)
                while len(self._buffer) >= 4:
                    length = struct.unpack_from('<I', self._buffer)[0]
                    if not 0 < length <= _MAX_FRAME:
                        raise ValueError('IPC frame limit')
                    if len(self._buffer) < length + 4:
                        break
                    payload = bytes(self._buffer[4:4 + length])
                    del self._buffer[:4 + length]
                    message = json.loads(payload)
                    if not isinstance(message, dict):
                        raise ValueError('Invalid IPC frame')
                    self._message(message, wanted)
                    del payload, message
        except (OSError, ValueError, TypeError, KeyError):
            self.close()
            self._connect_after = now + 5
        return self.pending
