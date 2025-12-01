# Changelog

All notable changes to VritraAI will be documented in this file.

## [0.29.5] - 2025-12-01

### Added
- Smart interactive command detection with comprehensive pattern matching
- Enhanced error recovery system with AI-powered suggestions
- Traceback sanitization to improve AI error analysis accuracy
- Support for detecting interactive commands with flags (`-i`, `--interactive`, `-it`, `-ti`)
- Improved detection of "command not found" errors (exit code 127)
- Enhanced history command with timestamps, head/tail piping support, and duplicate prevention
- Comprehensive path expansion for ~ and environment variables across all file/directory commands
- Enhanced AI context system - all AI requests now include full system info, directory structure, and project details
- Improved command validation - detects and rejects invalid flags/arguments before launching interactive shell
- `expand_path()` helper function for consistent path expansion across all commands
- `build_comprehensive_context()` function for rich AI context with system and directory information

### Fixed
- **Interactive commands now work properly** - Fixed issue where interactive commands (vim, nano, python, node, docker exec -it, etc.) would get stuck without output
- **Error recovery for system commands** - System commands like `bash test.sh` (when file doesn't exist) now properly show recovery options menu
- **AI error analysis** - Traceback sanitization removes vritraai.py references so AI focuses on user's actual errors instead of shell wrapper code
- Improved terminal handling for interactive subprocess commands
- Better error message detection from stderr for "not found" type errors
- **History command display** - Now correctly counts and shows only commands (not timestamps as separate entries)
- **Path expansion issues** - Commands like `ls ~/.config-vritrasecz/vritraai/` now work correctly
- **History duplicate entries** - Fixed issue where commands were being saved twice with file locking and duplicate detection
- **Invalid flag/argument handling** - Now properly detects and rejects invalid flags and non-flag arguments
- **OS info detection** - Robust error handling for Termux/Android environments with fallback methods

### Changed
- Interactive command execution now uses simpler subprocess approach (matching testt.py implementation)
- Error recovery system now checks actual error messages from stderr, not just exit codes
- Enhanced interactive command detection to include more patterns (git commands, docker, kubectl, etc.)
- **Error recovery prompts** - AI now provides multiple fix command options (3-5 different approaches) instead of single suggestions
- **Traceback display** - Removed full traceback display, now shows only error type and message for cleaner output
- **AI response branding** - All AI output now shows "VritraAI:" instead of "AI:" for consistent branding
- **History recording** - Enhanced with file locking, duplicate detection, and proper timestamp pairing
- **History display** - Improved formatting with cleaner output, proper command counting, and timestamp display

### Improved
- **History command** - Now supports piping to head/tail commands (e.g., `history | head 5`)
- **Path detection** - All file/directory commands now automatically expand shell variables (~, $VAR)
- **AI context** - Comprehensive context building includes system info, Python version, shell, directory structure, and project type
- **OS info function** - Enhanced `get_os_info()` with robust error handling, fallback methods, and Termux/Android detection
- **Error recovery** - AI suggestions now include multiple fix approaches with step-by-step instructions

### Technical Details
- Updated `is_interactive_command()` function with comprehensive detection patterns
- Added `sanitize_traceback_for_ai()` function to filter out shell wrapper code from tracebacks
- Improved error handling in both `subprocess.run()` and `subprocess.Popen()` code paths
- Enhanced `build_smart_error_context()` to use sanitized tracebacks
- Added `record_command_to_history()` function with file locking and duplicate prevention
- Created `_get_history_commands()` helper function for reusable history parsing
- Added `history_command_with_pipe()` function for head/tail support
- Implemented `expand_path()` function for consistent path expansion
- Enhanced `build_comprehensive_context()` for rich AI context
- Improved `get_os_info()` with fallback methods and Termux/Android detection
- Updated `parse_flags()` to detect invalid flags and non-flag arguments

## [0.29.1] - 2025-11-27

### Fixed
- **OpenAI library compatibility in Termux** - Fixed installation issues caused by `openai>=1.0.0` dependency
- Pinned OpenAI library to `openai==0.28.0` for stable Termux compatibility
- Resolved breaking issues with new OpenAI module dependencies that were causing installation failures
- The newer OpenAI version (1.0.0+) was installing incompatible modules that broke in Termux environment

## [0.29.0] - 2025-11-27

### Added
- Initial release of VritraAI
- AI-powered terminal shell with advanced features
- Beautiful theming and prompt customization
- Powerful command execution capabilities
- Built-in AI assistant for command suggestions and error recovery
- Rich terminal output formatting
- Command history and session management
- Project detection and analysis features
- Code review and optimization tools
- Security scanning capabilities
- And many more features...

---

[0.29.5]: https://github.com/VritraSecz/VritraAI/compare/v0.29.1...v0.29.5
[0.29.1]: https://github.com/VritraSecz/VritraAI/compare/v0.29.0...v0.29.1
[0.29.0]: https://github.com/VritraSecz/VritraAI/releases/tag/v0.29.0

