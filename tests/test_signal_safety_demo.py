"""
Focused test to demonstrate signal handler safety violations.
"""
import signal
import threading
import time
import logging
from unittest import TestCase, skipIf
from unittest.mock import patch, MagicMock

from circus.sighandler import SysHandler
from circus.util import IS_WINDOWS


class TestSignalSafetyDemo(TestCase):
    """Demonstrate the specific signal handler safety violations."""
    
    @skipIf(IS_WINDOWS, "Signal handling different on Windows")
    def test_signal_handler_unsafe_operations(self):
        """
        Demonstrate that signal handlers perform unsafe operations.
        
        This test proves that the current signal handler implementation
        violates async-signal-safety rules.
        """
        # Create a signal handler
        mock_controller = MagicMock()
        mock_controller.loop = MagicMock()
        
        handler = SysHandler(mock_controller)
        
        # Track what operations are performed in signal handler
        unsafe_operations = []
        
        # Patch logging to track when it's called
        with patch('circus.sighandler.logger') as mock_logger:
            def track_logging(*args, **kwargs):
                unsafe_operations.append('logging')
                
            mock_logger.info.side_effect = track_logging
            mock_logger.error.side_effect = track_logging
            
            # Patch string operations
            original_upper = str.upper
            def track_string_upper(self):
                unsafe_operations.append('string_operation')
                return original_upper(self)
            
            with patch.object(str, 'upper', track_string_upper):
                # Trigger signal handler
                handler.signal(signal.SIGTERM)
        
        # Verify unsafe operations were performed
        self.assertIn('logging', unsafe_operations, 
                     "Signal handler performed logging (not async-signal-safe)")
        self.assertIn('string_operation', unsafe_operations,
                     "Signal handler performed string operations (not async-signal-safe)")
        
        print("UNSAFE OPERATIONS DETECTED IN SIGNAL HANDLER:")
        for op in unsafe_operations:
            print(f"  - {op}")
    
    @skipIf(IS_WINDOWS, "Signal handling different on Windows")
    def test_signal_handler_exception_path_unsafe(self):
        """
        Test that exception handling in signal handler is unsafe.
        """
        mock_controller = MagicMock()
        mock_controller.loop.add_callback_from_signal.side_effect = Exception("Test error")
        
        handler = SysHandler(mock_controller)
        
        unsafe_operations = []
        
        with patch('circus.sighandler.traceback.format_exc') as mock_traceback, \
             patch('circus.sighandler.logger') as mock_logger, \
             patch('circus.sighandler.sys.exit') as mock_exit:
            
            def track_traceback():
                unsafe_operations.append('traceback_formatting')
                return "fake traceback"
            
            def track_exit(code):
                unsafe_operations.append('sys_exit')
                
            mock_traceback.side_effect = track_traceback
            mock_exit.side_effect = track_exit
            
            # This should trigger the exception handling path
            handler.signal(signal.SIGTERM)
            
        # Verify unsafe operations in exception path
        expected_unsafe = ['traceback_formatting', 'sys_exit']
        for unsafe_op in expected_unsafe:
            self.assertIn(unsafe_op, unsafe_operations,
                         f"Signal handler performed {unsafe_op} (not async-signal-safe)")
        
        print("UNSAFE EXCEPTION HANDLING IN SIGNAL HANDLER:")
        for op in unsafe_operations:
            print(f"  - {op}")
    
    def test_signal_handler_dict_access_unsafe(self):
        """
        Test that dictionary access in signal handler can be unsafe.
        """
        mock_controller = MagicMock()
        handler = SysHandler(mock_controller)
        
        # The signal handler accesses self.SIG_NAMES dictionary
        # Dictionary access can trigger Python's garbage collector
        # or memory allocation, which is not async-signal-safe
        
        with patch('circus.sighandler.logger') as mock_logger:
            # Test with a signal number that's in the dict
            handler.signal(signal.SIGTERM)
            
            # Test with a signal number that's NOT in the dict  
            handler.signal(999)  # Invalid signal number
            
        # Both cases involve dictionary lookups and string operations
        # which are not guaranteed to be async-signal-safe
        self.assertTrue(mock_logger.info.called,
                       "Signal handler performed dictionary access and logging")
        
        print("SIGNAL HANDLER PERFORMS UNSAFE DICTIONARY ACCESS")


class TestActualSignalHandlerCode(TestCase):
    """Test the actual signal handler code to show unsafe patterns."""
    
    def test_show_unsafe_signal_handler_source(self):
        """
        Display the actual signal handler code to show unsafe operations.
        """
        import inspect
        from circus.sighandler import SysHandler
        
        # Get the source code of the signal method
        signal_method_source = inspect.getsource(SysHandler.signal)
        
        print("\nACTUAL SIGNAL HANDLER CODE:")
        print("=" * 50)
        print(signal_method_source)
        print("=" * 50)
        
        # Identify unsafe operations in the source
        unsafe_patterns = [
            ('logger.info', 'Logging operations are not async-signal-safe'),
            ('logger.error', 'Logging operations are not async-signal-safe'),
            ('.get(', 'Dictionary access can trigger memory allocation'),
            ('getattr(', 'Attribute access can trigger Python machinery'),
            ('traceback.format_exc', 'Traceback formatting involves complex operations'),
            ('sys.exit', 'sys.exit() is not async-signal-safe'),
            ('% ', 'String formatting is not async-signal-safe'),
            ('.upper()', 'String methods are not async-signal-safe')
        ]
        
        print("\nUNSAFE OPERATIONS FOUND IN SIGNAL HANDLER:")
        print("-" * 50)
        
        found_unsafe = False
        for pattern, explanation in unsafe_patterns:
            if pattern in signal_method_source:
                print(f"❌ {pattern}: {explanation}")
                found_unsafe = True
        
        if found_unsafe:
            print("\n🚨 SIGNAL HANDLER VIOLATES ASYNC-SIGNAL-SAFETY!")
            print("This can cause deadlocks, crashes, or undefined behavior.")
        else:
            print("✅ No obvious unsafe operations found.")


if __name__ == '__main__':
    import unittest
    unittest.main(verbosity=2)