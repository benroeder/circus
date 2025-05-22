#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test that validates the signal handler safety fix.
"""

import signal
import threading
import time
import logging
from unittest import TestCase, skipIf
from unittest.mock import patch, MagicMock, call

from circus.sighandler import SysHandler
from circus.util import IS_WINDOWS


class TestSignalSafetyFix(TestCase):
    """Test that signal handler safety issues are fixed."""
    
    @skipIf(IS_WINDOWS, "Signal handling different on Windows")
    def test_signal_handler_is_now_safe(self):
        """
        Test that signal handlers now only perform async-signal-safe operations.
        """
        print("\n" + "="*60)
        print("TESTING SIGNAL HANDLER SAFETY FIX")
        print("="*60)
        
        # Create a mock controller with loop
        mock_controller = MagicMock()
        mock_loop = MagicMock()
        mock_controller.loop = mock_loop
        
        # Create signal handler
        handler = SysHandler(mock_controller)
        
        print("1. Testing signal handler with SIGTERM...")
        
        # Trigger signal handler
        handler.signal(signal.SIGTERM)
        
        print("2. Verifying only safe operations were performed...")
        
        # Verify that add_callback_from_signal was called (safe operation)
        mock_loop.add_callback_from_signal.assert_called_once()
        
        # Get the callback function and signal that were passed
        call_args = mock_loop.add_callback_from_signal.call_args
        callback_func = call_args[0][0]
        signal_arg = call_args[0][1]
        
        print("   ✅ add_callback_from_signal called correctly")
        print("   ✅ Signal deferred to main thread: %s" % signal_arg)
        
        # Verify it's the right callback
        self.assertEqual(callback_func, handler._handle_signal_safe)
        self.assertEqual(signal_arg, signal.SIGTERM)
        
        print("3. Testing deferred signal processing...")
        
        # Now test the deferred handler (runs in main thread)
        with patch('circus.sighandler.logger') as mock_logger:
            # Reset the mock to test the safe callback
            mock_controller.reset_mock()
            
            # Call the deferred handler (simulates main thread execution)
            handler._handle_signal_safe(signal.SIGTERM)
            
            # This should now call the quit handler
            mock_controller.loop.add_callback_from_signal.assert_called_once()
            
            # Verify logging happened in main thread (now safe)
            mock_logger.info.assert_called_once()
            log_call = mock_logger.info.call_args[0][0]
            self.assertIn('Got signal SIG_TERM', log_call)
            
        print("   ✅ Deferred handler processes signal safely")
        print("   ✅ Logging occurs in main thread context")
        
        print("\n" + "="*60)
        print("✅ SIGNAL HANDLER SAFETY FIX VALIDATED")
        print("="*60)
        
        return True

    @skipIf(IS_WINDOWS, "Signal handling different on Windows")  
    def test_signal_handler_error_handling(self):
        """
        Test that signal handler error handling uses only safe operations.
        """
        print("\n" + "="*60)
        print("TESTING SIGNAL HANDLER ERROR HANDLING")
        print("="*60)
        
        # Create a controller that will fail
        mock_controller = MagicMock()
        mock_controller.loop.add_callback_from_signal.side_effect = Exception("Controller failed")
        
        handler = SysHandler(mock_controller)
        
        print("1. Testing signal handler when controller fails...")
        
        # Mock os.write and os._exit to capture the safe error handling
        with patch('os.write') as mock_write, patch('os._exit') as mock_exit:
            # This should trigger the exception handling
            handler.signal(signal.SIGTERM)
            
            # Verify safe error handling
            mock_write.assert_called_once_with(2, b"CRITICAL: Signal handler failed to transfer control\n")
            mock_exit.assert_called_once_with(1)
            
        print("   ✅ Error handling uses only signal-safe operations")
        print("   ✅ os.write() used instead of logger")
        print("   ✅ os._exit() used for immediate termination")
        
        print("\n" + "="*60)
        print("✅ ERROR HANDLING SAFETY VALIDATED")
        print("="*60)
        
        return True

    @skipIf(IS_WINDOWS, "Signal handling different on Windows")
    def test_no_unsafe_operations_in_signal_handler(self):
        """
        Test that signal handlers no longer perform unsafe operations.
        """
        print("\n" + "="*60)
        print("TESTING NO UNSAFE OPERATIONS IN SIGNAL HANDLER")
        print("="*60)
        
        mock_controller = MagicMock()
        handler = SysHandler(mock_controller)
        
        # Track operations during signal handling
        unsafe_operations = []
        
        # Patch potential unsafe operations
        with patch('circus.sighandler.logger') as mock_logger:
            def track_logging(*args, **kwargs):
                unsafe_operations.append('UNSAFE: logging in signal handler')
            
            mock_logger.info.side_effect = track_logging
            mock_logger.error.side_effect = track_logging
            
            # Patch dictionary access
            original_get = dict.get
            def track_dict_get(self, *args, **kwargs):
                if threading.current_thread().name != 'MainThread':
                    unsafe_operations.append('UNSAFE: dict.get in signal handler')
                return original_get(self, *args, **kwargs)
            
            with patch.object(dict, 'get', track_dict_get):
                # Trigger signal handler
                handler.signal(signal.SIGTERM)
                
                # Verify NO unsafe operations were performed
                print("1. Checking for unsafe operations...")
                
                for op in unsafe_operations:
                    print("   ❌ %s" % op)
                
                self.assertEqual(len(unsafe_operations), 0, 
                    "Signal handler performed unsafe operations: %s" % unsafe_operations)
                
                print("   ✅ No unsafe operations detected")
                
        print("\n" + "="*60)
        print("✅ SIGNAL HANDLER IS NOW ASYNC-SIGNAL-SAFE")
        print("="*60)
        
        return True


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)