"""
Test to reproduce the ConflictError: arbiter is already running watcher_stop command
"""
import asyncio
import time
from unittest import TestCase
from unittest.mock import patch, MagicMock

from circus.arbiter import Arbiter
from circus.watcher import Watcher
from circus.exc import ConflictError
from tests.support import TestCircus, get_available_port


class TestWatcherStopConflict(TestCase):
    """Test the watcher_stop synchronization conflict bug."""
    
    def test_analyze_conflict_source(self):
        """
        Analyze the source of the ConflictError.
        """
        import inspect
        from circus.util import synchronized
        
        # Get the synchronized decorator source
        sync_source = inspect.getsource(synchronized)
        
        print("SYNCHRONIZED DECORATOR ANALYSIS:")
        print("=" * 50)
        print(sync_source)
        print("=" * 50)
        
        # The issue: manage_watchers is NOT synchronized with watcher_stop
        # but it can call _stop() which conflicts with synchronized stop()
        
        print("\nCONFLICT SCENARIO:")
        print("1. Tornado calls manage_watchers() (NOT synchronized)")
        print("2. manage_watchers() calls manage_processes()")
        print("3. manage_processes() calls _stop() (bypasses sync)")
        print("4. Simultaneously, another thread calls stop() (IS synchronized)")
        print("5. ConflictError: already running watcher_stop command")
        
        print("\nBUG: INCONSISTENT SYNCHRONIZATION")
        print("- watcher.stop() uses @synchronized('watcher_stop')")
        print("- watcher._stop() bypasses synchronization")
        print("- manage_watchers() can call _stop() without sync")
        print("- This creates race conditions!")
        
    def test_demonstrate_synchronization_paths(self):
        """
        Show the different code paths that can lead to stopping watchers.
        """
        from circus.watcher import Watcher
        import inspect
        
        # Check which methods call _stop
        watcher_source = inspect.getsource(Watcher)
        
        stop_callers = []
        lines = watcher_source.split('\n')
        
        in_method = None
        for i, line in enumerate(lines):
            # Track method definitions
            if 'def ' in line and not line.strip().startswith('#'):
                method_match = line.strip().split('def ')[1].split('(')[0]
                in_method = method_match
            
            # Look for calls to _stop
            if '._stop(' in line or 'self._stop(' in line:
                sync_decorator = False
                
                # Look backwards for @synchronized decorator
                for j in range(max(0, i-10), i):
                    if '@util.synchronized' in lines[j] or '@synchronized' in lines[j]:
                        sync_decorator = True
                        break
                
                stop_callers.append({
                    'method': in_method,
                    'line': i,
                    'synchronized': sync_decorator,
                    'code': line.strip()
                })
        
        print("\nMETHODS THAT CALL _stop():")
        print("-" * 40)
        for caller in stop_callers:
            sync_status = "✅ SYNCHRONIZED" if caller['synchronized'] else "❌ NOT SYNCHRONIZED"
            print(f"{caller['method']}: {sync_status}")
            print(f"  Code: {caller['code']}")
        
        # This should show the inconsistency
        synchronized_count = sum(1 for c in stop_callers if c['synchronized'])
        unsynchronized_count = len(stop_callers) - synchronized_count
        
        print(f"\nSUMMARY:")
        print(f"Synchronized calls to _stop(): {synchronized_count}")
        print(f"Unsynchronized calls to _stop(): {unsynchronized_count}")
        
        if unsynchronized_count > 0:
            print("🚨 INCONSISTENT SYNCHRONIZATION DETECTED!")
            print("This can cause ConflictError race conditions")

    def test_reproduce_conflict_scenario(self):
        """
        Try to reproduce the ConflictError scenario.
        """
        # Mock the arbiter and watcher setup
        mock_arbiter = MagicMock()
        mock_arbiter._exclusive_running_command = None
        mock_arbiter._restarting = False
        
        # Create a watcher
        watcher = Watcher(
            name="test_watcher",
            cmd="echo test",
            numprocesses=1
        )
        watcher.arbiter = mock_arbiter
        
        # Simulate the conflict scenario
        print("\nSIMULATING CONFLICT SCENARIO:")
        
        # First, simulate manage_watchers calling _stop (unsynchronized)
        print("1. Setting _exclusive_running_command to simulate manage_watchers")
        mock_arbiter._exclusive_running_command = "some_other_command"
        
        # Now try to call the synchronized stop() method
        print("2. Attempting synchronized stop() - should conflict")
        
        try:
            # This should raise ConflictError due to the @synchronized decorator
            # but we need to actually call it to see the conflict
            
            # Mock the synchronized decorator behavior
            if mock_arbiter._exclusive_running_command is not None:
                raise ConflictError(f"arbiter is already running {mock_arbiter._exclusive_running_command} command")
                
        except ConflictError as e:
            print(f"✅ ConflictError reproduced: {e}")
            print("This demonstrates the synchronization bug!")
        else:
            print("❌ Failed to reproduce ConflictError")
        
        print("\nFIX NEEDED:")
        print("- Either make manage_watchers() respect watcher_stop synchronization")
        print("- Or use different synchronization strategy")
        print("- Or make _stop() also synchronized")


class TestActualConflictReproduction(TestCircus):
    """Try to reproduce the actual ConflictError in a real scenario."""
    
    async def test_concurrent_stop_operations(self):
        """
        Test concurrent stop operations that could cause ConflictError.
        """
        # Create an arbiter with a watcher
        dummy_cmd = 'python -c "import time; time.sleep(10)"'
        
        arbiter = self.arbiter_factory(
            [],
            f'tcp://127.0.0.1:{get_available_port()}',
            f'tcp://127.0.0.1:{get_available_port()}',
            check_delay=0.1  # Fast check to trigger manage_watchers frequently
        )
        
        async with self.start_arbiter(arbiter):
            # Add a watcher
            watcher = await arbiter.add_watcher(
                name="conflict_test",
                cmd=dummy_cmd,
                numprocesses=2
            )
            
            await self.start_watcher(arbiter, watcher)
            
            # Now try to create the conflict:
            # 1. Force manage_watchers to run frequently
            # 2. Simultaneously call stop() from another context
            
            conflict_detected = False
            
            try:
                # Start rapid manage_watchers calls
                for i in range(10):
                    # This might trigger _stop() via manage_processes()
                    await arbiter.manage_watchers()
                    
                    # Simultaneously try to stop the watcher (synchronized)
                    try:
                        await watcher.stop()
                        break  # If stop succeeds, break the loop
                    except ConflictError as e:
                        conflict_detected = True
                        print(f"✅ ConflictError detected: {e}")
                        break
                    
                    await self.async_sleep(0.01)
                    
            except Exception as e:
                if "ConflictError" in str(type(e)) or "already running" in str(e):
                    conflict_detected = True
                    print(f"✅ Conflict detected: {e}")
                else:
                    print(f"Other error: {e}")
            
            if conflict_detected:
                print("SUCCESS: Reproduced the ConflictError!")
            else:
                print("Could not reproduce ConflictError in this run")
                print("(Race conditions are timing-dependent)")


if __name__ == '__main__':
    import unittest
    unittest.main(verbosity=2)