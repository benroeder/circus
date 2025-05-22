# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## About Circus

Circus is a process and socket management system for Python applications. It runs, monitors, and controls multiple processes and sockets from a central daemon using ZeroMQ for distributed communication.

## Development Commands

### Testing
```bash
# Run tests with tox (recommended)
tox

# Run tests with pytest directly
pytest tests/

# Run specific test file
pytest tests/test_arbiter.py

# Run with coverage
pytest --cov=circus tests/
```

### Build and Documentation
```bash
# Build documentation
make docs

# Generate coverage report  
make coverage

# Clean build artifacts
make clean
```

### Installation for Development
```bash
# Install in development mode
pip install -e .

# Install with test dependencies
pip install -e .[test]
```

## Core Architecture

Circus follows a **multi-process architecture** with ZeroMQ communication:

### Main Components

**Arbiter** (`circus/arbiter.py`)
- Central coordinator managing all watchers
- Handles configuration loading/reloading
- Manages ZeroMQ communication endpoints
- Entry point: `circusd`

**Watcher** (`circus/watcher.py`)
- Manages groups of processes for a single command
- Handles process lifecycle and restart policies
- Supports hooks for custom startup/shutdown logic

**Process** (`circus/process.py`)
- Wraps individual OS processes using psutil
- Provides process control and monitoring

**Controller** (`circus/controller.py`)
- ZeroMQ-based command processor
- Handles commands from `circusctl` client

**Client** (`circus/client.py`)
- ZeroMQ client for daemon communication
- Used by `circusctl` and programmatic access

### Communication Endpoints
- **Controller**: tcp://127.0.0.1:5555 (commands)
- **PubSub**: tcp://127.0.0.1:5556 (events)
- **Stats**: tcp://127.0.0.1:5557 (statistics)

### Configuration System
- INI-based configuration files
- Sections: `[circus]`, `[watcher:name]`, `[socket:name]`, `[plugin:name]`
- Supports environment variable expansion
- Live reloading without service restart

## Extension Points

### Adding Commands (`circus/commands/`)
1. Create new command class inheriting from `Command`
2. Implement `message()` and `execute()` methods
3. Add to command registry

### Writing Plugins (`circus/plugins/`)
1. Inherit from `CircusPlugin`
2. Implement event handlers (`handle_recv()`)
3. Register in configuration as `[plugin:name]`

### Custom Hooks
- `before_start`, `after_start`, `before_stop`, `after_stop`
- Define in watcher configuration
- Can be Python callables or shell commands

## Testing Patterns

### Test Structure
- Tests in `tests/` directory
- Configuration files in `tests/config/`
- Use `TestCase` from `tests.support`
- Mock external dependencies

### Running Specific Tests
```bash
# Test specific functionality
pytest tests/test_watcher.py::TestWatcher::test_process_spawn

# Test command functionality  
pytest tests/test_command_*.py
```

## Key Modules

- `circus/arbiter.py` - Main process coordinator
- `circus/watcher.py` - Process group management
- `circus/process.py` - Individual process wrapper
- `circus/controller.py` - Command handling
- `circus/config.py` - Configuration parsing
- `circus/util.py` - Common utilities
- `circus/stats/` - Statistics collection and streaming
- `circus/stream/` - Output redirection handling

## Dependencies

Core dependencies managed in `pyproject.toml`:
- `psutil` - Process monitoring
- `pyzmq` - ZeroMQ messaging
- `tornado` - Async I/O (for web components)

## Known Issues and Bug Fix Plan

### Critical Issues Identified

#### 1. Signal Handler Safety Issues (HIGH PRIORITY)
**Location**: `circus/sighandler.py:48-61`
**Problem**: Signal handlers perform non-async-signal-safe operations (logging, string operations, exception handling)
**Impact**: Can cause deadlocks, crashes, or signal handler corruption
**Test**: `test_signal_handler_deadlock.py` - Send rapid signals while monitoring for deadlocks

#### 2. Process Reaping Race Condition (HIGH PRIORITY) 
**Location**: `circus/arbiter.py:615-641`
**Problem**: Race condition between building process mapping and waitpid() calls
**Impact**: Orphaned/zombie processes, inconsistent process counts
**Test**: `test_reaping_race_condition.py` - Kill processes externally while circus is reaping

#### 3. Resource Leaks (MEDIUM PRIORITY)
**Locations**: 
- `circus/process.py:220-234` - devnull fd not closed on error
- `circus/process.py:254-260` - socket leaks on bind failure
**Impact**: File descriptor exhaustion over time
**Test**: `test_resource_leaks.py` - Monitor `/proc/pid/fd/` during failure scenarios

#### 4. ThreadedArbiter Signal Issues (MEDIUM PRIORITY)
**Location**: `circus/arbiter.py:820-836`
**Problem**: Signal handlers designed for single-threaded operation used with threading
**Impact**: Signals delivered to arbitrary threads, race conditions
**Test**: `test_threaded_arbiter_signals.py` - Verify signal handling in threaded context

#### 5. Missing SIGCHLD Handler (MEDIUM PRIORITY)
**Problem**: No explicit SIGCHLD handler, relies on polling for process reaping
**Impact**: Delayed detection of child process deaths, potential zombies
**Test**: `test_sigchld_handling.py` - Measure time between child death and detection

#### 6. Stream Redirector Lifecycle Issues (LOW PRIORITY)
**Location**: `circus/watcher.py:640-642`
**Problem**: Stream redirector started before process spawn, not cleaned up on failure
**Impact**: Resource leaks, orphaned threads
**Test**: `test_stream_redirector_lifecycle.py` - Force spawn failures, verify cleanup

### Bug Fix Plan

#### Phase 1: Write Comprehensive Tests
1. Create test framework for bug reproduction
2. Implement tests for each identified issue
3. Document specific failure modes and resource leaks
4. Establish baseline measurements for resource usage

#### Phase 2: Fix Critical Issues
1. **Signal Handler Safety**: Rewrite handlers to use self-pipe trick or signalfd
2. **Process Reaping Race**: Add proper synchronization or atomic operations
3. **Resource Leaks**: Add proper error handling and cleanup in all paths

#### Phase 3: Fix Medium Priority Issues  
1. **ThreadedArbiter**: Implement thread-safe signal handling
2. **SIGCHLD Handler**: Add immediate process reaping via signal handler
3. **Error Handling**: Improve error propagation and resource cleanup

#### Phase 4: Fix Low Priority Issues
1. **Signal Interruption**: Configure all relevant signals properly
2. **Stream Redirector**: Fix lifecycle management

#### Phase 5: Verification
1. Run all tests to verify fixes
2. Perform stress testing and resource monitoring
3. Test on multiple platforms and Python versions

### Testing Strategy

#### Test Types
- **Unit Tests**: Specific bug reproduction cases
- **Integration Tests**: End-to-end scenarios with resource monitoring
- **Stress Tests**: High-load scenarios to trigger race conditions
- **Platform Tests**: Linux, macOS, different Python versions

#### Resource Monitoring
- File descriptor tracking via `/proc/pid/fd/` and `lsof`
- Process monitoring for zombies/orphans via `ps`
- Signal handler execution tracing via `strace`/`dtrace`
- Memory leak detection for long-running tests

#### Verification Criteria
- No resource leaks after test completion
- Proper signal handler execution (async-signal-safe only)
- No race conditions under stress testing
- Clean process lifecycle management
- Consistent behavior across platforms