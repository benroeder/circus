#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test the exact production scenario from BUG-4 stack trace.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from circus.stream.redirector import Redirector
from tornado import ioloop

def test_production_scenario():
    """Test the exact scenario that caused the production error."""
    
    print("Testing production scenario from BUG-4...")
    
    # Create redirector 
    redirector = Redirector(
        stdout_redirect=lambda x: None,
        stderr_redirect=lambda x: None
    )
    
    # Mock a tornado IOLoop that already has the handler removed
    class ProductionMockLoop:
        def __init__(self):
            self.handlers = {}
            
        def add_handler(self, fd, handler, events):
            print("  IOLoop.add_handler(fd=%d)" % fd)
            if fd in self.handlers:
                raise ValueError("fd %d added twice" % fd)
            self.handlers[fd] = handler
            
        def remove_handler(self, fd):
            print("  IOLoop.remove_handler(fd=%d)" % fd)
            if fd not in self.handlers:
                # This is what happens in production - handler already removed
                raise KeyError("fd %d not found in handlers" % fd)
            del self.handlers[fd]
    
    redirector.loop = ProductionMockLoop()
    
    # Simulate the exact production scenario:
    # 1. Handler was added to IOLoop
    fd = 23
    redirector.loop.add_handler(fd, "handler", ioloop.IOLoop.READ)
    redirector._active[fd] = "handler"
    
    # 2. Something else removed it from IOLoop (tornado cleanup, etc)
    del redirector.loop.handlers[fd]
    
    # 3. Circus tries to clean up - this would crash before our fix
    print("State before cleanup:")
    print("  IOLoop has fd %d: %s" % (fd, fd in redirector.loop.handlers))
    print("  _active has fd %d: %s" % (fd, fd in redirector._active))
    
    try:
        result = redirector._stop_one(fd)
        print("After cleanup:")
        print("  returned: %d" % result)
        print("  IOLoop has fd %d: %s" % (fd, fd in redirector.loop.handlers))
        print("  _active has fd %d: %s" % (fd, fd in redirector._active))
        print("SUCCESS: Production scenario handled gracefully!")
        return True
        
    except Exception as e:
        print("FAILED: Production scenario still crashes: %s" % e)
        return False

if __name__ == "__main__":
    success = test_production_scenario()
    sys.exit(0 if success else 1)