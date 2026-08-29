"""Regression coverage for descriptor-relative boundary operations."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class DescriptorBoundaryTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "Windows handle-relative race probe requires native CI implementation")
    def test_broker_parent_swap_cannot_redirect_read_write_or_cwd(self):
        import fable_v2.execution_broker as broker

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            root.mkdir()
            sub = root / "sub"
            sub.mkdir()
            outside = Path(td) / "outside"
            outside.mkdir()
            (outside / "secret").write_text("outside")
            policy = broker.BrokerPolicy(root, allowed_executables=("true",))
            instance = broker.ExecutionBroker(policy)
            original = broker._open_child_dirs

            def swap(root_fd, parts, *, create=False):
                if parts:
                    shutil.rmtree(sub)
                    sub.symlink_to(outside, target_is_directory=True)
                return original(root_fd, parts, create=create)

            with mock.patch.object(broker, "_open_child_dirs", side_effect=swap):
                with self.assertRaises(Exception):
                    instance.inspect_files("sub/secret")
                instance._writes_unlocked = True
                with self.assertRaises(Exception):
                    instance.write_file("sub/new", "must stay inside")
                with self.assertRaises(Exception):
                    instance.execute_command(("true",), cwd="sub", timeout_seconds=1)
            self.assertFalse((outside / "new").exists())
            self.assertFalse((outside / "cwd-race").exists())

    def test_config_atomic_write_rejects_parent_swap(self):
        import fable_mode.adapters as adapters

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = root / "config"
            parent.mkdir()
            outside = root / "outside"
            outside.mkdir()
            target = parent / "mcp.json"
            original = adapters._safe_path
            fired = False

            def swap(path, *args, **kwargs):
                nonlocal fired
                result = original(path, *args, **kwargs)
                if path == parent and not fired:
                    fired = True
                    shutil.rmtree(parent)
                    parent.symlink_to(outside, target_is_directory=True)
                return result

            with mock.patch.object(adapters, "_safe_path", side_effect=swap):
                with self.assertRaises(Exception):
                    adapters._atomic_write(target, b"secret")
            self.assertFalse((outside / "mcp.json").exists())

    def test_session_and_cas_parent_swaps_fail_closed(self):
        import fable_engine.server as server

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sessions = root / "sessions"
            sessions.mkdir()
            outside = root / "outside"
            outside.mkdir()
            target = sessions / "x.json"
            original_assert = server._assert_private_path
            fired = False

            def swap(path):
                nonlocal fired
                original_assert(path)
                if path == sessions and not fired:
                    fired = True
                    shutil.rmtree(sessions)
                    sessions.symlink_to(outside, target_is_directory=True)

            with mock.patch.object(server, "_assert_private_path", side_effect=swap):
                with self.assertRaises(Exception):
                    server.FableSession("x", "x", 1).save(target)
            self.assertFalse((outside / "x.json").exists())

            cas_root = root / "cas"
            store = server.FableCASStore(cas_root)
            payload = b"payload"
            digest = hashlib.sha256(payload).hexdigest()
            shard = cas_root / "objects" / digest[:2]
            outside_shard = root / "outside-shard"
            outside_shard.mkdir()
            original_safe = server._safe_cas_node
            fired = False

            def cas_swap(path, *args, **kwargs):
                nonlocal fired
                result = original_safe(path, *args, **kwargs)
                if path == store._get_object_path(digest) and not fired:
                    fired = True
                    shutil.rmtree(shard)
                    shard.symlink_to(outside_shard, target_is_directory=True)
                return result

            with mock.patch.object(server, "_safe_cas_node", side_effect=cas_swap):
                with self.assertRaises(Exception):
                    store.put(payload)
            self.assertFalse((outside_shard / digest[2:]).exists())


if __name__ == "__main__":
    unittest.main()
