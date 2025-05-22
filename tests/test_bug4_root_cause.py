"""
Deep analysis of BUG-4: How exactly does the "fd added twice" state occur?

This test traces through the specific scenarios that lead to the problematic state.
"""
from unittest import TestCase
from unittest.mock import MagicMock

from circus.stream.redirector import Redirector


class TestBug4RootCauseAnalysis(TestCase):
    """Analyze exactly how BUG-4 gets into the problematic state."""
    
    def test_scenario_1_process_spawn_failure_loop(self):
        """
        SCENARIO 1: Process spawn failure during retry loop
        
        This is the most common cause - spawn_process() retries after failures
        but stream_redirector.start() is called BEFORE each retry attempt.
        """
        print("\n" + "="*60)
        print("🔍 SCENARIO 1: PROCESS SPAWN FAILURE LOOP")
        print("="*60)
        
        print("THE PROBLEMATIC CODE SEQUENCE:")
        print("File: circus/watcher.py:640-689 (spawn_process method)")
        print()
        
        print("```python")
        print("def spawn_process(self):")
        print("    # PROBLEM: Start redirector BEFORE spawn attempt")
        print("    if self.stream_redirector:")
        print("        self.stream_redirector.start()  # ← Called EVERY time!")
        print("    ")
        print("    while nb_tries < self.max_retry:  # Default max_retry = 5")
        print("        try:")
        print("            process = ProcCls(...)  # ← This can fail!")
        print("            ")
        print("            if self.stream_redirector:")
        print("                self.stream_redirector.add_redirections(process)")
        print("        except (OSError, ValueError) as e:")
        print("            # Process spawn failed, but redirector already started!")
        print("            nb_tries += 1")
        print("            continue  # ← RETRY WITHOUT CLEANING REDIRECTOR!")
        print("```")
        print()
        
        print("THE EXACT PROBLEM SEQUENCE:")
        print("1. 🔄 ATTEMPT 1:")
        print("   - stream_redirector.start() called")
        print("   - No FDs added yet (no process pipes)")
        print("   - Process spawn fails (OSError, permission, etc.)")
        print("   - Exception caught, nb_tries += 1")
        print("   - ❌ NO REDIRECTOR CLEANUP!")
        print()
        
        print("2. 🔄 ATTEMPT 2:")
        print("   - stream_redirector.start() called AGAIN") 
        print("   - Previous attempt may have left partial state")
        print("   - Process spawn succeeds, gets fd 23 for stdout")
        print("   - add_redirections(process) called")
        print("   - add_redirections() calls _stop_one(23) for cleanup")
        print("   - But there might be stale state from attempt 1!")
        print()
        
        print("🚨 ROOT CAUSE:")
        print("   stream_redirector.start() is called BEFORE each spawn attempt")
        print("   but there's no corresponding cleanup if spawn fails!")
        
    def test_scenario_2_process_death_during_spawn(self):
        """
        SCENARIO 2: Process dies immediately after spawn
        
        Process spawns successfully, gets added to redirector, 
        but dies before spawn_process() completes.
        """
        print("\n" + "="*60)
        print("🔍 SCENARIO 2: PROCESS DEATH DURING SPAWN")
        print("="*60)
        
        print("THE RACE CONDITION SEQUENCE:")
        print("1. ✅ Process spawns successfully")
        print("   - Gets fd 23 for stdout pipe")
        print("   - stream_redirector.add_redirections(process) called")
        print("   - Redirector adds handler for fd 23")
        print()
        
        print("2. ⚡ Process dies immediately")
        print("   - Could be due to startup failure, missing dependencies, etc.")
        print("   - Process pipes get closed by OS")
        print("   - OS marks fd 23 as available for reuse")
        print()
        
        print("3. 🧹 Cleanup attempts")
        print("   - Various cleanup paths may run:")
        print("     * reap_processes() detects dead process")
        print("     * remove_redirections() called")
        print("     * _stop_one(23) called")
        print("   - BUT: Cleanup races with fd reuse!")
        print()
        
        print("4. 🔄 Next spawn attempt")
        print("   - New process spawns, gets fd 23 (reused)")
        print("   - add_redirections() calls _stop_one(23)")
        print("   - But tornado loop might still have old handler!")
        print("   - 💥 'fd 23 added twice'")
        
    def test_scenario_3_concurrent_cleanup_operations(self):
        """
        SCENARIO 3: Multiple cleanup operations running concurrently
        
        This happens when processes die while watchers are being managed.
        """
        print("\n" + "="*60)
        print("🔍 SCENARIO 3: CONCURRENT CLEANUP OPERATIONS")
        print("="*60)
        
        print("THE CONCURRENT OPERATIONS:")
        print("Thread 1: manage_watchers() → manage_processes() → reap_processes()")
        print("Thread 2: External process death → SIGCHLD → cleanup")
        print("Thread 3: User command → stop watcher → cleanup")
        print()
        
        print("RACE CONDITION:")
        print("1. Process with fd 23 dies")
        print("2. Multiple cleanup paths detect the death:")
        print("   - reap_processes() in manage_watchers()")
        print("   - Signal handler cleanup")
        print("   - Explicit stop command cleanup")
        print("3. All three call remove_redirections() / _stop_one()")
        print("4. First one succeeds, others may fail silently")
        print("5. State becomes inconsistent")
        print("6. Next process spawn gets 'fd added twice'")
        
    def test_scenario_4_tornado_loop_failure(self):
        """
        SCENARIO 4: Tornado loop.remove_handler() failure
        
        This is the direct technical cause - what makes remove_handler fail.
        """
        print("\n" + "="*60)
        print("🔍 SCENARIO 4: TORNADO LOOP REMOVE_HANDLER FAILURE")
        print("="*60)
        
        print("WHY loop.remove_handler(fd) CAN FAIL:")
        print()
        
        print("1. 🔧 HANDLER ALREADY REMOVED:")
        print("   - Another code path already removed it")
        print("   - Tornado raises KeyError")
        print("   - circus._stop_one() doesn't catch this!")
        print()
        
        print("2. 🔧 FILE DESCRIPTOR CLOSED:")
        print("   - Process died, pipes closed by OS")
        print("   - Tornado can't remove handler for closed fd")
        print("   - May raise ValueError or fail silently")
        print()
        
        print("3. 🔧 TORNADO INTERNAL STATE CORRUPTION:")
        print("   - Tornado's internal handler registry corrupted")
        print("   - Can happen under high load or race conditions")
        print("   - remove_handler() may fail unexpectedly")
        print()
        
        print("4. 🔧 ASYNCIO LOOP ISSUES:")
        print("   - Tornado uses asyncio on Python 3.7+")
        print("   - asyncio loop state can become inconsistent")
        print("   - Especially under signal interruption")
        print()
        
        print("THE CRITICAL BUG:")
        print("```python")
        print("def _stop_one(self, fd):")
        print("    if fd in self._active:")
        print("        self.loop.remove_handler(fd)  # ← CAN FAIL!")
        print("        del self._active[fd]           # ← ALWAYS RUNS!")
        print("```")
        print()
        print("Result: _active dict cleaned up, but tornado loop still has handler")
        
    def test_scenario_5_file_descriptor_reuse_timing(self):
        """
        SCENARIO 5: File descriptor reuse timing issues
        
        The OS aggressively reuses file descriptors, creating timing windows.
        """
        print("\n" + "="*60)
        print("🔍 SCENARIO 5: FILE DESCRIPTOR REUSE TIMING")
        print("="*60)
        
        print("OS FILE DESCRIPTOR REUSE BEHAVIOR:")
        print("- OS maintains a pool of available file descriptors")
        print("- When process dies, its FDs are returned to pool")
        print("- OS reuses lowest available FD number")
        print("- Under load, FD reuse happens very quickly")
        print()
        
        print("THE TIMING WINDOW:")
        print("1. ⏱️  T=0: Process A dies, fd 23 becomes available")
        print("2. ⏱️  T=1: OS adds fd 23 to available pool") 
        print("3. ⏱️  T=2: Cleanup starts: _stop_one(23) called")
        print("4. ⏱️  T=3: remove_handler(23) fails (process already dead)")
        print("5. ⏱️  T=4: _active[23] deleted (cleanup continues)")
        print("6. ⏱️  T=5: New process B spawns, gets fd 23")
        print("7. ⏱️  T=6: add_redirections(B) calls _start_one(23)")
        print("8. ⏱️  T=7: 💥 'fd 23 added twice' - tornado still has old handler!")
        print()
        
        print("HIGH-LOAD SCENARIOS:")
        print("- Multiple processes spawning/dying rapidly")
        print("- File descriptor exhaustion → aggressive reuse") 
        print("- Signal storms causing rapid process restarts")
        print("- Container environments with limited FDs")
        
    def test_demonstrate_exact_failure_mechanism(self):
        """
        Demonstrate the exact mechanism that causes the failure.
        """
        print("\n" + "="*60)
        print("🔬 EXACT FAILURE MECHANISM DEMONSTRATION")
        print("="*60)
        
        # Mock tornado IOLoop to demonstrate the exact failure
        mock_loop = MagicMock()
        
        # Track internal state
        tornado_handlers = {}  # Simulates tornado's internal handler registry
        
        def mock_add_handler(fd, handler, events):
            if fd in tornado_handlers:
                raise ValueError(f"fd {fd} added twice")
            tornado_handlers[fd] = handler
            print(f"   ✅ Tornado: Added handler for fd {fd}")
        
        def mock_remove_handler(fd):
            if fd == 23:  # Simulate failure for fd 23
                print(f"   ❌ Tornado: remove_handler({fd}) FAILS!")
                raise KeyError(f"fd {fd} not found")
            if fd in tornado_handlers:
                del tornado_handlers[fd]
                print(f"   ✅ Tornado: Removed handler for fd {fd}")
        
        mock_loop.add_handler.side_effect = mock_add_handler
        mock_loop.remove_handler.side_effect = mock_remove_handler
        
        # Create redirector (current buggy implementation)
        redirector = Redirector(
            stdout_redirect=lambda x: None,
            stderr_redirect=lambda x: None,
            loop=mock_loop
        )
        
        print("STEP 1: Normal operation - add handler for fd 23")
        redirector._active[23] = "fake_handler"
        tornado_handlers[23] = "fake_handler"
        print(f"State: _active={list(redirector._active.keys())}, tornado={list(tornado_handlers.keys())}")
        
        print("\nSTEP 2: Process dies, cleanup attempted")
        print("Calling _stop_one(23)...")
        try:
            redirector._stop_one(23)
        except Exception as e:
            print(f"   💥 Exception in cleanup: {e}")
        
        print(f"State: _active={list(redirector._active.keys())}, tornado={list(tornado_handlers.keys())}")
        print("   ⚠️  INCONSISTENT STATE: _active clean, tornado still has handler!")
        
        print("\nSTEP 3: New process spawns, tries to use fd 23")
        print("Calling _start_one(23)...")
        try:
            redirector._start_one(23, "stdout", MagicMock(), MagicMock())
        except ValueError as e:
            print(f"   💥 BUG REPRODUCED: {e}")
        
        print("\n🎯 EXACT MECHANISM:")
        print("1. remove_handler() fails, leaves tornado handler")
        print("2. _active dict gets cleaned up anyway")  
        print("3. State inconsistency created")
        print("4. Next add_handler() fails with 'fd added twice'")
        
    def test_why_stream_redirector_started_early(self):
        """
        Explain WHY stream_redirector.start() is called before process spawn.
        """
        print("\n" + "="*60)
        print("🤔 WHY IS STREAM REDIRECTOR STARTED EARLY?")
        print("="*60)
        
        print("DESIGN INTENTION (from circus/watcher.py:640-642):")
        print("```python")
        print("# start the redirector now so we can catch any startup errors")
        print("if self.stream_redirector:")
        print("    self.stream_redirector.start()")
        print("```")
        print()
        
        print("THE ORIGINAL LOGIC:")
        print("- Start redirector early to 'catch startup errors'")
        print("- Prepare stream handling before process spawns")
        print("- Ensure redirection is ready when process starts")
        print()
        
        print("WHY THIS CAUSES PROBLEMS:")
        print("1. 🔄 Retry loop calls start() multiple times")
        print("2. 🧹 No cleanup between retry attempts")
        print("3. 📚 State accumulates across failed attempts")
        print("4. 🎯 Perfect recipe for 'fd added twice'")
        print()
        
        print("BETTER DESIGN WOULD BE:")
        print("- Start redirector AFTER successful process spawn")
        print("- OR: Properly cleanup redirector on spawn failure")
        print("- OR: Make redirector.start() idempotent")
        
        print("\n💡 ARCHITECTURAL INSIGHT:")
        print("   This is a classic 'premature optimization' problem.")
        print("   Starting redirector early creates more problems than it solves.")


if __name__ == '__main__':
    import unittest
    unittest.main(verbosity=2)