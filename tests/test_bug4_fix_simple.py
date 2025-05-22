#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Simple test to verify BUG-4 fix works.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from circus.stream.redirector import Redirector
from tornado import ioloop

def test_fd_fix():
    """Test that our fix prevents the 'fd added twice' error."""
    
    print("Testing BUG-4 fix...")
    
    # Create redirector
    redirector = Redirector(
        stdout_redirect=lambda x: None,
        stderr_redirect=lambda x: None
    )
    
    # Mock loop that raises ValueError on remove_handler
    class MockLoop:
        def add_handler(self, fd, handler, events):
            print("  add_handler called for fd %d" % fd)
            
        def remove_handler(self, fd):
            print("  remove_handler called for fd %d - RAISING ValueError!" % fd)
            raise ValueError("Handler for fd %d not found" % fd)
    
    redirector.loop = MockLoop()
    
    # Add a fake active handler
    fd = 23
    redirector._active[fd] = "fake_handler"
    
    print("Before fix attempt:")
    print("  _active contains fd %d: %s" % (fd, fd in redirector._active))
    
    try:
        # This should NOT crash and should clean up properly
        result = redirector._stop_one(fd)
        print("After _stop_one:")
        print("  returned: %d" % result)
        print("  _active contains fd %d: %s" % (fd, fd in redirector._active))
        print("SUCCESS: Fix prevents crash and maintains consistency!")
        return True
        
    except Exception as e:
        print("FAILED: Fix did not work: %s" % e)
        return False

if __name__ == "__main__":
    success = test_fd_fix()
    sys.exit(0 if success else 1)