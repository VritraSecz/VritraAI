#!/usr/bin/env python3
"""
Enhanced Configuration Manager for VritraAI Shell
Handles unified configuration persistence with robust error handling
"""

import os
import json
import time
import shutil
import threading
from pathlib import Path
from typing import Dict, Any, Optional, Union

class ConfigurationManager:
    """Centralized configuration management with persistence and error recovery."""
    
    def __init__(self, config_dir: Optional[str] = None):
        self._lock = threading.RLock()  # Reentrant lock for nested calls
        self._config_cache = {}
        self._cache_timestamp = 0
        self._cache_ttl = 5.0  # Cache valid for 5 seconds
        
        # Set up paths
        if config_dir is None:
            config_dir = os.path.expanduser("~/.config-vritrasecz/vritraai")
        
        self.config_dir = Path(config_dir)
        self.config_file = self.config_dir / "config.json"
        self.backup_file = self.config_dir / "config.json.backup"
        self.lock_file = self.config_dir / ".config.lock"
        
        # Default configuration
        self.defaults = {
            # API Configuration
            "api_key": "",
            "gemini_api_key": "",
            "api_base": "gemini",
            "model": "gemini-2.0-flash",
            "ai_enabled": False,
            
            # UI Configuration
            "theme": "matrix",
            "prompt_style": "hacker",
            
            # Banner / MOTD Configuration
            # banner_id: string identifier of the selected banner ("1".."25")
            # banner_random: when True, a random banner is chosen on startup
            # banner_sync: when True, banners use theme-based (Rich) colors;
            #              when False, use hardcoded ANSI-colored templates.
            "banner_id": "1",
            "banner_random": False,
            "banner_sync": True,
            
            # System Configuration
            "safe_mode": True,
            "auto_backup": True,
            "log_commands": True,
            "command_prefix": "",
            "paranoid_mode": False,
            "model_profile": "quality",
            "offline_mode": False,
            "auto_model_switch": True,
            
            # Feedback / telemetry
            "feedback_worker_url": "https://feedback-n-review.vritrasec.workers.dev/",
            
            # Metadata
            "_config_version": None,  # Will be synced with VRITRA_VERSION on first load/save
            "_created_timestamp": None,
            "_last_updated": None,
            "_update_count": 0
        }
        
        # Initialize
        self._ensure_directory()
        self._initialize_config()
    
    def _ensure_directory(self) -> bool:
        """Ensure configuration directory exists with proper permissions."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            
            # Test write permissions
            test_file = self.config_dir / ".test_write"
            test_file.write_text("test")
            test_file.unlink()
            return True
            
        except PermissionError:
            print(f"[WARNING] Permission denied: {self.config_dir}")
            return False
        except Exception as e:
            print(f"[WARNING] Directory error: {e}")
            return False
    
    def _acquire_file_lock(self, timeout: float = 5.0) -> bool:
        """Acquire file-based lock for config operations."""
        start_time = time.time()
        retry_count = 0
        
        while time.time() - start_time < timeout:
            try:
                if not self.lock_file.exists():
                    # Create lock file atomically
                    try:
                        # Use exclusive creation to avoid race conditions
                        with self.lock_file.open('x') as f:  # 'x' mode fails if file exists
                            f.write(str(os.getpid()))
                        return True
                    except FileExistsError:
                        # Lock file was created by another process, continue to check
                        pass
                
                # Check if existing lock is stale
                try:
                    lock_content = self.lock_file.read_text().strip()
                    if not lock_content:
                        # Empty lock file, remove it
                        self.lock_file.unlink()
                        continue
                        
                    lock_pid = int(lock_content)
                    
                    # Check if the process still exists
                    try:
                        import psutil
                        if not psutil.pid_exists(lock_pid):
                            self.lock_file.unlink()
                            continue
                    except ImportError:
                        # Fallback: check lock age
                        try:
                            lock_age = time.time() - self.lock_file.stat().st_mtime
                            if lock_age > 30:  # 30 seconds timeout
                                self.lock_file.unlink()
                                continue
                        except Exception:
                            pass
                    
                    # If we're here, lock is held by an active process
                    
                except (ValueError, FileNotFoundError):
                    # Invalid or missing lock file, remove it
                    try:
                        self.lock_file.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                
                # Wait with exponential backoff
                retry_count += 1
                wait_time = min(0.1 * (2 ** min(retry_count, 4)), 0.5)  # Max 0.5 seconds
                time.sleep(wait_time)
                
            except Exception as e:
                # On any exception, wait briefly and try again
                time.sleep(0.1)
        
        return False
    
    def _release_file_lock(self):
        """Release file-based lock."""
        try:
            if self.lock_file.exists():
                self.lock_file.unlink()
        except Exception:
            pass
    
    def _create_backup(self) -> bool:
        """Create backup of current configuration."""
        try:
            if self.config_file.exists():
                shutil.copy2(str(self.config_file), str(self.backup_file))
                return True
        except Exception:
            pass
        return False
    
    def _restore_from_backup(self) -> bool:
        """Restore configuration from backup."""
        try:
            if self.backup_file.exists():
                shutil.copy2(str(self.backup_file), str(self.config_file))
                return True
        except Exception:
            pass
        return False
    
    def _validate_config(self, config: Dict[str, Any]) -> bool:
        """Validate configuration structure and values."""
        if not isinstance(config, dict):
            return False
        
        # Check for required keys
        required_keys = ["api_key", "theme", "prompt_style"]
        for key in required_keys:
            if key not in config:
                return False
        
        # Validate theme exists (accept any string value - validation happens in vritraai.py)
        # We just check that it's a string type
        if "theme" in config and not isinstance(config.get("theme"), str):
            config["theme"] = "matrix"
        
        valid_api_bases = ["openrouter", "gemini"]
        if config.get("api_base") not in valid_api_bases:
            config["api_base"] = "gemini"
        
        return True
    
    def _initialize_config(self):
        """Initialize configuration system."""
        with self._lock:
            if not self.config_file.exists():
                # Create initial config
                initial_config = self.defaults.copy()
                initial_config["_created_timestamp"] = time.time()
                initial_config["_last_updated"] = time.time()
                # Sync _config_version with VRITRA_VERSION on first initialization
                try:
                    import sys
                    if 'vritraai' in sys.modules:
                        vritraai_module = sys.modules['vritraai']
                        if hasattr(vritraai_module, 'VRITRA_VERSION'):
                            initial_config["_config_version"] = vritraai_module.VRITRA_VERSION
                except Exception:
                    pass  # Silently fail if version sync not possible
                self._save_config_unsafe(initial_config)
                print(f"🔧 Initialized VritraAI configuration at {self.config_file}")
    
    def _load_config_unsafe(self) -> Dict[str, Any]:
        """Load configuration without thread safety (internal use)."""
        attempts = 0
        max_attempts = 3
        
        while attempts < max_attempts:
            try:
                if not self.config_file.exists():
                    return self.defaults.copy()
                
                # Read and parse config
                content = self.config_file.read_text(encoding='utf-8').strip()
                if not content:
                    raise ValueError("Empty configuration file")
                
                config = json.loads(content)
                
                # Validate and merge with defaults
                if not self._validate_config(config):
                    raise ValueError("Invalid configuration structure")
                
                # Merge with defaults to add new keys
                merged_config = self.defaults.copy()
                merged_config.update(config)
                
                # Sync _config_version if None or missing
                if not merged_config.get("_config_version"):
                    try:
                        import sys
                        if 'vritraai' in sys.modules:
                            vritraai_module = sys.modules['vritraai']
                            if hasattr(vritraai_module, 'VRITRA_VERSION'):
                                merged_config["_config_version"] = vritraai_module.VRITRA_VERSION
                    except Exception:
                        pass
                
                # Update cache
                self._config_cache = merged_config
                self._cache_timestamp = time.time()
                
                return merged_config
                
            except (json.JSONDecodeError, ValueError) as e:
                print(f"[WARNING] Config corruption (attempt {attempts + 1}): {e}")
                
                if attempts == 0 and self._restore_from_backup():
                    print("[INFO] Restored from backup")
                    attempts += 1
                    continue
                
                if attempts >= max_attempts - 1:
                    print("[INFO] Creating fresh configuration")
                    try:
                        self.config_file.unlink()
                    except Exception:
                        pass
                    
                    fresh_config = self.defaults.copy()
                    fresh_config["_created_timestamp"] = time.time()
                    fresh_config["_last_updated"] = time.time()
                    # Sync _config_version with VRITRA_VERSION when recreating
                    try:
                        import sys
                        if 'vritraai' in sys.modules:
                            vritraai_module = sys.modules['vritraai']
                            if hasattr(vritraai_module, 'VRITRA_VERSION'):
                                fresh_config["_config_version"] = vritraai_module.VRITRA_VERSION
                    except Exception:
                        pass  # Silently fail if version sync not possible
                    return fresh_config
            
            except Exception as e:
                print(f"[ERROR] Config load error (attempt {attempts + 1}): {e}")
            
            attempts += 1
        
        # Fallback to defaults
        print("[WARNING] Using default configuration")
        return self.defaults.copy()
    
    def _save_config_unsafe(self, config: Dict[str, Any]) -> bool:
        """Save configuration without thread safety (internal use)."""
        try:
            if not self._validate_config(config):
                print("[ERROR] Invalid configuration data")
                return False
            
            # Create backup
            self._create_backup()
            
            # Sync _config_version from vritraai if available (avoid circular import)
            try:
                import sys
                if 'vritraai' in sys.modules:
                    vritraai_module = sys.modules['vritraai']
                    if hasattr(vritraai_module, 'VRITRA_VERSION'):
                        config["_config_version"] = vritraai_module.VRITRA_VERSION
            except Exception:
                pass  # Silently fail if version sync not possible
            
            # Update metadata
            config["_last_updated"] = time.time()
            config["_update_count"] = config.get("_update_count", 0) + 1
            
            # Atomic write via temporary file
            temp_file = self.config_file.with_suffix('.tmp')
            
            with temp_file.open('w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            
            # Atomic rename
            if os.name == 'nt':  # Windows
                if self.config_file.exists():
                    self.config_file.unlink()
                temp_file.rename(self.config_file)
            else:  # Unix-like
                temp_file.replace(self.config_file)
            
            # Update cache
            self._config_cache = config.copy()
            self._cache_timestamp = time.time()
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Save config error: {e}")
            # Cleanup temp file
            try:
                temp_file = self.config_file.with_suffix('.tmp')
                if temp_file.exists():
                    temp_file.unlink()
            except Exception:
                pass
            return False
    
    def load_config(self, use_cache: bool = True) -> Dict[str, Any]:
        """Load configuration with thread safety and caching."""
        with self._lock:
            # Use cache if valid and requested
            if (use_cache and self._config_cache and 
                time.time() - self._cache_timestamp < self._cache_ttl):
                return self._config_cache.copy()
            
            # Acquire file lock for read
            if self._acquire_file_lock():
                try:
                    config = self._load_config_unsafe()
                    return config.copy()
                finally:
                    self._release_file_lock()
            else:
                print("[WARNING] Could not acquire config lock for reading, using cache/defaults")
                return self._config_cache.copy() if self._config_cache else self.defaults.copy()
    
    def save_config(self, config: Dict[str, Any]) -> bool:
        """Save configuration with thread safety and file locking."""
        with self._lock:
            if self._acquire_file_lock():
                try:
                    success = self._save_config_unsafe(config)
                    if success:
                        print(f"[SUCCESS] Configuration saved successfully")
                    return success
                finally:
                    self._release_file_lock()
            else:
                print("[ERROR] Could not acquire config lock for writing")
                return False
    
    def get_value(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        config = self.load_config()
        return config.get(key, default)
    
    def set_value(self, key: str, value: Any) -> bool:
        """Set a configuration value."""
        config = self.load_config()
        old_value = config.get(key)
        
        if old_value != value:
            config[key] = value
            success = self.save_config(config)
            if success:
                print(f"[CONFIG] Updated {key}: {old_value} -> {value}")
            return success
        
        return True  # No change needed
    
    def update_values(self, updates: Dict[str, Any]) -> bool:
        """Update multiple configuration values."""
        config = self.load_config()
        changed = False
        
        for key, value in updates.items():
            if config.get(key) != value:
                config[key] = value
                changed = True
        
        if changed:
            success = self.save_config(config)
            if success:
                print(f"[CONFIG] Updated {len(updates)} configuration values")
            return success
        
        return True  # No changes needed
    
    def reset_to_defaults(self) -> bool:
        """Reset configuration to default values."""
        self._create_backup()
        fresh_config = self.defaults.copy()
        fresh_config["_created_timestamp"] = time.time()
        fresh_config["_last_updated"] = time.time()
        fresh_config["_update_count"] = 0
        
        if self.save_config(fresh_config):
            print("🔄 Configuration reset to defaults")
            return True
        return False
    
    def get_config_info(self) -> Dict[str, Any]:
        """Get information about the configuration system."""
        config = self.load_config()
        
        return {
            "config_file": str(self.config_file),
            "backup_file": str(self.backup_file),
            "config_exists": self.config_file.exists(),
            "backup_exists": self.backup_file.exists(),
            "config_version": config.get("_config_version"),
            "last_updated": config.get("_last_updated"),
            "created_timestamp": config.get("_created_timestamp"),
            "update_count": config.get("_update_count", 0),
            "cache_valid": time.time() - self._cache_timestamp < self._cache_ttl
        }

# Global instance
_global_config_manager = None

def get_config_manager() -> ConfigurationManager:
    """Get global configuration manager instance."""
    global _global_config_manager
    if _global_config_manager is None:
        _global_config_manager = ConfigurationManager()
    return _global_config_manager

# Convenience functions for backward compatibility
def load_config() -> Dict[str, Any]:
    return get_config_manager().load_config()

def save_config(config: Dict[str, Any]) -> bool:
    return get_config_manager().save_config(config)

def get_config_value(key: str, default: Any = None) -> Any:
    return get_config_manager().get_value(key, default)

def set_config_value(key: str, value: Any) -> bool:
    return get_config_manager().set_value(key, value)

def reset_config() -> bool:
    return get_config_manager().reset_to_defaults()