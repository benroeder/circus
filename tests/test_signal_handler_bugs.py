"""
Test cases to reproduce signal handler safety bugs in Circus.

These tests are designed to demonstrate the async-signal-safety violations
and other signal handling issues identified in the codebase.
"""
import os
import signal
import subprocess
import sys
import tempfile
import time
import threading
import multiprocessing
from unittest import TestCase, skipIf
from unittest.mock import patch, MagicMock

import psutil

from circus.arbiter import Arbiter
from circus.sighandler import SysHandler
from circus.controller import Controller
from circus.util import IS_WINDOWS
from tests.support import TestCircus, get_available_port


class TestSignalHandlerSafety(TestCase):
    """Test signal handler async-signal-safety violations."""
    
    def setUp(self):
        self.temp_files = []
        self.processes = []
    
    def tearDown(self):
        # Clean up any spawned processes
        for proc in self.processes:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=5)
            except:
                pass
        
        # Clean up temp files
        for temp_file in self.temp_files:
            try:
                os.unlink(temp_file)
            except:
                pass
    
    @skipIf(IS_WINDOWS, "Signal handling different on Windows")
    def test_signal_handler_logging_deadlock(self):
        """
        Test that demonstrates potential deadlock in signal handlers.
        
        Signal handlers call logger.info() which is not async-signal-safe.
        This can cause deadlocks if the signal interrupts a logging operation.
        """
        # Create a simple circus configuration
        config_content = """
[circus]
check_delay = 1
endpoint = tcp://127.0.0.1:{}
pubsub_endpoint = tcp://127.0.0.1:{}

[watcher:dummy]
cmd = python -c "import time; time.sleep(30)"
numprocesses = 1
""".format(get_available_port(), get_available_port())
        
        config_fd, config_path = tempfile.mkstemp(suffix='.ini')
        self.temp_files.append(config_path)
        
        with os.fdopen(config_fd, 'w') as f:
            f.write(config_content)
        
        # Start circusd in a subprocess
        circus_cmd = [sys.executable, '-m', 'circus.circusd', config_path]
        proc = subprocess.Popen(
            circus_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid if not IS_WINDOWS else None
        )
        self.processes.append(proc)
        
        # Give circus time to start
        time.sleep(2)
        
        # Verify circus is running
        self.assertIsNone(proc.poll(), "Circus should be running")
        
        # Send rapid signals to trigger the signal handler multiple times
        # This tests the async-signal-safety issue
        for i in range(10):
            os.kill(proc.pid, signal.SIGTERM)
            time.sleep(0.1)
            
            # Check if process is still responsive
            if proc.poll() is not None:
                # Process died, check output for deadlock indicators
                stdout, stderr = proc.communicate()
                
                # Look for signs of signal handler issues
                output = stdout.decode() + stderr.decode()
                
                # These are indicators of signal handler problems
                problematic_patterns = [
                    'deadlock',
                    'signal handler',
                    'recursive',
                    'not async-signal-safe'
                ]
                
                for pattern in problematic_patterns:
                    if pattern.lower() in output.lower():
                        self.fail(f"Signal handler issue detected: {pattern}")
                
                break
        else:
            # If we get here, circus survived all signals
            # This doesn't necessarily mean the bug is fixed,
            # just that we didn't trigger it this time
            proc.terminate()
            proc.wait(timeout=5)
    
    @skipIf(IS_WINDOWS, "Signal handling different on Windows")  
    def test_signal_handler_exception_handling(self):
        """
        Test signal handler exception handling safety.
        
        Signal handlers use traceback.format_exc() and sys.exit()
        which are not async-signal-safe.
        """
        # Create a mock controller with a broken loop
        mock_controller = MagicMock()
        mock_controller.loop = MagicMock()
        
        # Make add_callback_from_signal raise an exception
        mock_controller.loop.add_callback_from_signal.side_effect = RuntimeError("Test error")
        
        handler = SysHandler(mock_controller)
        
        # Capture what happens when signal handler hits an exception
        with patch('circus.sighandler.logger') as mock_logger, \
             patch('circus.sighandler.sys.exit') as mock_exit:
            
            # This should trigger the exception handling in signal()
            handler.signal(signal.SIGTERM)
            
            # Verify that unsafe operations were attempted
            mock_logger.error.assert_called()
            mock_exit.assert_called_with(1)
            
            # The real issue is that these operations are not async-signal-safe
            # This test documents the current behavior that needs fixing
    
    def test_signal_names_dictionary_access(self):
        """
        Test signal handler dictionary access safety.
        
        Signal handlers access self.SIG_NAMES dict and use getattr()
        which are not guaranteed to be async-signal-safe.
        """
        mock_controller = MagicMock()
        handler = SysHandler(mock_controller)
        
        # Test with a signal not in SIG_NAMES
        unknown_signal = 99  # Unlikely to be a real signal
        
        with patch('circus.sighandler.logger') as mock_logger:
            # This should handle unknown signal gracefully
            handler.signal(unknown_signal)
            
            # The issue is that logger.info() is called regardless
            # which is not async-signal-safe
            mock_logger.info.assert_called()


class TestProcessReapingRaceCondition(TestCircus):
    """Test race conditions in process reaping logic."""
    
    @skipIf(IS_WINDOWS, "waitpid not available on Windows")
    async def test_reaping_race_condition(self):
        """
        Test race condition between process mapping and waitpid.
        
        This test demonstrates the race condition in arbiter.reap_processes()
        where a process could die between building the watchers_pids mapping
        and the waitpid() call.
        """
        # Create a watcher with a short-lived process
        dummy_cmd = 'python -c "import time; time.sleep(0.1)"'
        
        arbiter = self.arbiter_factory(
            [],
            'tcp://127.0.0.1:{}'.format(get_available_port()),
            'tcp://127.0.0.1:{}'.format(get_available_port()),
            check_delay=0.1
        )
        
        async with self.start_arbiter(arbiter):
            # Add a watcher with processes that die quickly
            watcher = await arbiter.add_watcher(
                name="quick_death",
                cmd=dummy_cmd,
                numprocesses=5
            )
            
            # Wait for processes to start
            await self.start_watcher(arbiter, watcher)
            
            # Get initial process count
            initial_processes = len(watcher.processes)
            self.assertGreater(initial_processes, 0)
            
            # Kill processes externally while arbiter is trying to reap
            # This simulates the race condition
            external_kills = []
            for process in list(watcher.processes.values()):
                if hasattr(process, 'pid'):
                    try:
                        # Kill process externally (simulating crash)
                        os.kill(process.pid, signal.SIGKILL)
                        external_kills.append(process.pid)
                    except ProcessLookupError:
                        # Process already dead
                        pass
            
            # Force reaping to happen multiple times rapidly
            for _ in range(10):
                arbiter.reap_processes()
                await self.async_sleep(0.01)
            
            # Wait for arbiter to detect and clean up
            await self.async_sleep(1.0)
            
            # Check for inconsistencies
            # The race condition can cause processes to remain in 
            # watcher.processes even though they're dead
            live_processes = 0
            dead_in_mapping = 0
            
            for pid, process in watcher.processes.items():
                try:
                    # Check if process is actually alive
                    os.kill(pid, 0)  # Signal 0 just checks if process exists
                    live_processes += 1
                except ProcessLookupError:
                    # Process is dead but still in mapping - this is the bug
                    dead_in_mapping += 1
            
            if dead_in_mapping > 0:
                self.fail(f"Race condition detected: {dead_in_mapping} dead processes "
                         f"still in watcher mapping")
    
    @skipIf(IS_WINDOWS, "Process management different on Windows")
    async def test_zombie_accumulation(self):
        """
        Test for zombie process accumulation due to reaping issues.
        """
        # Create processes that die quickly
        zombie_cmd = 'python -c "import os; os._exit(42)"'
        
        arbiter = self.arbiter_factory(
            [],
            'tcp://127.0.0.1:{}'.format(get_available_port()),
            'tcp://127.0.0.1:{}'.format(get_available_port()),
            check_delay=0.1
        )
        
        async with self.start_arbiter(arbiter):
            # Add watcher that creates processes that immediately exit
            watcher = await arbiter.add_watcher(
                name="zombie_maker",
                cmd=zombie_cmd,
                numprocesses=3,
                respawn=False  # Don't restart them
            )
            
            await self.start_watcher(arbiter, watcher)
            
            # Wait for processes to die
            await self.async_sleep(2.0)
            
            # Force multiple reaping cycles
            for _ in range(5):
                arbiter.reap_processes()
                await self.async_sleep(0.1)
            
            # Check for zombie processes
            current_process = psutil.Process()
            zombie_children = []
            
            for child in current_process.children(recursive=True):
                try:
                    if child.status() == psutil.STATUS_ZOMBIE:
                        zombie_children.append(child.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            if zombie_children:
                self.fail(f"Zombie processes detected: {zombie_children}")


class TestResourceLeaks(TestCase):
    """Test resource leak issues."""
    
    def setUp(self):
        self.initial_fd_count = self._count_open_fds()
    
    def tearDown(self):
        # Check for file descriptor leaks
        final_fd_count = self._count_open_fds()
        fd_leak = final_fd_count - self.initial_fd_count
        
        # Allow for some variation in fd count (test framework overhead)
        if fd_leak > 5:
            print(f"WARNING: Potential FD leak detected: {fd_leak} extra descriptors")
    
    def _count_open_fds(self):
        """Count open file descriptors for current process."""
        try:
            # On Unix systems, count files in /proc/self/fd/
            if os.path.exists('/proc/self/fd'):
                return len(os.listdir('/proc/self/fd'))
            else:
                # Fallback for systems without /proc
                import resource
                return resource.getrlimit(resource.RLIMIT_NOFILE)[0]
        except:
            return 0
    
    @skipIf(IS_WINDOWS, "File descriptor handling different on Windows")
    def test_devnull_fd_leak(self):
        """
        Test file descriptor leak in _null_streams.
        
        The _null_streams method opens /dev/null but may not close it
        if an exception occurs during processing.
        """
        from circus.process import Process
        
        # Create a process instance
        process = Process(
            name="test",
            wid=1,
            cmd="echo test",
            spawn=False  # Don't actually spawn
        )
        
        # Mock streams that will cause an exception
        class BadStream:
            def flush(self):
                raise IOError("Simulated flush error")
            
            def fileno(self):
                return 1  # stdout
        
        bad_stream = BadStream()
        
        initial_fds = self._count_open_fds()
        
        # This should handle the exception and still close devnull
        try:
            process._null_streams([bad_stream])
        except Exception:
            pass
        
        final_fds = self._count_open_fds()
        
        # Check for file descriptor leak
        fd_diff = final_fds - initial_fds
        self.assertLessEqual(fd_diff, 0, f"File descriptor leak detected: {fd_diff}")
    
    def test_socket_leak_on_bind_failure(self):
        """
        Test socket leak when bind_and_listen fails.
        
        If socket creation succeeds but bind fails, the socket
        may not be properly cleaned up.
        """
        from circus.sockets import CircusSocket
        
        initial_fds = self._count_open_fds()
        
        # Try to bind to an invalid address/port combination
        # This should cause bind to fail after socket creation
        try:
            sock = CircusSocket(
                name='test_socket',
                host='999.999.999.999',  # Invalid IP
                port=99999  # Invalid port
            )
            sock.bind_and_listen()
        except Exception:
            # Expected to fail
            pass
        
        final_fds = self._count_open_fds()
        fd_diff = final_fds - initial_fds
        
        # Should not leak file descriptors
        self.assertLessEqual(fd_diff, 1, f"Socket file descriptor leak detected: {fd_diff}")


if __name__ == '__main__':
    import unittest
    unittest.main()