import unittest
from ai_progress_monitor.chatgpt_stream import RequestState


class RequestStateTests(unittest.TestCase):
    def snapshot(self, requests, revision=1):
        return {'type': 'snapshot', 'revision': revision,
                'conversationState': {'requests': requests, 'turnHistory': ['private text']}}

    def request(self, ident='a', completed=False):
        return {'id': ident, 'method': 'mcpServer/elicitation/request', 'completed': completed,
                'params': {'threadId': 'thread', 'turnId': 'turn', 'message': 'PRIVATE',
                           'requestedSchema': {'secret': 'PRIVATE'}}}

    def test_pending_restart_and_multiple_independent_resolutions(self):
        state = RequestState()
        self.assertTrue(state.apply(self.snapshot([self.request('a'), self.request('b')])))
        self.assertEqual(state.pending_turns, ('turn', 'turn'))
        self.assertTrue(state.apply({'type': 'patches', 'baseRevision': 1, 'revision': 2,
                                    'patches': [{'op': 'replace', 'path': ['requests', 0, 'completed'], 'value': True}]}))
        self.assertEqual(state.pending_turns, ('turn',))
        self.assertTrue(state.apply({'type': 'patches', 'baseRevision': 2, 'revision': 3,
                                    'patches': [{'op': 'remove', 'path': ['requests', 1]}]}))
        self.assertEqual(state.pending_turns, ())
        recovered = RequestState()
        recovered.apply(self.snapshot([self.request('a', True)]))
        self.assertEqual(recovered.pending_turns, ())

    def test_revision_gap_and_invalid_patch_preserve_pending(self):
        state = RequestState()
        state.apply(self.snapshot([self.request()]))
        self.assertFalse(state.apply({'type': 'patches', 'baseRevision': 0, 'revision': 2, 'patches': []}))
        self.assertEqual(state.pending_turns, ('turn',))
        self.assertFalse(state.apply({'type': 'patches', 'baseRevision': 1, 'revision': 2,
                                     'patches': [{'op': 'remove', 'path': ['requests', 8]}]}))
        self.assertEqual(state.pending_turns, ('turn',))
        self.assertTrue(state.apply(self.snapshot([], 5)))
        self.assertEqual(state.pending_turns, ())

    def test_content_is_not_retained_and_normal_tools_are_not_approvals(self):
        state = RequestState()
        normal = self.request('b'); normal['method'] = 'tools/call'
        state.apply(self.snapshot([normal, self.request()]))
        self.assertNotIn('PRIVATE', repr(state.__dict__))
        self.assertNotIn('private text', repr(state.__dict__))
        self.assertEqual(state.pending_turns, ('turn',))
        state.apply({'type': 'patches', 'baseRevision': 1, 'revision': 2, 'patches': [
            {'op': 'replace', 'path': ['turnHistory', 0], 'value': 'PRIVATE'},
            {'op': 'replace', 'path': ['requests', 1, 'params', 'message'], 'value': 'PRIVATE'}]})
        self.assertNotIn('PRIVATE', repr(state.__dict__))
        self.assertEqual(state.pending_turns, ('turn',))

    def test_whole_array_and_index_changes(self):
        state = RequestState(); state.apply(self.snapshot([]))
        self.assertTrue(state.apply({'type': 'patches', 'baseRevision': 1, 'revision': 2, 'patches': [
            {'op': 'add', 'path': ['requests', 0], 'value': self.request()}]}))
        self.assertEqual(state.pending_turns, ('turn',))
        self.assertTrue(state.apply({'type': 'patches', 'baseRevision': 2, 'revision': 3, 'patches': [
            {'op': 'replace', 'path': ['requests'], 'value': []}]}))
        self.assertEqual(state.pending_turns, ())


class StreamTransportTests(unittest.TestCase):
    def setUp(self):
        import tempfile, socket, os
        from pathlib import Path
        from ai_progress_monitor.chatgpt_stream import DesktopRequestStream
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'ipc.sock'
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(self.path)); os.chmod(str(self.path), 0o600)
        self.server.listen(); self.server.settimeout(1)
        self.addCleanup(self.server.close)
        self.stream = DesktopRequestStream(self.path); self.addCleanup(self.stream.close)
        self.stream.poll(['thread'], ['process-1'])
        self.peer, _ = self.server.accept(); self.peer.settimeout(1); self.addCleanup(self.peer.close)
        self.respond(self.read(), {'clientId': 'monitor'})
        self.poll(); self.poll()
        self.respond(self.read(), {})
        self.poll(); self.poll()
        self.assertEqual(self.read()['params']['following'], True)

    def poll(self, processes=('process-1',)):
        return self.stream.poll(['thread'], processes)

    def read(self):
        import json, struct
        def exact(n):
            data = b''
            while len(data) < n:
                data += self.peer.recv(n-len(data))
            return data
        return json.loads(exact(struct.unpack('<I', exact(4))[0]))

    def wire(self, message):
        import json, struct
        data = json.dumps(message).encode()
        return struct.pack('<I', len(data)) + data

    def respond(self, request, result):
        self.peer.sendall(self.wire({'type': 'response', 'requestId': request['requestId'],
            'resultType': 'success', 'handledByClientId': 'owner', 'result': result}))

    def snapshot(self, requests=None):
        return {'type': 'broadcast', 'sourceClientId': 'owner', 'version': 11,
                'method': 'thread-stream-state-changed', 'params': {'hostId': 'local',
                'conversationId': 'thread', 'change': {'type': 'snapshot', 'revision': 1,
                'conversationState': {'requests': requests if requests is not None else [
                    {'id': 1, 'method': 'mcpServer/elicitation/request', 'params': {'turnId': 'turn'}}]}}}}

    def test_fragmented_snapshot_disconnect_and_confirmed_exit(self):
        wire = self.wire(self.snapshot())
        self.peer.sendall(wire[:9]); self.assertEqual(self.poll(), {})
        self.peer.sendall(wire[9:]); self.assertEqual(self.poll(), {'thread': ('turn',)})
        self.peer.close(); self.assertEqual(self.poll(), {'thread': ('turn',)})
        self.assertEqual(self.poll([]), {})

    def test_wrong_owner_host_version_and_gap_cannot_clear_pending(self):
        self.peer.sendall(self.wire(self.snapshot())); self.poll()
        for key, value in [('sourceClientId', 'stranger'), ('version', 12)]:
            msg = self.snapshot([]); msg[key] = value
            self.peer.sendall(self.wire(msg)); self.assertEqual(self.poll(), {'thread': ('turn',)})
        msg = self.snapshot([]); msg['params']['hostId'] = 'remote'
        self.peer.sendall(self.wire(msg)); self.assertEqual(self.poll(), {'thread': ('turn',)})
        self.peer.sendall(self.wire(self.snapshot([]))); self.assertEqual(self.poll(), {})

    def test_large_fragment_exceeding_poll_budget(self):
        from unittest.mock import patch
        wire = self.wire(self.snapshot())
        self.peer.sendall(wire)
        with patch('ai_progress_monitor.chatgpt_stream._POLL_BYTES', 12):
            self.assertEqual(self.poll(), {})
        self.assertEqual(self.poll(), {'thread': ('turn',)})

    def test_process_replacement_clears_stale_pending(self):
        self.peer.sendall(self.wire(self.snapshot())); self.poll()
        self.assertEqual(self.poll(['process-2']), {})


    def test_failed_initialization_disconnects_for_retry(self):
        import time
        self.stream._client = None
        self.stream._requests['retry-init'] = ('initialize', None, time.monotonic())
        self.peer.sendall(self.wire({'type': 'response', 'requestId': 'retry-init',
                                   'resultType': 'error', 'method': 'initialize'}))
        self.poll()
        self.assertIsNone(self.stream._socket)
        self.assertGreater(self.stream._connect_after, time.monotonic())

    def test_malformed_params_disconnect_without_losing_pending(self):
        self.peer.sendall(self.wire(self.snapshot())); self.poll()
        message = self.snapshot([]); message['params'] = ['unsupported']
        self.peer.sendall(self.wire(message))
        self.assertEqual(self.poll(), {'thread': ('turn',)})
        self.assertIsNone(self.stream._socket)


class StreamSourceTests(unittest.TestCase):
    def setUp(self):
        import tempfile, json
        from pathlib import Path
        from datetime import datetime, timezone
        from ai_progress_monitor.chatgpt_approvals import DesktopApprovalLog
        from ai_progress_monitor.sources import ChatGPTSessionSource
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); self.path = root / 'sample.jsonl'
        self.records = [
            {'timestamp': '2026-10-22T00:00:00Z', 'type': 'session_meta', 'payload':
             {'id': 'sample', 'originator': 'Codex Desktop', 'cwd': '/projects/example'}},
            {'timestamp': '2026-10-22T00:00:00Z', 'type': 'event_msg', 'payload':
             {'type': 'task_started', 'turn_id': 'turn'}}]
        self.write()
        self.current = datetime(2026, 10, 22, 1, tzinfo=timezone.utc)
        class Stream:
            pending = {'sample': ('turn',)}
            def poll(self, threads, live): return self.pending if live else {}
        self.stream = Stream()
        log = root / 'codex-desktop-00000000-0000-0000-0000-000000000001-123-t0-i1-000000-0.log'
        log.write_text('')
        self.alive = True
        self.log = DesktopApprovalLog(root, process_alive=lambda pid: self.alive)
        self.source = ChatGPTSessionSource(root, now=lambda: self.current,
            source_started_at=self.current, approval_log=self.log, request_stream=self.stream)

    def write(self):
        import json
        self.path.write_text('\n'.join(json.dumps(row) for row in self.records))

    def test_restart_recovers_old_wait_then_resolves_to_running(self):
        from ai_progress_monitor.models import SessionStatus
        import os
        os.utime(self.path, (1, 1))
        update = self.source.poll()[0]
        self.assertEqual(update.status, SessionStatus.NEEDS_ACTION)
        self.assertFalse(update.view_ack_required)
        self.stream.pending = {}
        self.assertEqual(self.source.poll()[0].status, SessionStatus.RUNNING)

    def test_completed_turn_and_new_turn_override_stale_stream(self):
        from ai_progress_monitor.models import SessionStatus
        self.source.poll()
        self.records.append({'timestamp': '2026-10-22T01:01:00Z', 'type': 'event_msg', 'payload':
                            {'type': 'task_complete', 'turn_id': 'turn'}})
        self.write()
        self.assertEqual(self.source.poll()[0].status, SessionStatus.IDLE)
        self.records.append({'timestamp': '2026-10-22T01:02:00Z', 'type': 'event_msg', 'payload':
                            {'type': 'task_started', 'turn_id': 'next'}})
        self.write()
        self.assertEqual(self.source.poll()[0].status, SessionStatus.RUNNING)

    def test_uncertain_liveness_preserves_source_and_exit_ends_attention(self):
        self.assertTrue(self.source.poll())
        self.alive = None
        self.assertIsNone(self.source.poll())
        self.alive = False
        self.assertEqual(self.source.poll(), [])

    def test_custom_directory_never_connects_to_host(self):
        from ai_progress_monitor.sources import ChatGPTSessionSource
        self.assertIsNone(ChatGPTSessionSource(self.path.parent).request_stream)

    def test_mcp_resolution_does_not_clear_async_question(self):
        import json
        from ai_progress_monitor.models import SessionStatus
        self.records.append({'timestamp': '2026-10-22T01:00:00Z', 'type': 'response_item', 'payload':
            {'type': 'function_call', 'name': 'functions.request_user_input_async', 'call_id': 'question',
             'arguments': json.dumps({'questions': [{'title': 'Choose an option'}]})}})
        self.write(); self.source.poll()
        self.stream.pending = {}
        update = self.source.poll()[0]
        self.assertEqual(update.status, SessionStatus.NEEDS_ACTION)
        self.assertFalse(update.view_ack_required)

    def test_mcp_resolution_does_not_clear_command_approval(self):
        from ai_progress_monitor.models import SessionStatus
        log = next(self.path.parent.glob('*.log'))
        log.write_text('2026-10-22T01:00:00Z info [electron-message-handler] '
                       '[desktop-notifications] received approval conversationId=sample kind=commandExecution requestId=123\n')
        self.source.poll(); self.stream.pending = {}
        update = self.source.poll()[0]
        self.assertEqual(update.status, SessionStatus.NEEDS_ACTION)
        self.assertFalse(update.view_ack_required)


    def test_discovery_read_race_never_publishes_mixed_file(self):
        from unittest.mock import patch
        from ai_progress_monitor import sources
        read = sources._read_chatgpt_session_evidence
        def change_after_read(path, *args):
            result = read(path, *args)
            self.records.append({'timestamp': '2026-10-22T01:01:00Z', 'type': 'event_msg',
                                 'payload': {'type': 'task_complete', 'turn_id': 'turn'}})
            self.write()
            return result
        with patch.object(sources, '_read_chatgpt_session_evidence', side_effect=change_after_read):
            self.assertIsNone(self.source.poll())

    def test_process_replacement_is_not_permission_resolution(self):
        self.source.poll()
        log = next(self.path.parent.glob('*.log'))
        log.rename(log.with_name(log.name.replace('000000000001', '000000000002')))
        self.stream.pending = {}
        self.assertEqual(self.source.poll(), [])


if __name__ == '__main__':
    unittest.main()
