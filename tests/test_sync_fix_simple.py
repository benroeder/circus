#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Simple test to validate synchronization fix.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from circus.util import synchronized
from circus.exc import ConflictError

def test_synchronization_fix():
    """Test that the synchronization fix works correctly."""
    
    print("Testing synchronization fix...")
    
    # Create a mock arbiter object
    class MockArbiter:
        def __init__(self):
            self._restarting = False
            self._exclusive_running_command = None
    
    # Create a mock object that has an arbiter
    class MockObject:
        def __init__(self):
            self.arbiter = MockArbiter()
    
    obj = MockObject()
    
    # Test 1: Basic synchronization still works
    @synchronized("test_command")
    def test_sync_method(self):
        return "test_result"
    
    result = test_sync_method(obj)
    print("✅ Basic synchronization works: %s" % result)
    assert result == "test_result"
    assert obj.arbiter._exclusive_running_command is None
    
    # Test 2: Nested operations from manage_watchers should be allowed
    @synchronized("manage_watchers")
    def manage_watchers_method(self):
        print("  In manage_watchers, command: %s" % self.arbiter._exclusive_running_command)
        
        @synchronized("arbiter_start_watchers")
        def start_watchers_method(inner_self):
            print("  In start_watchers, command: %s" % inner_self.arbiter._exclusive_running_command)
            return "started"
        
        # This should work - nested operation from manage_watchers
        result = start_watchers_method(self)
        print("  After start_watchers, command: %s" % self.arbiter._exclusive_running_command)
        return result
    
    try:
        result = manage_watchers_method(obj)
        print("✅ Nested operations allowed: %s" % result)
        success = True
    except ConflictError as e:
        print("❌ Nested operations blocked: %s" % e)
        success = False
    
    assert success, "Nested operations should be allowed"
    
    # Test 3: True conflicts should still be blocked
    obj.arbiter._exclusive_running_command = "some_other_command"
    
    try:
        test_sync_method(obj)
        print("❌ Conflict not detected")
        conflict_blocked = False
    except ConflictError as e:
        print("✅ True conflicts still blocked: %s" % e)
        conflict_blocked = True
    
    assert conflict_blocked, "True conflicts should be blocked"
    
    print("✅ All synchronization tests passed!")
    return True

if __name__ == "__main__":
    success = test_synchronization_fix()
    sys.exit(0 if success else 1)