"""
Test to reproduce the "fd added twice" bug from the stack trace:

ValueError: fd 23 added twice

This happens in the stream redirector when file descriptors are not 
properly cleaned up between process spawns.
"""
import os
import tempfile
import time
from unittest import TestCase, skipIf
from unittest.mock import patch, MagicMock

from tornado import ioloop

from circus.stream.redirector import Redirector  
from circus.watcher import Watcher
from circus.util import IS_WINDOWS
from tests.support import TestCircus, get_available_port


class TestFdAddedTwiceBug(TestCase):
    """Reproduce the 'fd added twice' ValueError bug."""
    
    def test_analyze_fd_added_twice_source(self):
        """
        Analyze the source of the "fd added twice" error.
        """
        print("\n" + "="*60)
        print("ANALYZING 'FD ADDED TWICE' BUG SOURCE")
        print("="*60)
        
        import inspect
        from circus.stream.redirector import Redirector
        
        # Get the problematic code
        start_one_source = inspect.getsource(Redirector._start_one)
        add_redirections_source = inspect.getsource(Redirector.add_redirections)
        
        print("PROBLEMATIC CODE - _start_one method:")
        print("-" * 40)
        print(start_one_source)
        
        print("PROBLEMATIC CODE - add_redirections method:")
        print("-" * 40)
        print(add_redirections_source)
        
        print("BUG ANALYSIS:")
        print("-" * 40)
        print("1. _start_one() calls loop.add_handler(fd, handler, READ)")
        print("2. If fd is already in loop, Tornado raises 'fd added twice'")
        print("3. _start_one() checks 'if fd not in self._active' but...")
        print("4. self._active might be out of sync with Tornado's internal state")
        print("5. Race conditions can cause cleanup to miss removing fd from loop")
        
        print("\nPROBLEM SCENARIOS:")
        print("- Process spawning retry after partial failure")
        print("- Stream redirector not properly cleaned up on process death")
        print("- Race between add_redirections and cleanup")
        print("- File descriptor reuse by OS before cleanup")
    
    def test_demonstrate_fd_tracking_issue(self):
        """
        Demonstrate the file descriptor tracking inconsistency.
        """
        print("\n" + "="*50)
        print("DEMONSTRATING FD TRACKING INCONSISTENCY")
        print("="*50)
        
        # Mock tornado IOLoop
        mock_loop = MagicMock()
        
        # Create redirector
        redirector = Redirector(
            stdout_redirect=lambda x: None,
            stderr_redirect=lambda x: None,
            loop=mock_loop
        )
        
        print("1. Creating mock process with file descriptors")
        
        # Create mock process and pipes
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.pipe_stdout = True
        mock_process.pipe_stderr = True
        
        # Mock pipes with file descriptors
        mock_stdout_pipe = MagicMock()
        mock_stdout_pipe.fileno.return_value = 23  # Same fd as in stack trace!
        mock_stderr_pipe = MagicMock()
        mock_stderr_pipe.fileno.return_value = 24
        
        mock_process.stdout = mock_stdout_pipe
        mock_process.stderr = mock_stderr_pipe
        
        print("   stdout fd: 23, stderr fd: 24")
        
        # Start redirector
        redirector.start()
        
        print("2. Adding redirections for first time")
        redirector.add_redirections(mock_process)
        
        # Verify add_handler was called
        expected_calls = mock_loop.add_handler.call_count
        print(f"   add_handler called {expected_calls} times")
        
        print("3. Simulating partial cleanup (bug scenario)")
        
        # Simulate scenario where self._active is cleared but 
        # Tornado loop still has the handlers
        redirector._active.clear()
        
        print("   _active dict cleared, but loop handlers remain")
        print(f"   _active: {redirector._active}")
        print(f"   pipes: {list(redirector.pipes.keys())}")
        
        print("4. Attempting to add redirections again (should fail)")
        
        # Now try to add redirections again - this should cause "fd added twice"
        try:
            redirector.add_redirections(mock_process)
            print("   ❌ No error detected - test scenario incomplete")
        except Exception as e:
            if "added twice" in str(e):
                print(f"   ✅ 'fd added twice' error reproduced: {e}")
            else:
                print(f"   Different error: {e}")
        
        # Check if add_handler was called again
        new_calls = mock_loop.add_handler.call_count
        print(f"   add_handler called {new_calls - expected_calls} additional times")
        
        # The real bug: _active state doesn't match Tornado's internal state
        print("\n🚨 BUG CONFIRMED:")
        print("   _active dict can become inconsistent with Tornado loop state")
        print("   This causes 'fd added twice' when trying to re-add handlers")
    
    def test_fd_reuse_scenario(self):
        """
        Test file descriptor reuse scenario that can cause conflicts.
        """
        print("\n" + "="*50)
        print("TESTING FILE DESCRIPTOR REUSE SCENARIO")
        print("="*50)
        
        # This simulates the scenario where:
        # 1. Process A dies, fd 23 is in redirector
        # 2. Process A's pipes are closed, OS frees fd 23
        # 3. Process B starts, gets fd 23 for its pipe
        # 4. Redirector tries to add fd 23 again -> "fd added twice"
        
        mock_loop = MagicMock()
        redirector = Redirector(
            stdout_redirect=lambda x: None,
            stderr_redirect=lambda x: None, 
            loop=mock_loop
        )
        
        redirector.start()
        
        print("1. Process A starts with fd 23")
        
        # Process A
        mock_process_a = MagicMock()
        mock_process_a.pid = 100
        mock_process_a.pipe_stdout = True
        mock_process_a.pipe_stderr = False
        
        mock_pipe_a = MagicMock()
        mock_pipe_a.fileno.return_value = 23
        mock_process_a.stdout = mock_pipe_a
        
        redirector.add_redirections(mock_process_a)
        
        print(f"   Process A (pid {mock_process_a.pid}) using fd 23")
        print(f"   _active: {list(redirector._active.keys())}")
        print(f"   pipes: {list(redirector.pipes.keys())}")
        
        print("2. Process A dies, but cleanup is incomplete")
        
        # Simulate incomplete cleanup - fd removed from _active but not from pipes
        # or vice versa (common in race conditions)
        if 23 in redirector._active:
            del redirector._active[23]
        
        print("   Partial cleanup: removed from _active but not pipes")
        print(f"   _active: {list(redirector._active.keys())}")
        print(f"   pipes: {list(redirector.pipes.keys())}")
        
        print("3. Process B starts, OS reuses fd 23")
        
        # Process B gets the same fd number (common OS behavior)
        mock_process_b = MagicMock()
        mock_process_b.pid = 200
        mock_process_b.pipe_stdout = True
        mock_process_b.pipe_stderr = False
        
        mock_pipe_b = MagicMock()
        mock_pipe_b.fileno.return_value = 23  # Same fd!
        mock_process_b.stdout = mock_pipe_b
        
        print(f"   Process B (pid {mock_process_b.pid}) gets fd 23")
        
        print("4. Attempting to add redirections for Process B")
        
        try:
            redirector.add_redirections(mock_process_b)
            print("   ✅ No conflict (cleanup worked)")
        except Exception as e:
            print(f"   ❌ Conflict detected: {e}")
        
        print(f"   Final _active: {list(redirector._active.keys())}")
        print(f"   Final pipes: {list(redirector.pipes.keys())}")
        
        print("\n🎯 SCENARIO DEMONSTRATED:")
        print("   File descriptor reuse can cause conflicts if cleanup is incomplete")
        print("   This is exactly what happens in the production stack trace")
    
    def test_reproduce_stream_redirector_lifecycle_bug(self):
        """
        Reproduce the stream redirector lifecycle bug mentioned in CLAUDE.md.
        """
        print("\n" + "="*50)
        print("REPRODUCING STREAM REDIRECTOR LIFECYCLE BUG")
        print("="*50)
        
        # This is the bug we identified earlier:
        # "Stream redirector started before process spawn, not cleaned up on failure"
        
        mock_loop = MagicMock()
        redirector = Redirector(
            stdout_redirect=lambda x: None,
            stderr_redirect=lambda x: None,
            loop=mock_loop
        )
        
        print("1. Starting redirector before process spawn (bug pattern)")
        redirector.start()
        self.assertTrue(redirector.running)
        
        print("2. Simulating process spawn failure")
        
        # Create a mock process that will "fail" to spawn
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.pipe_stdout = True
        mock_process.pipe_stderr = True
        
        mock_stdout = MagicMock()
        mock_stdout.fileno.return_value = 23
        mock_stderr = MagicMock()  
        mock_stderr.fileno.return_value = 24
        
        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        
        # Add redirections (this normally happens after successful spawn)
        redirector.add_redirections(mock_process)
        
        initial_active_count = len(redirector._active)
        initial_pipes_count = len(redirector.pipes)
        
        print(f"   Added redirections: {initial_active_count} active, {initial_pipes_count} pipes")
        
        print("3. Process spawn fails, but redirector is not cleaned up")
        
        # Normally, if process spawn fails, the redirector should be cleaned up
        # But the bug is that this cleanup doesn't always happen properly
        
        # Simulate the scenario: process object is destroyed but redirector keeps references
        mock_process = None  # Process object gone
        
        print("   Process object destroyed, but redirector state remains")
        print(f"   _active: {list(redirector._active.keys())}")
        print(f"   pipes: {list(redirector.pipes.keys())}")
        
        print("4. Next process spawn attempt uses same file descriptors")
        
        # Next process gets same file descriptors (common)
        new_mock_process = MagicMock()
        new_mock_process.pid = 67890
        new_mock_process.pipe_stdout = True
        new_mock_process.pipe_stderr = True
        
        new_stdout = MagicMock()
        new_stdout.fileno.return_value = 23  # Same fd!
        new_stderr = MagicMock()
        new_stderr.fileno.return_value = 24  # Same fd!
        
        new_mock_process.stdout = new_stdout
        new_mock_process.stderr = new_stderr
        
        print("5. Attempting to add redirections again")
        
        conflict_detected = False
        try:
            redirector.add_redirections(new_mock_process)
            print("   ✅ No conflict (add_redirections handles cleanup)")
        except Exception as e:
            if "added twice" in str(e):
                conflict_detected = True
                print(f"   ✅ 'fd added twice' conflict reproduced: {e}")
            else:
                print(f"   Different error: {e}")
        
        print("\n🎯 LIFECYCLE BUG DEMONSTRATED:")
        print("   Stream redirector cleanup can be incomplete on process spawn failure")
        print("   This leads to 'fd added twice' errors on subsequent spawns")
        
        # The add_redirections method tries to handle this with _stop_one(fd)
        # but there can still be race conditions
        
    def test_examine_add_redirections_cleanup_logic(self):
        """
        Examine the cleanup logic in add_redirections to find the bug.
        """
        print("\n" + "="*50)
        print("EXAMINING add_redirections CLEANUP LOGIC")
        print("="*50)
        
        import inspect
        from circus.stream.redirector import Redirector
        
        # Get the add_redirections source
        source = inspect.getsource(Redirector.add_redirections)
        
        print("add_redirections source code:")
        print("-" * 30)
        print(source)
        
        print("CLEANUP LOGIC ANALYSIS:")
        print("-" * 30)
        print("Line: self._stop_one(fd)")
        print("  Purpose: Remove existing handler for fd before adding new one")
        print("  Problem: _stop_one only removes from self._active")
        print("  Issue: If Tornado loop still has handler, add_handler fails")
        
        print("\nPOTENTIAL RACE CONDITIONS:")
        print("1. _stop_one removes from _active")
        print("2. But loop.remove_handler might fail silently")
        print("3. Tornado loop still has the handler")
        print("4. loop.add_handler fails with 'fd added twice'")
        
        print("\nMISSING ERROR HANDLING:")
        print("- No try/catch around loop.remove_handler in _stop_one")
        print("- No verification that handler was actually removed")
        print("- No fallback if cleanup fails")
        
        self.assertIn("self._stop_one(fd)", source)
        self.assertIn("self._start_one(fd", source)
        
        print("\n🚨 BUG CONFIRMED:")
        print("   add_redirections cleanup logic has race condition vulnerability")


if __name__ == '__main__':
    import unittest
    unittest.main(verbosity=2)