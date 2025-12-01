import os
import json
import time
import shutil
from pathlib import Path
from threading import RLock

# Thread safety for config operations
_config_lock = RLock()

# Default configuration - UNIFIED
DEFAULT_CONFIG = {
    # API Configuration
    "api_key": "",
    "gemini_api_key": "",
    "api_base": "gemini",  # "openrouter" or "gemini"
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
    
    # Persistence metadata
    "_config_version": None,  # Will be synced with VRITRA_VERSION on first load/save
    "_last_updated": None
}

# Professional config directory structure with better Windows support
CONFIG_DIR = os.path.expanduser("~/.config-vritrasecz/vritraai")

def ensure_config_directory():
    """Ensure config directory exists with proper permissions."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        # Test write permissions
        test_file = os.path.join(CONFIG_DIR, ".test_write")
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
        return True
    except PermissionError:
        print(f"⚠️ Warning: No write permission to config directory: {CONFIG_DIR}")
        return False
    except Exception as e:
        print(f"⚠️ Warning: Could not create config directory: {e}")
        return False

ensure_config_directory()
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
CONFIG_BACKUP_FILE = os.path.join(CONFIG_DIR, "config.json.backup")

def create_config_backup():
    """Create a backup of the config file."""
    try:
        if os.path.exists(CONFIG_FILE):
            shutil.copy2(CONFIG_FILE, CONFIG_BACKUP_FILE)
            return True
    except Exception:
        pass
    return False

def restore_config_from_backup():
    """Restore config from backup if main config is corrupted."""
    try:
        if os.path.exists(CONFIG_BACKUP_FILE):
            shutil.copy2(CONFIG_BACKUP_FILE, CONFIG_FILE)
            return True
    except Exception:
        pass
    return False

def validate_config(config):
    """Validate configuration data."""
    if not isinstance(config, dict):
        return False
    
    # Check required keys exist
    required_keys = ['api_key', 'theme', 'prompt_style']
    for key in required_keys:
        if key not in config:
            return False
    
    # Validate theme exists
    valid_themes = [
        'dark','light','retro','cyberpunk','matrix','hacker_green',
        'terminal_green','neon','rainbow','purple','cherry','mint',
        'ocean','sunset','forest','winter','spring','summer',
        'grayscale','royal','coffee','autumn','pastel','toxic',
        'volcano','galaxy','deep_sea','candy','lava','ice',
        'electric','forest_night','synthwave','desert_sunset',
        'midnight','sunrise','lavender'
    ]
    if config.get('theme') not in valid_themes:
        config['theme'] = 'matrix'
    
    return True

def load_config():
    """Load configuration from file with robust error handling."""
    with _config_lock:
        attempts = 0
        max_attempts = 3
        
        while attempts < max_attempts:
            try:
                if os.path.exists(CONFIG_FILE):
                    # Try to read config
                    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if not content:
                            raise ValueError("Empty config file")
                        
                        config = json.loads(content)
                        
                        # Validate config structure
                        if not validate_config(config):
                            raise ValueError("Invalid config structure")
                        
                        # Merge with defaults for new keys
                        merged_config = DEFAULT_CONFIG.copy()
                        merged_config.update(config)
                        merged_config["_last_updated"] = time.time()
                        
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
                        
                        # Save merged config back (adds any new default keys)
                        _save_config_unsafe(merged_config)
                        
                        print(f"✅ Configuration loaded successfully from {CONFIG_FILE}")
                        return merged_config
                else:
                    # No config file exists, create default
                    print(f"📝 Creating default configuration at {CONFIG_FILE}")
                    default_config = DEFAULT_CONFIG.copy()
                    default_config["_last_updated"] = time.time()
                    _save_config_unsafe(default_config)
                    return default_config
                    
            except (json.JSONDecodeError, ValueError) as e:
                print(f"⚠️ Config file corrupted (attempt {attempts + 1}): {e}")
                
                # Try to restore from backup
                if attempts == 0 and restore_config_from_backup():
                    print("🔄 Restored config from backup")
                    attempts += 1
                    continue
                
                # If still failing, recreate config
                if attempts >= max_attempts - 1:
                    print("🆕 Creating fresh configuration")
                    try:
                        os.remove(CONFIG_FILE)
                    except:
                        pass
                    default_config = DEFAULT_CONFIG.copy()
                    default_config["_last_updated"] = time.time()
                    _save_config_unsafe(default_config)
                    return default_config
                    
            except Exception as e:
                print(f"❌ Unexpected error loading config (attempt {attempts + 1}): {e}")
                
            attempts += 1
        
        # Fallback to defaults if all attempts failed
        print("⚠️ Using default configuration (file operations failed)")
        fallback_config = DEFAULT_CONFIG.copy()
        # Try to sync version even in fallback
        try:
            import sys
            if 'vritraai' in sys.modules:
                vritraai_module = sys.modules['vritraai']
                if hasattr(vritraai_module, 'VRITRA_VERSION'):
                    fallback_config["_config_version"] = vritraai_module.VRITRA_VERSION
        except Exception:
            pass  # Silently fail if version sync not possible
        return fallback_config

def _save_config_unsafe(config):
    """Save configuration without acquiring lock (internal use only)."""
    if not ensure_config_directory():
        print("❌ Cannot save config: directory not accessible")
        return False
    
    try:
        # Validate config before saving
        if not validate_config(config):
            print("❌ Cannot save invalid config")
            return False
        
        # Create backup before saving
        create_config_backup()
        
        # Sync _config_version from vritraai if available (avoid circular import)
        try:
            import sys
            if 'vritraai' in sys.modules:
                vritraai_module = sys.modules['vritraai']
                if hasattr(vritraai_module, 'VRITRA_VERSION'):
                    config["_config_version"] = vritraai_module.VRITRA_VERSION
        except Exception:
            pass  # Silently fail if version sync not possible
        
        # Update timestamp
        config["_last_updated"] = time.time()
        
        # Write to temporary file first, then rename (atomic operation)
        temp_file = CONFIG_FILE + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            f.flush()  # Ensure data is written to disk
            os.fsync(f.fileno())  # Force OS to write to disk
        
        # Atomic rename
        if os.path.exists(CONFIG_FILE):
            os.replace(temp_file, CONFIG_FILE)
        else:
            os.rename(temp_file, CONFIG_FILE)
        
        print(f"💾 Configuration saved successfully to {CONFIG_FILE}")
        return True
        
    except PermissionError:
        print(f"❌ Permission denied saving config to {CONFIG_FILE}")
        return False
    except Exception as e:
        print(f"❌ Error saving config: {e}")
        # Clean up temp file if it exists
        try:
            temp_file = CONFIG_FILE + ".tmp"
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except:
            pass
        return False

def save_config(config):
    """Save configuration to file with robust error handling."""
    with _config_lock:
        return _save_config_unsafe(config)

def get_config_value(key, default=None):
    """Get a specific configuration value."""
    config = load_config()
    return config.get(key, default)

def set_config_value(key, value):
    """Set a specific configuration value."""
    config = load_config()
    config[key] = value
    return save_config(config)

def reset_config():
    """Reset configuration to defaults."""
    try:
        create_config_backup()
        default_config = DEFAULT_CONFIG.copy()
        default_config["_last_updated"] = time.time()
        # Sync _config_version with VRITRA_VERSION when resetting
        try:
            import sys
            if 'vritraai' in sys.modules:
                vritraai_module = sys.modules['vritraai']
                if hasattr(vritraai_module, 'VRITRA_VERSION'):
                    default_config["_config_version"] = vritraai_module.VRITRA_VERSION
        except Exception:
            pass  # Silently fail if version sync not possible
        if save_config(default_config):
            print("🔄 Configuration reset to defaults")
            return True
    except Exception as e:
        print(f"❌ Error resetting config: {e}")
    return False

# Load configuration with new robust system
config = load_config()
API_KEY = config.get("api_key", "")
GEMINI_API_KEY = config.get("gemini_api_key", "")
API_BASE = config.get("api_base", "gemini")
MODEL = config.get("model", "gemini-2.0-flash")

# Export main functions for external use
__all__ = ['load_config', 'save_config', 'get_config_value', 'set_config_value', 'reset_config', 
           'API_KEY', 'GEMINI_API_KEY', 'API_BASE', 'MODEL', 'CONFIG_FILE', 'CONFIG_DIR']
