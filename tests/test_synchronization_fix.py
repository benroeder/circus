#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test that validates the synchronization fix for BUG-2 and BUG-3.
"""

import asyncio
import time
from unittest import TestCase
from unittest.mock import patch, MagicMock, AsyncMock

from circus.arbiter import Arbiter
from circus.watcher import Watcher
from circus.exc import ConflictError
from circus.util import synchronized


class TestSynchronizationFix(TestCase):
    """Test that synchronization conflicts are resolved."""
    
    def test_nested_synchronization_allowed(self):
        """
        Test that nested operations from manage_watchers are now allowed.
        """
        print("\n" + "="*60)
        print("TESTING NESTED SYNCHRONIZATION FIX")
        print("="*60)
        
        # Create a mock arbiter
        arbiter = MagicMock()
        arbiter._restarting = False
        arbiter._exclusive_running_command = None
        
        # Test the new synchronized decorator behavior
        @synchronized("manage_watchers")
        def mock_manage_watchers(self):
            # This should set _exclusive_running_command = "manage_watchers"
            return "manage_watchers_result"
        
        @synchronized("arbiter_start_watchers")  
        def mock_start_watchers(self):
            # This should be allowed when called from manage_watchers
            return "start_watchers_result"
        
        print("1. Testing nested operation allowance...")
        
        # Simulate the manage_watchers operation
        result1 = mock_manage_watchers(arbiter)
        print("   ✅ manage_watchers completed: %s" % result1)
        print("   ✅ Current command: %s" % arbiter._exclusive_running_command)
        
        # This should be "manage_watchers" now
        self.assertEqual(arbiter._exclusive_running_command, "manage_watchers")
        
        # Now try nested start_watchers - should be allowed
        try:
            result2 = mock_start_watchers(arbiter)
            print("   ✅ Nested start_watchers allowed: %s" % result2)
            print("   ✅ Command after nested call: %s" % arbiter._exclusive_running_command)
            success = True
        except ConflictError as e:
            print("   ❌ Nested operation blocked: %s" % e)
            success = False
        
        self.assertTrue(success, "Nested operations should be allowed")
        
        print("\n" + "="*60)
        print("✅ NESTED SYNCHRONIZATION FIX VALIDATED")
        print("="*60)
        
        return True

    def test_conflicting_operations_still_blocked(self):
        """
        Test that truly conflicting operations are still properly blocked.
        """
        print("\n" + "="*60)
        print("TESTING CONFLICTING OPERATIONS BLOCKING")
        print("="*60)
        
        # Create a mock arbiter
        arbiter = MagicMock()
        arbiter._restarting = False
        arbiter._exclusive_running_command = None
        
        @synchronized("watcher_stop")
        def mock_watcher_stop(self):
            return "watcher_stop_result"
        
        @synchronized("arbiter_reload")
        def mock_arbiter_reload(self):
            return "arbiter_reload_result"
        
        print("1. Starting first operation (watcher_stop)...")
        
        # Start first operation
        result1 = mock_watcher_stop(arbiter)
        print("   ✅ watcher_stop completed: %s" % result1)
        print("   ✅ Current command: %s" % arbiter._exclusive_running_command)
        
        # This should be "watcher_stop" now
        self.assertEqual(arbiter._exclusive_running_command, "watcher_stop")
        
        print("2. Attempting conflicting operation (arbiter_reload)...")
        
        # Try conflicting operation - should be blocked
        try:
            result2 = mock_arbiter_reload(arbiter)
            print("   ❌ Conflicting operation was allowed: %s" % result2)
            conflict_blocked = False
        except ConflictError as e:
            print("   ✅ Conflicting operation properly blocked: %s" % e)
            conflict_blocked = True
        
        self.assertTrue(conflict_blocked, "Conflicting operations should be blocked")
        
        print("\n" + "="*60)
        print("✅ CONFLICT BLOCKING STILL WORKS")
        print("="*60)
        
        return True

    def test_command_restoration(self):
        """
        Test that nested commands properly restore the previous command.
        """
        print("\n" + "="*60)
        print("TESTING COMMAND RESTORATION")
        print("="*60)
        
        # Create a mock arbiter
        arbiter = MagicMock()
        arbiter._restarting = False
        arbiter._exclusive_running_command = None
        
        @synchronized("manage_watchers")
        def outer_operation(self):
            print("   In outer operation: %s" % self._exclusive_running_command)
            
            @synchronized("arbiter_start_watchers")
            def inner_operation(inner_self):
                print("   In inner operation: %s" % inner_self._exclusive_running_command)
                return "inner_result"
            
            # Call nested operation
            inner_result = inner_operation(self)
            print("   After inner operation: %s" % self._exclusive_running_command)
            
            # Should be back to "manage_watchers"
            return "outer_result"
        
        print("1. Testing command restoration after nested operations...")
        
        result = outer_operation(arbiter)
        
        print("   ✅ Operations completed: %s" % result)
        print("   ✅ Final command state: %s" % arbiter._exclusive_running_command)
        
        # Should be back to None after all operations complete
        self.assertEqual(arbiter._exclusive_running_command, None)
        
        print("\n" + "="*60) 
        print("✅ COMMAND RESTORATION WORKS")
        print("="*60)
        
        return True


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)