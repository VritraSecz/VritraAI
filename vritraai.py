#!/usr/bin/env python3

import os
import subprocess
import shutil
import re
import json
import platform
import time
import datetime
import threading
import signal
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

try:
    import openai
except ImportError:
    print("OpenAI library not found.")
    exit()

import requests

try:
    from prompt_toolkit import PromptSession, print_formatted_text
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import WordCompleter, PathCompleter, Completer, Completion
    from prompt_toolkit.styles import Style
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.shortcuts import confirm
except ImportError:
    print("prompt_toolkit library not found.")
    exit()

try:
    from rich.console import Console, Group
    from rich.syntax import Syntax
    from rich.text import Text
    from rich.panel import Panel
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("rich library not found. Install it for better output formatting: pip install rich")

# Import new unified configuration system
try:
    from config_manager import get_config_manager, ConfigurationManager
    config_manager = get_config_manager()
    current_config = config_manager.load_config()
    
    # Load configuration values
    API_KEY = current_config.get("api_key", "")
    GEMINI_API_KEY = current_config.get("gemini_api_key", "")
    API_BASE = current_config.get("api_base", "gemini")
    MODEL = current_config.get("model", "gemini-2.0-flash")
    
    print(f"[CONFIG] Configuration loaded: API_BASE={API_BASE}, Theme={current_config.get('theme')}, Prompt={current_config.get('prompt_style')}")
    
except ImportError:
    # Fallback to old system if new system not available
    try:
        from config import load_config, save_config, API_KEY, GEMINI_API_KEY, API_BASE, MODEL
        current_config = load_config()
        if current_config:
            API_KEY = current_config.get("api_key", API_KEY or "")
            GEMINI_API_KEY = current_config.get("gemini_api_key", GEMINI_API_KEY or "")
            API_BASE = current_config.get("api_base", API_BASE or "gemini")
            MODEL = current_config.get("model", MODEL or "gemini-2.0-flash")
        config_manager = None
        print("⚠️ Using legacy configuration system")
    except ImportError:
        API_KEY = None
        GEMINI_API_KEY = None
        API_BASE = "gemini"
        MODEL = None
        current_config = None
        config_manager = None
        print("❌ No configuration system available")

# --- Configuration ---
# Central version info (change here to update everywhere)
VRITRA_VERSION = "v0.29.5"

def sync_config_version(config_dict: dict) -> dict:
    """Sync the _config_version field in config dictionary with VRITRA_VERSION."""
    if config_dict is None:
        return config_dict
    config_dict["_config_version"] = VRITRA_VERSION
    return config_dict

# Sync version in config after loading (moved after VRITRA_VERSION definition)
try:
    if current_config and current_config.get("_config_version") != VRITRA_VERSION:
        sync_config_version(current_config)
        if config_manager:
            try:
                config_manager.save_config(current_config)
            except Exception:
                pass
        elif 'save_config' in globals():
            try:
                save_config(current_config)
            except Exception:
                pass
except Exception:
    pass  # Silently fail if sync not possible

# What's New data for current version (hardcoded - only main highlights)
WHATS_NEW_HIGHLIGHTS = [
    "Fixed interactive commands (vim, nano, python, etc.) - they now work properly without getting stuck",
    "Improved error recovery - system commands now show helpful recovery options with multiple fix suggestions",
    "Better AI error analysis - AI now focuses on your actual errors, not shell internals",
    "Enhanced history command - now shows commands with timestamps, supports head/tail piping, and prevents duplicates",
    "Improved path detection - automatically expands ~ and environment variables for better file/directory access",
    "Enhanced AI context - all AI requests now include full system info, directory structure, and project details",
    "Improved OS info detection - robust error handling for Termux/Android environments with fallback methods",
    "Better command validation - detects and rejects invalid flags/arguments before launching interactive shell"
]

# Professional config directory structure
CONFIG_DIR = os.path.expanduser("~/.config-vritrasecz/vritraai")
os.makedirs(CONFIG_DIR, exist_ok=True)

HISTORY_FILE = os.path.join(CONFIG_DIR, "history")
SESSION_LOG_FILE = os.path.join(CONFIG_DIR, "session.log")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
LEARNING_FILE = os.path.join(CONFIG_DIR, "learning.md")
LASTCMD_LOG_FILE = os.path.join(CONFIG_DIR, "lastcmd.log")
VERSION_INFO_FILE = os.path.join(CONFIG_DIR, "vritraai-version.json")

# Determine AI availability based on API base
def get_ai_enabled():
    if API_BASE == "gemini":
        return bool(GEMINI_API_KEY)
    else:  # openrouter
        return bool(API_KEY)

AI_ENABLED = get_ai_enabled()

# AI Models organized by API provider
OPENROUTER_MODELS = {
    # DeepSeek Models
    'ds1': {
        'name': 'deepseek/deepseek-chat-v3-0324',
        'display_name': 'DeepSeek Chat v3.0324',
        'description': 'Latest DeepSeek chat model with enhanced capabilities',
        'provider': 'DeepSeek',
        'category': 'Chat'
    },
    'ds2': {
        'name': 'deepseek/deepseek-chat',
        'display_name': 'DeepSeek Chat',
        'description': 'Standard DeepSeek conversational model',
        'provider': 'DeepSeek',
        'category': 'Chat'
    },
    'ds3': {
        'name': 'deepseek/deepseek-prover-v2',
        'display_name': 'DeepSeek Prover v2',
        'description': 'Mathematical reasoning and theorem proving',
        'provider': 'DeepSeek',
        'category': 'Reasoning'
    },
    
    # Meta LLaMA Models
    'll1': {
        'name': 'meta-llama/llama-3.3-70b-instruct',
        'display_name': 'LLaMA 3.3 70B Instruct',
        'description': 'Latest LLaMA 3.3 with 70B parameters',
        'provider': 'Meta',
        'category': 'Large'
    },
    'll2': {
        'name': 'meta-llama/llama-3.1-405b-instruct',
        'display_name': 'LLaMA 3.1 405B Instruct',
        'description': 'Massive 405B parameter instruction-tuned model',
        'provider': 'Meta',
        'category': 'Ultra Large'
    },
    'll3': {
        'name': 'meta-llama/llama-3.1-405b',
        'display_name': 'LLaMA 3.1 405B Base',
        'description': '405B parameter base model for fine-tuning',
        'provider': 'Meta',
        'category': 'Ultra Large'
    },
    'll4': {
        'name': 'meta-llama/llama-3.2-3b-instruct',
        'display_name': 'LLaMA 3.2 3B Instruct',
        'description': 'Lightweight 3B parameter instruction model',
        'provider': 'Meta',
        'category': 'Small'
    },
    'll5': {
        'name': 'meta-llama/llama-3-8b-instruct',
        'display_name': 'LLaMA 3 8B Instruct',
        'description': 'Balanced 8B parameter instruction model',
        'provider': 'Meta',
        'category': 'Medium'
    },
    'll6': {
        'name': 'meta-llama/llama-3.1-8b-instruct',
        'display_name': 'LLaMA 3.1 8B Instruct',
        'description': 'Updated 8B parameter instruction model',
        'provider': 'Meta',
        'category': 'Medium'
    },
    
    # Mistral AI Models
    'ms1': {
        'name': 'mistralai/mistral-7b-instruct',
        'display_name': 'Mistral 7B Instruct',
        'description': 'Efficient 7B parameter instruction model',
        'provider': 'Mistral AI',
        'category': 'Medium'
    },
    'ms2': {
        'name': 'mistralai/mistral-nemo',
        'display_name': 'Mistral Nemo',
        'description': 'Advanced Mistral model with enhanced capabilities',
        'provider': 'Mistral AI',
        'category': 'Chat'
    },
    'ms3': {
        'name': 'mistralai/pixtral-12b',
        'display_name': 'Pixtral 12B',
        'description': 'Multimodal model with vision capabilities',
        'provider': 'Mistral AI',
        'category': 'Multimodal'
    },
    
    # Google Models
    'gm1': {
        'name': 'google/gemma-3-27b-it',
        'display_name': 'Gemma 3 27B IT',
        'description': 'Google\'s 27B parameter instruction-tuned model',
        'provider': 'Google',
        'category': 'Large'
    },
    'gm2': {
        'name': 'google/gemma-3-4b-it',
        'display_name': 'Gemma 3 4B IT',
        'description': 'Lightweight 4B parameter instruction model',
        'provider': 'Google',
        'category': 'Small'
    },
    
    # OpenAI Models
    'o1': {
        'name': 'openai/gpt-3.5-turbo',
        'display_name': 'GPT-3.5 Turbo',
        'description': 'Fast and efficient OpenAI model',
        'provider': 'OpenAI',
        'category': 'Chat'
    },
    'o2': {
        'name': 'openai/gpt-oss-20b',
        'display_name': 'GPT OSS 20B',
        'description': 'Open source 20B parameter GPT model',
        'provider': 'OpenAI',
        'category': 'Large'
    },
    
    # Specialized Models
    'qw1': {
        'name': 'qwen/qwen3-coder',
        'display_name': 'Qwen 3 Coder',
        'description': 'Specialized coding and programming assistant',
        'provider': 'Qwen',
        'category': 'Code'
    },
    'z1': {
        'name': 'z-ai/glm-4.5-air',
        'display_name': 'GLM 4.5 Air',
        'description': 'Lightweight general language model',
        'provider': 'Z-AI',
        'category': 'Chat'
    }
}

# Gemini Models
GEMINI_MODELS = {
    'gf1': {
        'name': 'gemini-2.0-flash',
        'display_name': 'Gemini 2.0 Flash',
        'description': 'Next-generation Gemini Flash model',
        'provider': 'Google',
        'category': 'Chat'
    },
    'gf2': {
        'name': 'gemini-2.5-flash',
        'display_name': 'Gemini 2.5 Flash',
        'description': 'Latest Gemini Flash with enhanced capabilities',
        'provider': 'Google',
        'category': 'Chat'
    },
    'gf3': {
        'name': 'gemini-2.5-flash-lite',
        'display_name': 'Gemini 2.5 Flash Lite',
        'description': 'Lightweight and efficient Gemini Flash model',
        'provider': 'Google',
        'category': 'Chat'
    },
    'gf4': {
        'name': 'gemini-flash-latest',
        'display_name': 'Gemini Flash Latest',
        'description': 'Latest Gemini Flash model with cutting-edge features',
        'provider': 'Google',
        'category': 'Chat'
    },
    'gp1': {
        'name': 'gemini-2.5-pro',
        'display_name': 'Gemini 2.5 Pro',
        'description': 'Premium Gemini model with advanced reasoning',
        'provider': 'Google',
        'category': 'Pro'
    }
}

# Dynamic AI_MODELS based on API_BASE
def get_available_models():
    global API_BASE
    if API_BASE == "gemini":
        return GEMINI_MODELS
    else:  # openrouter
        return OPENROUTER_MODELS

def update_ai_models():
    """Update AI_MODELS based on current API_BASE"""
    global AI_MODELS
    AI_MODELS = get_available_models()

AI_MODELS = get_available_models()

# Initialize Rich console
console = Console() if RICH_AVAILABLE else None

# Dangerous commands that require confirmation
DANGEROUS_COMMANDS = {
    'rm -rf', 'rm -rfv', 'rm *', 'rm -r', 'rmdir /s', 'del /s', 'format', 'fdisk',
    'dd', 'mkfs', 'shutdown', 'reboot', 'halt', 'init 0', 'init 6',
    'chmod 777', 'chmod -R 777', 'chown -R', 'sudo rm', 'sudo dd',
    '> /dev/null', 'truncate', 'shred'
}

# Command aliases
ALIASES = {
    'll': 'ls -la',
    'la': 'ls -a', 
    'l': 'ls',
    'gp': 'git push',
    'gs': 'git status',
    'ga': 'git add',
    'gc': 'git commit'
}

THEMES = {
    "dark": {
        "prompt_user": "#50fa7b bold",
        "prompt_arrow": "#f1fa8c", 
        "prompt_path": "#bd93f9 bold",
        "output": "#f8f8f2",
        "error": "#ff5555",
        "success": "#50fa7b",
        "warning": "#ffb86c",
        "info": "#8be9fd"
    },
    "light": {
        "prompt_user": "#008000 bold", 
        "prompt_arrow": "#FF8C00",
        "prompt_path": "#800080 bold",
        "output": "#000000",
        "error": "#FF0000",
        "success": "#008000", 
        "warning": "#FF8C00",
        "info": "#0000FF"
    },
    "retro": {
        "prompt_user": "#00ff00 bold",
        "prompt_arrow": "#ffff00",
        "prompt_path": "#ff00ff bold", 
        "output": "#00ffff",
        "error": "#ff0000",
        "success": "#00ff00",
        "warning": "#ffff00",
        "info": "#00ffff"
    },
    "cyberpunk": {
        "prompt_user": "#00ffff bold",
        "prompt_arrow": "#ff0080", 
        "prompt_path": "#80ff00 bold",
        "output": "#ffffff",
        "error": "#ff0040",
        "success": "#00ff80",
        "warning": "#ffff00",
        "info": "#0080ff"
    },
    "matrix": {
        "prompt_user": "#00ff41 bold",
        "prompt_arrow": "#008f11", 
        "prompt_path": "#41ff00 bold",
        "output": "#00ff41",
        "error": "#ff4141",
        "success": "#00ff41",
        "warning": "#ffff41",
        "info": "#41ffff"
    },
    "ocean": {
        "prompt_user": "#4FC3F7 bold",
        "prompt_arrow": "#29B6F6", 
        "prompt_path": "#0277BD bold",
        "output": "#E1F5FE",
        "error": "#F44336",
        "success": "#4CAF50",
        "warning": "#FF9800",
        "info": "#2196F3"
    },
    "sunset": {
        "prompt_user": "#FF5722 bold",
        "prompt_arrow": "#FF9800", 
        "prompt_path": "#FFC107 bold",
        "output": "#FFECB3",
        "error": "#D32F2F",
        "success": "#388E3C",
        "warning": "#F57C00",
        "info": "#1976D2"
    },
    "forest": {
        "prompt_user": "#4CAF50 bold",
        "prompt_arrow": "#8BC34A", 
        "prompt_path": "#2E7D32 bold",
        "output": "#E8F5E8",
        "error": "#D32F2F",
        "success": "#388E3C",
        "warning": "#F57C00",
        "info": "#1976D2"
    },
    "neon": {
        "prompt_user": "#FF1493 bold",
        "prompt_arrow": "#00FFFF", 
        "prompt_path": "#ADFF2F bold",
        "output": "#FFFFFF",
        "error": "#FF4500",
        "success": "#32CD32",
        "warning": "#FFD700",
        "info": "#1E90FF"
    },
    "grayscale": {
        "prompt_user": "#CCCCCC bold",
        "prompt_arrow": "#888888", 
        "prompt_path": "#FFFFFF bold",
        "output": "#DDDDDD",
        "error": "#FF6B6B",
        "success": "#51CF66",
        "warning": "#FFD43B",
        "info": "#339AF0"
    },
    "purple": {
        "prompt_user": "#9B59B6 bold",
        "prompt_arrow": "#8E44AD", 
        "prompt_path": "#E74C3C bold",
        "output": "#ECF0F1",
        "error": "#E74C3C",
        "success": "#27AE60",
        "warning": "#F39C12",
        "info": "#3498DB"
    },
    "rainbow": {
        "prompt_user": "#FF0080 bold",
        "prompt_arrow": "#00FF80", 
        "prompt_path": "#8000FF bold",
        "output": "#FFFFFF",
        "error": "#FF4040",
        "success": "#40FF40",
        "warning": "#FFFF40",
        "info": "#4040FF"
    },
    "autumn": {
        "prompt_user": "#D2691E bold",
        "prompt_arrow": "#CD853F", 
        "prompt_path": "#8B4513 bold",
        "output": "#F4E4BC",
        "error": "#B22222",
        "success": "#228B22",
        "warning": "#FF8C00",
        "info": "#4682B4"
    },
    "winter": {
        "prompt_user": "#B0C4DE bold",
        "prompt_arrow": "#87CEEB", 
        "prompt_path": "#4682B4 bold",
        "output": "#F0F8FF",
        "error": "#DC143C",
        "success": "#32CD32",
        "warning": "#FFD700",
        "info": "#1E90FF"
    },
    "spring": {
        "prompt_user": "#98FB98 bold",
        "prompt_arrow": "#90EE90", 
        "prompt_path": "#00FF7F bold",
        "output": "#F0FFF0",
        "error": "#FF6347",
        "success": "#32CD32",
        "warning": "#FFD700",
        "info": "#87CEEB"
    },
    "summer": {
        "prompt_user": "#FFE135 bold",
        "prompt_arrow": "#FFA500", 
        "prompt_path": "#FF6347 bold",
        "output": "#FFFAF0",
        "error": "#FF4500",
        "success": "#32CD32",
        "warning": "#FFD700",
        "info": "#00BFFF"
    },
    "pastel": {
        "prompt_user": "#FFB6C1 bold",
        "prompt_arrow": "#DDA0DD", 
        "prompt_path": "#98FB98 bold",
        "output": "#F5F5DC",
        "error": "#F08080",
        "success": "#90EE90",
        "warning": "#F0E68C",
        "info": "#87CEEB"
    },
    "toxic": {
        "prompt_user": "#39FF14 bold",
        "prompt_arrow": "#CCFF00", 
        "prompt_path": "#32CD32 bold",
        "output": "#F0FFF0",
        "error": "#FF1493",
        "success": "#00FF00",
        "warning": "#FFFF00",
        "info": "#00FFFF"
    },
    "royal": {
        "prompt_user": "#4169E1 bold",
        "prompt_arrow": "#6A5ACD", 
        "prompt_path": "#8A2BE2 bold",
        "output": "#F8F8FF",
        "error": "#DC143C",
        "success": "#228B22",
        "warning": "#FFD700",
        "info": "#4169E1"
    },
    "coffee": {
        "prompt_user": "#8B4513 bold",
        "prompt_arrow": "#A0522D", 
        "prompt_path": "#D2691E bold",
        "output": "#F5DEB3",
        "error": "#CD853F",
        "success": "#228B22",
        "warning": "#DAA520",
        "info": "#4682B4"
    },
    "cherry": {
        "prompt_user": "#DC143C bold",
        "prompt_arrow": "#B22222", 
        "prompt_path": "#8B0000 bold",
        "output": "#FFE4E1",
        "error": "#FF0000",
        "success": "#32CD32",
        "warning": "#FFA500",
        "info": "#4169E1"
    },
    "mint": {
        "prompt_user": "#00FA9A bold",
        "prompt_arrow": "#40E0D0", 
        "prompt_path": "#20B2AA bold",
        "output": "#F0FFFF",
        "error": "#FF6347",
        "success": "#32CD32",
        "warning": "#FFD700",
        "info": "#00CED1"
    },
    "volcano": {
        "prompt_user": "#FF4500 bold",
        "prompt_arrow": "#DC143C", 
        "prompt_path": "#B22222 bold",
        "output": "#FFF8DC",
        "error": "#FF0000",
        "success": "#32CD32",
        "warning": "#FFD700",
        "info": "#FF6347"
    },
    "galaxy": {
        "prompt_user": "#4B0082 bold",
        "prompt_arrow": "#8A2BE2", 
        "prompt_path": "#9400D3 bold",
        "output": "#E6E6FA",
        "error": "#FF1493",
        "success": "#00FA9A",
        "warning": "#FFD700",
        "info": "#00BFFF"
    },
    "deep_sea": {
        "prompt_user": "#000080 bold",
        "prompt_arrow": "#191970", 
        "prompt_path": "#0000CD bold",
        "output": "#F0F8FF",
        "error": "#DC143C",
        "success": "#20B2AA",
        "warning": "#FFD700",
        "info": "#4169E1"
    },
    "candy": {
        "prompt_user": "#FF69B4 bold",
        "prompt_arrow": "#FF1493", 
        "prompt_path": "#DA70D6 bold",
        "output": "#FFF0F5",
        "error": "#DC143C",
        "success": "#32CD32",
        "warning": "#FFD700",
        "info": "#FF69B4"
    },
    "terminal_green": {
        "prompt_user": "#00FF00 bold",
        "prompt_arrow": "#32CD32", 
        "prompt_path": "#228B22 bold",
        "output": "#F0FFF0",
        "error": "#FF4500",
        "success": "#00FF00",
        "warning": "#FFFF00",
        "info": "#ADFF2F"
    },
    "lava": {
        "prompt_user": "#FF6347 bold",
        "prompt_arrow": "#FF4500", 
        "prompt_path": "#DC143C bold",
        "output": "#FFFAF0",
        "error": "#B22222",
        "success": "#32CD32",
        "warning": "#FF8C00",
        "info": "#FF6347"
    },
    "ice": {
        "prompt_user": "#B0E0E6 bold",
        "prompt_arrow": "#87CEEB", 
        "prompt_path": "#4682B4 bold",
        "output": "#F0FFFF",
        "error": "#DC143C",
        "success": "#00CED1",
        "warning": "#FFD700",
        "info": "#87CEFA"
    },
    "electric": {
        "prompt_user": "#00FFFF bold",
        "prompt_arrow": "#1E90FF", 
        "prompt_path": "#0080FF bold",
        "output": "#F0FFFF",
        "error": "#FF4500",
        "success": "#00FF7F",
        "warning": "#FFFF00",
        "info": "#00BFFF"
    },
    "forest_night": {
        "prompt_user": "#228B22 bold",
        "prompt_arrow": "#006400", 
        "prompt_path": "#2E8B57 bold",
        "output": "#F0FFF0",
        "error": "#B22222",
        "success": "#32CD32",
        "warning": "#FFD700",
        "info": "#90EE90"
    },
    "synthwave": {
        "prompt_user": "#FF0080 bold",
        "prompt_arrow": "#00FFFF", 
        "prompt_path": "#8000FF bold",
        "output": "#FFFFFF",
        "error": "#FF4040",
        "success": "#00FF80",
        "warning": "#FFFF00",
        "info": "#FF00FF"
    },
    "desert_sunset": {
        "prompt_user": "#CD853F bold",
        "prompt_arrow": "#D2691E", 
        "prompt_path": "#F4A460 bold",
        "output": "#FDF5E6",
        "error": "#B22222",
        "success": "#32CD32",
        "warning": "#FF8C00",
        "info": "#DAA520"
    },
    "midnight": {
        "prompt_user": "#191970 bold",
        "prompt_arrow": "#000080", 
        "prompt_path": "#4169E1 bold",
        "output": "#E6E6FA",
        "error": "#DC143C",
        "success": "#32CD32",
        "warning": "#FFD700",
        "info": "#87CEFA"
    },
    "sunrise": {
        "prompt_user": "#FF7F50 bold",
        "prompt_arrow": "#FF6347", 
        "prompt_path": "#FFA500 bold",
        "output": "#FFFAF0",
        "error": "#DC143C",
        "success": "#32CD32",
        "warning": "#FFD700",
        "info": "#FF8C00"
    },
    "hacker_green": {
        "prompt_user": "#39FF14 bold",
        "prompt_arrow": "#00FF41", 
        "prompt_path": "#32CD32 bold",
        "output": "#000000",
        "error": "#FF0000",
        "success": "#00FF00",
        "warning": "#FFFF00",
        "info": "#00FFFF"
    },
    "lavender": {
        "prompt_user": "#9370DB bold",
        "prompt_arrow": "#BA55D3", 
        "prompt_path": "#DA70D6 bold",
        "output": "#F8F8FF",
        "error": "#DC143C",
        "success": "#32CD32",
        "warning": "#FFD700",
        "info": "#9370DB"
    }
}

THEME_DESCRIPTIONS = {
    "dark": "Default dark terminal theme",
    "light": "Light theme with classic colors",
    "retro": "Retro neon green-on-black look",
    "cyberpunk": "High-contrast cyberpunk palette",
    "matrix": "Matrix-style green hacker terminal",
    "ocean": "Cool blue ocean-inspired theme",
    "sunset": "Warm orange and gold sunset colors",
    "forest": "Natural green forest palette",
    "neon": "Bright neon accents for high contrast",
    "grayscale": "Neutral grayscale interface",
    "purple": "Purple-focused professional palette",
    "rainbow": "Vibrant multicolor rainbow theme",
    "autumn": "Earthy autumn browns and oranges",
    "winter": "Cold blue winter tones",
    "spring": "Fresh light green spring colors",
    "summer": "Bright summer-inspired colors",
    "pastel": "Soft pastel color scheme",
    "toxic": "Aggressive toxic-neon palette",
    "royal": "Royal blue and gold styling",
    "coffee": "Warm coffee/brown paper look",
    "cherry": "Red cherry-focused theme",
    "mint": "Minty teal and green palette",
    "volcano": "Fiery reds and oranges",
    "galaxy": "Space / galaxy purples and blues",
    "deep_sea": "Dark deep-sea blues",
    "candy": "Playful candy-like colors",
    "terminal_green": "Classic green terminal",
    "lava": "Lava-inspired warm colors",
    "ice": "Icy blue and white theme",
    "electric": "Electric cyan and blue palette",
    "forest_night": "Dark forest tones",
    "synthwave": "80s synthwave neon palette",
    "desert_sunset": "Desert sunset oranges and golds",
    "midnight": "Deep midnight blues",
    "sunrise": "Soft sunrise oranges",
    "hacker_green": "Aggressive hacker green-on-black",
    "lavender": "Soft purple lavender scheme",
    "professional": "Balanced professional UI theme",
}

# Prompt style templates - Enhanced with many more options
PROMPT_STYLES = {
    "classic": {
        "template": [
            ("class:prompt_user", "user"),
            ("class:prompt_arrow", "@"),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " > "),
        ],
        "description": "Classic terminal style: user@path > "
    },
    "minimal": {
        "template": [
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " $ "),
        ],
        "description": "Minimal style: path $ "
    },
    "modern": {
        "template": [
            ("class:prompt_arrow", "❯ "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " ❯ "),
        ],
        "description": "Modern style with arrows: ❯ path ❯ "
    },
    "powerline": {
        "template": [
            ("class:prompt_user", " "),
            ("class:prompt_user", "user"),
            ("class:prompt_arrow", "  "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", "  "),
        ],
        "description": "Powerline style:  user  path  "
    },
    "git": {
        "template": [
            ("class:prompt_user", "["),
            ("class:prompt_path", "{path}"),
            ("class:prompt_user", "]"),
            ("class:prompt_arrow", " » "),
        ],
        "description": "Git-style brackets: [path] » "
    },
    "elegant": {
        "template": [
            ("class:prompt_arrow", "╭─ "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", "\n╰─▶ "),
        ],
        "description": "Elegant multi-line: ╭─ path\n╰─▶ "
    },
    "hacker": {
        "template": [
            ("class:prompt_user", "┌──("),
            ("class:prompt_user", "user"),
            ("class:prompt_arrow", "㉿"),
            ("class:prompt_path", "vritraai"),
            ("class:prompt_user", ")-["),
            ("class:prompt_path", "{path}"),
            ("class:prompt_user", "]\n└─"),
            ("class:prompt_arrow", "$ "),
        ],
        "description": "Hacker-style multi-line: ┌──(user㉿vritraai)-[path]\n└─$ "
    },
    "cyberpunk": {
        "template": [
            ("class:prompt_arrow", "▶ "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " ◀ "),
        ],
        "description": "Cyberpunk style: ▶ path ◀ "
    },
    "matrix": {
        "template": [
            ("class:prompt_user", "wake up, "),
            ("class:prompt_user", "neo"),
            ("class:prompt_arrow", ":// "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " $ "),
        ],
        "description": "Matrix style: wake up, neo:// path $ "
    },
    "corporate": {
        "template": [
            ("class:prompt_user", "["),
            ("class:prompt_arrow", "VritraAI"),
            ("class:prompt_user", "] "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " → "),
        ],
        "description": "Corporate style: [VritraAI] path → "
    },
    "retro_dos": {
        "template": [
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", "> "),
        ],
        "description": "Retro DOS style: path> "
    },
    "starship": {
        "template": [
            ("class:prompt_arrow", "🚀 "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " ▸ "),
        ],
        "description": "Starship style: 🚀 path ▸ "
    },
    "lambda": {
        "template": [
            ("class:prompt_arrow", "λ "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " → "),
        ],
        "description": "Lambda functional style: λ path → "
    },
    "ascii_art": {
        "template": [
            ("class:prompt_arrow", "╔═══ "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " ═══╗\n║ "),
        ],
        "description": "ASCII art style: ╔═══ path ═══╗\n║ "
    },
    "ninja": {
        "template": [
            ("class:prompt_arrow", "⚡ "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " ⚡ "),
        ],
        "description": "Ninja style: ⚡ path ⚡ "
    },
    "brackets": {
        "template": [
            ("class:prompt_user", "{"),
            ("class:prompt_path", "{path}"),
            ("class:prompt_user", "} "),
            ("class:prompt_arrow", "» "),
        ],
        "description": "Brackets style: {path} » "
    },
    "diamond": {
        "template": [
            ("class:prompt_arrow", "◆ "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " ◆ "),
        ],
        "description": "Diamond style: ◆ path ◆ "
    },
    "terminal_classic": {
        "template": [
            ("class:prompt_user", "user"),
            ("class:prompt_arrow", ":"),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", "$ "),
        ],
        "description": "Terminal classic: user:path$ "
    },
    "space": {
        "template": [
            ("class:prompt_arrow", "🌌 "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " ⭐ "),
        ],
        "description": "Space style: 🌌 path ⭐ "
    },
    "fire": {
        "template": [
            ("class:prompt_arrow", "🔥 "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🔥 "),
        ],
        "description": "Fire style: 🔥 path 🔥 "
    },
    "water": {
        "template": [
            ("class:prompt_arrow", "🌊 "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🌊 "),
        ],
        "description": "Water style: 🌊 path 🌊 "
    },
    "earth": {
        "template": [
            ("class:prompt_arrow", "🌍 "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🏔️ "),
        ],
        "description": "Earth style: 🌍 path 🏔️ "
    },
    "air": {
        "template": [
            ("class:prompt_arrow", "💨 "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🌪️ "),
        ],
        "description": "Air style: 💨 path 🌪️ "
    },
    "robot": {
        "template": [
            ("class:prompt_arrow", "🤖 "),
            ("class:prompt_user", "[SYSTEM]"),
            ("class:prompt_arrow", " :: "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " >> "),
        ],
        "description": "Robot style: 🤖 [SYSTEM] :: path >> "
    },
    "alien": {
        "template": [
            ("class:prompt_arrow", "👽 "),
            ("class:prompt_user", "[PROBE]"),
            ("class:prompt_arrow", " ~~ "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🛸 "),
        ],
        "description": "Alien style: 👽 [PROBE] ~~ path 🛸 "
    },
    "magical": {
        "template": [
            ("class:prompt_arrow", "🔮 "),
            ("class:prompt_user", "✨"),
            ("class:prompt_path", "{path}"),
            ("class:prompt_user", "✨"),
            ("class:prompt_arrow", " 🪄 "),
        ],
        "description": "Magical style: 🔮 ✨path✨ 🪄 "
    },
    "pirate": {
        "template": [
            ("class:prompt_arrow", "🏴‍☠️ "),
            ("class:prompt_user", "[CAPTAIN]"),
            ("class:prompt_arrow", " @ "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " ⚓ "),
        ],
        "description": "Pirate style: 🏴‍☠️ [CAPTAIN] @ path ⚓ "
    },
    "medieval": {
        "template": [
            ("class:prompt_arrow", "⚔️ "),
            ("class:prompt_user", "[KNIGHT]"),
            ("class:prompt_arrow", " in "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🏰 "),
        ],
        "description": "Medieval style: ⚔️ [KNIGHT] in path 🏰 "
    },
    "western": {
        "template": [
            ("class:prompt_arrow", "🤠 "),
            ("class:prompt_user", "[SHERIFF]"),
            ("class:prompt_arrow", " in "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🌵 "),
        ],
        "description": "Western style: 🤠 [SHERIFF] in path 🌵 "
    },
    "steampunk": {
        "template": [
            ("class:prompt_arrow", "⚙️ "),
            ("class:prompt_user", "[ENGINEER]"),
            ("class:prompt_arrow", " » "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🔧 "),
        ],
        "description": "Steampunk style: ⚙️ [ENGINEER] » path 🔧 "
    },
    "gaming": {
        "template": [
            ("class:prompt_arrow", "🎮 "),
            ("class:prompt_user", "[PLAYER]"),
            ("class:prompt_arrow", " LVL99 "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🏆 "),
        ],
        "description": "Gaming style: 🎮 [PLAYER] LVL99 path 🏆 "
    },
    "music": {
        "template": [
            ("class:prompt_arrow", "🎵 "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🎶 "),
        ],
        "description": "Music style: 🎵 path 🎶 "
    },
    "chef": {
        "template": [
            ("class:prompt_arrow", "👨‍🍳 "),
            ("class:prompt_user", "[CHEF]"),
            ("class:prompt_arrow", " cooking in "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🍳 "),
        ],
        "description": "Chef style: 👨‍🍳 [CHEF] cooking in path 🍳 "
    },
    "scientist": {
        "template": [
            ("class:prompt_arrow", "🧪 "),
            ("class:prompt_user", "[LAB]"),
            ("class:prompt_arrow", " -> "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🔬 "),
        ],
        "description": "Scientist style: 🧪 [LAB] -> path 🔬 "
    },
    "detective": {
        "template": [
            ("class:prompt_arrow", "🕵️ "),
            ("class:prompt_user", "[DETECTIVE]"),
            ("class:prompt_arrow", " investigating "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🔍 "),
        ],
        "description": "Detective style: 🕵️ [DETECTIVE] investigating path 🔍 "
    },
    "artistic": {
        "template": [
            ("class:prompt_arrow", "🎨 "),
            ("class:prompt_user", "[ARTIST]"),
            ("class:prompt_arrow", " creating in "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🖌️ "),
        ],
        "description": "Artistic style: 🎨 [ARTIST] creating in path 🖌️ "
    },
    "zen": {
        "template": [
            ("class:prompt_arrow", "☯️ "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🧘 "),
        ],
        "description": "Zen style: ☯️ path 🧘 "
    },
    "party": {
        "template": [
            ("class:prompt_arrow", "🎉 "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🎊 "),
        ],
        "description": "Party style: 🎉 path 🎊 "
    },
    "professional": {
        "template": [
            ("class:prompt_user", "[VritraAI]"),
            ("class:prompt_arrow", " | "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " | "),
        ],
        "description": "Professional style: [VritraAI] | path | "
    },
    "vintage": {
        "template": [
            ("class:prompt_arrow", "📻 "),
            ("class:prompt_user", "[RADIO]"),
            ("class:prompt_arrow", " ~ "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 📼 "),
        ],
        "description": "Vintage style: 📻 [RADIO] ~ path 📼 "
    },
    "future": {
        "template": [
            ("class:prompt_arrow", "🚀 "),
            ("class:prompt_user", "[NEXUS]"),
            ("class:prompt_arrow", " ≫ "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " ∞ "),
        ],
        "description": "Future style: 🚀 [NEXUS] ≫ path ∞ "
    },
    "minimal_zen": {
        "template": [
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " · "),
        ],
        "description": "Minimal zen style: path · "
    },
    "code_matrix": {
        "template": [
            ("class:prompt_arrow", "⌨️ "),
            ("class:prompt_user", "[CODE]"),
            ("class:prompt_arrow", " :: "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " >> "),
        ],
        "description": "Code Matrix style: ⌨️ [CODE] :: path >> "
    },
    "sport": {
        "template": [
            ("class:prompt_arrow", "⚽ "),
            ("class:prompt_user", "[PLAYER]"),
            ("class:prompt_arrow", " playing in "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🏆 "),
        ],
        "description": "Sport style: ⚽ [PLAYER] playing in path 🏆 "
    },
    "medical": {
        "template": [
            ("class:prompt_arrow", "🏥 "),
            ("class:prompt_user", "[DOCTOR]"),
            ("class:prompt_arrow", " checking "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 💊 "),
        ],
        "description": "Medical style: 🏥 [DOCTOR] checking path 💊 "
    },
    "construction": {
        "template": [
            ("class:prompt_arrow", "🏗️ "),
            ("class:prompt_user", "[BUILDER]"),
            ("class:prompt_arrow", " working on "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🔨 "),
        ],
        "description": "Construction style: 🏗️ [BUILDER] working on path 🔨 "
    },
    "aviation": {
        "template": [
            ("class:prompt_arrow", "✈️ "),
            ("class:prompt_user", "[PILOT]"),
            ("class:prompt_arrow", " flying over "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🛩️ "),
        ],
        "description": "Aviation style: ✈️ [PILOT] flying over path 🛩️ "
    },
    "marine": {
        "template": [
            ("class:prompt_arrow", "🚢 "),
            ("class:prompt_user", "[CAPTAIN]"),
            ("class:prompt_arrow", " sailing in "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🌊 "),
        ],
        "description": "Marine style: 🚢 [CAPTAIN] sailing in path 🌊 "
    },
    "mountain": {
        "template": [
            ("class:prompt_arrow", "⛰️ "),
            ("class:prompt_user", "[CLIMBER]"),
            ("class:prompt_arrow", " at "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🏔️ "),
        ],
        "description": "Mountain style: ⛰️ [CLIMBER] at path 🏔️ "
    },
    "jungle": {
        "template": [
            ("class:prompt_arrow", "🌿 "),
            ("class:prompt_user", "[EXPLORER]"),
            ("class:prompt_arrow", " in "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🦜 "),
        ],
        "description": "Jungle style: 🌿 [EXPLORER] in path 🦜 "
    },
    "desert": {
        "template": [
            ("class:prompt_arrow", "🏜️ "),
            ("class:prompt_user", "[NOMAD]"),
            ("class:prompt_arrow", " crossing "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🐪 "),
        ],
        "description": "Desert style: 🏜️ [NOMAD] crossing path 🐪 "
    },
    "arctic": {
        "template": [
            ("class:prompt_arrow", "❄️ "),
            ("class:prompt_user", "[EXPLORER]"),
            ("class:prompt_arrow", " in "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🐧 "),
        ],
        "description": "Arctic style: ❄️ [EXPLORER] in path 🐧 "
    },
    "city": {
        "template": [
            ("class:prompt_arrow", "🏙️ "),
            ("class:prompt_user", "[CITIZEN]"),
            ("class:prompt_arrow", " in "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🚕 "),
        ],
        "description": "City style: 🏙️ [CITIZEN] in path 🚕 "
    },
    "farm": {
        "template": [
            ("class:prompt_arrow", "🚜 "),
            ("class:prompt_user", "[FARMER]"),
            ("class:prompt_arrow", " working in "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🌾 "),
        ],
        "description": "Farm style: 🚜 [FARMER] working in path 🌾 "
    },
    "school": {
        "template": [
            ("class:prompt_arrow", "📚 "),
            ("class:prompt_user", "[STUDENT]"),
            ("class:prompt_arrow", " studying in "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🎓 "),
        ],
        "description": "School style: 📚 [STUDENT] studying in path 🎓 "
    },
    "library": {
        "template": [
            ("class:prompt_arrow", "📖 "),
            ("class:prompt_user", "[READER]"),
            ("class:prompt_arrow", " browsing "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 📜 "),
        ],
        "description": "Library style: 📖 [READER] browsing path 📜 "
    },
    "cafe": {
        "template": [
            ("class:prompt_arrow", "☕ "),
            ("class:prompt_user", "[CUSTOMER]"),
            ("class:prompt_arrow", " at "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🥐 "),
        ],
        "description": "Cafe style: ☕ [CUSTOMER] at path 🥐 "
    },
    "gym": {
        "template": [
            ("class:prompt_arrow", "💪 "),
            ("class:prompt_user", "[ATHLETE]"),
            ("class:prompt_arrow", " training in "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 🏋️ "),
        ],
        "description": "Gym style: 💪 [ATHLETE] training in path 🏋️ "
    },
    "superhero": {
        "template": [
            ("class:prompt_arrow", "🦸 "),
            ("class:prompt_user", "[HERO]"),
            ("class:prompt_arrow", " protecting "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " ⚡ "),
        ],
        "description": "Superhero style: 🦸 [HERO] protecting path ⚡ "
    },
    "villian": {
        "template": [
            ("class:prompt_arrow", "🦹 "),
            ("class:prompt_user", "[VILLAIN]"),
            ("class:prompt_arrow", " plotting in "),
            ("class:prompt_path", "{path}"),
            ("class:prompt_arrow", " 💀 "),
        ],
        "description": "Villain style: 🦹 [VILLAIN] plotting in path 💀 "
    }
}

# Global variables for process management
current_process = None
shell_running = True

# Enhanced Configuration state using unified system
class Config:
    def __init__(self):
        global config_manager
        self._config_manager = config_manager
        
        # Load current settings or set defaults
        if self._config_manager:
            self._load_from_manager()
        else:
            # Fallback defaults if config manager not available
            self._theme = "matrix"
            self._prompt_style = "hacker"
            self.command_prefix = ""
            self.paranoid_mode = False
            self.model_profile = "quality"
            self.offline_mode = False
            self.auto_model_switch = True
    
    def _load_from_manager(self):
        """Load configuration from the config manager."""
        if not self._config_manager:
            return
        
        try:
            self._theme = self._config_manager.get_value('theme', 'dark')
            self._prompt_style = self._config_manager.get_value('prompt_style', 'classic')
            self.command_prefix = self._config_manager.get_value('command_prefix', '')
            self.paranoid_mode = self._config_manager.get_value('paranoid_mode', False)
            self.model_profile = self._config_manager.get_value('model_profile', 'quality')
            self.offline_mode = self._config_manager.get_value('offline_mode', False)
            self.auto_model_switch = self._config_manager.get_value('auto_model_switch', True)
        except Exception as e:
            print(f"⚠️ Error loading config: {e}")
    
    @property
    def theme(self):
        return self._theme
    
    @theme.setter
    def theme(self, value):
        old_value = self._theme
        self._theme = value
        if self._config_manager and old_value != value:
            success = self._config_manager.set_value('theme', value)
            if not success:
                print(f"⚠️ Failed to save theme: {value}")
                self._theme = old_value  # Revert on failure
    
    @property
    def prompt_style(self):
        return self._prompt_style
    
    @prompt_style.setter
    def prompt_style(self, value):
        old_value = self._prompt_style
        self._prompt_style = value
        if self._config_manager and old_value != value:
            success = self._config_manager.set_value('prompt_style', value)
            if not success:
                print(f"⚠️ Failed to save prompt_style: {value}")
                self._prompt_style = old_value  # Revert on failure
    
    def set_value(self, key: str, value):
        """Set any configuration value."""
        if hasattr(self, key):
            old_value = getattr(self, key)
            setattr(self, key, value)
            
            if self._config_manager and old_value != value:
                success = self._config_manager.set_value(key, value)
                if not success:
                    print(f"⚠️ Failed to save {key}: {value}")
                    setattr(self, key, old_value)  # Revert on failure
                    return False
        return True
    
    def get_value(self, key: str, default=None):
        """Get any configuration value."""
        if hasattr(self, key):
            return getattr(self, key)
        elif self._config_manager:
            return self._config_manager.get_value(key, default)
        return default
    
    def reload_config(self):
        """Reload configuration from file."""
        if self._config_manager:
            # Force refresh from disk
            config = self._config_manager.load_config(use_cache=False)
            self._load_from_manager()
            print("🔄 Configuration reloaded")
        else:
            self.load_config()  # Fallback
    
    def load_config(self):
        """Legacy load method for backward compatibility."""
        if self._config_manager:
            self._load_from_manager()
        else:
            # Old fallback method
            try:
                if os.path.exists(CONFIG_FILE):
                    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                        self._theme = config_data.get('theme', 'dark')
                        self._prompt_style = config_data.get('prompt_style', 'classic')
                        self.command_prefix = config_data.get('command_prefix', '')
                        self.paranoid_mode = config_data.get('paranoid_mode', False)
                        self.model_profile = config_data.get('model_profile', 'quality')
                        self.offline_mode = config_data.get('offline_mode', False)
                        self.auto_model_switch = config_data.get('auto_model_switch', True)
            except Exception as e:
                print(f"⚠️ Legacy config load error: {e}")
    
    def save_config(self):
        """Legacy save method - now uses unified system."""
        if self._config_manager:
            # Update all values in the manager
            updates = {
                'theme': self._theme,
                'prompt_style': self._prompt_style,
                'command_prefix': self.command_prefix,
                'paranoid_mode': self.paranoid_mode,
                'model_profile': self.model_profile,
                'offline_mode': self.offline_mode,
                'auto_model_switch': self.auto_model_switch
            }
            return self._config_manager.update_values(updates)
        else:
            # Old fallback method
            try:
                config_data = {
                    'theme': self._theme,
                    'prompt_style': self._prompt_style,
                    'command_prefix': self.command_prefix,
                    'paranoid_mode': self.paranoid_mode,
                    'model_profile': self.model_profile,
                    'offline_mode': self.offline_mode,
                    'auto_model_switch': self.auto_model_switch
                }
                with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, indent=2)
                return True
            except Exception as e:
                print(f"⚠️ Legacy config save error: {e}")
                return False

config_state = Config()

# Session context
class SessionContext:
    def __init__(self):
        self.start_time = datetime.datetime.now()
        self.commands_history = []
        self.current_project = None
        self.ai_context = []
        self.modified_files = []
        self.notes = []
        self.saved_sessions = {}
        self.frequent_commands = {}
        # Track how many times the model was actually called
        self.ai_interactions = 0
    
    def add_command(self, command: str, output: str = "", error: str = ""):
        self.commands_history.append({
            'timestamp': datetime.datetime.now(),
            'command': command,
            'output': output,
            'error': error
        })
        # Track command frequency for smarter suggestions
        try:
            base = (command or "").strip().split()[0]
            if base:
                self.frequent_commands[base] = self.frequent_commands.get(base, 0) + 1
        except Exception:
            # Never let telemetry break the shell
            pass
    
    def get_context_summary(self) -> str:
        return f"Session started: {self.start_time}\nCommands run: {len(self.commands_history)}\nCurrent directory: {os.getcwd()}"
    
    def get_detailed_summary(self) -> Dict[str, Any]:
        """Get detailed session statistics."""
        now = datetime.datetime.now()
        duration = now - self.start_time
        
        # Centralized command classification based on first token
        AI_COMMANDS = {
            'ai', 'review', 'summarize', 'security_scan', 'optimize_code',
            'refactor', 'generate', 'learn', 'cheat', 'doc', 'search_semantic',
            'diff_semantic', 'project_health', 'project_optimize',
        }
        BUILTIN_COMMANDS = {
            'cd', 'ls', 'dir', 'help', 'config', 'banner', 'theme', 'prompt',
            'apikey', 'api_base', 'project_type', 'dependencies_check',
            'missing_files', 'tree', 'find_files', 'sys_info', 'disk_usage',
            'env', 'path', 'which', 'uptime', 'memory', 'processes', 'time',
            'calc', 'hash', 'encode', 'decode', 'feedback', 'session', 'history',
            'create_file', 'create_dir', 'mkdir', 'read_file', 'edit_file',
            'search_file', 'compare', 'diff', 'diff_dir', 'diff_semantic',
            'search_regex', 'search_semantic', 'recent', 'doc', 'summarize',
            'explain', 'generate', 'template', 'validate', 'format', 'project',
            'review', 'explain_last', 'security_scan', 'optimize_code', 'refactor',
            'project_health', 'project_optimize', 'network', 'learn', 'optimize',
            'analyze_system', 'cheat', 'model', 'ai', 'cat', 'grep', 'safe_mode',
        }
        
        # Count command types
        ai_commands = 0
        system_commands = 0
        builtin_commands = 0
        failed_commands = 0
        
        for cmd_info in self.commands_history:
            cmd = (cmd_info.get('command') or '').strip()
            first = cmd.split()[0] if cmd else ''
            
            if cmd_info.get('error'):
                failed_commands += 1
            elif first in AI_COMMANDS:
                ai_commands += 1
            elif first in BUILTIN_COMMANDS:
                builtin_commands += 1
            elif first:
                system_commands += 1
        
        return {
            'start_time': self.start_time,
            'end_time': now,
            'duration': duration,
            'total_commands': len(self.commands_history),
            'ai_commands': ai_commands,
            'system_commands': system_commands,
            'builtin_commands': builtin_commands,
'failed_commands': failed_commands,
            'modified_files': len(self.modified_files),
            'notes_count': len(getattr(self, 'notes', [])),
            'current_directory': os.getcwd(),
            'ai_interactions': getattr(self, 'ai_interactions', 0),
        }

session = SessionContext()

# Initialize API based on API_BASE
def initialize_api():
    global AI_ENABLED
    if API_BASE == "gemini":
        AI_ENABLED = bool(GEMINI_API_KEY)
    else:  # openrouter
        if API_KEY:
            openai.api_key = API_KEY
            openai.api_base = "https://openrouter.ai/api/v1"
            AI_ENABLED = True
        else:
            AI_ENABLED = False

initialize_api()

# --- Utility Functions ---
def confirm_action(prompt, default_yes=True):
    """Enhanced confirmation prompt with better UX.
    
    Args:
        prompt: The question to ask the user
        default_yes: If True, pressing Enter defaults to 'yes' (Y/n)
                    If False, pressing Enter defaults to 'no' (y/N)
    
    Returns:
        bool: True if user confirms, False otherwise
    """
    if default_yes:
        choices = "[Y/n]"
        default_response = "y"
    else:
        choices = "[y/N]"
        default_response = "n"
    
    try:
        full_prompt = f"{prompt} {choices}: "
        user_input = input(full_prompt).strip().lower()
        
        # If user just presses Enter, use the default
        if not user_input:
            user_input = default_response
        
        return user_input in ['y', 'yes']
        
    except (EOFError, KeyboardInterrupt):
        print()  # Add newline for better formatting
        return False  # Default to no on interruption

def signal_handler(signum, frame):
    """Handle Ctrl+C (SIGINT) and other signals."""
    global current_process, shell_running
    
    if signum == signal.SIGINT:  # Ctrl+C
        if current_process and current_process.poll() is None:
            # If there's a running subprocess, terminate it properly
            try:
                if platform.system() == "Windows":
                    current_process.terminate()
                else:
                    # Send SIGINT to the process group to interrupt child processes
                    import os
                    try:
                        os.killpg(os.getpgid(current_process.pid), signal.SIGINT)
                    except (ProcessLookupError, PermissionError):
                        # Fallback to regular termination
                        current_process.terminate()
                
                # Wait a bit for graceful termination
                try:
                    current_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    # Force kill if it doesn't terminate gracefully
                    current_process.kill()
                
                current_process = None  # Clear the process reference
                print_with_rich("\n⚠️  Process interrupted by user", "warning")
                # Raise KeyboardInterrupt to properly return to prompt loop
                raise KeyboardInterrupt
            except KeyboardInterrupt:
                # Re-raise to be caught by main loop
                raise
            except Exception as e:
                print_with_rich(f"\n⚠️  Error terminating process: {e}", "warning")
                current_process = None
                raise KeyboardInterrupt
        else:
            # No running process, raise KeyboardInterrupt to return to prompt
            print_with_rich("\n⚠️  Operation cancelled (Ctrl+C). Type 'exit' to quit VritraAI.", "warning")
            # Raise KeyboardInterrupt to be caught by the main loop
            raise KeyboardInterrupt
    
    # For other signals (SIGTERM, SIGQUIT), exit gracefully
    if signum in [signal.SIGTERM, signal.SIGQUIT]:
        shell_running = False
        show_session_summary("Signal interrupt")
        sys.exit(0)

def setup_signal_handlers():
    """Setup signal handlers for proper process management."""
    if platform.system() != "Windows":
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGQUIT, signal_handler)
    else:
        # Windows handling
        signal.signal(signal.SIGINT, signal_handler)
        try:
            signal.signal(signal.SIGTERM, signal_handler)
        except (AttributeError, ValueError):
            # SIGTERM might not be available on all Windows versions
            pass

def show_session_summary(exit_reason: str = "Normal exit"):
    """Show comprehensive and beautiful session summary on exit."""
    try:
        summary = session.get_detailed_summary()
        
        # Format duration
        duration = summary['duration']
        hours, remainder = divmod(duration.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if hours > 0:
            duration_str = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
        elif minutes > 0:
            duration_str = f"{int(minutes)}m {int(seconds)}s"
        else:
            duration_str = f"{int(seconds)}s"
        
        # Calculate additional statistics
        total_commands = summary['total_commands']
        success_rate = ((total_commands - summary['failed_commands']) / total_commands * 100) if total_commands > 0 else 100
        commands_per_minute = (total_commands / (duration.total_seconds() / 60)) if duration.total_seconds() > 60 else total_commands
        
        # Determine session productivity level
        if total_commands >= 50:
            productivity = "🔥 Highly Productive"
            productivity_color = "bold bright_green"
        elif total_commands >= 20:
            productivity = "💪 Very Active"
            productivity_color = "bold green"
        elif total_commands >= 10:
            productivity = "⚡ Active"
            productivity_color = "bold yellow"
        elif total_commands >= 5:
            productivity = "📝 Moderate"
            productivity_color = "bold cyan"
        else:
            productivity = "🌱 Light Usage"
            productivity_color = "bold dim white"
        
        if RICH_AVAILABLE and console:
            from rich.panel import Panel
            from rich.table import Table
            from rich.text import Text
            from rich.columns import Columns
            from rich import box
            from rich.align import Align
            
            console.print()  # Empty line before summary
            
            # Header - Professional Title (no border, left-aligned)
            # Use olive color (ANSI 118) with bold - print directly to avoid Rich escaping
            import sys
            sys.stdout.write("\033[38;5;118m\033[1mVRITRAAI SESSION SUMMARY\033[0m\n")
            sys.stdout.flush()
            console.print(exit_reason, style="dim white italic")
            console.print()
            
            # Session Overview - Professional Stats Display (no border)
            console.print("📊 Session Overview", style="bold bright_cyan")
            console.print(f"  Duration: [bold bright_white]{duration_str}[/bold bright_white] [dim](Started: {summary['start_time'].strftime('%H:%M:%S')})[/dim]")
            console.print(f"  Total Commands: [bold bright_white]{total_commands}[/bold bright_white] [dim]({commands_per_minute:.1f} cmd/min)[/dim]")
            console.print(f"  Success Rate: [bold green]{success_rate:.1f}%[/bold green] [dim]({summary['failed_commands']} failed)[/dim]")
            console.print(f"  Productivity: [{productivity_color}]{productivity}[/{productivity_color}]")
            console.print()
            
            # Command Breakdown (if commands exist) - no border
            if total_commands > 0:
                console.print("📈 Command Breakdown", style="bold bright_magenta")
                ai_pct = summary['ai_commands']/total_commands*100
                sys_pct = summary['system_commands']/total_commands*100
                builtin_pct = summary['builtin_commands']/total_commands*100
                
                console.print(f"  🤖 VritraAI Commands: [bold bright_white]{summary['ai_commands']}[/bold bright_white] [dim]({ai_pct:.1f}%)[/dim]")
                console.print(f"  ⚙️ System Commands: [bold bright_white]{summary['system_commands']}[/bold bright_white] [dim]({sys_pct:.1f}%)[/dim]")
                console.print(f"  🛠️ Built-in Commands: [bold bright_white]{summary['builtin_commands']}[/bold bright_white] [dim]({builtin_pct:.1f}%)[/dim]")
                console.print()
            
            # Session Details - no border
            console.print("ℹ️ Session Details", style="bold bright_yellow")
            console.print(f"  📁 Final Directory: [bright_cyan]{summary['current_directory']}[/bright_cyan]")
            console.print(f"  🎨 Theme: [bright_yellow]{config_state.theme}[/bright_yellow]")
            console.print(f"  🎭 Prompt Style: [bright_yellow]{config_state.prompt_style}[/bright_yellow]")
            console.print()
            
            # AI Information (if applicable) - no border
            if summary['ai_commands'] > 0 or AI_ENABLED:
                console.print("🤖 VritraAI Information", style="bold bright_green")
                console.print(f"  🧠 VritraAI Interactions: [bright_green]{summary['ai_commands']}[/bright_green]")
                console.print(f"  🤖 Current Model: [bright_cyan]{MODEL if AI_ENABLED else 'Disabled'}[/bright_cyan]")
                if AI_ENABLED:
                    console.print("  🔑 API Status: [bold green]✅ Active[/bold green]")
                else:
                    console.print("  🔑 API Status: [bold red]❌ Not configured[/bold red]")
                console.print()
            
            # Additional Stats (if applicable) - no border
            if summary['modified_files'] > 0 or summary['notes_count'] > 0:
                console.print("📊 Activity Stats", style="bold bright_blue")
                if summary['modified_files'] > 0:
                    console.print(f"  📝 Files Modified: [bright_blue]{summary['modified_files']}[/bright_blue]")
                if summary['notes_count'] > 0:
                    console.print(f"  📔 Notes Created: [bright_blue]{summary['notes_count']}[/bright_blue]")
                console.print()
            
            # Motivational Message - Professional Footer (no border, left-aligned)
            if total_commands >= 30:
                message = "🏆 Outstanding session! You're mastering the terminal like a pro!"
                msg_style = "bold bright_green"
            elif total_commands >= 15:
                message = "⭐ Great work! You've been quite productive with VritraAI today!"
                msg_style = "bold green"
            elif total_commands >= 8:
                message = "👍 Nice session! You're getting comfortable with the AI shell!"
                msg_style = "bold yellow"
            else:
                message = "🌱 Thanks for trying VritraAI! Come back anytime for more AI assistance!"
                # Use olive color with bold - print directly to avoid Rich escaping
                import sys
                sys.stdout.write(f"\033[38;5;118m\033[1m{message}\033[0m\n")
                sys.stdout.flush()
                msg_style = None  # Already printed, skip default print
            
            if msg_style:
                console.print(message, style=msg_style)
            
            # Log enhanced session end (Rich path)
            log_session(f"Session ended: {exit_reason} - Duration: {duration_str} - Commands: {total_commands} - Success: {success_rate:.1f}% - Productivity: {productivity}")
            
        else:
            # Fallback for non-rich terminals - keep original format but cleaner
            print("\n" + "═" * 60)
            print_with_rich(f"🎆 VritraAI Session Summary - {exit_reason}", "success")
            print("═" * 60)
            
            print_with_rich("\n📊 SESSION OVERVIEW", "info")
            print_with_rich(f"  🕰️ Duration: {duration_str} (Started: {summary['start_time'].strftime('%H:%M:%S')})", "default")
            print_with_rich(f"  📝 Commands: {total_commands} total ({commands_per_minute:.1f} cmd/min)", "default")
            print_with_rich(f"  ✅ Success Rate: {success_rate:.1f}% ({summary['failed_commands']} failed)", "default")
            print_with_rich(f"  🏃 Productivity: {productivity}", "default")
            
            if total_commands > 0:
                print_with_rich("\n📊 COMMAND BREAKDOWN", "info")
                print_with_rich(f"  🤖 VritraAI Commands: {summary['ai_commands']} ({summary['ai_commands']/total_commands*100:.1f}%)", "default")
                print_with_rich(f"  ⚙️ System Commands: {summary['system_commands']} ({summary['system_commands']/total_commands*100:.1f}%)", "default")
                print_with_rich(f"  🛠️ Built-in Commands: {summary['builtin_commands']} ({summary['builtin_commands']/total_commands*100:.1f}%)", "default")
            
            print_with_rich("\nℹ️ SESSION DETAILS", "info")
            print_with_rich(f"  📁 Final Directory: {summary['current_directory']}", "default")
            print_with_rich(f"  🎨 Theme: {config_state.theme}", "default")
            print_with_rich(f"  🎭 Prompt Style: {config_state.prompt_style}", "default")
            
            if summary['ai_commands'] > 0 or AI_ENABLED:
                print_with_rich("\n🤖 VritraAI INFORMATION", "info")
                print_with_rich(f"  🧠 VritraAI Interactions: {summary['ai_commands']}", "default")
                print_with_rich(f"  🤖 Current Model: {MODEL if AI_ENABLED else 'Disabled'}", "default")
                print_with_rich(f"  🔑 API Status: {'✅ Active' if AI_ENABLED else '❌ Not configured'}", "default")
            
            if summary['modified_files'] > 0 or summary['notes_count'] > 0:
                print_with_rich("\n📊 ACTIVITY STATS", "info")
                if summary['modified_files'] > 0:
                    print_with_rich(f"  📝 Files Modified: {summary['modified_files']}", "default")
                if summary['notes_count'] > 0:
                    print_with_rich(f"  📔 Notes Created: {summary['notes_count']}", "default")
            
            print()
            if total_commands >= 30:
                message = "🏆 Outstanding session! You're mastering the terminal like a pro!"
            elif total_commands >= 15:
                message = "⭐ Great work! You've been quite productive with VritraAI today!"
            elif total_commands >= 8:
                message = "👍 Nice session! You're getting comfortable with the AI shell!"
            else:
                message = "🌱 Thanks for trying VritraAI! Come back anytime for more AI assistance!"
            
            print_with_rich(message, "success")
            print("═" * 60)
            
            # Log enhanced session end
            log_session(f"Session ended: {exit_reason} - Duration: {duration_str} - Commands: {total_commands} - Success: {success_rate:.1f}% - Productivity: {productivity}")
        
    except Exception as e:
        print_with_rich(f"\n👋 Thank you for using VritraAI! (Summary error: {e})", "info")
    
    # Final goodbye message - Professional and Clean
    goodbye_messages = [
        "👋 Thanks for using VritraAI! May your commands be swift and your code bug-free!",
        "🚀 VritraAI session complete! Keep exploring the power of AI-assisted terminal work!", 
        "💫 Farewell from VritraAI! Your AI terminal companion will be here when you return!",
        "🎯 VritraAI signing off! Remember: with great power comes great responsibility!",
        "✨ Until next time! VritraAI is always ready to assist your terminal adventures!"
    ]
    import random
    chosen_message = random.choice(goodbye_messages)
    if RICH_AVAILABLE and console:
        console.print()
        # Use olive color with bold for all goodbye messages - print directly to avoid Rich escaping
        import sys
        sys.stdout.write(f"\033[38;5;118m\033[1m{chosen_message}\033[0m\n")
        sys.stdout.flush()
        print()
    else:
        print_with_rich(f"\n{chosen_message}\n", "success")
        print()

def log_session(message: str):
    """Log session activity to file."""
    try:
        with open(SESSION_LOG_FILE, 'a', encoding='utf-8') as f:
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"[{timestamp}] {message}\n")
    except Exception as e:
        pass  # Silent fail for logging

def log_last_command(command: str, output: str, exit_code: int):
    """Log the last executed system command to lastcmd.log (overwrites each time)."""
    try:
        log_data = {
            "command": command,
            "output": output,
            "exit_code": exit_code,
            "timestamp": datetime.datetime.now().isoformat()
        }
        with open(LASTCMD_LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        pass  # Silent fail for logging

def is_interactive_command(command: str) -> bool:
    """Check if a command is interactive and can't have its output captured.
    
    Uses multiple heuristics to detect interactive commands:
    1. Known interactive command names
    2. Commands that typically need TTY (checking for common patterns)
    3. Commands with flags that indicate interactivity
    """
    command_lower = command.lower()
    
    # Known interactive command names
    interactive_indicators = [
        'vim', 'nano', 'vi', 'emacs', 'htop', 'top', 'less', 'more', 
        'ssh', 'scp', 'rsync', 'man', 'watch', 'ncurses', 'dialog',
        'whiptail', 'fzf', 'ranger', 'mc', 'tmux', 'screen', 'weechat',
        'irssi', 'mutt', 'alpine', 'lynx', 'links', 'w3m', 'git commit',
        'git rebase', 'git merge', 'git add -i', 'python', 'python3',
        'ipython', 'node', 'nodejs', 'ruby', 'irb', 'perl', 'mysql',
        'psql', 'sqlite3', 'redis-cli', 'mongo', 'mongosh', 'docker exec -it',
        'docker run -it', 'kubectl exec -it', 'kubectl run -it'
    ]
    
    # Check for interactive flags
    interactive_flags = ['-i', '--interactive', '-it', '-ti']
    has_interactive_flag = any(flag in command_lower for flag in interactive_flags)
    
    # Check for known interactive patterns
    has_interactive_pattern = any(indicator in command_lower for indicator in interactive_indicators)
    
    # Commands that read from stdin without flags are likely interactive
    # (but this is a weaker signal, so we use it as a fallback)
    stdin_readers = ['cat', 'grep', 'sed', 'awk', 'sort', 'uniq']
    is_stdin_reader = any(reader in command_lower.split()[0] for reader in stdin_readers if command_lower.split())
    
    # If it has pipes or redirects, it's less likely to be interactive
    has_pipes = '|' in command or '>' in command or '<' in command or '>>' in command
    
    # Return True if it matches interactive patterns and doesn't have pipes/redirects
    return (has_interactive_flag or has_interactive_pattern) and not has_pipes

def is_ai_command(cmd: str) -> bool:
    """Check if a command is an AI/internal VritraAI command that should not be logged."""
    ai_commands = {
        'ai', 'review', 'explain_last', 'explain', 'summarize', 'generate',
        'optimize', 'refactor', 'optimize_code', 'security_scan', 'doc',
        'project', 'project_type', 'dependencies_check', 'project_health',
        'missing_files', 'project_optimize', 'cheat', 'learn'
    }
    first_word = cmd.split()[0] if cmd.split() else ""
    return first_word.lower() in ai_commands

# Whitelist of built-in commands that are safe to log (simple, non-AI commands)
LOGGABLE_BUILTIN_COMMANDS = {
    'ls', 'dir', 'search_file', 'find_files', 'hash', 'validate', 'format',
    'search_regex', 'cd', 'sys_info', 'disk_usage', 'env', 'path', 'which',
    'uptime', 'memory', 'processes', 'time', 'calc', 'template', 'encode', 'decode'
}

def should_log_command(command: str) -> bool:
    """Check if a command should be logged to lastcmd.log.
    
    Returns True if:
    - It's a system command (found in PATH), OR
    - It's a built-in command in the LOGGABLE_BUILTIN_COMMANDS whitelist
    
    Returns False if:
    - It's an AI command
    - It's an interactive command
    - It's a built-in command not in the whitelist
    """
    if not command or not command.strip():
        return False
    
    first_word = command.split()[0] if command.split() else ""
    first_word_lower = first_word.lower()
    
    # Don't log AI commands
    if is_ai_command(command):
        return False
    
    # Don't log interactive commands
    if is_interactive_command(command):
        return False
    
    # Check if it's a system command (in PATH)
    if shutil.which(first_word):
        return True
    
    # Check if it's a whitelisted built-in command
    if first_word_lower in LOGGABLE_BUILTIN_COMMANDS:
        return True
    
    # Don't log other built-in commands not in whitelist
    return False

def _execute_and_log_builtin(command: str, command_func):
    """Execute a built-in command and log its output if it's in the whitelist."""
    import io
    import sys
    
    # Check if we should log this command
    if not should_log_command(command):
        # Just execute without logging
        command_func()
        return
    
    # Capture stdout and stderr (including Rich output)
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    
    # Capture Rich output by monkey-patching console.print and print_with_rich
    output_lines = []
    original_console_print = None
    original_print_with_rich_func = None
    
    if RICH_AVAILABLE and console:
        # Store original functions
        original_console_print = console.print
        
        # Get the original print_with_rich function from globals
        import builtins
        if hasattr(builtins, 'print_with_rich'):
            original_print_with_rich_func = builtins.print_with_rich
        elif 'print_with_rich' in globals():
            original_print_with_rich_func = globals()['print_with_rich']
        
        # Create capturing versions
        def capturing_console_print(*args, **kwargs):
            # Call original to display
            original_console_print(*args, **kwargs)
            # Capture plain text version
            for arg in args:
                if isinstance(arg, str):
                    output_lines.append(arg)
                elif hasattr(arg, 'plain'):
                    # Rich Text objects have a .plain property
                    output_lines.append(arg.plain)
                elif hasattr(arg, '__str__'):
                    output_lines.append(str(arg))
        
        def capturing_print_with_rich(text, style=None):
            # Call original to display
            if original_print_with_rich_func:
                original_print_with_rich_func(text, style)
            # Capture text
            output_lines.append(str(text))
        
        # Replace functions
        console.print = capturing_console_print
        if original_print_with_rich_func:
            if hasattr(builtins, 'print_with_rich'):
                builtins.print_with_rich = capturing_print_with_rich
            elif 'print_with_rich' in globals():
                globals()['print_with_rich'] = capturing_print_with_rich
    
    try:
        # Execute command
        command_func()
    except Exception as e:
        # If there's an exception, capture it
        error_msg = str(e)
        output_lines.append(error_msg)
        # Restore and re-raise
        if RICH_AVAILABLE and console and original_console_print:
            console.print = original_console_print
            if original_print_with_rich_func:
                import builtins
                if hasattr(builtins, 'print_with_rich'):
                    builtins.print_with_rich = original_print_with_rich_func
                elif 'print_with_rich' in globals():
                    globals()['print_with_rich'] = original_print_with_rich_func
        raise
    finally:
        # Restore original functions
        if RICH_AVAILABLE and console and original_console_print:
            console.print = original_console_print
            if original_print_with_rich_func:
                import builtins
                if hasattr(builtins, 'print_with_rich'):
                    builtins.print_with_rich = original_print_with_rich_func
                elif 'print_with_rich' in globals():
                    globals()['print_with_rich'] = original_print_with_rich_func
    
    # Get captured output
    stdout_text = stdout_capture.getvalue()
    stderr_text = stderr_capture.getvalue()
    rich_text = '\n'.join(output_lines) if output_lines else ""
    
    # Combine all output
    full_output = stdout_text + stderr_text + rich_text
    
    # Log the command
    log_last_command(command, full_output, 0)

def is_dangerous_command(command: str) -> bool:
    """Check if command is potentially dangerous."""
    command_lower = command.lower().strip()
    return any(dangerous in command_lower for dangerous in DANGEROUS_COMMANDS)

def is_complex_command(command: str) -> bool:
    """Check if command is complex and likely needs AI interpretation."""
    command_lower = command.lower().strip()
    
    # Keywords that indicate natural language commands
    ai_keywords_backup = [
        'create a', 'make a', 'generate', 'build', 'setup', 
        'install', 'configure', 'find all', 'search for',
        'how to', 'what is', 'explain', 'help me',
        'folder', 'directory', 'with', 'using', 'for'
    ]
    
    ai_keywords = [
        'create a', 'make a', 'generate', 'build', 'setup', 
        'install', 'configure', 'find all', 'search for',
        'how to', 'what is', 'explain', 'help me',
        'folder', 'directory', 'with', 'using', 'for',
        'show me', 'list all', 'write a', 'design', 'draft',
        'summarize', 'analyze', 'optimize', 'fix', 'debug',
        'why is', 'steps to', 'instructions for', 'tutorial',
        'convert', 'translate', 'explain like', 'give me',
        'compare', 'difference between', 'advantages of',
        'best way to', 'recommend', 'example of'
    ]



    # Complex patterns
    complex_patterns = [
        r'create.*folder.*named?.*\w+',  # "create folder named xyz"
        r'make.*directory.*called.*\w+', # "make directory called abc"
        r'\w+\s+(with|using|for)\s+\w+', # "script with error handling"
        r'find.*files?.*recursively',     # "find files recursively"
        r'\w+.*\|.*\w+',                 # Piped commands
    ]
    
    # Check for AI keywords
    if any(keyword in command_lower for keyword in ai_keywords):
        return True
    
    # Check for complex patterns
    for pattern in complex_patterns:
        if re.search(pattern, command_lower):
            return True
    
    # Check for multi-word commands with spaces (not single commands)
    words = command.strip().split()
    if len(words) > 3 and not any(word.startswith('-') for word in words[1:]):
        return True
    
    return False

def get_os_info() -> Dict[str, str]:
    """Get operating system information with robust error handling.
    
    Handles cases where platform functions may fail or return empty values,
    especially in Termux/Android environments. Always returns a complete dict
    with fallback values.
    """
    os_info = {}
    
    # Detect Termux/Android environment
    env = os.environ
    is_termux = "TERMUX_VERSION" in env or (env.get("PREFIX", "").startswith("/data/data/com.termux"))
    is_android = bool(env.get("ANDROID_ROOT") or env.get("ANDROID_DATA"))
    
    # Get system name with fallback
    try:
        system = platform.system()
        if not system or system.strip() == "":
            if is_termux or is_android:
                system = "Android"
            else:
                system = "Unknown"
    except Exception:
        system = "Unknown"
    
    os_info['system'] = system
    
    # Get release version with fallback
    try:
        release = platform.release()
        if not release or release.strip() == "":
            # Try to get Android version from build.prop or fallback
            if is_termux or is_android:
                try:
                    # Try to read Android version from system properties
                    import subprocess
                    result = subprocess.run(['getprop', 'ro.build.version.release'], 
                                          capture_output=True, text=True, timeout=2)
                    if result.returncode == 0 and result.stdout.strip():
                        release = result.stdout.strip()
                    else:
                        release = "Unknown"
                except Exception:
                    release = "Unknown"
            else:
                release = "Unknown"
    except Exception:
        release = "Unknown"
    
    os_info['release'] = release
    
    # Get version string with fallback
    try:
        version = platform.version()
        if not version or version.strip() == "":
            version = "Unknown"
    except Exception:
        version = "Unknown"
    
    os_info['version'] = version
    
    # Get machine architecture with fallback
    try:
        machine = platform.machine()
        if not machine or machine.strip() == "":
            # Try alternative methods for Termux/Android
            if is_termux or is_android:
                try:
                    import subprocess
                    result = subprocess.run(['uname', '-m'], 
                                          capture_output=True, text=True, timeout=2)
                    if result.returncode == 0 and result.stdout.strip():
                        machine = result.stdout.strip()
                    else:
                        machine = "Unknown"
                except Exception:
                    machine = "Unknown"
            else:
                machine = "Unknown"
    except Exception:
        machine = "Unknown"
    
    os_info['machine'] = machine
    
    # Get processor info with fallback (this often fails in Termux)
    try:
        processor = platform.processor()
        if not processor or processor.strip() == "":
            # Try alternative methods
            if is_termux or is_android:
                try:
                    import subprocess
                    # Try to get CPU info from /proc/cpuinfo
                    result = subprocess.run(['uname', '-p'], 
                                          capture_output=True, text=True, timeout=2)
                    if result.returncode == 0 and result.stdout.strip():
                        processor = result.stdout.strip()
                    else:
                        # Try reading from /proc/cpuinfo
                        try:
                            with open('/proc/cpuinfo', 'r') as f:
                                for line in f:
                                    if 'model name' in line.lower() or 'Processor' in line:
                                        processor = line.split(':')[-1].strip()
                                        break
                            if not processor or processor.strip() == "":
                                processor = "Unknown"
                        except Exception:
                            processor = "Unknown"
                except Exception:
                    processor = "Unknown"
            else:
                processor = "Unknown"
    except Exception:
        processor = "Unknown"
    
    os_info['processor'] = processor
    
    # Add Termux/Android detection info
    if is_termux:
        os_info['environment'] = 'Termux'
    elif is_android:
        os_info['environment'] = 'Android'
    
    return os_info

def detect_project_type() -> Optional[str]:
    """Detect the type of project in current directory."""
    cwd = Path.cwd()
    
    # Check for common project files
    if (cwd / 'package.json').exists():
        return 'Node.js'
    elif (cwd / 'requirements.txt').exists() or (cwd / 'pyproject.toml').exists():
        return 'Python'
    elif (cwd / 'Cargo.toml').exists():
        return 'Rust'
    elif (cwd / 'go.mod').exists():
        return 'Go'
    elif (cwd / 'pom.xml').exists():
        return 'Java/Maven'
    elif (cwd / 'Dockerfile').exists():
        return 'Docker'
    elif (cwd / '.git').exists():
        return 'Git Repository'
    elif (cwd / 'Makefile').exists():
        return 'C/C++'
    
    return None

def backup_file(filepath: str) -> str:
    """Create a backup of a file before modifying it."""
    backup_path = f"{filepath}.backup_{int(time.time())}"
    try:
        shutil.copy2(filepath, backup_path)
        return backup_path
    except Exception as e:
        print_formatted_text(f"Warning: Could not create backup: {e}", style=get_style())
        return ""

def generate_unique_filename(base_filename: str, use_timestamp: bool = False) -> str:
    """Generate a unique filename that won't conflict with existing files.
    
    Args:
        base_filename: The desired filename (e.g., "index.html", "script.py")
        use_timestamp: If True, use timestamp format; otherwise use counter format
    
    Returns:
        A unique filename that doesn't exist in the current directory
        
    Examples:
        If index.html exists:
        - Counter mode: index_2.html, index_3.html, ...
        - Timestamp mode: index_20250110_150640.html
    """
    # If file doesn't exist, return as-is
    if not os.path.exists(base_filename):
        return base_filename
    
    # Split filename into name and extension
    name, ext = os.path.splitext(base_filename)
    
    if use_timestamp:
        # Use timestamp format: filename_YYYYMMDD_HHMMSS.ext
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_filename = f"{name}_{timestamp}{ext}"
        
        # Edge case: if timestamp file also exists, add counter
        counter = 2
        while os.path.exists(unique_filename):
            unique_filename = f"{name}_{timestamp}_{counter}{ext}"
            counter += 1
    else:
        # Use counter format: filename_2.ext, filename_3.ext, ...
        counter = 2
        unique_filename = f"{name}_{counter}{ext}"
        while os.path.exists(unique_filename):
            counter += 1
            unique_filename = f"{name}_{counter}{ext}"
    
    return unique_filename

def get_smart_filename_for_content(base_filename: str, content: str = "", description: str = "") -> str:
    """Get smart filename based on content analysis and existing files.
    
    This function:
    1. Analyzes the content/description to suggest better filenames
    2. Checks for existing files and generates unique names
    3. Uses intelligent naming conventions
    
    Args:
        base_filename: Initial filename suggestion
        content: File content (optional, for analysis)
        description: Description of what the file does (optional)
    
    Returns:
        A unique, descriptive filename
    """
    # Extract meaningful keywords from description if provided
    if description:
        description_lower = description.lower()
        
        # Map common keywords to better filename prefixes
        keyword_mapping = {
            'phone': 'phone_lookup',
            'ip lookup': 'ip_lookup',
            'network scan': 'network_scanner',
            'port scan': 'port_scanner',
            'web scraper': 'web_scraper',
            'api': 'api_client',
            'calculator': 'calculator',
            'converter': 'converter',
            'parser': 'parser',
            'validator': 'validator',
            'generator': 'generator',
            'monitor': 'monitor',
            'tracker': 'tracker',
            'analyzer': 'analyzer',
            'manager': 'manager',
            'bot': 'bot',
            'scraper': 'scraper',
            'crawler': 'crawler',
            'fetcher': 'fetcher',
            'downloader': 'downloader',
            'uploader': 'uploader',
        }
        
        # Try to find a better base name from description
        for keyword, prefix in keyword_mapping.items():
            if keyword in description_lower:
                # Get extension from original filename
                _, ext = os.path.splitext(base_filename)
                base_filename = f"{prefix}{ext}"
                break
    
    # Generate unique filename
    return generate_unique_filename(base_filename, use_timestamp=False)

# Advanced Error Handling System
class VritraAIError(Exception):
    """Base exception for VritraAI."""
    pass

class NetworkError(VritraAIError):
    """Raised when network operations fail."""
    pass

class APIError(VritraAIError):
    """Raised when AI API operations fail."""
    pass

class FileOperationError(VritraAIError):
    """Raised when file operations fail."""
    pass

# Enhanced Error Knowledge Base
ERROR_KNOWLEDGE_BASE = {
    # Python Common Errors
    "FileNotFoundError": {
        "explanation": "The file or directory you're trying to access doesn't exist at the specified path.",
        "common_causes": [
            "Incorrect file path or filename",
            "File was deleted or moved",
            "Working in wrong directory",
            "Typo in filename or path"
        ],
        "fixes": [
            "Check if the file exists: ls -la [filename]",
            "Verify your current directory: pwd",
            "Use absolute path instead of relative path",
            "Create the file if it should exist: touch [filename]"
        ]
    },
    "PermissionError": {
        "explanation": "You don't have the necessary permissions to perform this operation on the file/directory.",
        "common_causes": [
            "File owned by another user",
            "Insufficient read/write/execute permissions",
            "Directory is protected",
            "Need administrator/root access"
        ],
        "fixes": [
            "Check permissions: ls -l [filename]",
            "Change permissions: chmod +x [filename] or chmod 644 [filename]",
            "Use sudo for system files: sudo [command]",
            "Change ownership: sudo chown $USER [filename]"
        ]
    },
    "ModuleNotFoundError": {
        "explanation": "Python can't find the module you're trying to import. It's not installed or not in Python's path.",
        "common_causes": [
            "Package not installed",
            "Using wrong Python environment",
            "Typo in module name",
            "Module name changed in newer version"
        ],
        "fixes": [
            "Install the module: pip install [module-name]",
            "Check installed packages: pip list",
            "Verify Python environment: which python",
            "Use virtual environment: python -m venv venv && source venv/bin/activate"
        ]
    },
    "ImportError": {
        "explanation": "There's an issue importing a module or package, possibly due to circular imports or missing dependencies.",
        "common_causes": [
            "Circular import between modules",
            "Missing dependencies",
            "Corrupted package installation",
            "Python version incompatibility"
        ],
        "fixes": [
            "Reinstall the package: pip uninstall [package] && pip install [package]",
            "Check for circular imports in your code",
            "Update package: pip install --upgrade [package]",
            "Check Python version compatibility"
        ]
    },
    "KeyError": {
        "explanation": "Trying to access a dictionary key that doesn't exist.",
        "common_causes": [
            "Key doesn't exist in dictionary",
            "Typo in key name",
            "Data structure changed",
            "API response format different than expected"
        ],
        "fixes": [
            "Use .get() method: dict.get('key', default_value)",
            "Check if key exists: if 'key' in dict:",
            "Print dictionary keys: print(dict.keys())",
            "Use try-except: try: value = dict['key'] except KeyError: ..."
        ]
    },
    "TypeError": {
        "explanation": "Operation performed on incompatible data types or wrong number of arguments.",
        "common_causes": [
            "Wrong data type for operation",
            "None value used where object expected",
            "Incorrect function arguments",
            "Missing or extra parameters"
        ],
        "fixes": [
            "Check data types: print(type(variable))",
            "Convert types: str(), int(), float(), list()",
            "Verify function signature",
            "Check for None values: if variable is not None:"
        ]
    },
    "ValueError": {
        "explanation": "Correct type but inappropriate value for the operation.",
        "common_causes": [
            "Invalid value for conversion (e.g., int('abc'))",
            "Wrong format for parsing",
            "Value out of expected range",
            "Empty sequence where value expected"
        ],
        "fixes": [
            "Validate input before conversion",
            "Use try-except for conversions",
            "Check value ranges",
            "Provide default values: variable = value if value else default"
        ]
    },
    "AttributeError": {
        "explanation": "Trying to access an attribute or method that doesn't exist on the object.",
        "common_causes": [
            "Object doesn't have that attribute",
            "Typo in attribute/method name",
            "Object is None",
            "Wrong object type"
        ],
        "fixes": [
            "Check object type: print(type(object))",
            "List available attributes: print(dir(object))",
            "Check for None: if object is not None:",
            "Use hasattr(): if hasattr(object, 'attribute'):"
        ]
    },
    "IndexError": {
        "explanation": "Trying to access a list/array index that's out of range.",
        "common_causes": [
            "Index beyond list length",
            "Empty list",
            "Off-by-one error",
            "Wrong loop range"
        ],
        "fixes": [
            "Check list length: if len(list) > index:",
            "Use enumerate: for i, item in enumerate(list):",
            "Handle empty lists: if list: ...",
            "Use try-except: try: item = list[index] except IndexError: ..."
        ]
    },
    "ConnectionError": {
        "explanation": "Failed to establish or maintain a network connection.",
        "common_causes": [
            "No internet connection",
            "Server is down",
            "Firewall blocking connection",
            "Wrong URL/hostname"
        ],
        "fixes": [
            "Check internet: ping google.com",
            "Verify URL is correct",
            "Check firewall settings",
            "Use VPN if connection restricted"
        ]
    },
    "TimeoutError": {
        "explanation": "Operation took too long and exceeded the timeout limit.",
        "common_causes": [
            "Slow network connection",
            "Server not responding",
            "Large data transfer",
            "Timeout value too short"
        ],
        "fixes": [
            "Increase timeout value",
            "Check network speed",
            "Split large operations into smaller chunks",
            "Implement retry logic with backoff"
        ]
    },
    "JSONDecodeError": {
        "explanation": "Failed to parse JSON data. The JSON format is invalid or corrupted.",
        "common_causes": [
            "Invalid JSON syntax",
            "HTML/text returned instead of JSON",
            "Incomplete response",
            "Encoding issues"
        ],
        "fixes": [
            "Print response before parsing: print(response.text)",
            "Check content type: print(response.headers['content-type'])",
            "Use json.loads() with try-except",
            "Validate JSON online: jsonlint.com"
        ]
    },
    "OSError": {
        "explanation": "Operating system related error occurred during I/O operation.",
        "common_causes": [
            "Disk full",
            "Path too long",
            "File in use by another process",
            "System resource limit reached"
        ],
        "fixes": [
            "Check disk space: df -h",
            "Close files properly: with open() as f:",
            "Check running processes: ps aux | grep [filename]",
            "Use shorter paths"
        ]
    },
    "NameError": {
        "explanation": "Variable or function name referenced before being defined.",
        "common_causes": [
            "Variable not defined",
            "Typo in variable name",
            "Variable out of scope",
            "Forgot to import"
        ],
        "fixes": [
            "Define variable before use",
            "Check spelling of variable names",
            "Import required modules",
            "Check variable scope"
        ]
    },
    "SyntaxError": {
        "explanation": "Python code has incorrect syntax and can't be parsed.",
        "common_causes": [
            "Missing colon (:)",
            "Incorrect indentation",
            "Unclosed brackets/quotes",
            "Invalid Python syntax"
        ],
        "fixes": [
            "Check line mentioned in error",
            "Verify indentation is consistent",
            "Match all brackets and quotes",
            "Use IDE/linter for syntax checking"
        ]
    },
    "IndentationError": {
        "explanation": "Incorrect indentation in Python code. Python is sensitive to whitespace.",
        "common_causes": [
            "Mixed tabs and spaces",
            "Inconsistent indentation levels",
            "Missing indentation",
            "Extra indentation"
        ],
        "fixes": [
            "Use consistent indentation (4 spaces recommended)",
            "Configure editor to use spaces instead of tabs",
            "Run autopep8: autopep8 --in-place [filename]",
            "Use Python linter: pylint [filename]"
        ]
    },
    "RuntimeError": {
        "explanation": "Generic error that occurs during program execution.",
        "common_causes": [
            "Recursive function exceeded max depth",
            "Invalid state for operation",
            "Resource allocation failed",
            "Unexpected program state"
        ],
        "fixes": [
            "Check error message for specific cause",
            "Add logging: import logging",
            "Use debugger: import pdb; pdb.set_trace()",
            "Validate program state before operations"
        ]
    },
    "KeyboardInterrupt": {
        "explanation": "User manually interrupted the program (Ctrl+C).",
        "common_causes": [
            "User pressed Ctrl+C",
            "Program taking too long",
            "Intentional interruption",
            "Stuck in infinite loop"
        ],
        "fixes": [
            "Let program complete normally",
            "Optimize slow operations",
            "Add progress indicators",
            "Handle KeyboardInterrupt: try: ... except KeyboardInterrupt: ..."
        ]
    },
    "MemoryError": {
        "explanation": "Program ran out of available memory.",
        "common_causes": [
            "Processing too much data at once",
            "Memory leak in code",
            "Insufficient system RAM",
            "Infinite recursion or loop"
        ],
        "fixes": [
            "Process data in chunks/batches",
            "Use generators instead of lists",
            "Close files and connections properly",
            "Increase system memory or use cloud computing"
        ]
    }
}

def display_enhanced_error(error: Exception, context: str = "", show_full_traceback: bool = False, traceback_str: str = None, code_frame: Dict[str, Any] = None):
    """Display error with detailed explanation and fixing suggestions.
    
    Args:
        error: The exception that occurred
        context: What was being done when error occurred
        show_full_traceback: Whether to show complete traceback
        traceback_str: Optional pre-captured traceback string to display
        code_frame: Optional dict with 'file', 'line', 'function', 'snippet' keys
    """
    error_type = type(error).__name__
    error_msg = str(error)
    
    # Display error header
    print()
    print_with_rich("═" * 70, "error")
    # Categorize for better UX
    try:
        category, icon, _ = categorize_error(f"{error_type}: {error_msg}")
        print_with_rich(f"{icon} {category}", "error")
    except Exception:
        print_with_rich("❌ ERROR DETECTED", "error")
    print_with_rich("═" * 70, "error")
    
    # Show error type and message
    print_with_rich(f"\n🔴 Error Type: {error_type}", "error")
    print_with_rich(f"📝 Error Message: {error_msg}", "error")
    
    if context:
        print_with_rich(f"📍 Context: {context}", "warning")
    
    # Get error knowledge from database
    error_info = ERROR_KNOWLEDGE_BASE.get(error_type)
    
    if error_info:
        # Mid-level explanation
        print_with_rich("\n💡 EXPLANATION (Mid-Level):", "info")
        print_with_rich(f"   {error_info['explanation']}", "default")
        
        # Common causes
        print_with_rich("\n🔍 COMMON CAUSES:", "info")
        for i, cause in enumerate(error_info['common_causes'], 1):
            print_with_rich(f"   {i}. {cause}", "default")
        
        # Fixing suggestions
        print_with_rich("\n🔧 HOW TO FIX:", "success")
        for i, fix in enumerate(error_info['fixes'], 1):
            print_with_rich(f"   {i}. {fix}", "success")
    else:
        # Generic advice for unknown errors
        print_with_rich("\n💡 GENERAL ADVICE:", "info")
        print_with_rich("   This is a less common error. Here are general debugging steps:", "default")
        print_with_rich("   1. Read the error message carefully - it often contains the cause", "default")
        print_with_rich("   2. Check the line number mentioned in the error", "default")
        print_with_rich("   3. Search for the error online: Google '[error-type] python'", "default")
        print_with_rich("   4. Check official documentation for the module/function", "default")
        
        if AI_ENABLED:
            print_with_rich("   5. Use AI assistance: Select option 3 below for AI analysis", "success")
    
    # Additional resources
    print_with_rich("\n📚 RESOURCES:", "info")
    print_with_rich(f"   • Search online: https://stackoverflow.com/search?q={error_type}+python", "default")
    print_with_rich(f"   • Python docs: https://docs.python.org/3/library/exceptions.html#{error_type}", "default")
    
    print_with_rich("\n" + "═" * 70, "error")

def build_code_frame_from_exc(exc_info) -> Dict[str, Any]:
    """Build a small code frame around the error location from exc_info.
    Returns a dict with file, line, function, snippet (with <ERR_LINE> marker).
    """
    try:
        import traceback
        etype, evalue, tb = exc_info
        if not tb:
            return None
        frames = traceback.extract_tb(tb)
        if not frames:
            return None
        frame = frames[-1]
        filename, lineno, func, _ = frame.filename, frame.lineno, frame.name, None
        snippet = None
        try:
            with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            start = max(1, lineno - 5)
            end = min(len(lines), lineno + 5)
            snippet_lines = []
            for i in range(start, end + 1):
                line_text = lines[i - 1].rstrip('\n')
                if i == lineno:
                    snippet_lines.append(f"<ERR_LINE>{i:5}: {line_text}")
                else:
                    snippet_lines.append(f"{i:5}: {line_text}")
            snippet = "\n".join(snippet_lines)
        except Exception:
            snippet = None
        return {
            'file': filename,
            'line': lineno,
            'function': func,
            'snippet': snippet
        }
    except Exception:
        return None


def expand_path(path: str) -> str:
    """Expand shell path variables like ~ and $VAR to actual paths.
    
    Args:
        path: Path string that may contain ~ or environment variables
        
    Returns:
        Expanded path string
    """
    if not path:
        return path
    try:
        # Expand ~ to home directory
        expanded = os.path.expanduser(path)
        # Expand environment variables like $HOME, ${VAR}
        expanded = os.path.expandvars(expanded)
        return expanded
    except Exception:
        return path

def sanitize_path(path: str) -> str:
    """Sanitize a path for privacy when paranoid_mode is enabled."""
    try:
        home = os.path.expanduser('~')
        if path.startswith(home):
            path = path.replace(home, '~', 1)
        # Optionally reduce depth
        parts = path.split(os.sep)
        if len(parts) > 3:
            return os.sep.join(parts[:2] + ['...', parts[-1]])
        return path
    except Exception:
        return path


def format_traceback_colorful(tb: str) -> str:
    """Apply simple ANSI coloring to Python traceback for readability."""
    try:
        lines = tb.split('\n')
        colored = []
        for line in lines:
            s = line
            ls = line.lstrip()
            if ls.startswith('Traceback'):
                s = f"\033[1;33m{line}\033[0m"  # bold yellow
            elif ls.startswith('File "') and '", line ' in ls:
                s = f"\033[36m{line}\033[0m"  # cyan
            elif ls.startswith('  File "'):
                s = f"\033[36m{line}\033[0m"
            elif ls.startswith('    '):
                s = f"\033[2m{line}\033[0m"  # dim code line
            elif ls and (ls[0].isalpha() and (':' in ls)):
                # Likely the exception type/message
                s = f"\033[1;31m{line}\033[0m"  # bold red
            colored.append(s)
        return '\n'.join(colored)
    except Exception:
        return tb

# --- Smart error context selection (offline filter) ---
SMART_CTX_IGNORED_DIRS = {'.git', 'node_modules', '.venv', 'venv', '__pycache__', 'dist', 'build', '.idea', '.pytest_cache'}
SMART_CTX_BINARY_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.pdf', '.zip', '.rar', '.7z', '.gz', '.tar', '.xz', '.mp4', '.mkv', '.mov', '.mp3', '.wav'}
SMART_CTX_DEFAULTS = {
    'max_depth': 3,
    'max_entries': 50,
    'max_snippets': 5,
    'snippet_chars': 2000
}

def sanitize_traceback_for_ai(traceback_str: str) -> str:
    """Remove vritraai.py references from traceback to avoid confusing AI.
    
    The AI should focus on the user's actual error, not the shell wrapper code.
    This function filters out lines containing vritraai.py file paths while preserving
    the traceback structure, exception type, and the actual user error message.
    """
    if not traceback_str:
        return traceback_str
    
    lines = traceback_str.split('\n')
    sanitized_lines = []
    skip_next_code_line = False
    
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        line_lower = line.lower()
        
        # Check if this line is a file path line referencing vritraai.py
        # Pattern: File "/path/to/vritraai.py", line X
        is_vritraai_file_line = (
            ('file "' in line_lower or "file '" in line_lower) and 
            'vritraai.py' in line_lower
        )
        
        if is_vritraai_file_line:
            # Skip this file path line and the next code line
            skip_next_code_line = True
            continue
        
        # If we're skipping the next code line (which is internal shell code)
        if skip_next_code_line:
            # Skip code lines that are clearly from vritraai.py internal code
            # But keep exception messages and important error info
            if (line_stripped.startswith('os.') or 
                line_stripped.startswith('subprocess.') or
                line_stripped.startswith('current_process') or
                line_stripped.startswith('result.') or
                line_stripped.startswith('execute_command') or
                line_stripped.startswith('handle_error') or
                (line_stripped and not line_stripped[0].isalpha() and '=' in line_stripped and 'vritraai' in line_lower)):
                skip_next_code_line = False
                continue
            # If it's an exception line or important info, keep it
            skip_next_code_line = False
        
        # Always keep exception type lines and error messages
        # These don't contain file paths and are important for AI
        sanitized_lines.append(line)
    
    # Join back and clean up any double newlines
    sanitized = '\n'.join(sanitized_lines)
    # Remove excessive blank lines (more than 2 consecutive)
    while '\n\n\n' in sanitized:
        sanitized = sanitized.replace('\n\n\n', '\n\n')
    
    return sanitized.strip()


def _depth_limited_walk(root: str, max_depth: int):
    root = os.path.abspath(root)
    for current_root, dirs, files in os.walk(root):
        depth = current_root[len(root):].count(os.sep)
        # Filter ignored dirs in-place
        dirs[:] = [d for d in dirs if d not in SMART_CTX_IGNORED_DIRS]
        yield current_root, dirs, files
        if depth >= max_depth:
            dirs[:] = []  # stop descending further


def _extract_error_clues(error: Exception, traceback_str: str, context_str: str) -> Dict[str, Any]:
    import re
    clues = {
        'filenames': set(),
        'modules': set(),
        'words': set()
    }
    text = f"{type(error).__name__}: {str(error)}\n{traceback_str or ''}\n{context_str or ''}"
    # file paths in quotes
    for m in re.finditer(r'File \"([^\"]+)\"', text):
        clues['filenames'].add(m.group(1))
    # module names from import errors
    for m in re.finditer(r"No module named ['\"]([^'\"]+)['\"]", text):
        clues['modules'].add(m.group(1))
    # quoted words
    for m in re.finditer(r"['\"]([A-Za-z0-9_./-]{2,})['\"]", text):
        clues['words'].add(m.group(1))
    # tokenized bare words (limited)
    for m in re.finditer(r'\b([A-Za-z0-9_./-]{3,})\b', text):
        token = m.group(1)
        if len(clues['words']) < 50:
            clues['words'].add(token)
    return clues


def _score_path(path: str, clues: Dict[str, Any], session: SessionContext) -> int:
    score = 0
    base = os.path.basename(path).lower()
    low_path = path.lower()
    # exact filename hits
    for fn in clues['filenames']:
        if os.path.basename(fn).lower() == base:
            score += 8
        elif os.path.basename(fn).lower() in base:
            score += 4
    # module hits (map module to path-like)
    for mod in clues['modules']:
        mod_base = mod.split('.')[-1].lower()
        if mod_base in base:
            score += 6
    # word hits
    for w in list(clues['words'])[:30]:
        lw = w.lower()
        if lw in base:
            score += 2
        elif lw in low_path:
            score += 1
    # recently modified by session
    if hasattr(session, 'modified_files') and any(path.endswith(mf) or mf.endswith(path) for mf in session.modified_files):
        score += 5
    # prefer code/config files
    _, ext = os.path.splitext(base)
    if ext in {'.py', '.js', '.ts', '.json', '.toml', '.ini', '.yaml', '.yml', '.sh'}:
        score += 2
    return score


def _get_file_snippet(path: str, tokens: set, max_chars: int) -> str:
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        # if tokens hit, extract a few lines around first hit; else head
        for t in list(tokens)[:10]:
            idx = content.lower().find(t.lower())
            if idx != -1:
                start = max(0, idx - max_chars // 4)
                end = min(len(content), idx + max_chars // 2)
                snippet = content[start:end]
                return snippet[:max_chars]
        return content[:max_chars]
    except Exception:
        return ""


def build_comprehensive_context(cwd: str = None, include_files: bool = True, limits: Dict[str, int] = None) -> str:
    """Build comprehensive context for AI including system info, directory structure, and project details."""
    if cwd is None:
        cwd = os.getcwd()
    
    limits = limits or SMART_CTX_DEFAULTS
    lines = []
    
    # System Information
    os_info = get_os_info()
    lines.append("=== SYSTEM INFORMATION ===")
    lines.append(f"OS: {os_info['system']} {os_info['release']}")
    lines.append(f"Version: {os_info['version']}")
    lines.append(f"Architecture: {os_info['machine']}")
    if os_info['processor']:
        lines.append(f"Processor: {os_info['processor']}")
    
    # Python version
    try:
        import sys
        lines.append(f"Python: {sys.version.split()[0]} ({sys.executable})")
    except:
        pass
    
    # Shell information
    try:
        shell = os.environ.get('SHELL', os.environ.get('COMSPEC', 'Unknown'))
        lines.append(f"Shell: {shell}")
    except:
        pass
    
    # Current Working Directory
    lines.append(f"\n=== CURRENT DIRECTORY ===")
    lines.append(f"Path: {cwd}")
    
    # Project Type
    project_type = detect_project_type()
    if project_type:
        lines.append(f"Project Type: {project_type}")
    
    # Directory Structure
    if include_files:
        lines.append(f"\n=== DIRECTORY STRUCTURE ===")
        try:
            entries = sorted(os.listdir(cwd))
            dirs = []
            files = []
            
            for name in entries:
                if name in SMART_CTX_IGNORED_DIRS:
                    continue
                path = os.path.join(cwd, name)
                if os.path.isdir(path):
                    dirs.append(name)
                else:
                    files.append(name)
            
            # List directories
            if dirs:
                lines.append("Directories:")
                for d in dirs[:limits.get('max_entries', 50)]:
                    lines.append(f"  📁 {d}/")
            
            # List files
            if files:
                lines.append("Files:")
                for f in files[:limits.get('max_entries', 50)]:
                    # Get file size for context
                    try:
                        size = os.path.getsize(os.path.join(cwd, f))
                        size_str = f" ({size} bytes)" if size < 1024 else f" ({size/1024:.1f} KB)"
                    except:
                        size_str = ""
                    lines.append(f"  📄 {f}{size_str}")
            
            # Always mention important manifest files
            important_files = ['requirements.txt', 'pyproject.toml', 'package.json', 'setup.cfg', 'Dockerfile', 
                             'Cargo.toml', 'go.mod', 'pom.xml', 'Makefile', 'CMakeLists.txt', '.gitignore']
            manifest_info = []
            for mf in important_files:
                p = os.path.join(cwd, mf)
                if os.path.exists(p):
                    manifest_info.append(mf)
            
            if manifest_info:
                lines.append(f"\nImportant Files Found: {', '.join(manifest_info)}")
                
        except Exception as e:
            lines.append(f"Could not list directory: {e}")
    
    return '\n'.join(lines)

def build_smart_error_context(cwd: str, error: Exception, context_str: str, traceback_str: str, paranoid: bool, limits: Dict[str, int] = None) -> str:
    """Build comprehensive context for AI error recovery including system info, directory structure, and error details."""
    limits = limits or SMART_CTX_DEFAULTS
    lines = []
    
    # Build comprehensive system and directory context
    comprehensive_ctx = build_comprehensive_context(cwd, include_files=True, limits=limits)
    lines.append(comprehensive_ctx)
    
    # Error Information
    lines.append(f"\n=== ERROR INFORMATION ===")
    disp_cwd = sanitize_path(cwd) if paranoid else cwd
    lines.append(f"Context: {context_str}" if context_str else f"Location: {disp_cwd}")
    lines.append(f"Error Type: {type(error).__name__}")
    lines.append(f"Error Message: {str(error)}")
    
    # Include sanitized traceback (tail only)
    if traceback_str:
        sanitized_tb = sanitize_traceback_for_ai(traceback_str)
        if sanitized_tb:
            tb_short = '\n'.join(sanitized_tb.strip().splitlines()[-12:])
            lines.append(f"\n=== TRACEBACK (last 12 lines) ===")
            lines.append(tb_short)
    
    return '\n'.join(lines)
def execute_with_error_recovery(operation_func, *args, context: str = "", max_retries: int = 3, **kwargs):
    """Execute an operation with automatic error recovery and retry logic.
    
    Args:
        operation_func: Function to execute
        *args: Positional arguments for the function
        context: Description of what the function does (for error reporting)
        max_retries: Maximum number of retry attempts
        **kwargs: Keyword arguments for the function
    
    Returns:
        The result of the function, or None if all attempts fail
    """
    attempts = 0
    
    while attempts < max_retries:
        try:
            return operation_func(*args, **kwargs)
        except (FileNotFoundError, PermissionError, OSError) as e:
            attempts += 1
            import sys, traceback as _tb
            tb_str = _tb.format_exc()
            code_frame = build_code_frame_from_exc(sys.exc_info())
            
            if attempts >= max_retries:
                # Max retries exceeded - show error recovery
                print_with_rich(f"❌ Max retry attempts ({max_retries}) exceeded", "error")
                should_retry = handle_error_with_recovery(e, context, show_suggestion=True, auto_mode=False, traceback_str=tb_str, code_frame=code_frame)
                if should_retry:
                    attempts = 0  # Reset attempts if user wants to retry
                    continue
                return None
            
            # Show error and ask for retry
            print_with_rich(f"⚠️ Attempt {attempts} failed: {str(e)}", "warning")
            should_retry = handle_error_with_recovery(e, context, show_suggestion=True, auto_mode=False, traceback_str=tb_str, code_frame=code_frame)
            
            if not should_retry:
                return None
            # Continue to retry
        except Exception as e:
            # For other exceptions, show error recovery once
            import sys, traceback as _tb
            tb_str = _tb.format_exc()
            code_frame = build_code_frame_from_exc(sys.exc_info())
            handle_error_with_recovery(e, context, show_suggestion=True, auto_mode=False, traceback_str=tb_str, code_frame=code_frame)
            return None
    
    return None

def handle_error_with_recovery(error: Exception, context: str = "", show_suggestion: bool = True, auto_mode: bool = False, custom_prompt: str = None, traceback_str: str = None, code_frame: Dict[str, Any] = None) -> bool:
    """Advanced error handler with recovery options.
    
    Args: 
        error: The exception that occurred
        context: Context about what was being done when error occurred
        show_suggestion: Whether to show AI suggestions for fixing the error
        auto_mode: If True, automatically shows AI explanation without user interaction
        custom_prompt: Custom AI prompt for explanation (used in auto_mode)
        traceback_str: Optional pre-captured traceback string
        code_frame: Optional code context dict
    
    Returns:
        bool: True if user wants to retry, False otherwise (always False in auto_mode)
    """
    import sys
    
    # Non-interactive fallback: no menus, just print info and return
    try:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            display_enhanced_error(error, context, show_full_traceback=False, traceback_str=traceback_str, code_frame=code_frame)
            if AI_ENABLED and show_suggestion:
                error_type = type(error).__name__
                error_msg = str(error)
                # Build minimal safe prompt
                cwd = os.getcwd()
                if getattr(config_state, 'paranoid_mode', False):
                    cwd_display = sanitize_path(cwd)
                    dir_context = ""
            else:
                cwd_display = cwd
                try:
                    files_in_dir = os.listdir(cwd)[:10]
                    dir_context = f"Files in current directory: {', '.join(files_in_dir)}"
                except Exception:
                    dir_context = "Could not list current directory"
                # Sanitize traceback to remove vritraai.py references before passing to AI
                sanitized_tb = sanitize_traceback_for_ai(traceback_str) if traceback_str else traceback_str
                smart_ctx = build_smart_error_context(cwd, error, context, sanitized_tb, getattr(config_state, 'paranoid_mode', False))
                prompt = f"""The user encountered an error and needs help fixing it.

{smart_ctx}

Please provide:
1. A clear explanation of what went wrong
2. Multiple possible fix commands (at least 3-5 different approaches)
3. Step-by-step instructions for each fix option

Format fix commands clearly so they can be easily extracted. Provide various approaches (e.g., create missing files/directories, check permissions, verify paths, alternative solutions). Plain text only."""
                explanation = get_ai_response(prompt)
                if explanation:
                    cleaned = clean_ai_response(explanation)
                    print_ai_response(cleaned, use_typewriter=False)
                    # Also surface any commands we detect
                    cmds = extract_fix_commands_improved(cleaned)
                    if cmds:
                        print_with_rich("\n🛠️ Suggested commands:", "info")
                        for i, c in enumerate(cmds, 1):
                            print_with_rich(f"  {i}. {c}", "default")
            return False
    except Exception:
        # If TTY detection fails, continue to interactive flow
        pass

    # Use enhanced error display (skip in auto_mode for cleaner output)
    if not auto_mode:
        display_enhanced_error(error, context, show_full_traceback=False, traceback_str=traceback_str, code_frame=code_frame)
    
    # Auto mode: Just show AI explanation automatically
    if auto_mode and AI_ENABLED and show_suggestion:
        error_type = type(error).__name__
        error_msg = str(error)
        
        # Use custom prompt if provided, otherwise generate default
        if custom_prompt:
            prompt = custom_prompt
        else:
            # Get context for better explanations
            cwd = os.getcwd()
            if getattr(config_state, 'paranoid_mode', False):
                cwd_display = sanitize_path(cwd)
                dir_context = ""
            else:
                cwd_display = cwd
                try:
                    files_in_dir = os.listdir(cwd)[:10]
                    dir_context = f"Files in current directory: {', '.join(files_in_dir)}"
                except Exception:
                    dir_context = "Could not list current directory"
            
                # Sanitize traceback to remove vritraai.py references before passing to AI
                sanitized_tb = sanitize_traceback_for_ai(traceback_str) if traceback_str else traceback_str
                smart_ctx = build_smart_error_context(cwd, error, context, sanitized_tb, getattr(config_state, 'paranoid_mode', False))
            prompt = f"""The user encountered an error and needs help fixing it.

{smart_ctx}

Please provide:
1) A clear explanation of what went wrong
2) Multiple possible fix commands (at least 3-5 different approaches)
3) Step-by-step instructions for each fix option

Format fix commands clearly so they can be easily extracted. Provide various approaches (e.g., create missing files/directories, check permissions, verify paths, alternative solutions).
2) How to fix it with specific steps
3) Concrete commands to run (if applicable)

Plain text only."""
        
        print_with_rich("\n💡 VritraAI Explanation:", "info")
        explanation = get_ai_response(prompt)
        if explanation:
            cleaned = clean_ai_response(explanation)
            # Use unified renderer that handles code blocks with color and no backticks
            print_ai_response(cleaned, use_typewriter=True)
        print()
        return False  # Auto mode doesn't support retry
    
    # Interactive mode: Show recovery options menu
    print_with_rich("\n🔧 RECOVERY OPTIONS:", "info")
    if AI_ENABLED and show_suggestion:
        print_with_rich("  1. Get AI suggestion for fix (with full traceback)", "default")
        print_with_rich("  2. Abort current operation", "default")
    else:
        print_with_rich("  1. Abort current operation", "default")
    
    try:
        max_options = 2 if (AI_ENABLED and show_suggestion) else 1
        choice = input(f"\nChoose recovery option (1-{max_options}): ").strip()
        
        if choice == "1" and AI_ENABLED and show_suggestion:
            # Show error type and message instead of full traceback
            error_type = type(error).__name__
            error_msg = str(error)
            print_with_rich(f"\n❌ Error: {error_type}: {error_msg}", "error")
            
            # Get AI suggestion for the error with traceback (still sanitized for AI)
            error_type = type(error).__name__
            error_msg = str(error)
            tb_for_prompt = traceback_str or "(no traceback captured)"
            
            # Sanitize traceback to remove vritraai.py references before passing to AI
            if tb_for_prompt != "(no traceback captured)":
                tb_for_prompt = sanitize_traceback_for_ai(tb_for_prompt)
            
            # Build smart context (filtered) before asking AI
            smart_ctx = build_smart_error_context(os.getcwd(), error, context, tb_for_prompt, getattr(config_state, 'paranoid_mode', False))
            suggestion_prompt = f"""The user encountered an error and needs a fix.

{smart_ctx}

Please provide:
1. A clear explanation of what went wrong
2. Multiple possible fix commands (at least 3-5 different approaches)
3. Step-by-step instructions for each fix option

Format fix commands clearly so they can be easily extracted. Provide various approaches (e.g., create missing files/directories, check permissions, verify paths, alternative solutions)."""
            
            print_with_rich("\n🤖 Asking VritraAI for help...", "info")
            suggestion = get_ai_response(suggestion_prompt)
            if suggestion:
                cleaned_suggestion = clean_ai_response(suggestion)
                print_with_rich(f"\n🤖 VritraAI Suggestion:", "info")
                # Unified renderer for colorful, fence-free output
                print_ai_response(cleaned_suggestion, use_typewriter=True)
                
                # Offer to run extracted fix commands
                cmds = extract_fix_commands_improved(cleaned_suggestion)
                if cmds:
                    print_with_rich("\n🛠️ Suggested commands:", "info")
                    for i, c in enumerate(cmds, 1):
                        print_with_rich(f"  {i}. {c}", "default")
                    print_with_rich("  a. Run all", "default")
                    print_with_rich("  n. Do nothing", "default")
                    sel = input("Select a command to run (1..N/a/n): ").strip().lower()
                    if sel == 'a':
                        for c in cmds:
                            if confirm_action(f"Run: {c}?"):
                                execute_command(c)
                    elif sel.isdigit():
                        idx = int(sel) - 1
                        if 0 <= idx < len(cmds):
                            c = cmds[idx]
                            if confirm_action(f"Run: {c}?"):
                                execute_command(c)
            else:
                print_with_rich("\n⚠️ Could not get AI suggestion", "warning")
            
            return False
        elif choice == "2" and AI_ENABLED and show_suggestion:
            print_with_rich("❌ Aborting operation", "error")
            return False
        elif choice == "1" and not (AI_ENABLED and show_suggestion):
            print_with_rich("❌ Aborting operation", "error")
            return False
        else:
            print_with_rich("❌ Invalid option. Aborting operation", "error")
            return False
            
    except (EOFError, KeyboardInterrupt):
        print_with_rich("\n❌ Operation aborted by user", "error")
        return False
    except Exception as recovery_error:
        print_with_rich(f"\n⚠️ Error in recovery handler: {recovery_error}", "warning")
        return False

def safe_execute(func, *args, context: str = "", max_retries: int = 2, **kwargs):
    """Safely execute a function with automatic error handling and retry logic.
    
    Args:
        func: Function to execute
        *args: Positional arguments for the function
        context: Description of what the function does (for error reporting)
        max_retries: Maximum number of retry attempts
        **kwargs: Keyword arguments for the function
    
    Returns:
        The result of the function, or None if all attempts fail
    """
    attempts = 0
    
    while attempts <= max_retries:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            attempts += 1
            import sys, traceback as _tb
            tb_str = _tb.format_exc()
            code_frame = build_code_frame_from_exc(sys.exc_info())
            
            if attempts > max_retries:
                print_with_rich(f"❌ Max retry attempts ({max_retries}) exceeded", "error")
                handle_error_with_recovery(e, context, show_suggestion=True, traceback_str=tb_str, code_frame=code_frame)
                return None
            
            print_with_rich(f"⚠️ Attempt {attempts} failed: {str(e)}", "warning")
            
            # For first few attempts, auto-retry with short delay
            if attempts < max_retries:
                import time
                print_with_rich(f"⏳ Auto-retrying in 1 second... (Attempt {attempts + 1}/{max_retries + 1})", "info")
                time.sleep(1)
            else:
                # Last attempt - ask user what to do
                should_retry = handle_error_with_recovery(e, context, traceback_str=tb_str, code_frame=code_frame)
                if not should_retry:
                    return None
    
    return None

def print_with_rich(text: str, style: str = "default"):
    """Print text using rich if available, fallback to plain text.
    If the text already contains ANSI escape sequences, print directly to preserve colors.
    """
    try:
        # Detect ANSI sequences and bypass Rich to preserve coloring
        if isinstance(text, str) and "\033[" in text:
            print(text)
            return
        if RICH_AVAILABLE and console:
            if style == "error":
                console.print(text, style="bold red")
            elif style == "success":
                console.print(text, style="bold green")
            elif style == "warning":
                console.print(text, style="bold yellow")
            elif style == "info":
                console.print(text, style="bold blue")
            else:
                console.print(text)
        else:
            print(text)
    except Exception:
        # Fallback to basic print if rich fails
        print(text)

def typewriter_print(text: str, style: str = "default", speed: float = 0.003, fast_mode: bool = False):
    """Print text with optimized typewriter effect - character by character.
    
    Args:
        text: Text to print
        style: Color style to use
        speed: Base delay between characters (default: 0.003 for fast output)
        fast_mode: If True, use even faster chunked printing for very long text
    """
    import sys
    import time
    
    if not text:
        return
    
    # For very long text (>500 chars), use chunked fast mode
    if len(text) > 500 or fast_mode:
        return typewriter_print_chunked(text, style, chunk_size=10, delay=0.015)
    
    # Determine color codes based on style
    color_codes = {
        "error": "\033[91m",      # Red
        "success": "\033[92m",    # Green  
        "warning": "\033[93m",    # Yellow
        "info": "\033[94m",       # Blue
        "ai": "\033[96m",         # Cyan for AI responses
        "default": "\033[0m"      # Default
    }
    
    reset_code = "\033[0m"
    color_code = color_codes.get(style, color_codes["default"])
    
    # Start with color code
    if style != "default":
        sys.stdout.write(color_code)
    
    # Optimized character printing with reduced delays
    for i, char in enumerate(text):
        sys.stdout.write(char)
        
        # Flush every few characters for better performance
        if i % 5 == 0 or char in '\n.,!?;:':
            sys.stdout.flush()
        
        # Much faster, optimized speed based on character type
        if char in '.,!?;:':
            time.sleep(speed * 8)  # Brief pause for punctuation (reduced from *3)
        elif char == ' ':
            time.sleep(speed * 3)  # Quick pause for spaces (reduced from *1.5)
        elif char == '\n':
            time.sleep(speed * 10)  # Pause for new lines (reduced from *2)
        else:
            time.sleep(speed)  # Very fast for letters/numbers
    
    # Final flush and reset
    sys.stdout.flush()
    if style != "default":
        sys.stdout.write(reset_code)
    sys.stdout.write('\n')
    sys.stdout.flush()

def typewriter_print_chunked(text: str, style: str = "default", chunk_size: int = 10, delay: float = 0.015):
    """Ultra-fast chunked typewriter effect for long text.
    
    Args:
        text: Text to print
        style: Color style
        chunk_size: Number of characters to print at once
        delay: Delay between chunks
    """
    import sys
    import time
    
    # Color codes
    color_codes = {
        "error": "\033[91m", "success": "\033[92m", "warning": "\033[93m",
        "info": "\033[94m", "ai": "\033[96m", "default": "\033[0m"
    }
    
    reset_code = "\033[0m"
    color_code = color_codes.get(style, color_codes["default"])
    
    # Start with color
    if style != "default":
        sys.stdout.write(color_code)
    
    # Print in chunks for much faster display
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        sys.stdout.write(chunk)
        sys.stdout.flush()
        
        # Very brief delay between chunks
        if '\n' in chunk or any(p in chunk for p in '.,!?;:'):
            time.sleep(delay * 2)  # Slightly longer for chunks with breaks/punctuation
        else:
            time.sleep(delay)
    
    # Reset and finish
    if style != "default":
        sys.stdout.write(reset_code)
    sys.stdout.write('\n')
    sys.stdout.flush()

def print_ai_response_with_code_blocks(text: str):
    """Print AI response with proper syntax highlighting for code blocks (clean, no borders)."""
    import re
    
    # Split text by code blocks
    parts = []
    current_pos = 0
    
    # Find all code blocks (``` or ````)
    pattern = r'````?([a-zA-Z]*)\n(.*?)````?'
    
    for match in re.finditer(pattern, text, re.DOTALL):
        # Add text before code block
        if match.start() > current_pos:
            text_part = text[current_pos:match.start()]
            parts.append(('text', text_part))
        
        # Add code block
        lang = match.group(1) if match.group(1) else 'bash'
        code = match.group(2).strip()
        parts.append(('code', lang, code))
        
        current_pos = match.end()
    
    # Add remaining text
    if current_pos < len(text):
        parts.append(('text', text[current_pos:]))
    
    # Print each part
    for part in parts:
        if part[0] == 'text':
            # Format and print text with streaming effect
            formatted = format_text_only(part[1])
            if formatted.strip():
                # Use typewriter for text parts
                typewriter_print(formatted, "ai", speed=0.002, fast_mode=len(formatted) > 500)
        elif part[0] == 'code':
            # Print code with clean syntax highlighting - ABSOLUTELY NO BORDERS!
            lang = part[1]
            code = part[2]
            
            print()  # Blank line before code
            
            # ONLY use Pygments - NO Rich at all!
            pygments_success = False
            try:
                from pygments import highlight
                from pygments.lexers import get_lexer_by_name, guess_lexer
                from pygments.formatters import Terminal256Formatter
                from pygments.util import ClassNotFound
                
                try:
                    # Try to get lexer by language name
                    lexer = get_lexer_by_name(lang.lower(), stripall=True)
                except ClassNotFound:
                    # Fallback: guess lexer from code
                    try:
                        lexer = guess_lexer(code)
                    except:
                        # If all fails, use text
                        from pygments.lexers import TextLexer
                        lexer = TextLexer()
                
                # Use Terminal256Formatter for clean, border-free output
                formatter = Terminal256Formatter(style='monokai')
                highlighted = highlight(code, lexer, formatter)
                print(highlighted, end='')
                pygments_success = True
                
            except:
                pass  # Will fall through to manual coloring
            
            # If Pygments failed, use simple manual coloring (NO RICH!)
            if not pygments_success:
                lines = code.split('\n')
                for line in lines:
                    # Very basic coloring for keywords
                    colored_line = line
                    # Python/common keywords
                    keywords = ['def', 'class', 'import', 'from', 'if', 'else', 'elif', 'for', 'while', 'try', 'except', 'return', 'with', 'as']
                    for kw in keywords:
                        colored_line = colored_line.replace(f' {kw} ', f' \033[95m{kw}\033[0m ')
                        if colored_line.startswith(f'{kw} '):
                            colored_line = f'\033[95m{kw}\033[0m' + colored_line[len(kw):]
                    
                    # Strings in quotes
                    import re
                    colored_line = re.sub(r'"([^"]*)"', r'\033[93m"\1"\033[0m', colored_line)
                    colored_line = re.sub(r"'([^']*)'", r"\033[93m'\1'\033[0m", colored_line)
                    
                    # Comments
                    if '#' in colored_line:
                        parts = colored_line.split('#', 1)
                        if len(parts) == 2:
                            colored_line = parts[0] + '\033[90m#' + parts[1] + '\033[0m'
                    
                    print(colored_line)
            
            print()  # Blank line after code

def format_text_only(text: str) -> str:
    """Format text without code blocks (headers, bold, lists, etc.)."""
    import re
    
    lines = text.split('\n')
    formatted_lines = []
    
    for line in lines:
        # Skip separator lines
        stripped = line.strip()
        if len(stripped) >= 3:
            separator_chars = sum(1 for c in stripped if c in '=-_*+#~^')
            if separator_chars / len(stripped) > 0.8:
                continue
        
        # Convert headers
        header_match = re.match(r'^(#{1,6})\s+(.*)', line)
        if header_match:
            header_text = header_match.group(2)
            header_text = re.sub(r'\*\*(.+?)\*\*', r'\1', header_text)
            formatted_lines.append(f"\033[1;33m{header_text}\033[0m")
            continue
        
        # Convert list items
        if re.match(r'^\s*[-+]\s+', line):
            content = re.sub(r'^\s*[-+]\s+', '', line)
            content = re.sub(r'\*\*(.+?)\*\*', r'\033[1;32m\1\033[0m', content)
            formatted_lines.append(f"  • {content}")
            continue
        
        # Handle ** bold ** - remove markers and highlight
        while '**' in line:
            line = re.sub(r'\*\*([^*]+?)\*\*', r'\033[1;32m\1\033[0m', line, count=1)
            if line.count('**') < 2:
                line = line.replace('**', '')
                break
        
        # Handle inline code
        if '`' in line:
            line = re.sub(r'`([^`]+)`', r'\033[33m\1\033[0m', line)
        
        # Remove markdown links
        line = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', line)
        
        formatted_lines.append(line)
    
    return '\n'.join(formatted_lines)

def print_ai_response(text: str, use_typewriter: bool = True):
    """Print AI response with optimized typewriter effect and clean formatting."""
    # Don't use typewriter for responses with code blocks - they need Rich rendering
    has_code_blocks = '```' in text
    
    if has_code_blocks:
        # Use special handler for responses with code blocks
        print_with_rich("🤖 VritraAI:", "info")
        print_ai_response_with_code_blocks(text)
    else:
        # Format the response for terminal output
        formatted_text = format_ai_response_for_terminal(text)
        
        if use_typewriter and len(formatted_text) > 20:
            print_with_rich("🤖 VritraAI:", "info")
            
            # Use fast mode for very long responses (>800 characters)
            fast_mode = len(formatted_text) > 800
            
            # Ultra-fast speed with automatic fast mode for long text
            typewriter_print(formatted_text, "ai", speed=0.002, fast_mode=fast_mode)
        else:
            # Instant printing for very short responses
            print_with_rich(f"🤖 VritraAI: {formatted_text}", "info")

def show_ai_thinking():
    """Show enhanced professional AI thinking indicator with multi-stage animation."""
    import threading
    import time
    import sys
    import random
    import os
    
    # -------- UNIVERSAL TTY OPEN (from new.py) --------
    def open_tty():
        if os.name == "posix":   # Linux / Termux / macOS
            try:
                return open("/dev/tty", "w", buffering=1)
            except:
                return sys.stdout
        elif os.name == "nt":    # Windows
            try:
                return open("CONOUT$", "w", buffering=1)
            except:
                return sys.stdout
        return sys.stdout
    
    def get_width():
        try:
            return os.get_terminal_size().columns
        except:
            return 80
    
    tty = open_tty()   # universal TTY
    
    thinking_active = threading.Event()
    thinking_active.set()
    
    def animate():
        # Multiple professional spinner sets for variety
        spinner_sets = {
            'dots': ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'],
            'bars': ['▏', '▎', '▍', '▌', '▋', '▊', '▉', '█'],
            'circles': ['◜', '◝', '◞', '◟'],
            'arrows': ['←', '↖', '↑', '↗', '→', '↘', '↓', '↙']
        }
        
        # Enhanced professional status messages with stages
        message_stages = {
            'analysis': [
                "Analyzing your request",
                "Understanding context",
                "Processing input data",
                "Evaluating requirements"
            ],
            'thinking': [
                "Generating intelligent response",
                "Synthesizing information",
                "Applying knowledge base",
                "Reasoning through solution"
            ],
            'finalizing': [
                "Optimizing response quality",
                "Formatting output",
                "Performing final checks",
                "Preparing delivery"
            ]
        }
        
        frame_idx = 0
        stage_idx = 0
        message_idx = 0
        message_counter = 0
        current_spinner_set = 'dots'
        stage_names = list(message_stages.keys())
        
        # Color codes for different stages
        stage_colors = {
            'analysis': '\033[94m',    # Blue
            'thinking': '\033[96m',    # Cyan  
            'finalizing': '\033[92m'   # Green
        }
        
        while thinking_active.is_set():
            # Get current stage and messages
            current_stage = stage_names[stage_idx % len(stage_names)]
            current_messages = message_stages[current_stage]
            
            # Change message every 15 frames (1.5 seconds)
            if message_counter % 15 == 0:
                message_idx = (message_idx + 1) % len(current_messages)
                
                # Change stage every 60 frames (6 seconds) 
                if message_counter % 60 == 0 and message_counter > 0:
                    stage_idx = (stage_idx + 1) % len(stage_names)
                    # Change spinner style with stage
                    spinner_options = list(spinner_sets.keys())
                    current_spinner_set = spinner_options[stage_idx % len(spinner_options)]
            
            spinners = spinner_sets[current_spinner_set]
            spinner = spinners[frame_idx % len(spinners)]
            current_message = current_messages[message_idx]
            
            if RICH_AVAILABLE and console:
                from rich.text import Text
                
                # Build plain text version first to check width (using new.py's algorithm)
                stage_label = {
                    'analysis': '[🔍 Analyzing] ',
                    'thinking': '[🧠 Thinking] ',
                    'finalizing': '[🎆 Finalizing] '
                }
                plain_text = f"{spinner} VritraAI {stage_label.get(current_stage, '')}{current_message}..."
                width = get_width()
                
                # Truncate if text exceeds terminal width (new.py method)
                if len(plain_text) > width - 1:
                    # Calculate how much space we have for the message
                    prefix_len = len(f"{spinner} VritraAI {stage_label.get(current_stage, '')}")
                    max_msg_len = width - prefix_len - 4  # -4 for "..."
                    if max_msg_len > 0:
                        current_message = current_message[:max_msg_len] + "..."
                
                # Create sophisticated rich text with stage-based styling (after truncation)
                rich_text = Text()
                rich_text.append(spinner, style="bold bright_cyan")
                rich_text.append(" VritraAI ", style="bold bright_white")
                
                # Color-coded stage indicator
                if current_stage == 'analysis':
                    rich_text.append("[🔍 Analyzing] ", style="bold blue")
                elif current_stage == 'thinking':
                    rich_text.append("[🧠 Thinking] ", style="bold cyan")
                else:
                    rich_text.append("[🎆 Finalizing] ", style="bold green")
                
                rich_text.append(current_message, style="dim bright_white")
                if not current_message.endswith("..."):
                    rich_text.append("...", style="bold bright_cyan")
                
                # Use new.py's flush algorithm: clear entire line with \033[2K\r
                tty.write("\033[2K\r")
                # Write rich formatted text to console, then sync with TTY
                console.print(rich_text, end="")
                tty.flush()
            else:
                # Enhanced fallback for non-rich terminals with colors
                stage_color = stage_colors.get(current_stage, '\033[96m')
                reset_color = '\033[0m'
                
                # Stage indicator emojis for fallback
                stage_emoji = {
                    'analysis': '🔍',
                    'thinking': '🧠', 
                    'finalizing': '🎆'
                }
                
                emoji = stage_emoji.get(current_stage, '🤖')
                display_text = f"{stage_color}{spinner} VritraAI {emoji} {current_message}...{reset_color}"
                
                # Use new.py's flush algorithm: clear entire line and truncate if needed
                width = get_width()
                # Remove ANSI codes to get actual text length
                import re
                plain_text = re.sub(r'\033\[[0-9;]*m', '', display_text)
                if len(plain_text) > width - 1:
                    # Truncate text (new.py method)
                    plain_truncated = plain_text[:width - 4] + "..."
                    # Reconstruct with color codes
                    display_text = f"{stage_color}{plain_truncated}{reset_color}"
                
                # Clear entire line using new.py's method: \033[2K\r
                tty.write("\033[2K\r")
                tty.write(display_text)
                tty.flush()
            
            frame_idx += 1
            message_counter += 1
            
            # Variable speed based on stage for more organic feel
            if current_stage == 'analysis':
                time.sleep(0.12)  # Slightly slower for analysis
            elif current_stage == 'finalizing':
                time.sleep(0.08)  # Faster for finalizing
            else:
                time.sleep(0.1)   # Normal speed for thinking
    
    thread = threading.Thread(target=animate, daemon=True)
    thread.start()
    
    return thinking_active

def stop_ai_thinking(thinking_active):
    """Stop the AI thinking animation."""
    import sys
    import time
    
    if thinking_active:
        thinking_active.clear()
        # Give a moment for the thread to stop
        time.sleep(0.15)
        
        # Clear the line completely with more space to ensure full cleanup
        sys.stdout.write("\r" + " " * 120 + "\r")
        sys.stdout.flush()

def format_colorful_output(text: str) -> str:
    """Format text with colors for professional terminal output."""
    import re
    
    lines = text.split('\n')
    formatted_lines = []
    
    for line in lines:
        # Skip empty lines
        if not line.strip():
            formatted_lines.append(line)
            continue
        
        # Section headers (lines ending with :)
        if line.strip().endswith(':') and len(line.strip()) < 80:
            formatted_lines.append(f"\033[1;36m{line}\033[0m")  # Cyan bold
            continue
        
        # Numbered sections (1. 2. 3. etc.) or labeled sections
        if re.match(r'^\s*\d+\.\s+', line) or re.match(r'^\s*(What|Root|Solution|Additional|Tips|Warning|Note):', line):
            formatted_lines.append(f"\033[1;33m{line}\033[0m")  # Yellow bold
            continue
        
        # Bullet points (*, -, •)
        if re.match(r'^\s*[*\-•]\s+', line):
            formatted_lines.append(f"\033[32m{line}\033[0m")  # Green
            continue
        
        # Lines with commands (contain common command words)
        if re.search(r'\b(sudo|apt|yum|npm|pip|git|docker|cd|ls|cp|mv|rm|python|node|mkdir|touch|nano|vim|cat|grep|find|chmod)\b', line, re.IGNORECASE):
            formatted_lines.append(f"\033[96m{line}\033[0m")  # Light cyan
            continue
        
        # Error-related keywords
        if re.search(r'\b(error|failed|wrong|issue|problem|not found|cannot|unable)\b', line, re.IGNORECASE):
            formatted_lines.append(f"\033[91m{line}\033[0m")  # Light red
            continue
        
        # Success/solution keywords
        if re.search(r'\b(fix|solution|resolve|correct|success)\b', line, re.IGNORECASE):
            formatted_lines.append(f"\033[92m{line}\033[0m")  # Light green
            continue
        
        # Regular text
        formatted_lines.append(f"\033[97m{line}\033[0m")  # Bright white
    
    return '\n'.join(formatted_lines)

def clean_ai_response(text: str) -> str:
    """Clean AI response from markdown artifacts and formatting with enhanced terminal output."""
    if not text:
        return text
    
    import re
    
    # Remove markdown-style borders (lines of | or ─ characters)
    lines = text.split('\n')
    cleaned_lines = []
    
    for line in lines:
        stripped = line.strip()
        
        # Skip lines that are mostly border characters
        if stripped:
            border_chars = sum(1 for c in stripped if c in '│┌┐└┘├┤┬┴┼─━═║╔╗╚╝╠╣╦╩╬|+')
            if len(stripped) > 0 and border_chars / len(stripped) > 0.7:
                continue
        
        # Remove leading/trailing │ characters and extra spaces
        line = re.sub(r'^[│\|]\s*', '', line)
        line = re.sub(r'\s*[│\|]$', '', line)
        
        cleaned_lines.append(line)
    
    text = '\n'.join(cleaned_lines)
    
    # Clean up excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Remove **bold** markers for cleaner output
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    
    return text.strip()

def format_ai_response_for_terminal(text: str) -> str:
    """Format AI response for clean, professional terminal output.
    
    Converts markdown to terminal-friendly format:
    - Preserves code blocks with Rich syntax highlighting
    - Converts headers to bold text
    - Converts ** and ** to highlighted text  
    - Converts - and + at line start to bullet points
    - Removes excessive formatting
    """
    if not text:
        return text
    
    import re
    
    lines = text.split('\n')
    formatted_lines = []
    in_code_block = False
    code_block_lang = None
    code_block_lines = []
    
    for line in lines:
        # Detect code blocks (both ``` and ````)
        if re.match(r'^````?([a-zA-Z]*)', line):
            if in_code_block:
                # End of code block - render with Rich syntax highlighting
                if code_block_lines and RICH_AVAILABLE:
                    try:
                        from rich.syntax import Syntax
                        from rich.console import Console
                        
                        code_content = '\n'.join(code_block_lines)
                        # Detect language or use bash as default for commands
                        if not code_block_lang:
                            # Try to detect if it's a bash command
                            lang = 'bash' if any(line.strip() and not line.strip().startswith('#') for line in code_block_lines) else 'text'
                        else:
                            lang = code_block_lang
                        
                        # Create a temporary console to capture the syntax highlighted output
                        import io
                        import sys
                        
                        # Use a buffer with ANSI support
                        buffer = io.StringIO()
                        temp_console = Console(
                            file=buffer,
                            force_terminal=True,
                            width=120,
                            legacy_windows=False,
                            color_system='truecolor'
                        )
                        
                        syntax = Syntax(
                            code_content,
                            lang,
                            theme="monokai",
                            line_numbers=False,
                            word_wrap=False,
                            background_color="default"
                        )
                        temp_console.print(syntax)
                        
                        # Get the rendered output
                        rendered = buffer.getvalue()
                        if rendered.strip():
                            formatted_lines.append(rendered.rstrip())
                        else:
                            # If rendering failed, fall back
                            raise Exception("Empty render")
                    except Exception as e:
                        # Fallback to simple colored output if Rich fails
                        formatted_lines.append(f"\033[90m--- Code ({code_block_lang or 'text'}) ---\033[0m")
                        for code_line in code_block_lines:
                            formatted_lines.append(f"\033[36m{code_line}\033[0m")
                        formatted_lines.append(f"\033[90m--- End Code ---\033[0m")
                else:
                    # Fallback when Rich not available
                    formatted_lines.append(f"\033[90m--- Code ({code_block_lang or 'text'}) ---\033[0m")
                    for code_line in code_block_lines:
                        formatted_lines.append(f"\033[36m{code_line}\033[0m")
                    formatted_lines.append(f"\033[90m--- End Code ---\033[0m")
                
                code_block_lines = []
                in_code_block = False
                code_block_lang = None
            else:
                # Start of code block
                match = re.match(r'^````?([a-zA-Z]*)', line)
                code_block_lang = match.group(1) if match else None
                in_code_block = True
            continue
        
        # If inside code block, preserve line exactly
        if in_code_block:
            code_block_lines.append(line)
            continue
        
        # Skip separator lines
        stripped = line.strip()
        if len(stripped) >= 3:
            separator_chars = sum(1 for c in stripped if c in '=-_*+#~^')
            if separator_chars / len(stripped) > 0.8:
                continue
        
        # Convert headers (###, ##, #) to bold highlighted text
        # First clean any ** markers in the header
        header_match = re.match(r'^(#{1,6})\s+(.*)', line)
        if header_match:
            header_level = len(header_match.group(1))
            header_text = header_match.group(2)
            # Remove ** markers from headers
            header_text = re.sub(r'\*\*(.+?)\*\*', r'\1', header_text)
            # Bold yellow for headers
            formatted_lines.append(f"\033[1;33m{header_text}\033[0m")
            continue
        
        # Convert list items (- or +) at start of line to bullet points
        if re.match(r'^\s*[-+]\s+', line):
            content = re.sub(r'^\s*[-+]\s+', '', line)
            # Also remove ** from list items
            content = re.sub(r'\*\*(.+?)\*\*', r'\033[1;32m\1\033[0m', content)
            formatted_lines.append(f"  • {content}")
            continue
        
        # Handle ** bold ** formatting - highlight these words AND remove markers
        # Use a more aggressive pattern to catch all **text** instances
        while '**' in line:
            # Replace **text** with highlighted text (no ** markers shown)
            line = re.sub(r'\*\*([^*]+?)\*\*', r'\033[1;32m\1\033[0m', line, count=1)
            # Break if no more ** pairs found
            if line.count('**') < 2:
                # Remove any remaining single ** markers
                line = line.replace('**', '')
                break
        
        # Handle inline code with backticks - show with different color
        if '`' in line:
            line = re.sub(r'`([^`]+)`', r'\033[33m\1\033[0m', line)
        
        # Remove markdown links but keep the text
        line = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', line)
        
        formatted_lines.append(line)
    
    # Handle unclosed code block
    if in_code_block and code_block_lines:
        if RICH_AVAILABLE:
            try:
                from rich.syntax import Syntax
                from rich.console import Console
                import io
                
                code_content = '\n'.join(code_block_lines)
                # Detect language or use bash as default for commands
                if not code_block_lang:
                    lang = 'bash' if any(line.strip() and not line.strip().startswith('#') for line in code_block_lines) else 'text'
                else:
                    lang = code_block_lang
                
                buffer = io.StringIO()
                temp_console = Console(
                    file=buffer,
                    force_terminal=True,
                    width=120,
                    legacy_windows=False,
                    color_system='truecolor'
                )
                
                syntax = Syntax(
                    code_content,
                    lang,
                    theme="monokai",
                    line_numbers=False,
                    word_wrap=False,
                    background_color="default"
                )
                temp_console.print(syntax)
                
                rendered = buffer.getvalue()
                if rendered.strip():
                    formatted_lines.append(rendered.rstrip())
                else:
                    raise Exception("Empty render")
            except Exception:
                formatted_lines.append(f"\033[90m--- Code ({code_block_lang or 'text'}) ---\033[0m")
                for code_line in code_block_lines:
                    formatted_lines.append(f"\033[36m{code_line}\033[0m")
                formatted_lines.append(f"\033[90m--- End Code ---\033[0m")
        else:
            formatted_lines.append(f"\033[90m--- Code ({code_block_lang or 'text'}) ---\033[0m")
            for code_line in code_block_lines:
                formatted_lines.append(f"\033[36m{code_line}\033[0m")
            formatted_lines.append(f"\033[90m--- End Code ---\033[0m")
    
    result = '\n'.join(formatted_lines)
    
    # Clean up excessive newlines
    result = re.sub(r'\n{3,}', '\n\n', result)
    
    return result.strip()

# --- Style ---
def get_style():
    """Returns the style for the prompt and output based on current theme."""
    return Style.from_dict(THEMES[config_state.theme])

# --- AI Functions ---
def get_ai_response(prompt: str, context: Optional[str] = None) -> Optional[str]:
    """Gets a response from the AI with optional context."""
    if not AI_ENABLED:
        api_name = "Gemini" if API_BASE == "gemini" else "OpenRouter"
        print_with_rich(f"[AI Disabled] Please configure your {api_name} API key to use AI features.", "warning")
        return None
    
    # Check internet connectivity for AI operations
    max_network_retries = 2
    network_attempts = 0
    
    while network_attempts <= max_network_retries:
        is_connected, connection_message = check_internet_for_ai()
        
        if not is_connected:
            if network_attempts >= max_network_retries:
                print_with_rich(f"❌ {connection_message}", "error")
                should_retry = handle_network_error("AI Response Generation")
                if not should_retry:
                    return None
                network_attempts = 0  # Reset attempts if user chooses to retry
            else:
                network_attempts += 1
                print_with_rich(f"⚠️ Network issue (attempt {network_attempts}): {connection_message}", "warning")
                continue
        else:
            break

    # Build comprehensive context
    comprehensive_context = build_comprehensive_context(cwd=os.getcwd(), include_files=True)
    
    # Add user-provided context if available
    if context:
        full_context = f"{comprehensive_context}\n\n=== USER CONTEXT ===\n{context}"
    else:
        full_context = comprehensive_context
    
    enhanced_prompt = f"{full_context}\n\n=== USER REQUEST ===\n{prompt}"
    
    # Start animated thinking indicator
    thinking_active = show_ai_thinking()

    # Count a logical "AI interaction" whenever we issue a model call.
    # This is separate from command count so multi-call commands are
    # properly reflected in the session summary.
    if hasattr(session, 'ai_interactions'):
        session.ai_interactions += 1
    
    try:
        if API_BASE == "gemini":
            # Use Gemini API with proper headers to prevent hanging
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GEMINI_API_KEY}"
            payload = {
                "contents": [{
                    "parts": [{
                        "text": f"You are VritraAI, an intelligent terminal assistant. Provide helpful, accurate, and safe responses. When suggesting commands, always consider the user's OS and current context.\n\n{enhanced_prompt}"
                    }]
                }]
            }
            # Critical: Use proper headers and settings to prevent chunked transfer hang
            response = requests.post(
                gemini_url,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Connection": "close"  # Force early TCP close to avoid hang
                },
                data=json.dumps(payload),  # Serialize manually instead of json parameter
                stream=False,  # Prevent chunk buffering issues
                timeout=(15, 220),  # (connect timeout, read timeout) - longer for code generation
                verify=True  # SSL verification
            )
            response.raise_for_status()
            data = response.json()
            result = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        else:
            # Use OpenRouter API with timeout
            response = openai.ChatCompletion.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": "You are VritraAI, an intelligent terminal assistant. Provide helpful, accurate, and safe responses. When suggesting commands, always consider the user's OS and current context."},
                    {"role": "user", "content": enhanced_prompt}
                ],
                headers={
                    "HTTP-Referer": "http://localhost",
                    "X-Title": "VritraAI"
                },
                request_timeout=220
            )
            result = response.choices[0].message.content.strip()
        
        # Stop thinking animation
        stop_ai_thinking(thinking_active)
        
        return result
    except KeyboardInterrupt:
        # Stop thinking animation on Ctrl+C
        stop_ai_thinking(thinking_active)
        print_with_rich("\n⚠️  AI request cancelled by user", "warning")
        raise  # Re-raise to be handled by signal handler
    except requests.exceptions.Timeout:
        # Stop thinking animation on timeout
        stop_ai_thinking(thinking_active)
        print_with_rich("\n⏱️  AI request timed out after 2 minutes", "error")
        print_with_rich("💡 This could be due to:", "info")
        print_with_rich("   • Slow network connection", "default")
        print_with_rich("   • API service being overloaded", "default")
        print_with_rich("   • Extremely large or complex request", "default")
        print_with_rich("\n🔄 Please try again or check your internet connection", "warning")
        log_session(f"AI Timeout Error")
        return None
    except Exception as e:
        # Stop thinking animation on error
        stop_ai_thinking(thinking_active)
        
        # Check if it's a network-related error
        error_str = str(e).lower()
        if any(net_error in error_str for net_error in ['network', 'connection', 'timeout', 'dns', 'unreachable', 'refused']):
            print_with_rich(f"🌐 Network Error: {e}", "error")
            should_retry = handle_network_error("AI API Request")
            if should_retry:
                return get_ai_response(prompt, context)  # Recursive retry
        else:
            print_with_rich(f"❌ AI API Error: {e}", "error")
            
            # Offer recovery options for API errors
            if "api key" in error_str or "unauthorized" in error_str:
                print_with_rich("🔑 This looks like an API key issue. Use 'apikey set <your-key>' to configure.", "warning")
            elif "rate limit" in error_str or "quota" in error_str:
                print_with_rich("⏳ Rate limit exceeded. Please wait a moment before trying again.", "warning")
            elif "model" in error_str and "not found" in error_str:
                print_with_rich("🤖 Model not available. Use 'config model' to see available models.", "warning")
        
        log_session(f"AI Error: {e}")
        return None

def extract_fix_commands_improved(text: str) -> List[str]:
    """Extract actual commands from AI suggestion text (improved version)."""
    import re
    
    commands = []
    lines = text.split('\n')
    
    # Look for command patterns
    for line in lines:
        line = line.strip()
        
        # Skip empty lines and section headers
        if not line or line.endswith(':'):
            continue
        
        # Look for actual shell commands
        # Commands typically start with common command names
        command_starters = r'^(ls|cd|python|python3|pip|npm|git|docker|mkdir|touch|nano|vim|cat|grep|find|chmod|chown|sudo|apt|yum|dnf|brew|make|rm|cp|mv)\b'
        
        if re.match(command_starters, line, re.IGNORECASE):
            # Clean up the command
            cmd = line.strip()
            # Remove any leading/trailing quotes or punctuation
            cmd = cmd.strip('"\'.,;')
            if cmd and len(cmd) > 2:
                commands.append(cmd)
        
        # Also look for commands after common indicators
        indicators = ['run:', 'execute:', 'use:', 'try:']
        for indicator in indicators:
            if indicator in line.lower():
                # Extract text after the indicator
                parts = line.lower().split(indicator)
                if len(parts) > 1:
                    cmd = parts[1].strip()
                    cmd = cmd.strip('"\'.,;')
                    if cmd and len(cmd) > 2:
                        commands.append(cmd)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_commands = []
    for cmd in commands:
        if cmd not in seen:
            seen.add(cmd)
            unique_commands.append(cmd)
    
    return unique_commands[:5]  # Limit to 5 commands

def extract_fix_commands(text: str) -> List[str]:
    """Extract potential fix commands from AI suggestion text."""
    import re
    
    commands = []
    
    # Pattern to match various command formats
    patterns = [
        r'(?:run|execute|try)\s*:?\s*([^\n]+)',
        r'(?:command|cmd)\s*:?\s*([^\n]+)',
        r'(?:fix|solution)\s*:?\s*([^\n]+)',
        r'(?:install|update|upgrade)\s+[^\s]+(?:\s+[^\n]+)?',
        r'(?:pip|npm|apt|brew|choco)\s+install\s+[^\n]+',
        r'(?:sudo\s+)?(?:apt|yum|dnf)\s+[^\n]+',
        r'(?:python|node|java|go)\s+[^\n]+\.(?:py|js|java|go)',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            cmd = match.strip()
            if cmd and len(cmd) > 3 and cmd not in commands:
                commands.append(cmd)
    
    # Clean up commands
    cleaned_commands = []
    for cmd in commands:
        # Remove quotes and clean up
        cmd = cmd.strip('"\'`')
        # Skip if too generic
        if len(cmd) > 5 and not any(skip in cmd.lower() for skip in ['example', 'your_', '<', '>', 'replace']):
            cleaned_commands.append(cmd)
    
    return cleaned_commands[:3]  # Limit to 3 commands

def categorize_error(error_message: str) -> tuple:
    """Categorize error type and return (category, icon, color)."""
    error_lower = error_message.lower()
    
    if any(keyword in error_lower for keyword in ['syntax error', 'syntaxerror', 'invalid syntax']):
        return ('Syntax Error', '🧱', 'red')
    elif any(keyword in error_lower for keyword in ['no such file', 'not found', 'cannot find', 'does not exist', 'filenotfounderror']):
        return ('File/Path Error', '🗂', 'yellow')
    elif any(keyword in error_lower for keyword in ['permission denied', 'access denied', 'permissionerror']):
        return ('Permission Error', '🔒', 'red')
    elif any(keyword in error_lower for keyword in ['network', 'connection', 'timeout', 'unreachable', 'dns']):
        return ('Network Error', '🌐', 'yellow')
    elif any(keyword in error_lower for keyword in ['modulenotfounderror', 'importerror', 'no module named']):
        return ('Dependency Error', '⚙️', 'yellow')
    elif any(keyword in error_lower for keyword in ['indentation', 'indentationerror']):
        return ('Indentation Error', '📏', 'red')
    elif any(keyword in error_lower for keyword in ['runtime', 'exception', 'error']):
        return ('Runtime Exception', '🧠', 'red')
    else:
        return ('General Error', '⚠️', 'yellow')

def find_similar_files(target_filename: str, max_distance: int = 3) -> list:
    """Find similar filenames in current directory using Levenshtein distance."""
    import os
    from difflib import SequenceMatcher
    
    similar_files = []
    target_lower = target_filename.lower()
    
    try:
        for filename in os.listdir('.'):
            if os.path.isfile(filename):
                # Calculate similarity
                similarity = SequenceMatcher(None, target_lower, filename.lower()).ratio()
                if similarity > 0.6 and filename.lower() != target_lower:
                    similar_files.append((filename, similarity))
        
        # Sort by similarity (highest first)
        similar_files.sort(key=lambda x: x[1], reverse=True)
        return [f[0] for f in similar_files[:3]]  # Return top 3 matches
    except Exception:
        return []

def check_recently_created_files(filename: str) -> str:
    """Check if user recently created or modified this file."""
    import time
    
    # Check session modified files
    if hasattr(session, 'modified_files'):
        for modified_file in session.modified_files:
            if filename in modified_file:
                return modified_file
    
    # Check recent commands for file creation
    if hasattr(session, 'commands_history'):
        for cmd_info in reversed(session.commands_history[-10:]):
            cmd = cmd_info.get('command', '')
            if filename in cmd and any(create_cmd in cmd for create_cmd in ['create_file', 'touch', 'nano', 'vim']):
                return f"Recently created via: {cmd}"
    
    return None

# suggest_fix function removed - use handle_error_with_recovery instead
            
def read_file_content(filepath: str) -> Optional[str]:
    """Read file content safely."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        try:
            with open(filepath, 'r', encoding='latin-1') as f:
                return f.read()
        except Exception as e:
            print_with_rich(f"Error reading file {filepath}: {e}", "error")
            return None
    except Exception as e:
        print_with_rich(f"Error reading file {filepath}: {e}", "error")
        return None

def write_file_content(filepath: str, content: str, create_backup: bool = True) -> bool:
    """Write content to file with optional backup."""
    try:
        if os.path.exists(filepath) and create_backup:
            backup_path = backup_file(filepath)
            if backup_path:
                session.modified_files.append(filepath)
                backup_filename = os.path.basename(backup_path)
                print_with_rich(f"📋 Backup created: {backup_filename}", "info")
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        log_session(f"File written: {filepath}")
        return True
    except Exception as e:
        print_with_rich(f"Error writing to file {filepath}: {e}", "error")
        return False

def search_in_file(filepath: str, pattern: str) -> List[Dict[str, Any]]:
    """Search for pattern in file and return matches with line numbers."""
    matches = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                if re.search(pattern, line, re.IGNORECASE):
                    matches.append({
                        'line_number': line_num,
                        'line_content': line.strip(),
                        'match': pattern
                    })
    except Exception as e:
        print_with_rich(f"Error searching in file {filepath}: {e}", "error")
    
    return matches

def summarize_directory() -> str:
    """Generate a summary of the current directory."""
    try:
        cwd = Path.cwd()
        files = list(cwd.glob('*'))
        
        summary = []
        summary.append(f"Directory: {cwd}")
        summary.append(f"Total items: {len(files)}")
        
        dirs = [f for f in files if f.is_dir()]
        regular_files = [f for f in files if f.is_file()]
        
        if dirs:
            summary.append(f"Directories ({len(dirs)}): {', '.join([d.name for d in dirs[:10]])}")
            if len(dirs) > 10:
                summary.append(f"... and {len(dirs) - 10} more directories")
        
        if regular_files:
            # Group by extension
            extensions = {}
            for f in regular_files:
                ext = f.suffix.lower() or 'no extension'
                extensions[ext] = extensions.get(ext, 0) + 1
            
            summary.append(f"Files ({len(regular_files)}):")
            for ext, count in sorted(extensions.items()):
                summary.append(f"  {ext}: {count} files")
        
        project_type = detect_project_type()
        if project_type:
            summary.append(f"Project type detected: {project_type}")
        
        return "\n".join(summary)
    except Exception as e:
        return f"Error summarizing directory: {e}"

# --- Command Handling ---
def is_command(command):
    """Checks if a command exists and is executable."""
    return shutil.which(command) is not None

def is_valid_command(command):
    """Checks if a command is valid (system command or built-in).
    
    Uses shutil.which() to check system commands (like check-cmd.py)
    and maintains a list of built-in commands.
    """
    if not command:
        return False
    
    # Extract first word if it's a complex command
    first_word = command.split()[0] if command.split() else command
    
    # List of shell built-in commands that won't be found by shutil.which
    shell_builtins = {
        'cd', 'exit', 'clear', 'help', 'pwd', 'echo', 'export', 'alias',
        'unalias', 'source', 'type', 'read', 'set', 'unset', 'shift',
        'test', '[', 'eval', 'exec', 'return', 'break', 'continue',
        'if', 'then', 'else', 'elif', 'fi', 'case', 'esac', 'for',
        'while', 'until', 'do', 'done', 'function'
    }
    
    # List of VritraAI built-in commands
    vritraai_builtins = {
        'ls', 'dir', 'create_file', 'create_dir', 'mkdir', 'read_file',
        'edit_file', 'search_file', 'summarize', 'ai', 'config',
        'model', 'project', 'apikey', 'api_base', 'review', 'optimize_code',
        'refactor', 'template', 'theme', 'prompt', 'explain', 'cheat',
        'security_scan', 'project_type', 'dependencies_check', 'project_health',
        'network', 'tool', 'learn', 'compare', 'diff', 'diff_dir', 'diff_semantic', 'hash', 'encode',
        'session', 'history',
        'decode', 'time', 'calc', 'generate', 'validate', 'format',
        'tree', 'find_files', 'sys_info', 'disk_usage', 'env', 'path',
        'which', 'uptime', 'memory', 'processes', 'analyze_system', 'optimize',
        # Smart search & navigation
        'search_regex', 'search_semantic', 'recent',
        # Documentation generator
        'doc'
    }
    
    # Check if it's a shell built-in
    if first_word in shell_builtins:
        return True
    
    # Check if it's a VritraAI built-in
    if first_word in vritraai_builtins:
        return True
    
    # Check if it's a system command (using shutil.which like check-cmd.py)
    if shutil.which(first_word) is not None:
        return True
    
    return False

class SmartCommandCompleter(Completer):
    """Context-aware, fuzzy, and predictive command completer for VritraAI."""

    def __init__(self, commands: List[str], alias_map: Dict[str, str]):
        self.commands = sorted(set(commands))
        self.alias_map = alias_map or {}
        self.path_completer = PathCompleter(expanduser=True)
        # Commands that primarily expect file or directory arguments
        self.file_arg_commands = {
            'cd', 'read_file', 'edit_file', 'create_file', 'create_dir', 'mkdir',
            'compare', 'diff', 'diff_dir', 'diff_semantic', 'hash',
            'validate', 'format', 'template', 'summarize', 'search_file',
            'project_type', 'dependencies_check', 'project_health',
        }
        # Simple command chaining / template suggestions for common workflows
        self.chaining_suggestions = {
            'git': ['status', 'diff', 'log', 'commit -m ""', 'push'],
            'ls': ['-la', '-la | grep '],
            'grep': ['-R "" .', '"pattern" *.py'],
            'python': ['-m unittest', 'script.py'],
        }

    def _ranked_commands(self) -> List[str]:
        """Return commands ranked by session frequency and name."""
        try:
            freq = getattr(session, 'frequent_commands', {}) or {}
        except Exception:
            freq = {}
        return sorted(
            self.commands,
            key=lambda c: (-freq.get(c, 0), c)
        )

    def _command_matches(self, prefix: str) -> List[str]:
        """Prefix + fuzzy matches for a given prefix."""
        import difflib

        prefix_lower = prefix.lower()
        ranked = self._ranked_commands()

        # First, prefix matches (case-insensitive)
        exact_matches = [
            cmd for cmd in ranked
            if cmd.lower().startswith(prefix_lower)
        ]

        # Then fuzzy matches using difflib
        fuzzy_candidates = difflib.get_close_matches(
            prefix_lower,
            [c.lower() for c in self.commands],
            n=8,
            cutoff=0.6,
        )
        fuzzy_lookup = {c.lower(): c for c in self.commands}
        for low in fuzzy_candidates:
            cmd = fuzzy_lookup.get(low)
            if cmd and cmd not in exact_matches:
                exact_matches.append(cmd)

        return exact_matches

    def get_completions(self, document, complete_event):  # type: ignore[override]
        text = document.text_before_cursor
        stripped = text.lstrip()
        words = stripped.split()

        # If nothing typed yet: suggest most frequent commands
        if not words:
            for cmd in self._ranked_commands()[:10]:
                yield Completion(cmd, start_position=0)
            return

        # Determine current token (word) before cursor
        current_word = document.get_word_before_cursor(WORD=True)
        current_word = current_word or ""
        base_cmd = words[0]

        # Completing the command name (first word)
        if len(words) == 1 and not text.endswith(' '):
            matches = self._command_matches(current_word)
            for cmd in matches[:15]:
                yield Completion(cmd, start_position=-len(current_word))
            return

        # If we're on arguments: provide context-aware argument suggestions
        # File / path arguments
        if base_cmd in self.file_arg_commands:
            for c in self.path_completer.get_completions(document, complete_event):
                yield c
            return

        # Simple chaining suggestions for common tools ("git status", "ls -la", etc.)
        if len(words) == 1 and text.endswith(' '):
            for suggestion in self.chaining_suggestions.get(base_cmd, []):
                # Only insert the second token/fragment, not the whole command again
                # e.g., user typed "git " → we offer "status", "diff", ...
                second_part = suggestion
                yield Completion(second_part, start_position=0)
            return

        # Fallback: no special handling, but still try file paths as a generic hint
        for c in self.path_completer.get_completions(document, complete_event):
            yield c


def get_completer():
    """Creates a completer for commands and file paths."""
    builtin_commands = [
        "exit", "clear", "help", "cd", "create_file", "create_dir", "mkdir", "explain", 
        "read_file", "edit_file", "search_file", "summarize", 
        "session", "config", "project", "feedback",
        "history", "ai", "ls", "dir", "apikey", "api_base",
        "network", "learn",
        "theme", "prompt", "banner",
        "safe_mode", "optimize", "analyze_system", "cheat", "tree", "find_files", "sys_info",
        "disk_usage", "env", "path", "which", "uptime", "memory", "processes",
        "compare", "diff", "diff_dir", "diff_semantic", "hash", "encode", "decode", "time", "calc",
        "generate", "template", "validate", "format",
        # Smart search & navigation
        "search_regex", "search_semantic", "recent",
        # Documentation generator
        "doc",
        # AI Code Review & Analysis Commands
        "review", "explain_last", "security_scan", "optimize_code", "refactor",
        # Intelligent Project Detection Commands
        "project_type", "dependencies_check", "project_health", "missing_files", "project_optimize",
        # Model management
        "model",
        # Special file operations (handled specially but still built-in)
        "cat", "grep"
    ]
    
    commands = builtin_commands.copy()
    
    # Add aliases
    commands.extend(ALIASES.keys())
    
    try:
        path_dirs = os.environ.get("PATH", "").split(os.pathsep)
        for path_dir in path_dirs:
            if os.path.isdir(path_dir):
                try:
                    commands.extend(os.listdir(path_dir))
                except (PermissionError, FileNotFoundError):
                    continue
    except Exception:
        pass

    try:
        commands.extend(os.listdir("."))
    except FileNotFoundError:
        pass

    return WordCompleter(list(set(commands)), ignore_case=True)

def colored_ls(args: List[str] = []):
    """Native-style ls implementation with colorful output and icons (no borders)."""
    import stat
    import shutil
    from pathlib import Path
    import io
    import sys
    
    # Capture output for logging
    output_capture = io.StringIO()
    original_stdout = sys.stdout
    
    # ANSI color codes for different file types (matching standard ls colors)
    COLORS = {
        'reset': '\033[0m',
        'dir': '\033[1;34m',          # Bold blue for directories
        'executable': '\033[1;32m',    # Bold green for executables
        'archive': '\033[1;31m',       # Bold red for archives
        'image': '\033[1;35m',         # Bold magenta for images
        'video': '\033[1;35m',         # Bold magenta for videos
        'audio': '\033[1;36m',         # Bold cyan for audio
        'code_python': '\033[1;33m',   # Bold yellow for Python
        'code_js': '\033[1;33m',       # Bold yellow for JavaScript
        'code_shell': '\033[1;32m',    # Bold green for shell scripts
        'code_c': '\033[1;36m',        # Bold cyan for C/C++
        'code_web': '\033[1;35m',      # Bold magenta for HTML/CSS
        'code_php': '\033[35m',        # Magenta for PHP
        'doc_text': '\033[37m',        # White for text files
        'doc_markdown': '\033[1;37m',  # Bold white for markdown
        'doc_log': '\033[33m',         # Yellow for log files
        'config': '\033[1;33m',        # Bold yellow for config files
        'database': '\033[1;36m',      # Bold cyan for database files
        'backup': '\033[2;37m',        # Dim white for backup files
        'default': '\033[0m',          # Default (white)
    }
    
    # Icons for different file types
    ICONS = {
        'dir': '📁',
        'executable': '⚙️',
        'archive': '📦',
        'image': '🖼️',
        'video': '🎬',
        'audio': '🎵',
        'code_python': '🐍',
        'code_js': '📜',
        'code_shell': '🔧',
        'code_c': '⚡',
        'code_web': '🌐',
        'code_php': '🐘',
        'doc_text': '📄',
        'doc_markdown': '📝',
        'doc_log': '📋',
        'config': '⚙️',
        'database': '🗄️',
        'backup': '💾',
        'default': '📄',
    }
    
    def get_file_info(item):
        """Get appropriate color and icon for a file based on its type."""
        if item.is_dir():
            return COLORS['dir'], ICONS['dir']
        
        name = item.name.lower()
        ext = item.suffix.lower()
        
        # Check for backup files first (files with backup in name or specific extensions)
        if 'backup' in name or ext in ['.bak', '.old', '.orig', '.swp', '.swo']:
            return COLORS['backup'], ICONS['backup']
        
        # Check if executable (files with execute permission)
        try:
            if item.stat().st_mode & stat.S_IXUSR:
                return COLORS['executable'], ICONS['executable']
        except:
            pass
        
        # Shell scripts (even without execute permission)
        if ext in ['.sh', '.bash', '.zsh', '.fish', '.ksh']:
            return COLORS['code_shell'], ICONS['code_shell']
        
        # Archives
        if ext in ['.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar', '.tgz', '.tar.gz', '.tar.bz2', '.tar.xz']:
            return COLORS['archive'], ICONS['archive']
        
        # Images
        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.ico', '.webp', '.tiff', '.tif']:
            return COLORS['image'], ICONS['image']
        
        # Videos
        if ext in ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg']:
            return COLORS['video'], ICONS['video']
        
        # Audio
        if ext in ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma', '.opus']:
            return COLORS['audio'], ICONS['audio']
        
        # Programming - Python
        if ext in ['.py', '.pyw', '.pyx', '.pyd', '.pyc', '.pyo']:
            return COLORS['code_python'], ICONS['code_python']
        
        # Programming - JavaScript/TypeScript/Node
        if ext in ['.js', '.mjs', '.jsx', '.ts', '.tsx', '.vue']:
            return COLORS['code_js'], ICONS['code_js']
        
        # Programming - C/C++
        if ext in ['.c', '.h', '.cpp', '.hpp', '.cc', '.cxx', '.c++', '.h++']:
            return COLORS['code_c'], ICONS['code_c']
        
        # Web files
        if ext in ['.html', '.htm', '.css', '.scss', '.sass', '.less']:
            return COLORS['code_web'], ICONS['code_web']
        
        # PHP
        if ext in ['.php', '.phtml', '.php3', '.php4', '.php5']:
            return COLORS['code_php'], ICONS['code_php']
        
        # Markdown files
        if ext in ['.md', '.markdown', '.mdown', '.mkd', '.rst']:
            return COLORS['doc_markdown'], ICONS['doc_markdown']
        
        # Log files
        if ext in ['.log'] or 'log' in name:
            return COLORS['doc_log'], ICONS['doc_log']
        
        # Text files
        if ext in ['.txt', '.text', '.readme']:
            return COLORS['doc_text'], ICONS['doc_text']
        
        # Config files
        if ext in ['.json', '.yaml', '.yml', '.toml', '.ini', '.conf', '.cfg', '.xml', '.env', '.config']:
            return COLORS['config'], ICONS['config']
        
        # Database
        if ext in ['.db', '.sqlite', '.sqlite3', '.sql', '.mdb']:
            return COLORS['database'], ICONS['database']
        
        # Other code files
        if ext in ['.java', '.go', '.rs', '.rb', '.pl', '.lua', '.r', '.swift', '.kt', '.scala', '.dart']:
            return COLORS['code_js'], ICONS['code_js']  # Use same color/icon as JS for other code
        
        return COLORS['default'], ICONS['default']
    
    # Parse arguments
    show_hidden = False
    show_details = False
    show_one_per_line = False
    target_dir = "."
    
    for arg in args:
        if arg.startswith('-'):
            if 'a' in arg:
                show_hidden = True
            if 'l' in arg:
                show_details = True
            if '1' in arg:
                show_one_per_line = True
        else:
            target_dir = arg
    
    # Expand ~ and environment variables in target_dir before processing
    target_dir = os.path.expanduser(target_dir)
    target_dir = os.path.expandvars(target_dir)
    
    try:
        # Support basic glob patterns (like * and ?) in the ls target, e.g. "ls *md"
        # This mimics the behavior of the system ls by expanding patterns before listing.
        if any(ch in target_dir for ch in "*?[]"):
            import glob as _glob

            matched_paths = [Path(p) for p in _glob.glob(target_dir)]
            if not matched_paths:
                # Integrate with smart error explanation & recovery instead of plain print
                error = FileNotFoundError(f"ls: cannot access '{target_dir}': No such file or directory")
                # Log error
                command_str = "ls " + " ".join(args) if args else "ls"
                if should_log_command(command_str):
                    log_last_command(command_str, f"ls: cannot access '{target_dir}': No such file or directory", 1)
                handle_error_with_recovery(
                    error,
                    context=f"Command: ls {target_dir}",
                    show_suggestion=True,
                    auto_mode=False,
                    traceback_str=None,
                    code_frame=None,
                )
                return

            items = matched_paths
            # Filter hidden files if not requested
            if not show_hidden:
                items = [item for item in items if not item.name.startswith('.')]
            # Sort: directories first, then files alphabetically
            items = sorted(items, key=lambda x: (not x.is_dir(), x.name.lower()))
        else:
            # Use already expanded target_dir
            path = Path(target_dir)
            
            if not path.exists():
                # Use smart error explanation & recovery for missing paths
                error = FileNotFoundError(f"ls: cannot access '{target_dir}': No such file or directory")
                # Log error
                command_str = "ls " + " ".join(args) if args else "ls"
                if should_log_command(command_str):
                    log_last_command(command_str, f"ls: cannot access '{target_dir}': No such file or directory", 1)
                handle_error_with_recovery(
                    error,
                    context=f"Command: ls {target_dir}",
                    show_suggestion=True,
                    auto_mode=False,
                    traceback_str=None,
                    code_frame=None,
                )
                return
            
            if path.is_file():
                # If it's a file, show just that file
                items = [path]
            else:
                # List directory contents
                try:
                    items = list(path.iterdir())
                    # Filter hidden files if not requested
                    if not show_hidden:
                        items = [item for item in items if not item.name.startswith('.')]
                    # Sort: directories first, then files alphabetically
                    items = sorted(items, key=lambda x: (not x.is_dir(), x.name.lower()))
                except PermissionError as e:
                    # Route permission errors through the smart error explanation & recovery flow
                    import sys, traceback as _tb
                    tb_str = _tb.format_exc()
                    code_frame = build_code_frame_from_exc(sys.exc_info())
                    error = PermissionError(f"ls: cannot open directory '{target_dir}': Permission denied")
                    # Log error
                    command_str = "ls " + " ".join(args) if args else "ls"
                    if should_log_command(command_str):
                        log_last_command(command_str, f"ls: cannot open directory '{target_dir}': Permission denied", 1)
                    handle_error_with_recovery(
                        error,
                        context=f"Command: ls {target_dir}",
                        show_suggestion=True,
                        auto_mode=False,
                        traceback_str=tb_str,
                        code_frame=code_frame,
                    )
                    return
        
        if not items:
            # Log empty result
            command_str = "ls " + " ".join(args) if args else "ls"
            if should_log_command(command_str):
                log_last_command(command_str, "", 0)
            return
        
        # Display items
        if show_details:
            # Detailed listing (ls -l style)
            for item in items:
                try:
                    stat_info = item.stat()
                    
                    # Get permissions
                    mode = stat_info.st_mode
                    perms = stat.filemode(mode)
                    
                    # Get size
                    if item.is_dir():
                        size_str = "4096"
                    else:
                        size = stat_info.st_size
                        size_str = str(size)
                    
                    # Get time
                    import datetime
                    mtime = datetime.datetime.fromtimestamp(stat_info.st_mtime)
                    time_str = mtime.strftime("%b %d %H:%M")
                    
                    # Get color, icon and name
                    color, icon = get_file_info(item)
                    name = item.name
                    if item.is_dir():
                        name += '/'
                    
                    # Print line with icon
                    line = f"{perms} {size_str:>8} {time_str} {icon} {color}{name}{COLORS['reset']}"
                    print(line)
                    output_capture.write(line + '\n')
                    
                except (OSError, PermissionError):
                    line = f"?????????? ??????? ??? ?? ??:?? \033[91m{item.name}\033[0m"
                    print(line)
                    output_capture.write(line + '\n')
        
        elif show_one_per_line:
            # One item per line (ls -1 style)
            for item in items:
                color, icon = get_file_info(item)
                name = item.name
                if item.is_dir():
                    name += '/'
                line = f"{icon} {color}{name}{COLORS['reset']}"
                print(line)
                output_capture.write(line + '\n')
        
        else:
            # Column layout (default ls style)
            # Get terminal width
            try:
                term_width = shutil.get_terminal_size().columns
            except:
                term_width = 80
            
            # Calculate column width (find longest name + padding + icon)
            max_name_len = 0
            for item in items:
                name_len = len(item.name) + (1 if item.is_dir() else 0) + 3  # +1 for /, +3 for icon and space
                if name_len > max_name_len:
                    max_name_len = name_len
            
            col_width = max_name_len + 2  # Add spacing
            if col_width < 1:
                col_width = 1
            
            # Calculate number of columns
            num_cols = max(1, term_width // col_width)
            
            # Print items in columns
            col = 0
            line_parts = []
            for item in items:
                color, icon = get_file_info(item)
                name = item.name
                if item.is_dir():
                    name += '/'
                
                # Print with icon and proper spacing
                display_text = f"{icon} {name}"
                line = f"{color}{display_text:<{col_width}}{COLORS['reset']}"
                print(line, end='')
                line_parts.append(display_text)  # Plain text for logging
                
                col += 1
                if col >= num_cols:
                    print()  # New line
                    output_capture.write('  '.join(line_parts) + '\n')
                    line_parts = []
                    col = 0
            
            # Final newline if needed
            if col != 0:
                print()
                if line_parts:
                    output_capture.write('  '.join(line_parts) + '\n')
        
        # Log the ls command
        command_str = "ls " + " ".join(args) if args else "ls"
        if should_log_command(command_str):
            output_text = output_capture.getvalue()
            log_last_command(command_str, output_text, 0)
                    
    except Exception as e:
        error_msg = f"\033[91mError in ls: {e}\033[0m"
        print(error_msg)
        # Log error
        command_str = "ls " + " ".join(args) if args else "ls"
        if should_log_command(command_str):
            log_last_command(command_str, str(e), 1)

def execute_command(command: str):
    """Executes a shell command or sends it to the AI."""
    global current_process  # Declare global at function start
    
    if not command or not command.strip():
        return
    
    command = command.strip()
    original_command = command
    
    # Handle multi-command with && or ;
    # Extract the first command to check if it's valid
    if "&&" in command or ";" in command:
        # Get the first part before any separator
        import re
        first_part = re.split(r'[;&]', command)[0].strip()
        first_word = first_part.split()[0] if first_part.split() else ""

        if not is_valid_command(first_word):
            print_with_rich(f'⚠️ Unknown "{first_word}" command detected in multicommand.', "error")
            return

        # Check if multi-command pattern with valid first command
        if is_valid_command(first_word):
            # This is a multi-command sequence
            # Replace && with ; first, then split by ;
            normalized_command = command.replace('&&', ';')
            commands = [c.strip() for c in normalized_command.split(';')]
            
            # STRICT VALIDATION: Only allow system commands and whitelisted commands
            # Whitelist of VritraAI commands allowed in multi-command
            allowed_builtins = {
                # File operations
                'ls', 'dir', 'read_file', 'search_file', 'mkdir', 'create_dir',
                'find_files', 'compare', 'diff', 'hash', 'validate', 'format', 'tree',
                # System commands
                'cd', 'clear', 'exit', 'help', 'sys_info', 'disk_usage',
                'env', 'path', 'which', 'uptime', 'memory', 'processes',
                'time', 'calc', 'config', 'template', 'theme', 'prompt',
                'encode', 'decode', 'network', 'analyze_system',
                # API/Model management (not AI commands)
                'apikey', 'api_base', 'model'
            }
            
            # Check each command - first word must be system command or whitelisted
            for cmd_str in commands:
                cmd_word = cmd_str.split()[0] if cmd_str.split() else ""
                
                # Check if first word is system command or whitelisted
                is_system_command = shutil.which(cmd_word) is not None
                is_whitelisted = cmd_word in allowed_builtins
                
                # If first word is NOT system command or whitelisted, block it
                if not is_system_command and not is_whitelisted:
                    print_with_rich("⚠️  AI command detected. It should be run separately.", "error")
                    return
            
            # Execute all commands with labeled output
            for i, cmd in enumerate(commands):
                cmd = cmd.strip()
                if cmd:
                    # Print command label before execution
                    if len(commands) > 1:  # Only show labels for multiple commands
                        print_with_rich(f"\nOutput for: {cmd}", "info")
                    execute_command(cmd)  # Recursive call for each command
            return
    
    # Log the command
    log_session(f"Command: {command}")
    session.add_command(command)
    
    # Check if command contains pipe - if so, don't intercept with built-ins
    has_pipe = "|" in command
    
    # Handle aliases
    parts = command.split()
    cmd = parts[0]
    args = parts[1:]
    
    if cmd in ALIASES:
        command = ALIASES[cmd] + (" " + " ".join(args) if args else "")
        parts = command.split()
        cmd = parts[0]
        args = parts[1:]
        print_with_rich(f"Using alias: {original_command} -> {command}", "info")
    
    # Early validation for format command - check file extension before dangerous command check
    if cmd == "format" and args:
        filename = args[0]
        if os.path.exists(filename):
            file_ext = os.path.splitext(filename)[1].lower()
            if file_ext != '.py':
                print_with_rich(f"⚠️ This command only supports Python (.py) files!", "error")
                print_with_rich(f"You provided: {filename} ({file_ext})", "warning")
                print_with_rich("\nPlease use a Python file. Example: format script.py", "info")
                return
    
    # Safety check for dangerous commands (only if safe_mode is enabled)
    safe_mode = current_config.get('safe_mode', True) if current_config else True
    if safe_mode and is_dangerous_command(command):
        print_with_rich(f"⚠️  Warning: '{command}' is a potentially dangerous command!", "warning")
        if not confirm_action(f"Are you sure you want to execute: {command}?"):
            print_with_rich("Command cancelled for safety.", "info")
            return
    
    # Built-in commands
    if cmd == "exit":
        # Just raise EOFError - the main loop will handle the summary
        raise EOFError
    elif cmd == "clear":
        os.system("cls" if os.name == 'nt' else "clear")
    elif cmd == "help":
        print_help()
    elif cmd == "cd":
        change_directory(args)
    elif cmd == "create_file":
        create_file_command(args)
    elif cmd == "create_dir" or cmd == "mkdir":
        create_dir_command(args)
    elif cmd == "explain":
        explain_command(args)
    elif cmd == "read_file":
        read_file_command(args)
    elif cmd == "edit_file":
        edit_file_command(args)
    elif cmd == "search_file":
        _execute_and_log_builtin(command, lambda: search_file_command(args))
    elif cmd == "summarize":
        summarize_command(args)
    elif cmd == "config":
        config_command(args)
    elif cmd == "safe_mode":
        safe_mode_command(args)
    elif cmd == "model":
        model_command(args)
    elif cmd == "project":
        project_command(args)
    elif cmd == "ai":
        ai_command(" ".join(args) if args else "")
    elif (cmd == "ls" or cmd == "dir") and not has_pipe:
        # Only use built-in ls if no pipe is present
        colored_ls(args)
    elif cmd == "network":
        network_command(args)
    elif cmd == "learn":
        learn_command(args)
    elif cmd == "theme":
        theme_command(args)
    elif cmd == "prompt":
        prompt_command(args)
    elif cmd == "banner":
        banner_command(args)
    elif cmd == "optimize":
        optimize_command(args)
    elif cmd == "analyze_system":
        analyze_system_command(args)
    elif cmd == "cheat":
        cheat_command(args)
    elif cmd == "feedback":
        feedback_command(args)
    elif cmd == "session":
        session_command(args)
    elif cmd == "history":
        # Check if command has pipes
        if "|" in command:
            # Extract history part and pipe part
            parts = command.split("|", 1)
            history_part = parts[0].strip()
            pipe_part = parts[1].strip()
            
            # Parse history arguments
            history_args = history_part.split()[1:] if len(history_part.split()) > 1 else []
            
            # Execute history with pipe handling
            history_command_with_pipe(history_args, pipe_part)
        else:
            history_command(args)
    elif cmd == "tree":
        _execute_and_log_builtin(command, lambda: tree_command(args))
    elif cmd == "find_files":
        _execute_and_log_builtin(command, lambda: find_files_command(args))
    elif cmd == "sys_info":
        _execute_and_log_builtin(command, lambda: sys_info_command(args))
    elif cmd == "disk_usage":
        _execute_and_log_builtin(command, lambda: disk_usage_command(args))
    elif cmd == "env":
        _execute_and_log_builtin(command, lambda: env_command(args))
    elif cmd == "path":
        _execute_and_log_builtin(command, lambda: path_command(args))
    elif cmd == "which":
        _execute_and_log_builtin(command, lambda: which_command(args))
    elif cmd == "uptime":
        _execute_and_log_builtin(command, lambda: uptime_command(args))
    elif cmd == "memory":
        _execute_and_log_builtin(command, lambda: memory_command(args))
    elif cmd == "processes":
        _execute_and_log_builtin(command, lambda: processes_command(args))
    elif cmd == "compare":
        _execute_and_log_builtin(command, lambda: compare_command(args))
    elif cmd == "diff":
        _execute_and_log_builtin(command, lambda: diff_command(args))
    elif cmd == "diff_dir":
        _execute_and_log_builtin(command, lambda: diff_dir_command(args))
    elif cmd == "diff_semantic":
        _execute_and_log_builtin(command, lambda: diff_semantic_command(args))
    elif cmd == "search_regex":
        _execute_and_log_builtin(command, lambda: search_regex_command(args))
    elif cmd == "search_semantic":
        search_semantic_command(args)
    elif cmd == "recent":
        recent_command(args)
    elif cmd == "doc":
        doc_command(args)
    elif cmd == "hash":
        _execute_and_log_builtin(command, lambda: hash_command(args))
    elif cmd == "encode":
        _execute_and_log_builtin(command, lambda: encode_command(args))
    elif cmd == "decode":
        _execute_and_log_builtin(command, lambda: decode_command(args))
    elif cmd == "time":
        _execute_and_log_builtin(command, lambda: time_command(args))
    elif cmd == "calc":
        _execute_and_log_builtin(command, lambda: calc_command(args))
    elif cmd == "generate":
        generate_command(args)
    elif cmd == "template":
        _execute_and_log_builtin(command, lambda: template_command(args))
    elif cmd == "validate":
        _execute_and_log_builtin(command, lambda: validate_command(args))
    elif cmd == "format":
        _execute_and_log_builtin(command, lambda: format_command(args))
    elif cmd == "apikey":
        apikey_command(args)
    elif cmd == "api_base":
        api_base_command(args)
    # AI Code Review & Analysis Commands
    elif cmd == "review":
        review_command(args)
    elif cmd == "explain_last":
        explain_last_command(args)
    elif cmd == "security_scan":
        security_scan_command(args)
    elif cmd == "optimize_code":
        optimize_code_command(args)
    elif cmd == "refactor":
        refactor_command(args)
    # Intelligent Project Detection Commands
    elif cmd == "project_type":
        project_type_command(args)
    elif cmd == "dependencies_check":
        dependencies_check_command(args)
    elif cmd == "project_health":
        project_health_command(args)
    elif cmd == "missing_files":
        missing_files_command(args)
    elif cmd == "project_optimize":
        project_optimize_command(args)
    elif is_command(cmd):
        # Special handling for piped commands with grep
        if "|" in command and "grep" in command:
            handle_grep_command(command)
            return
        
        # Special handling for cat command - add syntax highlighting (no pipes)
        if cmd == "cat" and "|" not in command:
            handle_cat_command(args)
            return
        
        # Special handling for grep command - add highlighting (only if grep is the main command)
        if cmd == "grep":
            handle_grep_command(command)
            return
        
        # Execute system commands with smart interactive detection
        start_time = time.time()
        
        # Smart approach: Use simple subprocess.run() like testt.py for all commands
        # This ensures ALL interactive commands work properly without hardcoding
        try:
            # Check if command is interactive (can't capture output)
            is_likely_interactive = is_interactive_command(command)
            
            if is_likely_interactive:
                # For interactive commands, run without capture to allow interaction
                # Skip logging for interactive commands as we can't capture their output
                # Use simple subprocess.run() like testt.py - this works for all interactive commands
                result = subprocess.run(command, shell=True)
                execution_time = time.time() - start_time
            else:
                # For non-interactive commands, capture output for logging
                result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=None)
                
                # Combine stdout and stderr for logging
                full_output = ""
                if result.stdout:
                    full_output += result.stdout
                if result.stderr:
                    full_output += result.stderr
                
                # Log commands that should be logged (system commands or whitelisted built-ins)
                if should_log_command(command):
                    log_last_command(command, full_output, result.returncode)
                
                execution_time = time.time() - start_time
                
                # Display output
                if result.stdout:
                    print(result.stdout, end='')
                if result.stderr:
                    print_with_rich(result.stderr, "error")
            
            # Handle exit codes
            if result.returncode != 0:
                # For non-interactive errors, show exit code
                error_msg = f"Command exited with code {result.returncode}"
                
                # Combine stderr and stdout to check for "not found" patterns
                # The actual error message is usually in stderr
                error_text = ""
                if hasattr(result, 'stderr') and result.stderr:
                    error_text = result.stderr
                elif hasattr(result, 'stdout') and result.stdout:
                    error_text = result.stdout
                
                # Check if it's a "not found" type error in the actual error message
                # Also check exit code 127 which typically means "command not found"
                is_not_found = (
                    result.returncode == 127 or  # Standard "command not found" exit code
                    any(phrase in error_text.lower() for phrase in [
                        "no such file", "not found", "cannot find", "does not exist", 
                        "cannot access", "no existe", "cannot open", "command not found",
                        "no such file or directory"
                    ])
                )
                
                # Show error message (stderr already printed above, but show exit code too)
                if not is_not_found:
                    print_with_rich(error_msg, "warning")
                
                # Use the actual error text for logging and recovery
                actual_error_msg = error_text if error_text else error_msg
                session.add_command(command, error=actual_error_msg)
                
                # AI-powered error explanation for "not found" errors
                if AI_ENABLED and is_not_found:
                    error = FileNotFoundError(actual_error_msg)
                    # Use interactive error recovery with menu options
                    should_retry = handle_error_with_recovery(error, context=f"Command: {command}", show_suggestion=True, auto_mode=False)
                    if should_retry:
                        # Re-run the command once
                        execute_command(command)
                        return
            else:
                session.add_command(command, "Command completed successfully")
            
            # Show execution time for longer commands
            if execution_time > 1.0:
                print_with_rich(f"⏱️  Completed in {execution_time:.2f}s", "info")
                
        except FileNotFoundError as e:
            error_msg = f"Command not found: {cmd}"
            print_with_rich(error_msg, "error")
            # Log command failure if it should be logged
            if should_log_command(command):
                log_last_command(command, error_msg, 127)  # 127 is standard "command not found" exit code
            should_retry = False
            if AI_ENABLED:
                # Use interactive error recovery with menu options
                import traceback as _tb, sys as _sys
                tb_str = _tb.format_exc()
                code_frame = build_code_frame_from_exc(_sys.exc_info())
                should_retry = handle_error_with_recovery(e, context=f"Command: {command}", show_suggestion=True, auto_mode=False, traceback_str=tb_str, code_frame=code_frame)
            session.add_command(command, error=error_msg)
            if should_retry:
                execute_command(command)
                return
        except KeyboardInterrupt:
            print_with_rich("\nCommand interrupted by user", "info")
            # Log interrupted command if it should be logged
            if should_log_command(command):
                log_last_command(command, "Command interrupted by user", 130)  # 130 is SIGINT exit code
            session.add_command(command, error="Interrupted by user")
        except Exception as e:
            error_msg = f"An unexpected error occurred: {e}"
            print_with_rich(error_msg, "error")
            # Log command error if it should be logged
            if should_log_command(command):
                log_last_command(command, error_msg, 1)  # 1 is general error exit code
            import traceback as _tb, sys as _sys
            tb_str = _tb.format_exc()
            code_frame = build_code_frame_from_exc(_sys.exc_info())
            should_retry = False
            if AI_ENABLED:
                should_retry = handle_error_with_recovery(e, context=f"Command: {command}", show_suggestion=True, auto_mode=False, traceback_str=tb_str, code_frame=code_frame)
            session.add_command(command, error=error_msg)
            if should_retry:
                execute_command(command)
                return
    else:
        # Check if it's a complex command that might need AI interpretation
        if is_complex_command(command):
            # Send complex commands to AI for interpretation
            ai_command(command)
        elif shutil.which(cmd):
            # Try to execute as system command if it exists in PATH
            try:
                # Check if interactive - if so, run without capture
                if is_interactive_command(command):
                    # For interactive commands, skip logging
                    # Use simple subprocess.run() like testt.py - this works for all interactive commands
                    current_process = subprocess.Popen(command, shell=True)
                    current_process.wait()
                    current_process = None
                else:
                    # For non-interactive commands, capture output
                    current_process = subprocess.Popen(
                        command,
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    stdout, stderr = current_process.communicate()
                    exit_code = current_process.returncode
                    current_process = None  # Clear after completion
                    
                    # Combine output for logging
                    full_output = ""
                    if stdout:
                        full_output += stdout
                    if stderr:
                        full_output += stderr
                    
                    # Log commands that should be logged (system commands or whitelisted built-ins)
                    if should_log_command(command):
                        log_last_command(command, full_output, exit_code)
                    
                    if stdout:
                        print(stdout)
                    if stderr:
                        print_with_rich(stderr, "error")
                    
                    # Handle exit codes and check for "not found" errors
                    if exit_code != 0:
                        # Check if it's a "not found" type error
                        # Exit code 127 typically means "command not found"
                        error_text = stderr if stderr else stdout
                        is_not_found = (
                            exit_code == 127 or  # Standard "command not found" exit code
                            any(phrase in error_text.lower() for phrase in [
                                "no such file", "not found", "cannot find", "does not exist", 
                                "cannot access", "no existe", "cannot open", "command not found",
                                "no such file or directory"
                            ])
                        )
                        
                        # Use the actual error text for logging and recovery
                        actual_error_msg = error_text if error_text else f"Command exited with code {exit_code}"
                        session.add_command(command, error=actual_error_msg)
                        
                        # AI-powered error explanation for "not found" errors
                        if AI_ENABLED and is_not_found:
                            error = FileNotFoundError(actual_error_msg)
                            # Use interactive error recovery with menu options
                            should_retry = handle_error_with_recovery(error, context=f"Command: {command}", show_suggestion=True, auto_mode=False)
                            if should_retry:
                                # Re-run the command once
                                execute_command(command)
                                return
                    
            except Exception as e:
                error_msg = str(e)
                print_with_rich(f"Error executing command: {e}", "error")
                # Log error case if it should be logged
                if should_log_command(command):
                    log_last_command(command, error_msg, -1)
        else:
            # Send to AI if not a recognized command
            ai_command(command)

def handle_cat_command(args):
    """Handle cat command with syntax highlighting like read_file.

    Also integrates with the enhanced error explanation/recovery system
    when files are missing or inaccessible.
    """
    command = "cat " + " ".join(args) if args else "cat"
    
    if not args:
        # No arguments - read from stdin (interactive, can't capture)
        # Skip logging for interactive stdin reading
        result = subprocess.run(["cat"], shell=False)
        return
    
    # Parse arguments to find the filename and flags
    flags = [arg for arg in args if arg.startswith('-')]
    files = [arg for arg in args if not arg.startswith('-')]
    
    # If single file with or without flags, use syntax highlighting and error recovery
    if len(files) == 1:
        filepath = files[0]

        def cat_operation():
            if not os.path.exists(filepath):
                raise FileNotFoundError(f"File not found: {filepath}")
            if not os.path.isfile(filepath):
                raise IsADirectoryError(f"Not a regular file: {filepath}")
            return read_file_content(filepath) or ""

        # Use the same error recovery flow as read_file_command
        content = execute_with_error_recovery(cat_operation, context=f"Command: cat {filepath}")
        if content is None:
            # Log failed command attempt if it should be logged
            if should_log_command(command):
                log_last_command(command, f"File not found or error reading: {filepath}", 1)
            return
        
        if content:
            try:
                from pygments import highlight
                from pygments.lexers import guess_lexer_for_filename, TextLexer
                from pygments.formatters import Terminal256Formatter
                from pygments.util import ClassNotFound
                
                try:
                    lexer = guess_lexer_for_filename(filepath, content)
                except ClassNotFound:
                    lexer = TextLexer()
                
                # Apply syntax highlighting
                formatter = Terminal256Formatter(style='monokai')
                highlighted = highlight(content, lexer, formatter)
                
                # Handle flags manually
                lines = highlighted.split('\n')
                
                if '-n' in flags or '--number' in flags:
                    # Add line numbers
                    for i, line in enumerate(lines, 1):
                        print(f"{i:6}  {line}")
                elif '-b' in flags or '--number-nonblank' in flags:
                    # Add line numbers to non-blank lines
                    line_num = 1
                    for line in lines:
                        if line.strip():
                            print(f"{line_num:6}  {line}")
                            line_num += 1
                        else:
                            print(line)
                else:
                    # No flags or other flags - just print highlighted content
                    print(highlighted, end='')
                
                # Log successful cat command (not AI commands)
                if not is_ai_command(command):
                    log_last_command(command, content, 0)
                return
            except ImportError:
                # Fallback if pygments not available - just print content
                print(content, end='')
                # Log successful cat command if it should be logged
                if should_log_command(command):
                    log_last_command(command, content, 0)
                return
    
    # For multiple files or if we didn't handle it specially, use normal cat
    result = subprocess.run(["cat"] + args, shell=False, capture_output=True, text=True)
    # Log command if it should be logged
    if should_log_command(command):
        full_output = (result.stdout or "") + (result.stderr or "")
        log_last_command(command, full_output, result.returncode)
    # Display output
    if result.stdout:
        print(result.stdout, end='')
    if result.stderr:
        print_with_rich(result.stderr, "error")

def handle_grep_command(command):
    """Handle grep command with highlighted search terms."""
    try:
        # Execute grep and capture output
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        
        # Combine output for logging
        full_output = ""
        if result.stdout:
            full_output += result.stdout
        if result.stderr:
            full_output += result.stderr
        
        # Log grep commands if they should be logged
        if should_log_command(command):
            log_last_command(command, full_output, result.returncode)
        
        if result.stdout:
            # Extract grep pattern from command
            import re
            # Try multiple patterns to extract the search term
            pattern_match = re.search(r'grep\s+(?:-\w+\s+)*["\']([^"\']+)["\']', command)
            if not pattern_match:
                pattern_match = re.search(r'grep\s+(?:-\w+\s+)*([^\s|;>&]+)', command)
            
            if pattern_match:
                search_term = pattern_match.group(1)
                
                # Highlight the search term in output (case-insensitive if -i flag)
                is_case_insensitive = '-i' in command
                output_lines = result.stdout.split('\n')
                
                for line in output_lines:
                    if line:
                        # Highlight search term in red/bold
                        if is_case_insensitive:
                            # Case-insensitive replacement
                            import re
                            highlighted_line = re.sub(
                                f'({re.escape(search_term)})', 
                                r'\033[1;31m\1\033[0m', 
                                line, 
                                flags=re.IGNORECASE
                            )
                        else:
                            # Case-sensitive replacement
                            highlighted_line = line.replace(search_term, f"\033[1;31m{search_term}\033[0m")
                        print(highlighted_line)
            else:
                # If can't extract pattern, just print normal output
                print(result.stdout, end='')
        
        if result.stderr:
            print_with_rich(result.stderr, "error")
            
    except Exception as e:
        error_msg = str(e)
        print_with_rich(f"Error running grep: {e}", "error")
        # Log error case if it should be logged
        if should_log_command(command):
            log_last_command(command, error_msg, 1)

# explain_not_found_error function removed - use handle_error_with_recovery directly instead

def change_directory(args):
    """Changes the current working directory."""
    # cd with no args -> home
    if not args:
        target_path = os.path.expanduser("~")
        command_str = "cd ~"
        # Check permissions before attempting to change directory
        if not os.path.exists(target_path):
            import sys, traceback as _tb
            tb_str = _tb.format_exc()
            code_frame = build_code_frame_from_exc(sys.exc_info())
            e = FileNotFoundError(f"cd: no such file or directory: {target_path}")
            # Log error
            if should_log_command(command_str):
                log_last_command(command_str, f"cd: no such file or directory: {target_path}", 1)
            handle_error_with_recovery(e, context="Command: cd ~", show_suggestion=True, auto_mode=False, traceback_str=tb_str, code_frame=code_frame)
            return
        if not os.access(target_path, os.R_OK | os.X_OK):
            error_msg = f"cd: permission denied: {target_path}"
            print_with_rich(error_msg, "error")
            # Log error
            if should_log_command(command_str):
                log_last_command(command_str, error_msg, 1)
            return
        try:
            old_dir = os.getcwd()
            os.chdir(target_path)
            new_dir = os.getcwd()
            # Log success
            if should_log_command(command_str):
                log_last_command(command_str, f"Changed directory to: {new_dir}", 0)
        except PermissionError:
            error_msg = f"cd: permission denied: {target_path}"
            print_with_rich(error_msg, "error")
            # Log error
            if should_log_command(command_str):
                log_last_command(command_str, error_msg, 1)
        except Exception as e:
            import sys, traceback as _tb
            tb_str = _tb.format_exc()
            code_frame = build_code_frame_from_exc(sys.exc_info())
            # Log error
            if not is_ai_command(command_str):
                log_last_command(command_str, str(e), 1)
            handle_error_with_recovery(e, context="Command: cd ~", show_suggestion=True, auto_mode=False, traceback_str=tb_str, code_frame=code_frame)
        return

    raw_path = args[0]
    expanded_path = os.path.expanduser(raw_path)
    command_str = f"cd {raw_path}"
    
    # Check permissions before attempting to change directory (only for permission errors)
    # For file not found, let the original error handling work
    if os.path.exists(expanded_path):
        if not os.path.isdir(expanded_path):
            import sys, traceback as _tb
            tb_str = _tb.format_exc()
            code_frame = build_code_frame_from_exc(sys.exc_info())
            e = NotADirectoryError(f"cd: not a directory: {raw_path}")
            # Log error
            if not is_ai_command(command_str):
                log_last_command(command_str, f"cd: not a directory: {raw_path}", 1)
            handle_error_with_recovery(e, context=f"Command: cd {raw_path}", show_suggestion=True, auto_mode=False, traceback_str=tb_str, code_frame=code_frame)
            return
        
        if not os.access(expanded_path, os.R_OK | os.X_OK):
            error_msg = f"cd: permission denied: {raw_path}"
            print_with_rich(error_msg, "error")
            # Log error
            if should_log_command(command_str):
                log_last_command(command_str, error_msg, 1)
            return
    
    try:
        old_dir = os.getcwd()
        os.chdir(expanded_path)
        new_dir = os.getcwd()
        # Log success
        if not is_ai_command(command_str):
            log_last_command(command_str, f"Changed directory to: {new_dir}", 0)
    except PermissionError:
        error_msg = f"cd: permission denied: {raw_path}"
        print_with_rich(error_msg, "error")
        # Log error
        if not is_ai_command(command_str):
            log_last_command(command_str, error_msg, 1)
    except Exception as e:
        import sys, traceback as _tb
        tb_str = _tb.format_exc()
        code_frame = build_code_frame_from_exc(sys.exc_info())
        # Log error
        if not is_ai_command(command_str):
            log_last_command(command_str, str(e), 1)
        # Use the professional error recovery for file not found and other errors
        should_retry = handle_error_with_recovery(e, context=f"Command: cd {raw_path}", show_suggestion=True, auto_mode=False, traceback_str=tb_str, code_frame=code_frame)
        if should_retry:
            try:
                os.chdir(expanded_path)
                new_dir = os.getcwd()
                # Log success after retry
                if should_log_command(command_str):
                    log_last_command(command_str, f"Changed directory to: {new_dir}", 0)
                return
            except Exception as e2:
                # Do not loop further; show one more handler and exit
                tb_str2 = _tb.format_exc()
                code_frame2 = build_code_frame_from_exc(sys.exc_info())
                # Log error
                if should_log_command(command_str):
                    log_last_command(command_str, str(e2), 1)
                handle_error_with_recovery(e2, context=f"Retry: cd {raw_path}", show_suggestion=True, auto_mode=False, traceback_str=tb_str2, code_frame=code_frame2)

def print_help():
    """Prints comprehensive help message with colorful Rich formatting."""
    if not RICH_AVAILABLE or not console:
        # Fallback for systems without Rich
        print("VritraAI Shell - Type 'help' for commands")
        return
    
    # Header with gradient effect
    header = Text("🚀 VritraAI Shell", style="bold magenta")
    subheader = Text(f"Complete AI-Powered Terminal {VRITRA_VERSION}", style="green italic")
    tagline = Text("ALL FEATURES + NEW IMPROVEMENTS", style="yellow bold")
    
    console.print("\n")
    console.print(Panel.fit(Group(header, subheader, tagline), 
                          border_style="green", padding=(1, 2)))
    console.print("")
    
    # File Operations Section
    console.print(Text("📁 FILE OPERATIONS:", style="bold green"))
    file_commands = [
        ("ls [options] [path]", "Rich colored directory listing (-l, -a, -la)", "green"),
        ("dir [options] [path]", "Alias for ls command", "green"),
        ("read_file <filename>", "Read and display with syntax highlighting", "green"),
        ("cat <filename>", "Enhanced cat with syntax highlighting (no pipes)", "green"),
        ("grep <pattern> [file]", "Enhanced grep with highlighted search terms", "green"),
        ("edit_file <filename> <instruction>", "AI-powered file editing with diff preview", "green"),
        ("search_file <pattern> <target>", "Smart pattern matching in files/directories", "green"),
        ("create_file <filename> <prompt>", "Generate files using AI with backup", "green"),
        ("create_dir <dirname>", "Create directories", "green"),
        ("mkdir <dirname>", "Create directories (alias for create_dir)", "green"),
        ("tree [path] [max_depth]", "Display directory tree structure", "green"),
        ("find_files <pattern> [dir]", "Pattern-based file searching", "green"),
        ("compare <file1> <file2>", "File comparison with diff output", "green"),
        ("diff <file1> <file2>", "File differences (alias for compare)", "green"),
        ("diff_dir <dir1> <dir2>", "Directory tree diff & batch file comparison", "green"),
        ("diff_semantic <file1> <file2>", "AI-powered semantic code diff", "green"),
        ("hash <file> [algorithm]", "Calculate file hash (md5/sha1/sha256)", "green"),
        ("validate <file>", "File syntax validation (Python/JSON)", "green"),
        ("format <file>", "Code formatting (Python/JS/TS)", "green"),
    ]
    
    for cmd, desc, color in file_commands:
        text = Text()
        text.append(f"  {cmd:<35}", style=color)
        text.append(" - ", style="dim white")
        text.append(desc, style="dim white")
        console.print(text)
    console.print("")
    
    # Smart Search & Navigation Section
    console.print(Text("🔍 SMART SEARCH & NAVIGATION:", style="bold cyan"))
    search_commands = [
        ("search_regex <pattern> [path]", "Blazing-fast full-text regex search", "cyan"),
        ("search_semantic <query> [path]", "AI-powered semantic code search", "cyan"),
        ("recent [files|cmds]", "Show recent files and recent commands", "cyan"),
    ]

    for cmd, desc, color in search_commands:
        text = Text()
        text.append(f"  {cmd:<35}", style=color)
        text.append(" - ", style="dim white")
        text.append(desc, style="dim white")
        console.print(text)
    console.print("")

    # Dedicated AI Commands Section
    console.print(Text("🧪 DEDICATED AI COMMANDS:", style="bold magenta"))
    ai_commands = [
        ("ai <prompt>", "Natural language AI assistant", "magenta"),
        ("explain <command>", "Detailed command explanations", "magenta"),
        ("summarize [path]", "AI-powered directory/file analysis", "magenta"),
        ("project", "Show current project type and directory info", "magenta"),
        ("project analyze", "Deep project structure analysis", "magenta"),
        ("learn <topic>", "Interactive AI tutoring system", "magenta"),
        ("cheat <topic>", "Generate command cheatsheets", "magenta"),
        ("generate <description>", "AI content generation helper", "magenta"),
    ]

    for cmd, desc, color in ai_commands:
        text = Text()
        text.append(f"  {cmd:<35}", style=color)
        text.append(" - ", style="dim white")
        text.append(desc, style="dim white")
        console.print(text)
    console.print("")
    
    # AI Code Review & Analysis Section
    console.print(Text("📋 AI CODE REVIEW & ANALYSIS:", style="bold magenta"))
    review_commands = [
        ("review <file|directory> [--focus=<area>]", "Comprehensive code review with AI analysis", "magenta"),
        ("explain_last", "Explain last executed system command and its output", "magenta"),
        ("security_scan <file|directory>", "AI-powered security vulnerability scan", "magenta"),
        ("optimize_code <file>", "Get AI optimization suggestions for code", "magenta"),
        ("refactor <file> <description>", "AI-powered code refactoring suggestions", "magenta"),
    ]
    
    for cmd, desc, color in review_commands:
        text = Text()
        text.append(f"  {cmd:<35}", style=color)
        text.append(" - ", style="dim white")
        text.append(desc, style="dim white")
        console.print(text)
    console.print("")
    
    # Intelligent Project Detection Section
    console.print(Text("📂 INTELLIGENT PROJECT DETECTION:", style="bold green"))
    project_commands = [
        ("project_type [directory]", "Enhanced project type detection with AI", "green"),
        ("dependencies_check [directory]", "Check dependencies for security & updates", "green"),
        ("project_health [directory]", "Comprehensive project health analysis", "green"),
        ("missing_files [directory]", "AI suggests missing project files", "green"),
        ("project_optimize [directory]", "AI comprehensive project optimization", "green"),
    ]
    
    for cmd, desc, color in project_commands:
        text = Text()
        text.append(f"  {cmd:<35}", style=color)
        text.append(" - ", style="dim white")
        text.append(desc, style="dim white")
        console.print(text)
    console.print("")

    # Documentation Generator Section (explicit block as requested)
    console.print(Text("📚 DOCUMENTATION GENERATOR:", style="bold green"))
    doc_commands_short = [
        ("doc docstring <file>", "Suggest docstrings for functions/classes", "green"),
        ("doc readme", "Generate README.md for project/directory", "green"),
        ("doc readme <file>", "Generate README.md for a specific file", "green"),
        ("doc tutorial", "Create tutorial from this session's command history", "green"),
        ("doc diagram <file>", "Generate code architecture diagram (mermaid/plantuml/text)", "green"),
    ]

    for cmd, desc, color in doc_commands_short:
        text = Text()
        text.append(f"  {cmd:<35}", style=color)
        text.append(" - ", style="dim white")
        text.append(desc, style="dim white")
        console.print(text)
    console.print("")
    
    # API & Model Management Section
    console.print(Text("🔑 API & MODEL MANAGEMENT:", style="bold yellow"))
    api_commands = [
        ("api_base show", "Show current API base (OpenRouter/Gemini)", "yellow"),
        ("api_base openrouter", "Switch to OpenRouter API", "yellow"),
        ("api_base gemini", "Switch to Google Gemini API", "yellow"),
        ("api_base status", "Detailed API status report", "yellow"),
        ("apikey openrouter <key>", "Set OpenRouter API key (saves immediately, no hang!)", "yellow"),
        ("apikey gemini <key>", "Set Gemini API key (saves immediately, no hang!)", "yellow"),
        ("apikey show", "Show API key status (masked for all providers)", "yellow"),
        ("apikey clear <provider>", "Clear specific provider key (openrouter/gemini/all)", "yellow"),
        ("apikey test [provider]", "Test API key functionality", "yellow"),
    ]
    
    for cmd, desc, color in api_commands:
        text = Text()
        text.append(f"  {cmd:<35}", style=color)
        text.append(" - ", style="dim white")
        text.append(desc, style="dim white")
        console.print(text)
    console.print("")
    
    # AI Model Management Section
    console.print(Text("🤖 VritraAI MODEL MANAGEMENT:", style="bold yellow"))
    model_commands = [
        ("model", "List all available AI models by provider", "yellow"),
        ("model set <id>", "Switch model by ID (ds1, ll1, ms1, etc.) - FIXED: Saves permanently!", "yellow"),
        ("model search <term>", "Search models by provider/category/keyword", "yellow"),
        ("model current", "Show currently active model with full details", "yellow"),
        ("model list", "Detailed listing with categories and descriptions", "yellow"),
    ]
    
    for cmd, desc, color in model_commands:
        text = Text()
        text.append(f"  {cmd:<35}", style=color)
        text.append(" - ", style="dim white")
        text.append(desc, style="dim white")
        console.print(text)
    console.print("")
    
    # System Commands Section
    console.print(Text("⚙️ SYSTEM COMMANDS:", style="bold yellow"))
    system_commands = [
        ("cd <directory>", "Smart directory navigation", "yellow"),
        ("clear", "Clear screen", "yellow"),
        ("exit", "Exit with enhanced analytics summary", "yellow"),
        ("help", "Show this comprehensive help", "yellow"),
        ("safe_mode [on|off]", "Control safe mode (dangerous command protection)", "yellow"),
        ("sys_info", "Comprehensive system information", "yellow"),
        ("disk_usage [path]", "Human-readable disk usage stats", "yellow"),
        ("env [var] [value]", "Environment variable management", "yellow"),
        ("path [add <dir>]", "PATH environment variable tools", "yellow"),
        ("which <command>", "Command location finder", "yellow"),
        ("uptime", "System uptime and boot time", "yellow"),
        ("memory", "Memory usage statistics", "yellow"),
        ("processes", "Running process information", "yellow"),
        ("time", "Current time and date display", "yellow"),
        ("calc <expression>", "Safe mathematical calculator", "yellow"),
    ]
    
    for cmd, desc, color in system_commands:
        text = Text()
        text.append(f"  {cmd:<35}", style=color)
        text.append(" - ", style="dim white")
        text.append(desc, style="dim white")
        console.print(text)
    console.print("")
    
    # Network & System Section
    console.print(Text("🌐 NETWORK & SYSTEM:", style="bold green"))
    network_commands = [
        ("network [check|ip|ping|port|speed]", "Complete network diagnostics", "green"),
        ("analyze_system", "Detailed system performance analysis", "green"),
        ("optimize", "AI-powered system optimization", "green"),
    ]
    
    for cmd, desc, color in network_commands:
        text = Text()
        text.append(f"  {cmd:<35}", style=color)
        text.append(" - ", style="dim white")
        text.append(desc, style="dim white")
        console.print(text)
    console.print("")
    
    # Configuration & Templates Section
    console.print(Text("⚙️ CONFIGURATION & TEMPLATES:", style="bold green"))
    config_commands = [
        ("config", "Show current configuration - FIXED: Now read-only & simplified!", "green"),
        ("template <type> [filename]", "Create code templates (python/bash/html/readme)", "green"),
    ]
    
    for cmd, desc, color in config_commands:
        text = Text()
        text.append(f"  {cmd:<35}", style=color)
        text.append(" - ", style="dim white")
        text.append(desc, style="dim white")
        console.print(text)
    console.print("")
    
    # Customization Section
    console.print(Text("🎨 CUSTOMIZATION (37 THEMES!):", style="bold yellow"))
    custom_commands = [
        ("theme [name]", "Switch color themes - FIXED: Now saves permanently! (37 available)", "yellow"),
        ("theme reset", "Reset theme to default (matrix)", "yellow"),
        ("theme", "Show all themes organized by category (Basic, Tech, Colors, etc.)", "yellow"),
        ("prompt [style]", "Change prompt style (61+ creative styles available!)", "yellow"),
        ("prompt reset", "Reset prompt style to default (hacker)", "yellow"),
        ("banner [subcommand]", "Manage MOTD banners (list/set/random/reset/preview)", "yellow"),
    ]
    
    for cmd, desc, color in custom_commands:
        text = Text()
        text.append(f"  {cmd:<35}", style=color)
        text.append(" - ", style="dim white")
        text.append(desc, style="dim white")
        console.print(text)
    
    # Theme examples with colors
    console.print("    Popular themes: ", end="")
    themes = [("cyberpunk", "magenta"), ("galaxy", "green"), ("synthwave", "magenta"), 
              ("matrix", "green"), ("volcano", "yellow"), ("ocean", "green"), ("sunset", "yellow")]
    for i, (theme, color) in enumerate(themes):
        if i > 0:
            console.print(", ", end="")
        console.print(theme, style=color, end="")
    console.print("")
    
    console.print("    Popular prompts: ", end="")
    prompts = [("superhero", "yellow"), ("hacker", "green"), ("pirate", "yellow"), 
               ("ninja", "magenta"), ("alien", "green"), ("robot", "magenta")]
    for i, (prompt, color) in enumerate(prompts):
        if i > 0:
            console.print(", ", end="")
        console.print(prompt, style=color, end="")
    console.print("\n")
    
    # Session & History Section
    console.print(Text("📝 SESSION & HISTORY:", style="bold cyan"))
    session_commands = [
        ("session", "Show current session information and statistics", "cyan"),
        ("session save [filename]", "Save session data to JSON file", "cyan"),
        ("session clear", "Clear current session data", "cyan"),
        ("history [number]", "Show command history (all or last N commands)", "cyan"),
    ]
    
    for cmd, desc, color in session_commands:
        text = Text()
        text.append(f"  {cmd:<35}", style=color)
        text.append(" - ", style="dim white")
        text.append(desc, style="dim white")
        console.print(text)
    console.print("")
    
    # Utility Commands Section
    console.print(Text("🔧 CUSTOM UTILITIES:", style="bold green"))
    util_commands = [
        ("encode <method> <text>", "Text encoding (base64/url/hex)", "green"),
        ("decode <method> <text>", "Text decoding (base64/url/hex)", "green"),
        ("feedback", "Send feedback/bug reports to VritraAI team", "green"),
    ]

    for cmd, desc, color in util_commands:
        text = Text()
        text.append(f"  {cmd:<35}", style=color)
        text.append(" - ", style="dim white")
        text.append(desc, style="dim white")
        console.print(text)
    console.print("")
    
    # Built-in Aliases Section
    console.print(Text("🔧 BUILT-IN ALIASES:", style="bold yellow"))
    console.print("  ll/la/l -> ls variants          gp/gs/ga/gc -> git shortcuts", style="yellow")
    console.print("")
    
    # Usage Examples Section
    console.print(Text("🎯 USAGE EXAMPLES (FIXED & IMPROVED!):", style="bold magenta"))
    console.print("  # API Key & Model Management (All working perfectly now!)", style="yellow")
    
    # Helper function to split command and comment
    def print_usage_example(cmd_line: str):
        if "  # " in cmd_line:
            parts = cmd_line.split("  # ", 1)
            cmd_part = parts[0]
            comment_part = parts[1]
            text = Text()
            text.append(cmd_part, style="green")
            text.append("  # ", style="dim white")
            text.append(comment_part, style="dim white")
            console.print(text)
        else:
            console.print(cmd_line, style="green")
    
    print_usage_example("  apikey openrouter sk-or-v1-your-key  # No more hanging!")
    print_usage_example("  apikey gemini AIzaSy-your-key        # Fixed - won't freeze!")
    print_usage_example("  model set ds1                        # Saves permanently!")
    print_usage_example("  model search code                    # Find coding models")
    print_usage_example("  config                               # Clean view of all settings")
    console.print("")
    
    console.print("  # Theme & Customization (Persistence fixed!)", style="yellow")
    print_usage_example("  theme matrix                         # Saves permanently!")
    print_usage_example("  theme cyberpunk                      # Another great theme")
    print_usage_example("  theme                                # Browse all 37 themes")
    print_usage_example("  prompt superhero                     # Change prompt style")
    console.print("")
    
    console.print("  # AI with Typewriter Effect", style="yellow")
    console.print("  ai \"create a python web scraper with error handling\"", style="green")
    print_usage_example("  ai \"explain how neural networks work\"  # Watch text appear char-by-char!")
    console.print("")
    
    console.print("  # Advanced System Commands", style="yellow")
    print_usage_example("  sys_info && memory                     # System & memory info")
    print_usage_example("  find_files \"*.py\" src/               # Find Python files")
    console.print("")
    
    # Natural Language Section
    console.print(Panel.fit(Text("💬 NATURAL LANGUAGE VritraAI: VritraAI understands natural language!\n" +
                                "Try: \"find python files\", \"switch to galaxy theme\", \"use deepseek model\"", 
                                style="magenta italic"), 
                          border_style="magenta", title="AI Magic"))
    console.print("")
    
    # Footer with status
    status_text = Text("🎆 STATUS: ALL CRITICAL BUGS FIXED - PRODUCTION READY!", style="bold green")
    quick_start = Text("🚀 Quick Start: apikey openrouter <key> → model set ds1 → theme matrix → config", 
                      style="yellow italic")
    persistent_note = Text("💾 All settings (model, theme, apikey) persist automatically!", style="green bold")
    
    console.print(Panel.fit(Group(status_text, quick_start, persistent_note), 
                          border_style="green", title="Ready to Go!"))
    
    # Helpful reminder
    console.print("\n💡 ", end="")
    console.print("Type any command above or use natural language - VritraAI will understand!", 
                  style="magenta italic")
    console.print("")

def explain_command(args):
    """Handles the 'explain' command."""
    if not args:
        print_with_rich("Usage: explain [command]", "info")
        return

    command_to_explain = " ".join(args)
    prompt = f"""Provide a comprehensive explanation of the following command: {command_to_explain}

Include:
1. What the command does (overview)
2. Key features and functionality
3. Common use cases
4. Important options or flags (if applicable)
5. Usage examples with the command
6. Tips or notes about the command

Format your response in clear paragraphs and sections. Use plain text without markdown formatting like ** or `. Make it detailed and informative."""
    
    print_with_rich(f"📖 Explaining '{command_to_explain}'...", "info")
    explanation = get_ai_response(prompt)

    if explanation:
        # Clean formatting and use streaming output like optimize_code
        cleaned_explanation = clean_ai_response(explanation)
        print_with_rich(f"\n📖 Explanation: {command_to_explain}\n", "info")
        print_ai_response(cleaned_explanation, use_typewriter=True)

def create_file_command(args):
    """Handles the 'create_file' command."""
    if len(args) < 2:
        print_formatted_text("Usage: create_file [filename] [prompt]", style=get_style())
        return

    filename = args[0]
    prompt = " ".join(args[1:])

    #print_formatted_text("AI is thinking...", style=get_style())
    ai_prompt = f"""Generate content for a file named '{filename}' based on the following prompt:\n\n{prompt}\n\nIMPORTANT: Respond with ONLY the code/content that should be written to the file. Do NOT include any explanations, markdown code blocks, or commentary. Just provide the raw file content."""
    content = get_ai_response(ai_prompt)
    print_formatted_text("AI is generating...", style=get_style())

    if content:
        # Extract code from markdown code blocks if present
        cleaned_content = content.strip()
        
        # Remove markdown code blocks (```language ... ```)
        if cleaned_content.startswith("```"):
            # Find the closing ```
            parts = cleaned_content.split("```", 2)
            if len(parts) >= 3:
                # Extract content between code blocks
                code_content = parts[1]
                # Remove language identifier if present (first line)
                lines = code_content.split('\n')
                if lines and (lines[0].strip() in ['python', 'javascript', 'html', 'css', 'json', 'bash', 'sh', 'java', 'cpp', 'c', 'go', 'rust', 'php', 'ruby', 'sql', 'yaml', 'xml', 'markdown', 'text'] or lines[0].strip().startswith('python') or lines[0].strip().startswith('js')):
                    cleaned_content = '\n'.join(lines[1:])
                else:
                    cleaned_content = code_content
            else:
                # Malformed code block, try to extract anyway
                cleaned_content = cleaned_content.replace("```", "").strip()
                # Remove first line if it looks like a language identifier
                lines = cleaned_content.split('\n')
                if lines and len(lines[0].strip()) < 20 and not lines[0].strip().startswith(('import', 'def', 'class', 'function', '<', 'package', 'public', '#')):
                    cleaned_content = '\n'.join(lines[1:]) if len(lines) > 1 else cleaned_content
        
        # Remove any remaining markdown artifacts
        cleaned_content = cleaned_content.strip()
        
        # Remove common AI response prefixes
        prefixes_to_remove = [
            "Here's the content for",
            "Here is the content for",
            "Here's the code for",
            "Here is the code for",
            "Here's a",
            "Here is a",
            "Here's an",
            "Here is an",
        ]
        for prefix in prefixes_to_remove:
            if cleaned_content.lower().startswith(prefix.lower()):
                # Find the first colon or newline after the prefix
                idx = cleaned_content.find(':')
                if idx != -1:
                    cleaned_content = cleaned_content[idx+1:].strip()
                break
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(cleaned_content)
            print_formatted_text(f"File '{filename}' created successfully.", style=get_style())
        except Exception as e:
            print_formatted_text(f"Error creating file: {e}", style=get_style())

def create_dir_command(args):
    """Handles the 'create_dir' and 'mkdir' commands."""
    if not args:
        print_with_rich("Usage: create_dir [directory_name] or mkdir [directory_name]", "info")
        return

    dirname = args[0]
    try:
        os.makedirs(dirname, exist_ok=True)
        print_with_rich(f"✅ Directory '{dirname}' created successfully.", "success")
    except Exception as e:
        print_with_rich(f"❌ Error creating directory: {e}", "error")


# suggest_alternative_command function removed - use handle_error_with_recovery instead

def read_file_command(args: List[str]):
    """Read file content and display it."""
    if not args:
        print_with_rich("Usage: read_file <filename>", "info")
        return
    
    filepath = args[0]
    
    def read_file_operation():
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")
        return read_file_content(filepath)
    
    content = execute_with_error_recovery(read_file_operation, context=f"Reading file: {filepath}")
    if content is None:
        return
    
    if content:
        # Display with syntax highlighting but NO BORDERS
        try:
            from pygments import highlight
            from pygments.lexers import get_lexer_by_name, guess_lexer_for_filename, TextLexer
            from pygments.formatters import Terminal256Formatter
            from pygments.util import ClassNotFound
            
            # Try to get appropriate lexer
            try:
                lexer = guess_lexer_for_filename(filepath, content)
            except ClassNotFound:
                # Fallback to text lexer
                lexer = TextLexer()
            
            # Use Terminal256Formatter for clean, border-free output with syntax highlighting
            formatter = Terminal256Formatter(style='monokai')
            highlighted = highlight(content, lexer, formatter)
            print(highlighted, end='')
        except ImportError:
            # Fallback if pygments not available
            print(content)

# Enhanced File Editor System
def _get_file_language(filepath):
    """Detect file language for syntax highlighting."""
    ext = os.path.splitext(filepath)[1].lower()
    language_map = {
        '.py': 'python', '.pyw': 'python',
        '.js': 'javascript', '.mjs': 'javascript', '.jsx': 'javascript',
        '.ts': 'typescript', '.tsx': 'typescript',
        '.html': 'html', '.htm': 'html',
        '.css': 'css', '.scss': 'scss', '.sass': 'sass',
        '.json': 'json', '.jsonc': 'json',
        '.xml': 'xml', '.svg': 'xml',
        '.yaml': 'yaml', '.yml': 'yaml',
        '.md': 'markdown', '.rst': 'rst',
        '.sh': 'bash', '.bash': 'bash', '.zsh': 'bash',
        '.ps1': 'powershell', '.psm1': 'powershell',
        '.bat': 'batch', '.cmd': 'batch',
        '.c': 'c', '.h': 'c',
        '.cpp': 'cpp', '.cxx': 'cpp', '.hpp': 'cpp',
        '.java': 'java', '.go': 'go', '.rs': 'rust',
        '.php': 'php', '.rb': 'ruby', '.sql': 'sql',
        '.r': 'r', '.swift': 'swift', '.kt': 'kotlin',
        '.scala': 'scala', '.dart': 'dart', '.vim': 'vim',
        '.lua': 'lua', '.dockerfile': 'dockerfile',
        '.toml': 'toml', '.ini': 'ini', '.conf': 'ini',
        '.log': 'log'
    }
    return language_map.get(ext, 'text')

def _calculate_diff_stats(original_lines, new_lines):
    """Calculate detailed diff statistics."""
    import difflib
    
    matcher = difflib.SequenceMatcher(None, original_lines, new_lines)
    opcodes = matcher.get_opcodes()
    
    additions = 0
    deletions = 0
    modifications = 0
    unchanged = 0
    
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == 'replace':
            modifications += max(i2 - i1, j2 - j1)
        elif tag == 'delete':
            deletions += i2 - i1
        elif tag == 'insert':
            additions += j2 - j1
        elif tag == 'equal':
            unchanged += i2 - i1
    
    return {
        'additions': additions,
        'deletions': deletions, 
        'modifications': modifications,
        'unchanged': unchanged,
        'total_original': len(original_lines),
        'total_new': len(new_lines)
    }

def _show_advanced_diff_preview(filepath, original_content, new_content):
    """Show advanced diff preview with statistics and syntax highlighting."""
    import difflib
    from datetime import datetime
    
    original_lines = original_content.splitlines()
    new_lines = new_content.splitlines()
    
    # Calculate statistics
    stats = _calculate_diff_stats(original_lines, new_lines)
    
    # Check if there are any changes
    if original_content.strip() == new_content.strip():
        print_with_rich("⚠️  No changes detected - files are identical", "warning")
        return
    
    # Header with file info and timestamp
    file_language = _get_file_language(filepath)
    file_size_before = len(original_content.encode('utf-8'))
    file_size_after = len(new_content.encode('utf-8'))
    size_diff = file_size_after - file_size_before
    
    if RICH_AVAILABLE and console:
        from rich.panel import Panel
        from rich.table import Table
        from rich.columns import Columns
        from rich import box
        
        # Create header panel
        header_info = f"[bold blue]{filepath}[/bold blue] [{file_language}]\n"
        header_info += f"[dim]Modified: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]"
        
        header_panel = Panel(
            header_info,
            title="📝 File Modification Preview",
            title_align="left",
            border_style="blue",
            box=box.ROUNDED
        )
        console.print(header_panel)
        
        # Create statistics table
        stats_table = Table(show_header=True, header_style="bold magenta", box=box.SIMPLE)
        stats_table.add_column("Metric", style="cyan", width=15)
        stats_table.add_column("Count", style="green", justify="right", width=8)
        stats_table.add_column("Details", style="dim")
        
        # Add statistics rows
        if stats['additions'] > 0:
            stats_table.add_row("➕ Additions", str(stats['additions']), f"{stats['additions']} new lines")
        if stats['deletions'] > 0:
            stats_table.add_row("❌ Deletions", str(stats['deletions']), f"{stats['deletions']} removed lines")
        if stats['modifications'] > 0:
            stats_table.add_row("🔄 Changes", str(stats['modifications']), f"{stats['modifications']} modified lines")
        
        stats_table.add_row("📊 Total Lines", f"{stats['total_original']}→{stats['total_new']}", 
                           f"{'+'if stats['total_new'] > stats['total_original'] else ''}{stats['total_new'] - stats['total_original']} net change")
        
        size_change = f"{'+'if size_diff > 0 else ''}{size_diff} bytes" if size_diff != 0 else "no change"
        stats_table.add_row("💾 File Size", f"{file_size_before}→{file_size_after}", size_change)
        
        # Show impact assessment
        impact_level = "Low" if (stats['additions'] + stats['deletions'] + stats['modifications']) < 10 else "Medium" if (stats['additions'] + stats['deletions'] + stats['modifications']) < 50 else "High"
        impact_color = "green" if impact_level == "Low" else "yellow" if impact_level == "Medium" else "red"
        stats_table.add_row("🎯 Impact", f"[{impact_color}]{impact_level}[/{impact_color}]", 
                           f"{stats['additions'] + stats['deletions'] + stats['modifications']} total changes")
        
        stats_panel = Panel(
            stats_table,
            title="📊 Change Statistics",
            title_align="left",
            border_style="magenta",
            box=box.ROUNDED
        )
        console.print(stats_panel)
        
        # Show unified diff with syntax highlighting
        diff = difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"a/{filepath}",
            tofile=f"b/{filepath}",
            lineterm=''
        )
        diff_text = "\n".join(diff)
        
        if diff_text:
            diff_panel = Panel(
                Syntax(diff_text, "diff", theme="monokai", line_numbers=True, word_wrap=True),
                title="🔍 Detailed Changes",
                title_align="left",
                border_style="cyan",
                box=box.ROUNDED
            )
            console.print(diff_panel)
        
        # Show a preview of the final result (first 20 lines)
        if len(new_lines) > 0:
            preview_lines = new_lines[:20]
            if len(new_lines) > 20:
                preview_lines.append(f"... ({len(new_lines) - 20} more lines)")
            
            preview_content = "\n".join(preview_lines)
            result_panel = Panel(
                Syntax(preview_content, file_language, theme="monokai", line_numbers=True, line_range=(1, min(20, len(new_lines)))),
                title=f"🔮 Preview of {filepath} (after changes)",
                title_align="left",
                border_style="green",
                box=box.ROUNDED
            )
            console.print(result_panel)
    
    else:
        # Fallback for non-rich terminals
        print("\n" + "="*80)
        print(f"📋 ADVANCED DIFF PREVIEW: {filepath} [{file_language}]")
        print("="*80)
        
        print(f"📊 STATISTICS:")
        print(f"  ➕ Additions:     {stats['additions']} lines")
        print(f"  ❌ Deletions:     {stats['deletions']} lines") 
        print(f"  🔄 Modifications: {stats['modifications']} lines")
        print(f"  📊 Total Lines:   {stats['total_original']} → {stats['total_new']} ({stats['total_new'] - stats['total_original']:+d})")
        print(f"  💾 File Size:     {file_size_before} → {file_size_after} bytes ({size_diff:+d})")
        
        impact_level = "Low" if (stats['additions'] + stats['deletions'] + stats['modifications']) < 10 else "Medium" if (stats['additions'] + stats['deletions'] + stats['modifications']) < 50 else "High"
        print(f"  🎯 Impact Level:  {impact_level} ({stats['additions'] + stats['deletions'] + stats['modifications']} total changes)")
        
        print("\n" + "-"*80)
        print("🔍 DETAILED CHANGES:")
        print("-"*80)
        
        # Show unified diff
        diff = difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"a/{filepath}",
            tofile=f"b/{filepath}",
            lineterm=''
        )
        for line in diff:
            if line.startswith('+++'):
                print(f"[32m{line}[0m")  # Green
            elif line.startswith('---'):
                print(f"[31m{line}[0m")  # Red
            elif line.startswith('+'):
                print(f"[32m{line}[0m")  # Green
            elif line.startswith('-'):
                print(f"[31m{line}[0m")  # Red
            elif line.startswith('@@'):
                print(f"[36m{line}[0m")  # Cyan
            else:
                print(line)
        
        print("\n" + "-"*80)
        print(f"🔮 PREVIEW OF {filepath} (first 15 lines after changes):")
        print("-"*80)
        
        for i, line in enumerate(new_lines[:15], 1):
            print(f"{i:3d}: {line}")
        if len(new_lines) > 15:
            print(f"... ({len(new_lines) - 15} more lines)")
        
        print("="*80)

def edit_file_command(args: List[str]):
    """AI-powered file editing with diff preview."""
    if len(args) < 2:
        print_with_rich("Usage: edit_file <filename> <instruction>", "info")
        print_with_rich("Example: edit_file script.py 'add error handling to the main function'", "info")
        return
    
    filepath = args[0]
    instruction = " ".join(args[1:])
    
    # Handle file creation if it doesn't exist
    if not os.path.exists(filepath):
        if confirm_action(f"File '{filepath}' doesn't exist. Create it?"):
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("")
            print_with_rich(f"Created new file: {filepath}", "success")
        else:
            print_with_rich("Edit cancelled", "info")
            return
    
    # Read current file content with error recovery
    def read_file_for_edit():
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")
        return read_file_content(filepath)
    
    content = execute_with_error_recovery(read_file_for_edit, context=f"Reading file for editing: {filepath}")
    if content is None:
        return
    
    print_with_rich(f"🤖 VritraAI editing {filepath}: {instruction}", "info")
    
    # Detect file type for better context
    file_ext = os.path.splitext(filepath)[1].lower()
    file_type_hint = ""
    if file_ext:
        file_type_hint = f"This is a {file_ext} file. "
    
    # Create AI prompt for editing with better instruction understanding
    prompt = f"""Edit the following file according to this instruction: {instruction}

{file_type_hint}Understand the user's intent carefully. If they say "change api", they likely mean changing the API endpoint or API service, not just http to https.

Original file content:
```
{content}
```

Please provide ONLY the new file content without any explanation. Do not include markdown code blocks or any commentary. Just the raw file content that should replace the original. Make meaningful changes based on the instruction."""
    
    # Get AI response
    new_content = get_ai_response(prompt)
    if not new_content:
        print_with_rich("Failed to get AI response for editing", "error")
        return
    
    # Clean up AI response (remove code blocks if present)
    if new_content.startswith("```") and "```" in new_content[3:]:
        new_content = new_content.split("```", 2)[1]
        if any(new_content.startswith(lang) for lang in ["python", "javascript", "html", "css", "json"]):
            new_content = new_content.split("\n", 1)[1]
        new_content = new_content.strip()
    
    # Show advanced diff preview
    _show_advanced_diff_preview(filepath, content, new_content)
    
    # Confirm before applying changes
    if not confirm_action("Apply these changes?"):
        print_with_rich("Edit cancelled", "info")
        return
    
    # Write the new content
    if write_file_content(filepath, new_content):
        print_with_rich(f"✅ File {filepath} updated successfully", "success")
    else:
        print_with_rich(f"❌ Failed to update file {filepath}", "error")

def _iter_code_files(base_path: str) -> List[str]:
    """Collect code-like files under a path (used by search/navigation commands).

    NOTE: Also includes common script extensions like .sh so project-level
    docs (e.g. `doc readme`) see shell tools as part of the codebase.
    """
    code_exts = {
        '.py', '.js', '.ts', '.tsx', '.jsx', '.java', '.cs', '.cpp', '.c', '.h',
        '.go', '.rs', '.php', '.rb', '.swift', '.kt', '.scala', '.html', '.css',
        '.sh'
    }
    collected: List[str] = []
    for root, dirs, files in os.walk(base_path):
        # Skip heavy/irrelevant dirs
        dirs[:] = [d for d in dirs if d not in {'.git', 'node_modules', '__pycache__', 'dist', 'build'}]
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext in code_exts:
                collected.append(os.path.join(root, name))
    return collected


def search_file_command(args: List[str]):
    """Search for pattern in files."""
    if len(args) < 2:
        print_with_rich("Usage: search_file <pattern> <file_or_dir>", "info")
        return
    
    pattern = args[0]
    target = args[1] if len(args) > 1 else "."
    # Expand ~ and environment variables
    target = expand_path(target)
    
    # Gitignore-style patterns to ignore
    ignore_patterns = [
        '.git', '.gitignore', '__pycache__', 'node_modules', '.env',
        '.venv', 'venv', 'dist', 'build', '.pytest_cache', '.mypy_cache',
        '.coverage', '*.pyc', '*.pyo', '*.pyd', '.DS_Store', 'Thumbs.db',
        '.idea', '.vscode', '.vs', '*.swp', '*.swo', '*~', '.cache'
    ]
    
    def should_ignore_path(filepath: str) -> bool:
        """Check if a filepath should be ignored based on gitignore-style patterns."""
        path_parts = filepath.split(os.sep)
        for part in path_parts:
            # Check if any part matches ignore patterns
            for pattern in ignore_patterns:
                if pattern.startswith('*'):
                    # Wildcard pattern like *.pyc
                    if part.endswith(pattern[1:]):
                        return True
                elif part == pattern or part.startswith(pattern):
                    return True
        return False
    
    if os.path.isdir(target):
        # Search in all files in directory
        results = []
        for root, dirs, files in os.walk(target):
            # Filter out ignored directories
            dirs[:] = [d for d in dirs if not should_ignore_path(os.path.join(root, d))]
            
            for file in files:
                filepath = os.path.join(root, file)
                # Skip ignored files
                if should_ignore_path(filepath):
                    continue
                try:
                    matches = search_in_file(filepath, pattern)
                    if matches:
                        results.extend([{"file": filepath, **match} for match in matches])
                except Exception:
                    continue
        
        if results:
            print_with_rich(f"Found {len(results)} matches for '{pattern}':", "success")
            for result in results:
                print_with_rich(f"{result['file']}:{result['line_number']}: {result['line_content']}", "info")
        else:
            print_with_rich(f"No matches found for '{pattern}'", "warning")
    else:
        # Search in a single file
        def search_in_single_file():
            if not os.path.exists(target):
                raise FileNotFoundError(f"File not found: {target}")
            matches = search_in_file(target, pattern)
            if matches:
                print_with_rich(f"Found {len(matches)} matches for '{pattern}' in {target}:", "success")
                for match in matches:
                    print_with_rich(f"{target}:{match['line_number']}: {match['line_content']}", "info")
            else:
                print_with_rich(f"No matches found for '{pattern}' in {target}", "warning")
            return True
        
        result = execute_with_error_recovery(search_in_single_file, context=f"Searching in file: {target}")


def search_regex_command(args: List[str]):
    """Full-text search with regex across files/directories.

    Usage:
        search_regex <pattern> [path]
    """
    if not args:
        print_with_rich("Usage: search_regex <pattern> [path]", "info")
        return

    pattern = args[0]
    target = args[1] if len(args) > 1 else "."

    if not os.path.exists(target):
        print_with_rich(f"Path not found: {target}", "error")
        return

    regex = None
    try:
        regex = re.compile(pattern)
    except re.error as e:
        print_with_rich(f"Invalid regex: {e}", "error")
        return

    matches = []
    files_to_search: List[str] = []

    if os.path.isdir(target):
        files_to_search = _iter_code_files(target)
    else:
        files_to_search = [target]

    for filepath in files_to_search:
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                for line_no, line in enumerate(f, 1):
                    if regex.search(line):
                        matches.append((filepath, line_no, line.rstrip('\n')))
        except Exception:
            continue

    if not matches:
        print_with_rich(f"No matches for /{pattern}/ in {target}", "warning")
        return

    print_with_rich(f"Found {len(matches)} matches for /{pattern}/:", "success")
    for file_path, line_no, line in matches[:500]:
        # Simple highlight: wrap matches in red
        highlighted = regex.sub(lambda m: f"\033[1;31m{m.group(0)}\033[0m", line)
        print_with_rich(f"{file_path}:{line_no}: {highlighted}", "info")

    if len(matches) > 500:
        print_with_rich(f"... and {len(matches) - 500} more matches", "warning")


def search_semantic_command(args: List[str]):
    """AI-powered semantic code search.

    Usage:
        search_semantic <query> [path]
    """
    if not args:
        print_with_rich("Usage: search_semantic <query> [path]", "info")
        return

    if not AI_ENABLED:
        print_with_rich("AI is required for semantic search but is not enabled.", "warning")
        return

    query = " ".join(args[:-1]) if len(args) > 1 and os.path.exists(args[-1]) else " ".join(args)
    target = args[-1] if len(args) > 1 and os.path.exists(args[-1]) else "."

    if not os.path.exists(target):
        print_with_rich(f"Path not found: {target}", "error")
        return

    base_path = target if os.path.isdir(target) else os.path.dirname(target) or "."
    code_files = _iter_code_files(base_path)
    if not code_files:
        print_with_rich("No code files found for semantic search.", "warning")
        return

    # Collect a small corpus of relevant snippets
    snippets = []
    max_files = 12
    max_chars_per_file = 600

    for path in code_files[:max_files]:
        try:
            content = read_file_content(path)
            if not content:
                continue
            if query.lower() in content.lower():
                snippet = content[:max_chars_per_file]
            else:
                snippet = content[:max_chars_per_file]
            snippets.append(f"File: {path}\n\n```\n{snippet}\n```\n")
        except Exception:
            continue

    if not snippets:
        print_with_rich("Could not collect snippets for semantic search.", "warning")
        return

    prompt = f"""You are a code search engine embedded in a terminal.

The user query is:
"{query}"

You are given snippets from several project files. Identify where in the codebase the query is most relevant and answer:

1) Which files/snippets are most relevant (with reasons)
2) What the code does related to the query
3) Where to start reading or editing (file + rough line ranges)
4) Any potential pitfalls or related symbols to inspect

Snippets:
{''.join(snippets)}

Respond with a concise, structured explanation suitable for terminal output.
"""

    print_with_rich("🤖 VritraAI performing semantic search...", "info")
    result = get_ai_response(prompt)
    if result:
        cleaned = clean_ai_response(result)
        print_with_rich("\n🔍 Semantic Search Results\n", "info")
        print_ai_response(cleaned, use_typewriter=True)


def record_command_to_history(command: str):
    """Record a command to the history file with timestamp, preventing duplicates.
    
    Format:
        # YYYY-MM-DD HH:MM:SS.microseconds
        +command
    
    Args:
        command: The command string to record
    """
    if not command or not command.strip():
        return
    
    try:
        # Get current timestamp
        timestamp = datetime.datetime.now()
        timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")
        
        # Read existing history to check for duplicates
        # Check last 10 entries to catch rapid duplicates
        recent_commands = []
        
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    # Read backwards to get recent entries
                    i = len(lines) - 1
                    entry_count = 0
                    current_entry = {}
                    
                    while i >= 0 and entry_count < 10:
                        line = lines[i].strip()
                        if line.startswith('+'):
                            # Command line
                            current_entry['command'] = line[1:].strip()
                        elif line.startswith('#'):
                            # Timestamp line
                            current_entry['timestamp'] = line[1:].strip()
                            if 'command' in current_entry:
                                recent_commands.append(current_entry)
                                entry_count += 1
                                current_entry = {}
                        i -= 1
            except Exception:
                recent_commands = []
        
        # Check if this is a duplicate
        # A duplicate is: same command recorded within 0.5 seconds
        is_duplicate = False
        for entry in recent_commands:
            if entry.get('command') == command and entry.get('timestamp'):
                try:
                    # Parse timestamp
                    entry_ts = datetime.datetime.strptime(entry['timestamp'], "%Y-%m-%d %H:%M:%S.%f")
                    # Check if within 0.5 seconds (500ms) - very recent duplicate
                    time_diff = abs((timestamp - entry_ts).total_seconds())
                    if time_diff < 0.5:
                        is_duplicate = True
                        break
                except Exception:
                    pass
        
        # Only record if not a duplicate
        if not is_duplicate:
            # Use file locking to prevent concurrent writes
            try:
                import fcntl
                use_lock = True
            except ImportError:
                use_lock = False
            
            try:
                with open(HISTORY_FILE, 'a+', encoding='utf-8') as f:
                    # Try to acquire exclusive lock (non-blocking) if available
                    if use_lock:
                        try:
                            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except (IOError, OSError):
                            # Lock failed, continue without lock
                            use_lock = False
                    
                    # Double-check for duplicate after acquiring lock
                    # Read the last few lines to see if same command was just written
                    f.seek(0)  # Go to beginning
                    all_lines = f.readlines()
                    
                    # Check last 4 lines (2 entries: timestamp + command each)
                    if len(all_lines) >= 2:
                        # Get last command entry
                        last_lines = all_lines[-4:] if len(all_lines) >= 4 else all_lines
                        for i in range(len(last_lines) - 1, -1, -1):
                            line = last_lines[i].strip()
                            if line.startswith('+'):
                                last_cmd = line[1:].strip()
                                # Check if it's the same command
                                if last_cmd == command:
                                    # Check timestamp if available
                                    if i > 0 and last_lines[i-1].strip().startswith('#'):
                                        try:
                                            last_ts_str = last_lines[i-1].strip()[1:].strip()
                                            last_ts = datetime.datetime.strptime(last_ts_str, "%Y-%m-%d %H:%M:%S.%f")
                                            time_diff = abs((timestamp - last_ts).total_seconds())
                                            if time_diff < 0.5:  # Within 500ms
                                                # Duplicate found, skip
                                                if use_lock:
                                                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                                                return
                                        except Exception:
                                            pass
                                    else:
                                        # Same command but no timestamp, likely duplicate
                                        if use_lock:
                                            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                                        return
                                break
                    
                    # No duplicate found, write the entry
                    f.seek(0, 2)  # Seek to end
                    f.write(f"# {timestamp_str}\n")
                    f.write(f"+{command}\n")
                    f.flush()
                    os.fsync(f.fileno())  # Force write to disk
                    
                    if use_lock:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                # Fallback: simple write without locking
                try:
                    with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
                        f.write(f"# {timestamp_str}\n")
                        f.write(f"+{command}\n")
                        f.flush()
                except Exception:
                    pass
        
    except Exception as e:
        # Silent fail - don't break the shell if history recording fails
        pass


def _get_history_commands(args: List[str] = None):
    """Internal function to get history commands list.
    
    Returns:
        tuple: (commands_list, total_count)
    """
    if not os.path.exists(HISTORY_FILE):
        return [], 0
    
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Parse history entries: extract commands (lines starting with +) with their timestamps
    commands = []
    current_timestamp = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        if line.startswith('#'):
            # Timestamp line
            try:
                timestamp_str = line[1:].strip()
                current_timestamp = datetime.datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S.%f")
            except Exception:
                current_timestamp = None
        elif line.startswith('+'):
            # Command line
            command = line[1:].strip()
            if command:  # Only add non-empty commands
                commands.append({
                    'command': command,
                    'timestamp': current_timestamp
                })
                current_timestamp = None  # Reset after pairing
    
    # Get number of commands to show
    num_commands = None
    if args:
        try:
            num_commands = int(args[0])
        except ValueError:
            pass
    
    # Filter commands to show
    if num_commands:
        commands_to_show = commands[-num_commands:]
    else:
        commands_to_show = commands
    
    return commands_to_show, len(commands)

def history_command(args: List[str]):
    """Show command history from history file.
    
    Usage:
        history              - show all command history
        history [number]     - show last N commands
    """
    try:
        commands_to_show, total_commands = _get_history_commands(args)
        
        if not commands_to_show:
            print_with_rich("No command history found.", "info")
            return
        
        # Display history
        showing_count = len(commands_to_show)
        print_with_rich(f"\n📜 Command History (showing {showing_count} of {total_commands} commands):", "info")
        print_with_rich("=" * 60, "default")
        
        for i, entry in enumerate(commands_to_show, 1):
            # Calculate absolute command number
            cmd_num = total_commands - len(commands_to_show) + i
            
            # Format timestamp if available
            timestamp_str = ""
            if entry['timestamp']:
                try:
                    timestamp_str = entry['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    timestamp_str = ""
            
            # Display command with timestamp
            if timestamp_str:
                print_with_rich(f"  {cmd_num:4d}  [{timestamp_str}]  {entry['command']}", "default")
            else:
                print_with_rich(f"  {cmd_num:4d}  {entry['command']}", "default")
        
        print_with_rich("=" * 60, "default")
        
    except Exception as e:
        print_with_rich(f"Error reading history: {e}", "error")
        import traceback
        traceback.print_exc()

def history_command_with_pipe(args: List[str], pipe_command: str):
    """Show command history with pipe support (head/tail) with colored output.
    
    Usage:
        history | head 5     - show first 5 commands
        history | tail 5     - show last 5 commands
        history 10 | head 3  - show first 3 of last 10 commands
    """
    try:
        commands_to_show, total_commands = _get_history_commands(args)
        
        if not commands_to_show:
            print_with_rich("No command history found.", "info")
            return
        
        # Parse pipe command
        pipe_parts = pipe_command.strip().split()
        pipe_cmd = pipe_parts[0].lower() if pipe_parts else ""
        pipe_num = None
        
        if len(pipe_parts) > 1:
            try:
                pipe_num = int(pipe_parts[1])
            except ValueError:
                pass
        
        # Apply pipe filtering
        original_count = len(commands_to_show)
        if pipe_cmd == "head":
            if pipe_num:
                commands_to_show = commands_to_show[:pipe_num]
            else:
                commands_to_show = commands_to_show[:10]  # Default head 10
        elif pipe_cmd == "tail":
            if pipe_num:
                commands_to_show = commands_to_show[-pipe_num:]
            else:
                commands_to_show = commands_to_show[-10:]  # Default tail 10
        else:
            # Unknown pipe command, just show all
            pass
        
        # Display history with Rich formatting (same as regular history)
        showing_count = len(commands_to_show)
        pipe_info = f" | {pipe_cmd} {pipe_num}" if pipe_num else f" | {pipe_cmd}"
        print_with_rich(f"\n📜 Command History (showing {showing_count} of {total_commands} commands{pipe_info}):", "info")
        print_with_rich("=" * 60, "default")
        
        for i, entry in enumerate(commands_to_show, 1):
            # Calculate absolute command number
            # For head: start from 1
            # For tail: calculate from total
            if pipe_cmd == "head":
                cmd_num = i
            elif pipe_cmd == "tail":
                cmd_num = total_commands - len(commands_to_show) + i
            else:
                cmd_num = total_commands - len(commands_to_show) + i
            
            # Format timestamp if available
            timestamp_str = ""
            if entry['timestamp']:
                try:
                    timestamp_str = entry['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    timestamp_str = ""
            
            # Display command with timestamp (colored output)
            if timestamp_str:
                print_with_rich(f"  {cmd_num:4d}  [{timestamp_str}]  {entry['command']}", "default")
            else:
                print_with_rich(f"  {cmd_num:4d}  {entry['command']}", "default")
        
        print_with_rich("=" * 60, "default")
        
    except Exception as e:
        print_with_rich(f"Error reading history: {e}", "error")

def recent_command(args: List[str]):
    """Show recent files and commands.

    Usage:
        recent                - show both
        recent files          - show recent files
        recent cmds           - show recent commands
    """
    mode = args[0] if args else "both"

    if mode in ("both", "files"):
        print_with_rich("\n📝 Recent files this session:", "info")
        files = getattr(session, 'modified_files', []) or []
        if not files:
            print_with_rich("  (no files recorded yet)", "warning")
        else:
            for path in files[-20:]:
                print_with_rich(f"  {path}", "info")

    if mode in ("both", "cmds", "commands"):
        print_with_rich("\n⌨️  Recent commands:", "info")
        cmds = getattr(session, 'commands_history', []) or []
        if not cmds:
            print_with_rich("  (no commands recorded yet)", "warning")
        else:
            for entry in cmds[-20:]:
                ts = entry.get('timestamp')
                ts_str = ts.strftime('%H:%M:%S') if hasattr(ts, 'strftime') else ''
                print_with_rich(f"  [{ts_str}] {entry.get('command', '')}", "info")


def doc_command(args: List[str]):
    """AI-powered documentation generator entrypoint.

    Subcommands:
        doc docstring <file> [symbol]
        doc readme [path] [out]
        doc tutorial [out]
        doc diagram <file> [symbol] [format]
    """
    if not args or args[0] in {"help", "-h", "--help"}:
        print_with_rich("📚 Documentation generator:", "info")
        print_with_rich("  doc docstring <file> [symbol]     - Suggest docstrings", "info")
        print_with_rich("  doc readme [path] [out]           - Generate README.md for project/directory", "info")
        print_with_rich("  doc readme <file>                 - Generate README.md for a specific file", "info")
        print_with_rich("  doc tutorial [out]                - Tutorial from session history", "info")
        print_with_rich("  doc diagram <file> [symbol] [fmt] - Code-to-diagram (mermaid/plantuml/text)", "info")
        return

    sub = args[0]
    sub_args = args[1:]

    if sub == "docstring":
        _doc_docstring(sub_args)
    elif sub == "readme":
        _doc_readme(sub_args)
    elif sub == "tutorial":
        _doc_tutorial(sub_args)
    elif sub == "diagram":
        _doc_diagram(sub_args)
    else:
        print_with_rich(f"Unknown doc subcommand: {sub}", "error")
        doc_command(["help"])


def _doc_docstring(args: List[str]):
    """Generate docstring suggestions for a given source file (optionally a symbol).

    Now integrated with the explain/recovery system so missing or unreadable
    files trigger helpful AI guidance instead of silent failures.
    """
    if not AI_ENABLED:
        print_with_rich("AI is required for docstring generation but is not enabled.", "warning")
        return

    if not args:
        print_with_rich("Usage: doc docstring <file> [symbol]", "info")
        return

    file_path = args[0]
    symbol = args[1] if len(args) > 1 else None

    def generate_docstrings():
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        content = read_file_content(file_path)
        if not content:
            raise FileOperationError(f"Could not read file: {file_path}")

        language = get_file_language(file_path)
        max_len = 6000
        code = content
        if len(code) > max_len:
            code = code[:max_len] + "\n... [truncated]"

        symbol_part = f" for symbol '{symbol}'" if symbol else ""
        prompt = f"""You are a senior {language} engineer.

The user wants to improve documentation by adding or improving docstrings{symbol_part} in this file:

File: {file_path}
Language: {language}

Code:
```{language.lower() if language != 'Unknown' else 'text'}
{code}
```

Suggest high-quality docstrings (or comments if the language doesn't use docstrings) for functions, methods, classes, and modules.

IMPORTANT:
- Do NOT rewrite the entire file.
- For each function/class, show the signature and the docstring you propose beneath it.
- Use the idiomatic style for {language} (e.g., Python triple-quoted docstrings, JSDoc for JS/TS, etc.).
- Focus only on documentation text, not code changes.
"""

        print_with_rich("🤖 Generating docstring suggestions...", "info")
        result = get_ai_response(prompt)
        if not result:
            raise APIError("Failed to generate docstring suggestions.")

        cleaned = clean_ai_response(result)
        print_with_rich("\n📚 Docstring Suggestions\n", "info")
        print_ai_response(cleaned, use_typewriter=True)
        return True

    execute_with_error_recovery(generate_docstrings, context=f"Command: doc docstring {file_path}")


def _doc_readme(args: List[str]):
    """Generate README.md from project analysis or for a specific file.

    Modes:
        doc readme                 -> analyze current directory (project-level README)
        doc readme [path] [out]    -> directory/project-level README
        doc readme <file>          -> file-focused README next to that file

    Now integrates explain/recovery mode so invalid paths are handled
    gracefully and explained by the AI instead of silently falling back.
    """
    if not AI_ENABLED:
        print_with_rich("AI is required for README generation but is not enabled.", "warning")
        return

    target = args[0] if args else "."
    out_path = args[1] if len(args) >= 2 else None
    explicit_target = bool(args)

    # If user provided a target, validate that it exists before doing any AI work
    if explicit_target and not (os.path.isfile(target) or os.path.isdir(target)):
        def _missing_target():
            raise FileNotFoundError(f"Path not found: {target}")

        execute_with_error_recovery(_missing_target, context=f"Command: doc readme {target}")
        return

    # File-specific README mode
    if os.path.isfile(target):
        file_path = target

        def _generate_file_readme():
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")

            content = read_file_content(file_path)
            if not content:
                raise FileOperationError(f"Could not read file: {file_path}")

            language = get_file_language(file_path)
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            default_out = os.path.join(os.path.dirname(file_path), f"{base_name}.README.generated.md")
            output = out_path or default_out

            file_prompt = f"""You are generating a high-quality README.md for a single source file.

File path: {file_path}
Language: {language}

File content (truncated if large):
```{language.lower() if language != 'Unknown' else 'text'}
{content[:6000]}
```

Write a detailed README in Markdown that documents this file as a standalone tool/module.
Include:
- Title & Short Description
- What the Script/Tool Does
- Inputs (CLI args, env vars, config)
- Outputs & Side Effects
- Usage Examples (sort)
- Dependencies (Libraries, APIs)
- Notes & Limitations
- How It Works (Internal Architecture)
- Security Considerations
- Error Handling & Troubleshooting 
- License detail (sort MIT based license)

Return ONLY the README content in Markdown.
"""

            print_with_rich("🤖 Generating file-specific README.md...", "info")
            result = get_ai_response(file_prompt)
            if not result:
                raise APIError("Failed to generate README.")

            cleaned = clean_ai_response(result)
            if write_file_content(output, cleaned):
                print_with_rich(f"✅ README generated at: {output}", "success")
            return True

        execute_with_error_recovery(_generate_file_readme, context=f"Command: doc readme {file_path}")
        return

    # Directory/project-level README mode
    # If no explicit target was provided, default to current directory.
    target_dir = target if os.path.isdir(target) else "."

    def _generate_project_readme():
        if not os.path.isdir(target_dir):
            raise FileNotFoundError(f"Directory not found: {target_dir}")

        project_info = _analyze_project_structure(target_dir)
        health = _generate_health_report(target_dir)
        code_files = _iter_code_files(target_dir)

        samples = []
        for path in code_files[:5]:
            snippet = read_file_content(path)
            if not snippet:
                continue
            samples.append(f"File: {path}\n```\n{snippet[:800]}\n```\n")

        summary = f"""Project directory: {os.path.abspath(target_dir)}
Primary type: {project_info['primary_type']}
Secondary types: {', '.join(project_info['secondary_types'])}
Languages: {', '.join([f'{k} ({v})' for k, v in project_info['languages'].items()])}
Health scores:
  - Overall: {health['overall_score']}/100
  - Documentation: {health['documentation']['score']}/100
  - Testing: {health['testing']['score']}/100
  - Structure: {health['structure']['score']}/100

Representative code files (truncated excerpts):
{''.join(samples)}
"""

        prompt = f"""You are generating a high-quality README.md for a small CLI/utility project.

Project summary:
{summary}

Write a detailed README in Markdown that includes:
- Project title and short tagline
- Overview / description
- Features
- Installation instructions
- Usage examples
- Dependencies (Libraries, APIs)
- Configuration (if relevant)
- Running tests (if applicable)
- Folder structure overview
- Security Considerations
- Error Handling & Troubleshooting
- Contributing guidelines (brief)
- License placeholder (MIT based)

Return ONLY the README content in Markdown.
"""

        print_with_rich("🤖 Generating README.md...", "info")
        result = get_ai_response(prompt)
        if not result:
            raise APIError("Failed to generate README.")

        cleaned = clean_ai_response(result)
        output = out_path or os.path.join(target_dir, "README.generated.md")
        if write_file_content(output, cleaned):
            print_with_rich(f"✅ README generated at: {output}", "success")
        return True

    execute_with_error_recovery(_generate_project_readme, context=f"Command: doc readme {target}")


def _doc_tutorial(args: List[str]):
    """Create tutorial from this session's command history."""
    if not AI_ENABLED:
        print_with_rich("AI is required for tutorial generation but is not enabled.", "warning")
        return

    out_path = args[0] if args else os.path.join(os.getcwd(), "TUTORIAL.generated.md")

    history = getattr(session, 'commands_history', []) or []
    if not history:
        print_with_rich("No command history recorded in this session.", "warning")
        return

    lines = []
    for entry in history:
        ts = entry.get('timestamp')
        ts_str = ts.strftime('%Y-%m-%d %H:%M:%S') if hasattr(ts, 'strftime') else ''
        cmd = entry.get('command', '')
        lines.append(f"[{ts_str}] $ {cmd}")

    history_text = "\n".join(lines[-200:])  # last 200 commands

    prompt = f"""You are generating a step-by-step tutorial based on the following terminal session history:

{history_text}

Write a tutorial in Markdown that explains what the user was doing, grouped into logical sections.
For each section:
- Add a heading
- Explain the goal
- Show key commands
- Explain what each command does and why

Assume the reader starts from scratch.
"""

    print_with_rich("🤖 Generating tutorial from session history...", "info")
    result = get_ai_response(prompt)
    if not result:
        print_with_rich("Failed to generate tutorial.", "error")
        return

    cleaned = clean_ai_response(result)
    if write_file_content(out_path, cleaned):
        print_with_rich(f"✅ Tutorial generated at: {out_path}", "success")


def _doc_diagram(args: List[str]):
    """Generate a code architecture diagram description from a file.

    Usage:
        doc diagram <file> [symbol] [format]

    Now uses explain/recovery mode so missing or unreadable files trigger
    helpful guidance instead of just a single-line error.
    """
    if not AI_ENABLED:
        print_with_rich("AI is required for diagram generation but is not enabled.", "warning")
        return

    if not args:
        print_with_rich("Usage: doc diagram <file> [symbol] [format]", "info")
        return

    file_path = args[0]
    symbol = args[1] if len(args) > 1 and not args[1].startswith('-') else None
    fmt = args[2] if len(args) > 2 else "mermaid"
    fmt = fmt.lower()
    if fmt not in {"mermaid", "plantuml", "text"}:
        print_with_rich("Format must be one of: mermaid, plantuml, text", "warning")
        fmt = "mermaid"

    def _generate_diagram():
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        content = read_file_content(file_path)
        if not content:
            raise FileOperationError(f"Could not read file: {file_path}")

        language = get_file_language(file_path)
        max_len = 6000
        code = content
        if len(code) > max_len:
            code = code[:max_len] + "\n... [truncated]"

        symbol_part = f" focusing on symbol '{symbol}'" if symbol else ""

        if fmt == "mermaid":
            diagram_hint = "Produce a mermaid diagram (e.g., classDiagram, sequenceDiagram, flowchart) that best represents the structure."
        elif fmt == "plantuml":
            diagram_hint = "Produce a PlantUML diagram (@startuml ... @enduml) that represents the structure."
        else:
            diagram_hint = "Describe the architecture and relationships as an ASCII/text diagram."

        prompt = f"""You are generating an architecture diagram for this code file{symbol_part}.

File: {file_path}
Language: {language}

Code:
```{language.lower() if language != 'Unknown' else 'text'}
{code}
```

The goal is to show the static architecture of the codebase, not a
runtime flowchart of HTTP errors or argument parsing.

{diagram_hint}

IMPORTANT:
- First, identify the main entry point function (e.g. main()) and show it clearly.
- Then, show all important helper functions and how data flows between them.
- Focus on modules, classes, functions, and their relationships.
- Highlight how input (CLI args, config, etc.) flows into HTTP calls / I/O and
  then back out to output/printing.
- Group related functions or components logically.
- Avoid listing every possible error branch unless it is structurally important.
- Return ONLY the diagram content, ideally enclosed in a code block for {fmt}.
"""

        print_with_rich("🤖 Generating diagram description...", "info")
        result = get_ai_response(prompt)
        if not result:
            raise APIError("Failed to generate diagram.")

        cleaned = result.strip()
        base, _ = os.path.splitext(file_path)
        out_path = f"{base}.diagram.{fmt}.md" if fmt != "text" else f"{base}.diagram.txt"
        if write_file_content(out_path, cleaned):
            print_with_rich(f"✅ Diagram description written to: {out_path}", "success")
        return True

    execute_with_error_recovery(_generate_diagram, context=f"Command: doc diagram {file_path}")


def summarize_command(args: List[str]):
    """Summarize directory or file."""
    target = args[0] if args else "."
    # Expand ~ and environment variables
    target = expand_path(target)
    
    if os.path.isdir(target):
        # Summarize directory
        cwd = os.getcwd()
        try:
            if target != ".":
                os.chdir(target)
            summary = summarize_directory()
            print_with_rich(summary, "info")
        finally:
            if target != ".":
                os.chdir(cwd)
    elif os.path.isfile(target):
        # Summarize file with AI
        if not AI_ENABLED:
            print_with_rich("AI is required for file summarization but is not enabled.", "warning")
            return
        
        content = read_file_content(target)
        if content:
            prompt = f"""Summarize the following file in a professional and concise way. Include key information and purpose. Avoid using markdown formatting like ** for bold. Use plain text.\n\nFile: {target}\nContent:\n```\n{content[:4000]}\n```\n{"...content truncated..." if len(content) > 4000 else ""}"""
            summary = get_ai_response(prompt)
            if summary:
                # Clean formatting and use streaming effect
                cleaned_summary = clean_ai_response(summary)
                print_with_rich(f"\n📊 Summary of {target}\n", "info")
                print_ai_response(cleaned_summary, use_typewriter=True)
    else:
        # Path does not exist – integrate with error explanation/recovery
        error = FileNotFoundError(f"Path not found: {target}")
        should_retry = handle_error_with_recovery(
            error,
            context=f"Command: summarize {target}",
            show_suggestion=True,
            auto_mode=False,
            traceback_str=None,
            code_frame=None,
        )
        if should_retry:
            summarize_command([target])

def session_command(args: List[str]):
    """Manage session data."""
    if not args:
        # Show session info
        print_with_rich(session.get_context_summary(), "info")
        return
    
    subcmd = args[0]
    if subcmd == "save":
        # Save session data to file
        filename = args[1] if len(args) > 1 else f"vritraai_session_{int(time.time())}.json"
        try:
            data = {
                "start_time": session.start_time.isoformat(),
                "commands": session.commands_history,
                "modified_files": session.modified_files
            }
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
            print_with_rich(f"Session saved to {filename}", "success")
        except Exception as e:
            print_with_rich(f"Error saving session: {e}", "error")
    elif subcmd == "clear":
        # Clear session data
        session.commands_history = []
        session.modified_files = []
        print_with_rich("Session data cleared", "success")

def _show_available_models():
    """Display all available AI models with full content visibility."""
    print_with_rich(f"\n🤖 Available AI Models ({len(AI_MODELS)} total)", "info")
    print("=" * 100)
    
    # Group models by provider for better organization
    providers = {}
    for model_id, model_info in AI_MODELS.items():
        provider = model_info['provider']
        if provider not in providers:
            providers[provider] = []
        providers[provider].append((model_id, model_info))
    
    # Display without rich tables to avoid hidden content
    for provider in sorted(providers.keys()):
        print_with_rich(f"\n🏢 {provider.upper()}:", "success")
        print("-" * 80)
        
        for model_id, model_info in sorted(providers[provider]):
            current = " ✅ CURRENT" if model_info['name'] == MODEL else ""
            print_with_rich(f"  [{model_id}] {model_info['display_name']}{current}", "default")
            print_with_rich(f"      🏷️  Category: {model_info['category']}", "info")
            print_with_rich(f"      📝 {model_info['description']}", "default")
            print_with_rich(f"      🔗 Model Path: {model_info['name']}", "warning")
            print()  # Add spacing
    
    # Show comprehensive usage examples
    print_with_rich("\n📝 USAGE EXAMPLES:", "info")
    print("-" * 40)
    print_with_rich("  model list                      - Show all models", "default")
    print_with_rich("  model set ds1                   - Switch to DeepSeek Chat v3", "default")
    print_with_rich("  model set ll1                   - Switch to LLaMA 3.3 70B", "default")
    print_with_rich("  model search deepseek           - Find DeepSeek models", "default")
    print_with_rich("  model search code               - Find coding models", "default")
    print_with_rich("  model search large              - Find large models", "default")
    
    print_with_rich("\n💡 QUICK MODEL CATEGORIES:", "info")
    categories = {}
    for model_info in AI_MODELS.values():
        cat = model_info['category']
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(model_info['display_name'][:20])  # Shortened names
    
    for category, models in sorted(categories.items()):
        model_list = ", ".join(models[:3])  # Show first 3
        if len(models) > 3:
            model_list += f" (+{len(models)-3} more)"
        print_with_rich(f"  {category}: {model_list}", "default")
    
    print("\n" + "=" * 100)

def _show_available_models_fallback():
    """Fallback display for non-rich terminals."""
    # Fallback for non-rich terminals
    print("\n" + "="*80)
    print("🤖 AVAILABLE AI MODELS")
    print("="*80)
    
    # Group by provider for better organization
    providers = {}
    for model_id, model_info in AI_MODELS.items():
        provider = model_info['provider']
        if provider not in providers:
            providers[provider] = []
        providers[provider].append((model_id, model_info))
    
    for provider in sorted(providers.keys()):
        print(f"\n🏢 {provider}:")
        print("-" * 40)
        
        for model_id, model_info in sorted(providers[provider]):
            current = " ✅ CURRENT" if model_info['name'] == MODEL else ""
            print(f"  [{model_id}] {model_info['display_name']}{current}")
            print(f"      Category: {model_info['category']}")
            print(f"      {model_info['description']}")
            print()
    
    print("\n📝 Usage Examples:")
    print("  model set ds1              - Switch to DeepSeek Chat v3")
    print("  model set ll1              - Switch to LLaMA 3.3 70B")
    print("  model search code          - Find coding models")
    print("="*80)

def _search_models(search_term: str):
    """Search for models by provider, category, or description."""
    matches = []
    search_term = search_term.lower()
    
    for model_id, model_info in AI_MODELS.items():
        # Search in provider, category, display_name, description
        searchable = f"{model_info['provider']} {model_info['category']} {model_info['display_name']} {model_info['description']}".lower()
        
        if search_term in searchable:
            matches.append((model_id, model_info))
    
    if not matches:
        print_with_rich(f"❌ No models found matching '{search_term}'", "warning")
        print_with_rich("💡 Try searching for: deepseek, llama, mistral, google, openai, chat, code, large, small", "info")
        return
    
    # Display results with full visibility (no hidden content)
    print_with_rich(f"\n🔍 Search Results for '{search_term}' ({len(matches)} found)", "success")
    print("=" * 90)
    
    for model_id, model_info in sorted(matches, key=lambda x: x[1]['provider']):
        current = " ✅ CURRENT" if model_info['name'] == MODEL else ""
        print_with_rich(f"\n[{model_id}] {model_info['display_name']}{current}", "default")
        print_with_rich(f"  🏢 Provider: {model_info['provider']}", "info")
        print_with_rich(f"  🏷️  Category: {model_info['category']}", "info")
        print_with_rich(f"  📝 Description: {model_info['description']}", "default")
        print_with_rich(f"  🔗 Model Path: {model_info['name']}", "warning")
        
        # Show how to use this model
        print_with_rich(f"  ⚡ Quick Use: model set {model_id}", "success")
    
    print("\n" + "=" * 90)

def _search_models_fallback(matches, search_term):
    """Fallback display for non-rich terminals."""
    # Fallback for non-rich terminals
    print(f"\n🔍 Search Results for '{search_term}' ({len(matches)} found):")
    print("=" * 60)
    
    for model_id, model_info in sorted(matches, key=lambda x: x[1]['provider']):
        current = " ✅ CURRENT" if model_info['name'] == MODEL else ""
        print(f"  [{model_id}] {model_info['display_name']}{current}")
        print(f"      Provider: {model_info['provider']} | Category: {model_info['category']}")
        print(f"      {model_info['description']}")
        print()

def model_command(args: List[str]):
    """Comprehensive model management command."""
    global AI_ENABLED, MODEL, API_KEY, current_config
    
    if not args:
        # Show all available models when no args
        _show_available_models()
        return
    
    subcmd = args[0].lower()
    
    if subcmd == "list":
        _model_list()
    elif subcmd == "current":
        _model_current()
    elif subcmd == "set" and len(args) > 1:
        _model_set(args[1])
    elif subcmd == "search" and len(args) > 1:
        _model_search(args[1])
    elif subcmd == "view" and len(args) > 1:
        _model_view(args[1])
    elif subcmd == "categories":
        _model_categories()
    elif subcmd == "providers":
        _model_providers()
    else:
        print_with_rich(f"❌ Unknown model subcommand: {subcmd}", "error")
        print_with_rich("💡 Use 'model' to see available commands", "info")

def _model_list():
    """List all models with clear IDs for selection."""
    print_with_rich(f"\n🤖 Available AI Models ({len(AI_MODELS)} total)", "info")
    print("=" * 80)
    
    # Group models by provider for better organization
    providers = {}
    for model_id, model_info in AI_MODELS.items():
        provider = model_info['provider']
        if provider not in providers:
            providers[provider] = []
        providers[provider].append((model_id, model_info))
    
    current_model_name = MODEL if AI_ENABLED else None
    
    for provider in sorted(providers.keys()):
        print_with_rich(f"\n🏢 {provider.upper()}:", "success")
        print("-" * 50)
        
        for model_id, model_info in sorted(providers[provider]):
            current = " ✅ CURRENT" if model_info['name'] == current_model_name else ""
            
            # Show ID prominently for easy selection
            print_with_rich(f"  🆔 {model_id:<4} → {model_info['display_name']}{current}", "default")
            print_with_rich(f"       📂 Category: {model_info['category']} | 🔗 Path: {model_info['name']}", "info")
            print_with_rich(f"       📝 {model_info['description']}", "default")
            print()
    
    print("=" * 80)
    print_with_rich("💡 To switch models, use: model set <ID>", "info")
    print_with_rich("   Example: model set ds1", "success")

def _model_current():
    """Show current model information."""
    if not AI_ENABLED or not MODEL:
        print_with_rich("❌ No model currently configured", "warning")
        print_with_rich("💡 Use 'model list' to see available models", "info")
        print_with_rich("💡 Use 'model set <id>' to configure a model", "info")
        return
    
    # Find current model info
    current_info = None
    current_id = None
    
    for model_id, model_info in AI_MODELS.items():
        if model_info['name'] == MODEL:
            current_info = model_info
            current_id = model_id
            break
    
    if current_info:
        print_with_rich("\n🤖 Current AI Model", "info")
        print("=" * 40)
        print_with_rich(f"🆔 Model ID: {current_id}", "success")
        print_with_rich(f"📛 Display Name: {current_info['display_name']}", "default")
        print_with_rich(f"🏢 Provider: {current_info['provider']}", "info")
        print_with_rich(f"📂 Category: {current_info['category']}", "info")
        print_with_rich(f"🔗 Model Path: {current_info['name']}", "warning")
        print_with_rich(f"📝 Description: {current_info['description']}", "default")
        print("=" * 40)
    else:
        print_with_rich(f"⚠️  Current model '{MODEL}' not found in model registry", "warning")
        print_with_rich("💡 Use 'model list' to see available models", "info")

def _model_set(model_id: str):
    """Switch to a specific model by ID."""
    global MODEL, current_config, API_BASE
    
    if not current_config:
        current_config = {"api_key": "", "model": "gemini-2.0-flash", "theme": "dark", "prompt_style": "classic"}
    
    model_id = model_id.lower()
    
    if model_id not in AI_MODELS:
        print_with_rich(f"❌ Model ID '{model_id}' not found!", "error")
        print_with_rich("💡 Use 'model list' to see available model IDs", "info")
        
        # Show similar models
        similar = [mid for mid in AI_MODELS.keys() if model_id in mid.lower()]
        if similar:
            print_with_rich(f"🔍 Did you mean: {', '.join(similar[:3])}?", "warning")
        return
    
    model_info = AI_MODELS[model_id]
    old_model = MODEL
    MODEL = model_info['name']
    current_config["model"] = MODEL
    
    # Save configuration to persist the change
    if config_manager:
        success = config_manager.set_value('model', MODEL)
        if not success:
            print_with_rich("⚠️ Warning: Failed to save model configuration", "warning")
        
        # Also save to the appropriate API base-specific key
        if API_BASE == "gemini":
            config_manager.set_value('last_gemini_model', MODEL)
        else:  # openrouter
            config_manager.set_value('last_openrouter_model', MODEL)
    
    print_with_rich(f"✅ Model switched successfully!", "success")
    print()
    print_with_rich(f"🔄 Changed from:", "info")
    if old_model:
        print_with_rich(f"   {old_model}", "warning")
    else:
        print_with_rich(f"   No previous model", "warning")
    
    print_with_rich(f"🎯 Changed to:", "info")
    print_with_rich(f"   🆔 {model_id} → {model_info['display_name']}", "success")
    print_with_rich(f"   🏢 Provider: {model_info['provider']}", "info")
    print_with_rich(f"   📂 Category: {model_info['category']}", "info")
    print_with_rich(f"   🔗 Path: {model_info['name']}", "info")
    print_with_rich(f"   📝 {model_info['description']}", "default")
    print()
    print_with_rich("💡 Use 'model current' to verify the change", "info")

def _model_search(search_term: str):
    """Search models by provider, category, or description."""
    matches = []
    search_term = search_term.lower()
    
    for model_id, model_info in AI_MODELS.items():
        searchable = f"{model_info['provider']} {model_info['category']} {model_info['display_name']} {model_info['description']}".lower()
        
        if search_term in searchable:
            matches.append((model_id, model_info))
    
    if not matches:
        print_with_rich(f"❌ No models found matching '{search_term}'", "warning")
        print_with_rich("💡 Try searching for:", "info")
        print_with_rich("   • Provider names: deepseek, google, meta, mistral, openai, qwen", "default")
        print_with_rich("   • Categories: chat, code, large, medium, small, reasoning", "default")
        print_with_rich("   • Keywords: instruct, turbo, prover, multimodal", "default")
        return
    
    current_model_name = MODEL if AI_ENABLED else None
    
    print_with_rich(f"\n🔍 Search Results for '{search_term}' ({len(matches)} found)", "success")
    print("=" * 70)
    
    for model_id, model_info in sorted(matches, key=lambda x: (x[1]['provider'], x[0])):
        current = " ✅ CURRENT" if model_info['name'] == current_model_name else ""
        
        print_with_rich(f"\n🆔 {model_id} → {model_info['display_name']}{current}", "default")
        print_with_rich(f"   🏢 Provider: {model_info['provider']} | 📂 Category: {model_info['category']}", "info")
        print_with_rich(f"   📝 {model_info['description']}", "default")
        print_with_rich(f"   ⚡ Use: model set {model_id}", "success")
    
    print("\n" + "=" * 70)

def _model_view(model_id: str):
    """View detailed information about a specific model."""
    model_id = model_id.lower()
    
    if model_id not in AI_MODELS:
        print_with_rich(f"❌ Model ID '{model_id}' not found!", "error")
        print_with_rich("💡 Use 'model list' to see available model IDs", "info")
        return
    
    model_info = AI_MODELS[model_id]
    current = "✅ CURRENTLY ACTIVE" if AI_ENABLED and model_info['name'] == MODEL else "⭕ Not active"
    
    print_with_rich(f"\n🔍 Model Details: {model_id.upper()}", "info")
    print("=" * 50)
    print_with_rich(f"🆔 Model ID: {model_id}", "success")
    print_with_rich(f"📛 Display Name: {model_info['display_name']}", "default")
    print_with_rich(f"🏢 Provider: {model_info['provider']}", "info")
    print_with_rich(f"📂 Category: {model_info['category']}", "info")
    print_with_rich(f"🔗 Internal Path: {model_info['name']}", "warning")
    print_with_rich(f"📝 Description: {model_info['description']}", "default")
    print_with_rich(f"🎯 Status: {current}", "success" if "ACTIVE" in current else "warning")
    print("=" * 50)
    
    if AI_ENABLED and model_info['name'] == MODEL:
        print_with_rich("💡 This model is ready to use!", "success")
    else:
        print_with_rich(f"💡 To switch to this model, use: model set {model_id}", "info")

def _model_categories():
    """Show models grouped by category."""
    categories = {}
    
    for model_id, model_info in AI_MODELS.items():
        cat = model_info['category']
        if cat not in categories:
            categories[cat] = []
        categories[cat].append((model_id, model_info))
    
    current_model_name = MODEL if AI_ENABLED else None
    
    print_with_rich(f"\n📂 Models by Category ({len(categories)} categories)", "info")
    print("=" * 60)
    
    for category in sorted(categories.keys()):
        models = categories[category]
        print_with_rich(f"\n📂 {category.upper()} ({len(models)} models):", "success")
        print("-" * 40)
        
        for model_id, model_info in sorted(models):
            current = " ✅" if model_info['name'] == current_model_name else "  "
            print_with_rich(f"  {current} 🆔 {model_id:<4} → {model_info['display_name']}", "default")
            print_with_rich(f"        🏢 {model_info['provider']} | Use: model set {model_id}", "info")
    
    print("\n" + "=" * 60)

def _model_providers():
    """Show models grouped by provider."""
    providers = {}
    
    for model_id, model_info in AI_MODELS.items():
        provider = model_info['provider']
        if provider not in providers:
            providers[provider] = []
        providers[provider].append((model_id, model_info))
    
    current_model_name = MODEL if AI_ENABLED else None
    
    print_with_rich(f"\n🏢 Models by Provider ({len(providers)} providers)", "info")
    print("=" * 60)
    
    for provider in sorted(providers.keys()):
        models = providers[provider]
        print_with_rich(f"\n🏢 {provider.upper()} ({len(models)} models):", "success")
        print("-" * 40)
        
        for model_id, model_info in sorted(models):
            current = " ✅" if model_info['name'] == current_model_name else "  "
            print_with_rich(f"  {current} 🆔 {model_id:<4} → {model_info['display_name']}", "default")
            print_with_rich(f"        📂 {model_info['category']} | Use: model set {model_id}", "info")
    
    print("\n" + "=" * 60)


def theme_command(args: List[str]):
    """Manage UI themes."""
    global current_config
    
    if not current_config:
        current_config = {"api_key": "", "model": "gemini-2.0-flash", "theme": "matrix", "prompt_style": "hacker"}
    
    if not args:
        # Show available themes and current theme
        current_theme = config_state.theme
        print_with_rich(f"🎨 Current theme: {current_theme}", "success")
        print_with_rich(f"\n🎨 Available themes ({len(THEMES)}):" , "info")
        
        # Group themes by type for better display
        theme_groups = {
            "Basic": ["dark", "light"],
            "Tech": ["hacker_green", "matrix", "cyberpunk", "terminal_green"],
            "Colors": ["retro", "neon", "rainbow", "purple", "cherry", "mint"],
            "Nature": ["ocean", "sunset", "forest", "winter", "spring", "summer"],
            "Professional": ["grayscale", "royal", "coffee", "professional"]
        }
        
        for group_name, theme_list in theme_groups.items():
            print_with_rich(f"\n📂 {group_name}:", "success")
            for theme in theme_list:
                if theme in THEMES:
                    current_marker = " ✅" if theme == current_theme else "  "
                    desc = THEME_DESCRIPTIONS.get(theme, "")
                    if desc:
                        print_with_rich(f"{current_marker} {theme:<15} - {desc}", "default")
                    else:
                        print_with_rich(f"{current_marker} {theme}", "default")
        
        # Show remaining themes not in groups
        remaining = [t for t in THEMES.keys() if not any(t in group for group in theme_groups.values())]
        if remaining:
            print_with_rich(f"\n📂 Other:", "success")
            for theme in remaining:
                current_marker = " ✅" if theme == current_theme else "  "
                desc = THEME_DESCRIPTIONS.get(theme, "")
                if desc:
                    print_with_rich(f"{current_marker} {theme:<15} - {desc}", "default")
                else:
                    print_with_rich(f"{current_marker} {theme}", "default")
        
        print_with_rich(f"\nUsage: theme <name>  (e.g., 'theme matrix')", "info")
        return
    
    # Subcommands: reset
    if args[0] == "reset":
        default_theme = "matrix"
        if config_manager:
            print_with_rich("🔄 Resetting theme to default (matrix)...", "info")
            success = config_manager.set_value('theme', default_theme)
            if success:
                config_state._theme = default_theme
                if current_config:
                    current_config["theme"] = default_theme
                print_with_rich("✅ Theme reset to default: matrix", "success")
            else:
                print_with_rich("❌ Failed to reset theme in configuration", "error")
                print_with_rich("Theme may not persist after restart", "warning")
        else:
            print_with_rich("⚠️ No config manager available - using fallback", "warning")
            config_state.theme = default_theme
            if current_config:
                current_config["theme"] = default_theme
            print_with_rich("✅ Theme reset to default: matrix", "success")
        return
    
    theme = args[0]
    if theme in THEMES:
        old_theme = config_state.theme
        
        # Save via config_manager directly
        if config_manager:
            print_with_rich(f"💾 Saving theme '{theme}' to configuration...", "info")
            success = config_manager.set_value('theme', theme)
            if success:
                # Only update config_state if save succeeded
                config_state._theme = theme  # Direct assignment to avoid double-save
                if current_config:
                    current_config["theme"] = theme
                print_with_rich(f"✅ Theme switched to: {theme}", "success")
                print_with_rich(f"💾 Theme saved to: ~/.config-vritrasecz/vritraai/config.json", "info")
            else:
                print_with_rich(f"❌ Failed to save theme configuration", "error")
                try:
                    info = config_manager.get_config_info()
                    cfg_path = info.get('config_file')
                    if cfg_path:
                        print_with_rich(f"  Config file: {cfg_path}", "warning")
                except Exception:
                    pass
                print_with_rich(f"Theme changed in memory but will NOT persist after restart", "warning")
                print_with_rich("Check file permissions and disk space for the config directory.", "info")
                return
        else:
            # No config manager - try legacy method
            print_with_rich("⚠️ No config manager available - using fallback", "warning")
            config_state.theme = theme  # Use property setter
            if current_config:
                current_config["theme"] = theme
            print_with_rich(f"🎨 Theme switched to: {theme}", "success")
            print_with_rich("⚠️ Warning: Configuration manager not available, changes may not persist", "warning")
        
        # Show preview of the new theme
        print_with_rich(f"Preview of {theme} theme:", "info")
        theme_colors = THEMES[theme]
        for color_name, color_code in theme_colors.items():
            if color_name in ["prompt_user", "error", "success", "warning", "info"]:
                print_with_rich(f"  {color_name}: Sample text", color_name.replace("prompt_", ""))
    else:
        print_with_rich(f"❌ Unknown theme: {theme}", "error")
        print_with_rich(f"💡 Use 'theme' to see available themes", "info")


def banner_command(args: List[str]):
    """Manage MOTD / welcome banners."""
    if not args or args[0] in ("help", "-h", "--help"):
        print_with_rich("📜 Banner Management:", "info")
        print_with_rich("  banner                 - Show this help", "info")
        print_with_rich("  banner list            - List available banner IDs", "info")
        print_with_rich("  banner set <id>        - Set a specific banner", "info")
        print_with_rich("  banner random          - Enable random banner on each startup", "info")
        print_with_rich("  banner reset           - Reset to default banner (1)", "info")
        print_with_rich("  banner preview <id>    - Preview banner without saving", "info")
        print_with_rich("  banner sync on|off     - Toggle theme-synced vs hardcoded colors", "info")
        return

    subcmd = args[0]

    if subcmd == "list":
        print_with_rich("Available banners:", "info")
        for banner_id in sorted(BANNERS.keys(), key=lambda x: int(x)):
            name = BANNERS[banner_id].get("name", f"Banner {banner_id}")
            print_with_rich(f"  {banner_id}: {name}", "success")
    elif subcmd == "set":
        if len(args) < 2:
            print_with_rich("Usage: banner set <banner_id>", "info")
            return
        banner_id = args[1]
        if banner_id not in BANNERS:
            print_with_rich(f"❌ Unknown banner ID: {banner_id}", "error")
            print_with_rich("Use 'banner list' to see valid IDs", "info")
            return
        set_banner_config(banner_id=banner_id, banner_random=False)
        print_with_rich(f"✅ Banner set to {banner_id}", "success")
    elif subcmd == "random":
        set_banner_config(banner_random=True)
        print_with_rich("🎲 Banner will now be random on each startup", "success")
    elif subcmd == "reset":
        set_banner_config(banner_id="1", banner_random=False)
        print_with_rich("✅ Banner reset to default (1)", "success")
    elif subcmd == "preview":
        if len(args) < 2:
            print_with_rich("Usage: banner preview <banner_id>", "info")
            return
        banner_id = args[1]
        if banner_id not in BANNERS:
            print_with_rich(f"❌ Unknown banner ID: {banner_id}", "error")
            return
        print_with_rich(f"📄 Previewing banner {banner_id} (not saved)", "warning")
        render_banner(banner_id)
    elif subcmd == "sync":
        # Toggle between theme-synced (Rich) and hardcoded ANSI-colored banners
        if len(args) < 2 or args[1].lower() not in ("on", "off"):
            print_with_rich("Usage: banner sync on|off", "info")
            return
        mode = args[1].lower()
        sync_on = mode == "on"
        set_banner_config(banner_sync=sync_on)
        if sync_on:
            print_with_rich("🎨 Banner coloring synced with current theme (Rich)", "success")
        else:
            print_with_rich("🌈 Using hardcoded ANSI-colored banners", "success")
    else:
        print_with_rich(f"Unknown banner command: {subcmd}", "error")
        banner_command(["help"])


# Duplicate apikey_command removed - using the existing comprehensive implementation

def config_command(args: List[str]):
    """Show current VritraAI configuration."""
    global AI_ENABLED, MODEL, API_KEY, current_config, GEMINI_API_KEY
    
    if not current_config:
        current_config = {"api_key": "", "model": "gemini-2.0-flash", "theme": "matrix", "prompt_style": "hacker"}
    
    # Always show current configuration (no subcommands)
    print_with_rich("🔧 VritraAI Configuration", "success")
    print("═" * 50)
    
    # API Configuration
    print_with_rich("\n🤖 VritraAI Configuration:", "info")
    print_with_rich(f"  API Base: {API_BASE}", "default")
    print_with_rich(f"  AI Enabled: {'✅ Yes' if AI_ENABLED else '❌ No'}", "success" if AI_ENABLED else "error")
    
    if AI_ENABLED and MODEL:
        # Try to get model display name
        model_display = MODEL
        for model_id, model_info in AI_MODELS.items():
            if model_info['name'] == MODEL:
                model_display = f"{model_info['display_name']} ({model_id})"
                break
        print_with_rich(f"  Current Model: {model_display}", "default")
    else:
        print_with_rich(f"  Current Model: None", "default")
    
    # API Key status
    if API_BASE == "gemini":
        key_status = "✅ Configured" if GEMINI_API_KEY else "❌ Not configured"
        print_with_rich(f"  Gemini API Key: {key_status}", "success" if GEMINI_API_KEY else "error")
    else:
        key_status = "✅ Configured" if API_KEY else "❌ Not configured"
        print_with_rich(f"  OpenRouter API Key: {key_status}", "success" if API_KEY else "error")
    
    # UI Configuration
    print_with_rich("\n🎨 UI Configuration:", "info")
    current_theme = config_state.theme
    current_prompt = config_state.prompt_style
    print_with_rich(f"  Theme: {current_theme}", "default")
    print_with_rich(f"  Prompt Style: {current_prompt}", "default")

    # Banner configuration
    banner_id, banner_random = get_banner_config()
    banner_info = BANNERS.get(str(banner_id), {})
    banner_name = banner_info.get("name", f"Banner {banner_id}")
    mode_label = "Random" if banner_random else "Fixed"
    # Banner sync mode (shown as part of UI configuration)
    try:
        if config_manager:
            banner_sync = bool(config_manager.get_value("banner_sync", True))
        else:
            banner_sync = bool(current_config.get("banner_sync", True)) if current_config else True
    except Exception:
        banner_sync = True
    sync_label = "Theme-synced (Rich colors)" if banner_sync else "Hardcoded ANSI colors"

    # Show banner-related UI options together
    print_with_rich(f"  Banner: {banner_id} – {banner_name}", "default")
    print_with_rich(f"  Banner Mode: {mode_label}", "default")
    print_with_rich(f"  Banner Colors: {sync_label}", "default")
    
    # System Configuration
    print_with_rich("\n⚙️ System Configuration:", "info")
    safe_mode = current_config.get('safe_mode', True)
    auto_backup = current_config.get('auto_backup', True)
    print_with_rich(f"  Safe Mode: {'✅ Enabled' if safe_mode else '❌ Disabled'}", "success" if safe_mode else "warning")
    print_with_rich(f"  Auto Backup: {'✅ Enabled' if auto_backup else '❌ Disabled'}", "success" if auto_backup else "warning")
    
    # Configuration file info
    if config_manager:
        config_info = config_manager.get_config_info()
        print_with_rich("\n📁 Configuration Files:", "info")
        print_with_rich(f"  Config File: {config_info['config_file']}", "default")
        print_with_rich(f"  Backup Exists: {'✅ Yes' if config_info['backup_exists'] else '❌ No'}", "success" if config_info['backup_exists'] else "warning")
        print_with_rich(f"  Last Updated: {config_info.get('last_updated', 'Unknown')}", "default")
        print_with_rich(f"  Updates Count: {config_info.get('update_count', 0)}", "default")
    
    # Show available commands
    print_with_rich("\n💡 Related Commands:", "info")
    print_with_rich("  model          - Manage AI models", "default")
    print_with_rich("  theme          - Change UI themes", "default")
    print_with_rich("  apikey         - Manage API keys", "default")
    print_with_rich("  safe_mode      - Control safe mode (dangerous command protection)", "default")
    
    print("═" * 50)

def safe_mode_command(args: List[str]):
    """Control safe mode setting."""
    global current_config
    
    if not args:
        # Show current safe mode status
        safe_mode = current_config.get('safe_mode', True) if current_config else True
        status = "✅ Enabled" if safe_mode else "❌ Disabled"
        color = "success" if safe_mode else "warning"
        print_with_rich(f"🛡️  Safe Mode: {status}", color)
        print_with_rich("\nSafe mode protects you from potentially dangerous commands by asking for confirmation.", "info")
        print_with_rich("\n📋 Manage Safe Mode:", "info")
        print_with_rich("  safe_mode on      - Enable safe mode", "default")
        print_with_rich("  safe_mode off     - Disable safe mode", "default")
        print_with_rich("  safe_mode enable  - Enable safe mode (alias)", "default")
        print_with_rich("  safe_mode disable - Disable safe mode (alias)", "default")
        return
    
    subcmd = args[0].lower()
    
    if subcmd in ["on", "enable", "true", "1"]:
        new_value = True
        action = "enabled"
    elif subcmd in ["off", "disable", "false", "0"]:
        new_value = False
        action = "disabled"
    else:
        print_with_rich(f"Unknown option: {subcmd}", "error")
        print_with_rich("Usage: safe_mode [on|off|enable|disable]", "info")
        return
    
    # Update config
    if not current_config:
        current_config = {}
    
    current_config['safe_mode'] = new_value
    
    # Save to config
    try:
        if config_manager:
            success = config_manager.set_value('safe_mode', new_value)
            if success:
                print_with_rich(f"🛡️  Safe mode {action} successfully!", "success" if new_value else "warning")
            else:
                print_with_rich("⚠️  Failed to save safe mode setting", "error")
        else:
            from config import save_config
            if save_config(current_config):
                print_with_rich(f"🛡️  Safe mode {action} successfully!", "success" if new_value else "warning")
            else:
                print_with_rich("⚠️  Failed to save safe mode setting", "error")
    except Exception as e:
        print_with_rich(f"⚠️  Error saving safe mode: {e}", "error")

def network_check() -> bool:
    """Check if network/internet connection is available."""
    import socket
    
    # List of reliable servers to test connectivity
    test_servers = [
        ("8.8.8.8", 53),      # Google DNS
        ("1.1.1.1", 53),      # Cloudflare DNS
        ("8.8.4.4", 53),      # Google DNS Secondary
    ]
    
    for server, port in test_servers:
        try:
            socket.create_connection((server, port), timeout=2)
            return True
        except OSError:
            continue
    
    return False

def check_internet_for_ai() -> tuple[bool, str]:
    """Check internet connectivity specifically for AI operations.
    
    Returns:
        tuple: (is_connected, message)
    """
    if not network_check():
        return False, "No internet connection detected. AI features require internet access."
    
    # Test provider-specific connectivity
    import socket
    host = "openrouter.ai" if API_BASE != "gemini" else "generativelanguage.googleapis.com"
    try:
        socket.create_connection((host, 443), timeout=5)
        return True, f"Internet and AI service ({'OpenRouter' if API_BASE != 'gemini' else 'Gemini'}) connectivity confirmed"
    except OSError:
        return False, f"Internet available but AI service ({'OpenRouter' if API_BASE != 'gemini' else 'Gemini'}) unreachable."

def handle_network_error(operation_name: str) -> bool:
    """Handle network errors with user-friendly messages and options.
    
    Args:
        operation_name: Description of the operation that failed
    
    Returns:
        bool: True if user wants to retry, False otherwise
    """
    print_with_rich(f"\n🌐 NETWORK ERROR", "error")
    print_with_rich(f"Operation: {operation_name}", "warning")
    print_with_rich("Internet connection is required but not available", "error")
    
    # Show network troubleshooting options
    print_with_rich("\n🔧 TROUBLESHOOTING OPTIONS:", "info")
    print_with_rich("  1. Check your internet connection", "default")
    print_with_rich("  2. Retry the operation", "default")
    print_with_rich("  3. Use offline mode (limited functionality)", "default")
    print_with_rich("  4. Cancel operation", "default")
    
    try:
        choice = input("\nChoose option (1-4): ").strip()
        
        if choice == "1":
            # Run basic connectivity test
            print_with_rich("\n🔍 Testing connectivity...", "info")
            if network_check():
                print_with_rich("✅ Internet connection restored!", "success")
                return True
            else:
                print_with_rich("❌ Still no internet connection", "error")
                print_with_rich("Please check your network settings and try again", "warning")
                return False
        elif choice == "2":
            print_with_rich("🔄 Retrying operation...", "info")
            return True
        elif choice == "3":
            print_with_rich("⚙️ Switching to offline mode", "warning")
            print_with_rich("Note: AI features will be unavailable", "warning")
            global AI_ENABLED
            AI_ENABLED = False
            return False
        else:
            print_with_rich("❌ Operation cancelled", "error")
            return False
            
    except (EOFError, KeyboardInterrupt):
        print_with_rich("\n❌ Operation aborted by user", "error")
        return False
    except Exception as recovery_error:
        print_with_rich(f"\n⚠️ Error in recovery handler: {recovery_error}", "warning")
        return False


def collect_feedback_system_info() -> Dict[str, Any]:
    """Collect system snapshot for feedback report.

    Uses environment inspection similar to form_test.py but wired to
    VritraAI's central config and version constant.
    """
    env = os.environ
    os_name = platform.system().lower()

    prefix = env.get("PREFIX", "")
    is_termux = "TERMUX_VERSION" in env or prefix.startswith("/data/data/com.termux")
    is_android = bool(env.get("ANDROID_ROOT") or env.get("ANDROID_DATA"))
    is_wsl = bool(env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"))

    if is_termux:
        platform_label = "Termux (Android)"
    elif os_name == "linux" and is_wsl:
        platform_label = "WSL (Windows Subsystem for Linux)"
    elif os_name == "linux" and is_android:
        platform_label = "Android (Linux)"
    elif os_name == "linux":
        if env.get("DISPLAY") or env.get("WAYLAND_DISPLAY") or env.get("XDG_CURRENT_DESKTOP"):
            platform_label = "Linux Desktop"
        else:
            platform_label = "Linux Server/CLI"
    elif os_name == "darwin":
        platform_label = "macOS Desktop"
    elif os_name == "windows":
        platform_label = "Windows Desktop"
    else:
        platform_label = "Unknown"

    # Report Android as OS when running under Termux / Android
    if is_termux or (os_name == "linux" and is_android):
        reported_os = "android"
    else:
        reported_os = os_name

    cfg = current_config or {}

    return {
        "os": reported_os,
        "platform": platform_label,
        "python": platform.python_version(),
        "shell": env.get("SHELL", "unknown"),
        "cwd": os.getcwd(),
        "version": VRITRA_VERSION,
        "config": {
            "banner_id": cfg.get("banner_id"),
            "theme": cfg.get("theme", getattr(config_state, "theme", None)),
            "prompt_style": cfg.get("prompt_style", getattr(config_state, "prompt_style", None)),
            "model": cfg.get("model", MODEL),
            "api_base": cfg.get("api_base", API_BASE),
            "safe_mode": cfg.get("safe_mode"),
            "ai_enabled": cfg.get("ai_enabled", AI_ENABLED),
        },
    }


def _feedback_input(prompt_text: str) -> str:
    """Input helper that supports line editing (left/right arrows, etc.).

    Tries to use prompt_toolkit for a better editing experience and
    falls back to built-in input() if anything goes wrong.
    """
    try:
        from prompt_toolkit import prompt as pt_prompt  # type: ignore
        return pt_prompt(prompt_text)
    except Exception:
        return input(prompt_text)


def ask_feedback_form() -> Dict[str, Any]:
    """Interactive feedback form inside VritraAI shell."""

    print_with_rich("\n🤖 How was your experience with VritraAI today?", "info")
    print_with_rich("[1] Excellent ⭐", "default")
    print_with_rich("[2] Good 👍", "default")
    print_with_rich("[3] Average 😐", "default")
    print_with_rich("[4] Poor 👎", "default")
    print_with_rich("[5] Suggestion / Message ✍️", "default")

    choice = _feedback_input("\nEnter option (1-5): ").strip()

    experience_map = {
        "1": "Excellent ⭐",
        "2": "Good 👍",
        "3": "Average 😐",
        "4": "Poor 👎",
        "5": "Suggestion / Message ✍️",
    }

    experience = experience_map.get(choice, "Not Provided")

    message = _feedback_input("\n💬 Message (optional): ").strip()
    suggestion = _feedback_input("📝 Suggestion (optional): ").strip()
    email = _feedback_input("📧 Email (optional): ").strip()

    feedback_data = {
        "tool": "VritraAI Professional Shell",
        "version": VRITRA_VERSION,
        "vritraai_experience": experience,
        "message": message or None,
        "suggestion": suggestion or None,
        "email": email or None,
        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "system": collect_feedback_system_info(),
    }

    return feedback_data


def send_feedback(data: Dict[str, Any], debug: bool = False) -> bool:
    """Send feedback to configured Cloudflare Worker or just preview JSON.

    The worker URL is read from the central config (key: 'feedback_worker_url').
    """

    if debug:
        try:
            pretty = json.dumps(data, indent=4)
        except TypeError:
            pretty = str(data)
        print_with_rich("\n🟦 FEEDBACK DATA PREVIEW (NOT SENT)", "info")
        print(pretty)
        print_with_rich("\n🟩 Preview complete. Nothing was sent.\n", "success")
        return True

    # Normal send mode
    worker_url = None
    try:
        if config_manager:
            worker_url = config_manager.get_value("feedback_worker_url", None)
        elif current_config:
            worker_url = current_config.get("feedback_worker_url")
    except Exception:
        worker_url = None

    if not worker_url:
        print_with_rich("❌ Feedback worker URL not configured (feedback_worker_url)", "error")
        print_with_rich("💡 Add it to your config.json to enable live sending.", "info")
        return False

    try:
        resp = requests.post(worker_url, json=data, timeout=10)
        if resp.status_code == 200:
            print_with_rich("\n✅ Feedback sent successfully! Thank you for helping improve VritraAI.", "success")
            return True
        else:
            print_with_rich(f"❌ Worker error: {resp.status_code} {resp.text}", "error")
            return False
    except Exception as e:
        print_with_rich(f"❌ Failed to send feedback: {e}", "error")
        return False


def feedback_command(args: List[str]):
    """Launch interactive feedback form and send it to the configured worker.

    Usage:
      feedback           -> collect feedback and send to worker (if configured)
    """
    feedback = ask_feedback_form()
    send_feedback(feedback, debug=False)


def check_package_installed(package_name: str) -> bool:
    """Check if a package/command is installed."""
    return shutil.which(package_name) is not None

def suggest_package_install(package_name: str) -> str:
    """Suggest how to install a missing package based on OS."""
    os_type = platform.system().lower()
    
    if os_type == "windows":
        return f"Install via: winget install {package_name} or choco install {package_name}"
    elif os_type == "darwin":  # macOS
        return f"Install via: brew install {package_name}"
    elif os_type == "linux":
        return f"Install via: sudo apt install {package_name} or sudo yum install {package_name}"
    else:
        return f"Please install {package_name} using your system's package manager"

def network_command(args: List[str]):
    """Handle network-related commands."""
    if not args:
        # Basic network status
        if network_check():
            print_with_rich("✅ Internet connection: Available", "success")
        else:
            print_with_rich("❌ Internet connection: Not available", "error")
        
        # Show IP addresses
        try:
            import socket
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            print_with_rich(f"🏠 Local IP: {local_ip}", "info")
            print_with_rich(f"🖥️  Hostname: {hostname}", "info")
        except Exception as e:
            print_with_rich(f"Error getting network info: {e}", "error")
        return
    
    subcmd = args[0]
    if subcmd == "check":
        if network_check():
            print_with_rich("✅ Network connection is working", "success")
        else:
            print_with_rich("❌ No network connection detected", "error")
    
    elif subcmd == "ip":
        # Show detailed IP information
        if platform.system() == "Windows":
            execute_command("ipconfig")
        else:
            execute_command("ip addr show" if check_package_installed("ip") else "ifconfig")
    
    elif subcmd == "ping" and len(args) > 1:
        target = args[1]
        if check_package_installed("ping"):
            execute_command(f"ping {target} -c 4" if platform.system() != "Windows" else f"ping {target} -n 4")
        else:
            print_with_rich("Ping command not available", "error")
    
    elif subcmd == "port" and len(args) > 2:
        # Port scanning
        host = args[1]
        port = args[2]
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((host, int(port)))
            sock.close()
            
            if result == 0:
                print_with_rich(f"✅ Port {port} is open on {host}", "success")
            else:
                print_with_rich(f"❌ Port {port} is closed on {host}", "error")
        except Exception as e:
            print_with_rich(f"Error checking port: {e}", "error")
    
    elif subcmd == "speed":
        # Internet speed test
        if not network_check():
            print_with_rich("❌ No internet connection", "error")
            return
        
        if check_package_installed("speedtest-cli"):
            execute_command("speedtest-cli")
        else:
            print_with_rich("speedtest-cli not installed. Installing...", "info")
            if AI_ENABLED:
                ai_command("install speedtest tool and run internet speed test")
            else:
                print_with_rich(suggest_package_install("speedtest-cli"), "info")
    
    else:
        print_with_rich("Usage: network [check|ip|ping <host>|port <host> <port>|speed]", "info")

# Tool command removed as per user request

def learn_command(args: List[str]):
    """AI-powered learning assistant."""
    if not AI_ENABLED:
        print_with_rich("AI is required for learning features", "warning")
        return
    
    if not args:
        print_with_rich("Usage: learn <topic>", "info")
        print_with_rich("Examples: learn 'bash loops', learn 'git rebase', learn 'python decorators'", "info")
        return
    
    topic = " ".join(args)
    
    prompt = f"""Teach me about {topic} in a practical way. Include:
    1. Brief explanation
    2. Common use cases
    3. Practical examples with code
    4. Best practices or tips
    5. Common mistakes to avoid
    
    Keep it concise but informative, suitable for terminal display."""
    
    print_with_rich(f"🎓 Learning about: {topic}...", "info")
    explanation = get_ai_response(prompt)
    
    if explanation:
        # Clean formatting - remove borders and clean markdown
        cleaned_explanation = clean_ai_response(explanation)
        print_with_rich(f"\n🎓 Learning: {topic}\n", "info")
        # Use streaming effect for better readability
        print_ai_response(cleaned_explanation, use_typewriter=True)
        
        # Save to learning notes
        try:
            with open(LEARNING_FILE, 'a', encoding='utf-8') as f:
                f.write(f"\n## {topic}\n\n{explanation}\n\n---\n")
            print_with_rich(f"📝 Learning notes saved to {LEARNING_FILE}", "info")
        except Exception as e:
            print_with_rich(f"Could not save learning notes: {e}", "warning")

# Old theme_command removed - replaced with new implementation above

def prompt_command(args: List[str]):
    """Manage prompt styles."""
    if not args:
        print_with_rich(f"Current prompt style: {config_state.prompt_style}", "info")
        print_with_rich("\nAvailable prompt styles:", "info")
        
        if RICH_AVAILABLE and console:
            from rich.table import Table
            table = Table(show_header=True, header_style="bold blue")
            table.add_column("Style", style="cyan")
            table.add_column("Description", style="white")
            
            for style_name, style_info in PROMPT_STYLES.items():
                current_marker = " (current)" if style_name == config_state.prompt_style else ""
                table.add_row(f"{style_name}{current_marker}", style_info["description"])
            
            console.print(table)
        else:
            for style_name, style_info in PROMPT_STYLES.items():
                current_marker = " (current)" if style_name == config_state.prompt_style else ""
                print_with_rich(f"  {style_name}{current_marker}: {style_info['description']}", "info")
        return
    
    # Subcommand: reset
    if args[0].lower() == "reset":
        default_prompt = "hacker"
        # Prefer config_manager if available
        if config_manager:
            print_with_rich("🔄 Resetting prompt style to default (hacker)...", "info")
            success = config_manager.set_value('prompt_style', default_prompt)
            if success:
                config_state._prompt_style = default_prompt
                if current_config:
                    current_config["prompt_style"] = default_prompt
                print_with_rich("✅ Prompt style reset to default: hacker", "success")
            else:
                print_with_rich("❌ Failed to reset prompt style in configuration", "error")
                print_with_rich("Prompt style may not persist after restart", "warning")
        else:
            # Fallback: set via config_state, then legacy save
            print_with_rich("⚠️ No config manager available - using fallback", "warning")
            config_state.prompt_style = default_prompt
            if current_config:
                current_config["prompt_style"] = default_prompt
            print_with_rich("✅ Prompt style reset to default: hacker", "success")
        return
    
    style = args[0].lower()
    if style in PROMPT_STYLES:
        config_state.prompt_style = style
        print_with_rich(f"Prompt style changed to: {style}", "success")
        print_with_rich(f"Description: {PROMPT_STYLES[style]['description']}", "info")
    else:
        print_with_rich(f"Unknown prompt style: {style}. Available: {', '.join(PROMPT_STYLES.keys())}", "error")

def optimize_command(args: List[str]):
    """Optimize system and clean up files."""
    if not AI_ENABLED:
        print_with_rich("AI is required for system optimization", "warning")
        return
    
    print_with_rich("🛠️  Running system optimization...", "info")
    
    # Basic cleanup tasks
    cleanup_items = [
        "Temporary files",
        "Cache directories", 
        "Log files (older than 7 days)",
        "Unused dependencies",
        "Duplicate files"
    ]
    
    for item in cleanup_items:
        print_with_rich(f"  Checking: {item}", "info")
    
    if AI_ENABLED:
        ai_command("suggest system optimization commands for my OS and provide cleanup script")

def analyze_system_command(args: List[str]):
    """Analyze system performance and usage."""
    print_with_rich("🔍 System Analysis Report:", "info")
    
    try:
        # Disk usage
        import shutil
        disk_info = safe_stat(lambda: shutil.disk_usage("."), None)
        if disk_info is None or disk_info == "N/A":
            print_with_rich("Disk Usage: N/A", "warning")
        else:
            total, used, free = disk_info
            print_with_rich(f"Disk Usage: {used//1024//1024//1024}GB used / {total//1024//1024//1024}GB total", "info")
        
        # Memory info if psutil available
        try:
            import psutil
            import warnings
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=RuntimeWarning)
                memory = safe_stat(lambda: psutil.virtual_memory(), None)
                cpu_percent = safe_stat(lambda: psutil.cpu_percent(interval=1), None)
                
                if memory is None or memory == "N/A":
                    print_with_rich("Memory: N/A", "warning")
                else:
                    print_with_rich(f"Memory: {memory.percent}% used ({memory.available//1024//1024}MB free)", "info")
                
                if cpu_percent is None or cpu_percent == "N/A":
                    print_with_rich("CPU Usage: N/A", "warning")
                else:
                    print_with_rich(f"CPU Usage: {cpu_percent}%", "info")
                
                # Top processes
                try:
                    processes = safe_stat(lambda: sorted(psutil.process_iter(['pid', 'name', 'cpu_percent']), 
                                         key=lambda x: x.info['cpu_percent'] or 0, reverse=True)[:5], [])
                    if processes and processes != "N/A":
                        print_with_rich("Top CPU processes:", "info")
                        for proc in processes:
                            print_with_rich(f"  {proc.info['name']}: {proc.info['cpu_percent']}%", "info")
                except Exception:
                    pass
                    
        except ImportError:
            print_with_rich("Install psutil for detailed system stats: pip install psutil", "warning")
        
        # File count in current directory
        try:
            file_count = len([f for f in os.listdir(".") if os.path.isfile(f)])
            dir_count = len([d for d in os.listdir(".") if os.path.isdir(d)])
            print_with_rich(f"Current directory: {file_count} files, {dir_count} directories", "info")
        except Exception:
            print_with_rich("Current directory: N/A", "warning")
        
    except Exception:
        print_with_rich("Error analyzing system: Some information unavailable", "warning")

def cheat_command(args: List[str]):
    """Show cheatsheet for commands or topics."""
    if not AI_ENABLED:
        print_with_rich("AI is required for cheatsheets", "warning")
        return
    
    if not args:
        print_with_rich("Usage: cheat <topic>", "info")
        print_with_rich("Examples: cheat git, cheat docker, cheat vim", "info")
        return
    
    topic = " ".join(args)
    
    prompt = f"""Create a comprehensive cheatsheet for {topic}. Include:
1. Most commonly used commands with clear explanations
2. Practical usage examples
3. Important options and flags
4. Tips and best practices

IMPORTANT FORMATTING RULES:
- Use plain text WITHOUT code blocks or backticks
- Do NOT use ``` or ` anywhere
- Use normal case (not ALL CAPS)
- Use section headers ending with colon (:)
- Use bullet points with - or *
- Write commands and examples in normal text
- Keep it well-organized and readable"""
    
    print_with_rich(f"📝 Generating {topic} cheatsheet...", "info")
    cheatsheet = get_ai_response(prompt)
    
    if cheatsheet:
        # Remove all code block markers and backticks for clean output
        cleaned_cheatsheet = clean_ai_response(cheatsheet)
        # Remove any remaining code blocks or backticks
        import re
        cleaned_cheatsheet = re.sub(r'```[a-z]*\n', '', cleaned_cheatsheet)
        cleaned_cheatsheet = re.sub(r'```', '', cleaned_cheatsheet)
        cleaned_cheatsheet = cleaned_cheatsheet.replace('`', '')
        
        # Use streaming output like other AI commands
        print_with_rich(f"\n📝 {topic.title()} Cheatsheet\n", "info")
        print_ai_response(cleaned_cheatsheet, use_typewriter=True)

def project_command(args: List[str]):
    """Handle project-related commands."""
    if not args:
        # Show project info
        project_type = detect_project_type()
        if project_type:
            print_with_rich(f"Current project type: {project_type}", "info")
            print_with_rich(f"Working directory: {os.getcwd()}", "info")
        else:
            print_with_rich("No specific project type detected in current directory", "info")
        return
    
    subcmd = args[0]
    if subcmd == "analyze":
        # Analyze project with AI
        if not AI_ENABLED:
            print_with_rich("AI is required for project analysis but is not enabled.", "warning")
            return
        
        try:
            # Get basic project info
            project_type = detect_project_type()
            cwd = os.getcwd()
            
            print_with_rich(f"🔍 Analyzing project in: {cwd}", "info")
            
            # List main files in the project
            files = []
            try:
                for root, dirs, filenames in os.walk(".", topdown=True):
                    # Skip common build/cache directories
                    dirs[:] = [d for d in dirs if d not in [".git", "__pycache__", "node_modules", ".env", "build", "dist"]]
                    
                    for filename in filenames:
                        if (filename.startswith(".") or 
                            filename.endswith((".pyc", ".pyo", ".log", ".tmp"))):
                            continue
                        files.append(os.path.join(root, filename))
                        if len(files) >= 15:  # Limit to 15 files for the analysis
                            break
                    if len(files) >= 15:
                        break
            except Exception as e:
                print_with_rich(f"Error scanning files: {e}", "warning")
                files = []
            
            # Create a prompt for AI analysis
            file_contents = []
            for file in files[:3]:  # Analyze only first 3 files to avoid token limits
                try:
                    content = read_file_content(file)
                    if content and len(content.strip()) > 0:
                        truncated_content = content[:800]  # Limit content size
                        file_contents.append(f"File: {file}\nContent preview:\n```\n{truncated_content}\n```\n")
                except Exception as e:
                    print_with_rich(f"Warning: Could not read {file}: {e}", "warning")
                    continue
            
            # Build analysis prompt
            files_list = ', '.join(files[:10]) if files else 'No readable files found'
            content_preview = '\n'.join(file_contents) if file_contents else 'No file content available'
            
            prompt = f"""Analyze this project and provide an overview:

Project directory: {cwd}
Detected project type: {project_type or 'Unknown'}
Total files found: {len(files)}

Key files:
{files_list}

Sample content:
{content_preview}

Please provide:
1. Project purpose and functionality
2. Technology stack used
3. Project structure analysis
4. Suggestions for improvement

Keep the analysis concise but informative."""
            
            print_with_rich("🤖 VritraAI is analyzing your project...", "info")
            analysis = get_ai_response(prompt)
            
            if analysis:
                # Clean formatting - remove borders and clean markdown
                cleaned_analysis = clean_ai_response(analysis)
                print_with_rich("\n📊 Project Analysis\n", "info")
                # Use streaming effect for better readability
                print_ai_response(cleaned_analysis, use_typewriter=True)
            else:
                print_with_rich("❌ Failed to get AI analysis", "error")
                
        except Exception as e:
            print_with_rich(f"Error during project analysis: {e}", "error")
            import traceback
            traceback.print_exc()
    else:
        print_with_rich("Usage: project [analyze]", "info")

def ai_command(prompt):
    """Handles commands sent to the AI."""
    if not prompt or not prompt.strip():
        print_with_rich("Please provide a prompt for the AI.", "info")
        return

    # Enhanced AI prompt with comprehensive context
    comprehensive_context = build_comprehensive_context(cwd=os.getcwd(), include_files=True)
    recent_commands = f"Recent commands: {[cmd['command'] for cmd in session.commands_history[-3:]] if session.commands_history else 'None'}"
    
    ai_prompt = f"""You are VritraAI, an intelligent terminal assistant. The user's request is: '{prompt}'

{comprehensive_context}

=== RECENT COMMAND HISTORY ===
{recent_commands}

IMPORTANT: For file creation requests (tools, scripts, programs, web apps, etc.), you MUST respond with ONLY JSON in this exact format:
{{"action": "create_file", "filename": "filename.ext", "content": "complete file content here"}}

CRITICAL RULES FOR FILE CREATION:
1. Respond with ONLY the JSON object - no explanations, no pip install commands, no extra text
2. The content field must contain the COMPLETE, FULLY-FUNCTIONAL, production-ready code
3. For web applications, include ALL necessary code (HTML, CSS, JavaScript) in a SINGLE file
4. NEVER split web apps into separate files - combine everything into one complete HTML file
5. Do NOT mention pip install, dependencies, or setup instructions
6. Do NOT show the JSON to the user - it will be executed automatically
7. The file will be created automatically with the content you provide
8. Make the code complete and ready to use immediately without any modifications

EXAMPLES OF COMPLETE FILE GENERATION:
- Web app request: Create ONE complete HTML file with embedded CSS in <style> and JavaScript in <script> tags
- Python tool: Include ALL functions, error handling, and complete implementation
- Bash script: Include ALL logic, error checking, and full functionality

For directory/folder creation requests, use:
{{"action": "run_command", "command": "mkdir foldername"}}

For other actions:
- Edit file: {{"action": "edit_file", "filename": "name.ext", "changes": "description"}}
- Read file: {{"action": "read_file", "filename": "name.ext"}}
- Run command: {{"action": "run_command", "command": "command to execute"}}
- Search files: {{"action": "search_file", "pattern": "pattern", "target": "path"}}

Examples of requests that need create_file action (RESPOND WITH ONLY JSON):
- "create a python phone lookup tool" - Use JSON with complete code in content
- "generate a network scanner in bash" - Use JSON with complete script
- "make a file that..." - Use JSON with complete code
- "create a tool using python" - Use JSON with complete code
- "build a web app" - Use JSON with ONE complete HTML file containing all HTML, CSS, and JS
- "generate a calculator web app" - Use JSON with complete HTML file with inline CSS and JavaScript

For general questions/explanations, provide helpful text responses.

CRITICAL FORMATTING RULES:
- For text responses (not JSON), provide PLAIN TEXT ONLY - NO MARKDOWN
- NEVER use ```bash, ```python, ```cmd, or any code blocks in text responses
- NEVER use ### headers, ** bold **, * italic *, or [links]()
- NEVER use backticks ` around commands or code
- When suggesting commands, write them as plain text without formatting"""


    generated_response = get_ai_response(ai_prompt)
    if generated_response:
        # First try to parse as JSON for structured actions
        action_handled = False
        try:
            # Clean the response - sometimes it has extra text around JSON
            json_start = generated_response.find('{')
            json_end = generated_response.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_part = generated_response[json_start:json_end]
                data = json.loads(json_part)
                action = data.get("action")

                if action == "create_file":
                    filename = data.get("filename")
                    content = data.get("content", "")
                    if filename and content:
                        # Use smart filename generation to prevent overwrites
                        final_filename = get_smart_filename_for_content(filename, content, prompt)
                        
                        if write_file_content(final_filename, content, create_backup=False):
                            print_with_rich(f"✅ Saved code in {final_filename}", "success")
                            # Track in session
                            if final_filename not in session.modified_files:
                                session.modified_files.append(final_filename)
                            action_handled = True
                            return
                    else:
                        print_with_rich("❌ Missing filename or content in AI response", "error")
                    action_handled = True
                    return  # Successfully handled JSON action
            
                elif action == "edit_file":
                    filename = data.get("filename")
                    changes = data.get("changes", "")
                    if filename and changes:
                        edit_file_command([filename, changes])
                    action_handled = True
                    return
                
                elif action == "read_file":
                    filename = data.get("filename")
                    if filename:
                        read_file_command([filename])
                    action_handled = True
                    return
                
                elif action == "run_command":
                    command = data.get("command")
                    if command:
                        print_with_rich(f"🤖 VritraAI suggests running: {command}", "info")
                        if confirm_action("Execute this command?"):
                            execute_command(command)
                        else:
                            print_with_rich("Command cancelled", "info")
                    action_handled = True
                    return
                
                elif action == "search_file":
                    pattern = data.get("pattern")
                    target = data.get("target", ".")
                    if pattern:
                        search_file_command([pattern, target])
                    action_handled = True
                    return
                
                elif action == "explain":
                    command = data.get("command")
                    if command:
                        explain_command([command])
                    action_handled = True
                    return
                else:
                    # If we reach here, JSON was parsed but no valid action found
                    print_with_rich(f"Unknown action in AI response: {action}", "warning")
                    action_handled = True
                    return  # Return after handling unknown action

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            # Not a JSON response or malformed JSON, proceed as normal text response
            pass
        except KeyboardInterrupt:
            # Don't catch KeyboardInterrupt - let it propagate
            raise
        except Exception as e:
            print_with_rich(f"Error parsing AI response: {e}", "error")
            # Continue with text response instead of crashing
            pass

        # Only show text response if no JSON action was handled
        if not action_handled:
            print_ai_response(generated_response)

            # Check for command suggestions in response (more robust pattern)
            command_patterns = [
                r"```(?:bash|sh|cmd|powershell)?\s*\n(.*?)```",  # Standard code blocks
                r"Command:\s*([^\n]+)",                           # "Command: xyz"
                r"Run:\s*([^\n]+)",                              # "Run: xyz"
                r"Execute:\s*([^\n]+)",                          # "Execute: xyz"
                r"Try:\s*([^\n]+)",                              # "Try: xyz"
                r"Use:\s*([^\n]+)",                              # "Use: xyz"
            ]
            
            suggested_command = None
            for pattern in command_patterns:
                match = re.search(pattern, generated_response, re.DOTALL | re.IGNORECASE)
                if match:
                    suggested_command = match.group(1).strip()
                    # Filter out overly simple or generic suggestions
                    if len(suggested_command) > 2 and not suggested_command.lower() in ['cd', 'ls', 'dir', 'help']:
                        break
                    suggested_command = None

            if suggested_command:
                # Clean up the suggested command
                command_to_execute = suggested_command.strip()
                # Remove any remaining backticks or formatting
                command_to_execute = re.sub(r'^`+|`+$', '', command_to_execute)
                
                print_with_rich("\nThe AI has suggested a command.", "info")
                print_with_rich(f"Suggested: {command_to_execute}", "warning")
                if confirm_action("Execute this command?"):
                    execute_command(command_to_execute)
                else:
                    print_with_rich("Operation cancelled", "info")


def tree_command(args: List[str]):
    """Show directory tree structure."""
    target_dir = args[0] if args else "."
    # Expand ~ and environment variables
    target_dir = expand_path(target_dir)
    max_depth = int(args[1]) if len(args) > 1 and args[1].isdigit() else 3
    
    def print_tree(path, prefix="", depth=0, max_depth=3):
        if depth > max_depth:
            return
        
        try:
            items = sorted(os.listdir(path))
            dirs = [item for item in items if os.path.isdir(os.path.join(path, item)) and not item.startswith('.')]
            files = [item for item in items if os.path.isfile(os.path.join(path, item)) and not item.startswith('.')]
            
            # Print directories first
            for i, dirname in enumerate(dirs):
                is_last_dir = (i == len(dirs) - 1) and len(files) == 0
                print_with_rich(f"{prefix}{'└── ' if is_last_dir else '├── '}📁 {dirname}/", "info")
                
                new_prefix = prefix + ("    " if is_last_dir else "│   ")
                print_tree(os.path.join(path, dirname), new_prefix, depth + 1, max_depth)
            
            # Print files
            for i, filename in enumerate(files):
                is_last = (i == len(files) - 1)
                print_with_rich(f"{prefix}{'└── ' if is_last else '├── '}📄 {filename}", "info")
                
        except PermissionError:
            print_with_rich(f"{prefix}[Permission Denied]", "error")
    
    def show_tree():
        if not os.path.exists(target_dir):
            raise FileNotFoundError(f"Directory not found: {target_dir}")
        print_with_rich(f"📂 {os.path.abspath(target_dir)}", "success")
        print_tree(target_dir, "", 0, max_depth)
        return True
    
    result = execute_with_error_recovery(show_tree, context=f"Showing tree for: {target_dir}")

def find_files_command(args: List[str]):
    """Find files matching pattern."""
    if not args:
        print_with_rich("Usage: find_files <pattern> [directory]", "info")
        print_with_rich("Examples: find_files '*.py', find_files 'test*' /home/user", "info")
        return
    
    pattern = args[0]
    search_dir = args[1] if len(args) > 1 else "."
    
    if not os.path.exists(search_dir):
        print_with_rich(f"Directory not found: {search_dir}", "error")
        return
    
    import fnmatch
    found_files = []
    
    try:
        for root, dirs, files in os.walk(search_dir):
            for filename in files:
                if fnmatch.fnmatch(filename, pattern):
                    found_files.append(os.path.join(root, filename))
    except Exception as e:
        print_with_rich(f"Error searching files: {e}", "error")
        return
    
    if found_files:
        print_with_rich(f"Found {len(found_files)} files matching '{pattern}':", "success")
        for file_path in found_files[:20]:  # Limit to 20 results
            print_with_rich(f"  {file_path}", "info")
        if len(found_files) > 20:
            print_with_rich(f"  ... and {len(found_files) - 20} more files", "warning")
    else:
        print_with_rich(f"No files found matching '{pattern}'", "warning")

def safe_stat(func, default="N/A"):
    """Safely execute a function that might raise permission errors, returning default on failure."""
    try:
        return func()
    except (PermissionError, OSError, IOError):
        return default
    except Exception:
        return default

def sys_info_command(args: List[str]):
    """Show detailed system information."""
    print_with_rich("🖥️  System Information:", "info")
    
    # Basic OS info
    os_info = get_os_info()
    for key, value in os_info.items():
        print_with_rich(f"  {key.title()}: {value}", "info")
    
    # Python info
    print_with_rich(f"  Python Version: {sys.version.split()[0]}", "info")
    
    # Additional system details with safe error handling
    try:
        import psutil
        boot_time = safe_stat(lambda: datetime.datetime.fromtimestamp(psutil.boot_time()), "N/A")
        cpu_cores = safe_stat(lambda: psutil.cpu_count(), "N/A")
        cpu_physical = safe_stat(lambda: psutil.cpu_count(logical=False), "N/A")
        
        if boot_time != "N/A":
            print_with_rich(f"  Boot Time: {boot_time}", "info")
        if cpu_cores != "N/A":
            if cpu_physical != "N/A":
                print_with_rich(f"  CPU Cores: {cpu_cores} ({cpu_physical} physical)", "info")
            else:
                print_with_rich(f"  CPU Cores: {cpu_cores}", "info")
    except ImportError:
        print_with_rich("  Install 'psutil' for more detailed system info", "warning")

def disk_usage_command(args: List[str]):
    """Show disk usage information."""
    target = args[0] if args else "."
    # Expand ~ and environment variables
    target = expand_path(target)
    
    if not os.path.exists(target):
        print_with_rich(f"Path not found: {target}", "error")
        return
    
    try:
        import shutil
        total, used, free = shutil.disk_usage(target)
        
        # Convert to human readable format
        def format_bytes(bytes_val):
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if bytes_val < 1024.0:
                    return f"{bytes_val:.1f} {unit}"
                bytes_val /= 1024.0
            return f"{bytes_val:.1f} PB"
        
        print_with_rich(f"💾 Disk Usage for {os.path.abspath(target)}:", "info")
        print_with_rich(f"  Total: {format_bytes(total)}", "info")
        print_with_rich(f"  Used:  {format_bytes(used)} ({used/total*100:.1f}%)", "info")
        print_with_rich(f"  Free:  {format_bytes(free)} ({free/total*100:.1f}%)", "info")
        
    except Exception as e:
        print_with_rich(f"Error getting disk usage: {e}", "error")

def env_command(args: List[str]):
    """Show or modify environment variables."""
    if not args:
        # Show all environment variables
        print_with_rich("Environment Variables:", "info")
        for key, value in sorted(os.environ.items()):
            print_with_rich(f"  {key}={value}", "info")
        return
    
    var_name = args[0]
    if len(args) == 1:
        # Show specific variable
        value = os.environ.get(var_name)
        if value:
            print_with_rich(f"{var_name}={value}", "info")
        else:
            print_with_rich(f"Environment variable '{var_name}' not found", "warning")
    else:
        # Set variable (temporary for this session)
        var_value = " ".join(args[1:])
        os.environ[var_name] = var_value
        print_with_rich(f"Set {var_name}={var_value}", "success")

def path_command(args: List[str]):
    """Show or modify PATH environment variable."""
    if not args:
        # Show PATH
        path_dirs = os.environ.get("PATH", "").split(os.pathsep)
        print_with_rich("PATH directories:", "info")
        for i, path_dir in enumerate(path_dirs, 1):
            exists_marker = "✅" if os.path.exists(path_dir) else "❌"
            print_with_rich(f"  {i}. {exists_marker} {path_dir}", "info")
        return
    
    subcmd = args[0]
    if subcmd == "add" and len(args) > 1:
        # Add directory to PATH
        new_dir = args[1]
        if os.path.exists(new_dir):
            current_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{new_dir}{os.pathsep}{current_path}"
            print_with_rich(f"Added {new_dir} to PATH (session only)", "success")
        else:
            print_with_rich(f"Directory not found: {new_dir}", "error")
    else:
        print_with_rich("Usage: path [add <directory>]", "info")

def which_command(args: List[str]):
    """Find location of command."""
    if not args:
        print_with_rich("Usage: which <command>", "info")
        return
    
    command = args[0]
    location = shutil.which(command)
    
    if location:
        print_with_rich(f"{command} -> {location}", "success")
    else:
        print_with_rich(f"Command '{command}' not found in PATH", "error")

def uptime_command(args: List[str]):
    """Show system uptime using smart multi-method approach."""
    import subprocess
    import re
    
    def safe_command(cmd):
        """Safely execute a command and return output."""
        try:
            out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=2)
            return out.decode().strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return None
        except Exception:
            return None
    
    def parse_uptime_from_proc():
        """Reads /proc/uptime → works on Linux + Termux."""
        try:
            with open("/proc/uptime", "r") as f:
                seconds = float(f.read().split()[0])
            return seconds
        except (PermissionError, OSError, IOError):
            return None
        except Exception:
            return None
    
    def humanize_uptime(seconds):
        """Convert seconds to human-readable format."""
        try:
            seconds = int(seconds)
            days = seconds // 86400
            hours = (seconds % 86400) // 3600
            minutes = (seconds % 3600) // 60
            return f"{days}d {hours}h {minutes}m"
        except Exception:
            return "N/A"
    
    def get_last_boot_time(seconds):
        """Calculate boot time from uptime seconds."""
        try:
            boot = datetime.datetime.now() - datetime.timedelta(seconds=seconds)
            return boot.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return "N/A"
    
    os_name = platform.system().lower()
    uptime_seconds = None
    
    # MAIN METHOD (Termux + Linux + Android) - Read from /proc/uptime
    uptime_seconds = safe_stat(lambda: parse_uptime_from_proc(), None)
    
    # FALLBACK 1 — use `uptime -s` command
    if uptime_seconds is None or uptime_seconds == "N/A":
        uptime_s_output = safe_stat(lambda: safe_command("uptime -s"), None)
        if uptime_s_output and uptime_s_output != "N/A":
            try:
                boot_time = datetime.datetime.strptime(uptime_s_output, "%Y-%m-%d %H:%M:%S")
                uptime_seconds = (datetime.datetime.now() - boot_time).total_seconds()
            except Exception:
                uptime_seconds = None
    
    # FALLBACK 2 — Windows (WMIC)
    if (uptime_seconds is None or uptime_seconds == "N/A") and os_name == "windows":
        wmic_output = safe_stat(lambda: safe_command("wmic os get lastbootuptime"), None)
        if wmic_output and wmic_output != "N/A":
            try:
                match = re.search(r"(\d{14})", wmic_output)
                if match:
                    raw = match.group(1)
                    boot_time = datetime.datetime(
                        year=int(raw[0:4]),
                        month=int(raw[4:6]),
                        day=int(raw[6:8]),
                        hour=int(raw[8:10]),
                        minute=int(raw[10:12]),
                        second=int(raw[12:14])
                    )
                    uptime_seconds = (datetime.datetime.now() - boot_time).total_seconds()
            except Exception:
                uptime_seconds = None
    
    # FALLBACK 3 — psutil (if available)
    if uptime_seconds is None or uptime_seconds == "N/A":
        try:
            import psutil
            boot_time = safe_stat(lambda: psutil.boot_time(), None)
            if boot_time is not None and boot_time != "N/A":
                uptime_seconds = time.time() - boot_time
        except ImportError:
            pass
        except Exception:
            pass
    
    # Display results with rich formatting
    if uptime_seconds is None or uptime_seconds == "N/A":
        print_with_rich("⏰ System uptime: N/A", "warning")
        print_with_rich("🚀 Boot time: N/A", "warning")
    else:
        uptime_str = humanize_uptime(uptime_seconds)
        boot_time_str = get_last_boot_time(uptime_seconds)
        
        print_with_rich(f"⏰ System uptime: {uptime_str}", "info")
        print_with_rich(f"🚀 Boot time: {boot_time_str}", "info")
        
        # PRETTY uptime (Termux/Linux only) - if available
        if os_name in ['linux', 'android']:
            pretty_uptime = safe_stat(lambda: safe_command("uptime -p"), None)
            if pretty_uptime and pretty_uptime != "N/A":
                print_with_rich(f"📊 Pretty Format: {pretty_uptime}", "info")

def memory_command(args: List[str]):
    """Show memory usage information."""
    import warnings
    # Suppress psutil warnings about permission errors
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        try:
            import psutil
            memory = safe_stat(lambda: psutil.virtual_memory(), None)
            swap = safe_stat(lambda: psutil.swap_memory(), None)
            
            def format_bytes(bytes_val):
                return f"{bytes_val / 1024 / 1024 / 1024:.1f} GB"
            
            print_with_rich("💾 Memory Information:", "info")
            
            if memory is None or memory == "N/A":
                print_with_rich("  Total RAM: N/A", "warning")
                print_with_rich("  Available: N/A", "warning")
                print_with_rich("  Used: N/A", "warning")
            else:
                print_with_rich(f"  Total RAM: {format_bytes(memory.total)}", "info")
                print_with_rich(f"  Available: {format_bytes(memory.available)} ({100-memory.percent:.1f}%)", "info")
                print_with_rich(f"  Used: {format_bytes(memory.used)} ({memory.percent:.1f}%)", "info")
                cached_val = memory.cached if hasattr(memory, 'cached') else 0
                print_with_rich(f"  Cached: {format_bytes(cached_val)}", "info")
            
            if swap is None or swap == "N/A":
                print_with_rich("  Swap Total: N/A", "warning")
                print_with_rich("  Swap Used: N/A", "warning")
            elif swap.total > 0:
                print_with_rich(f"  Swap Total: {format_bytes(swap.total)}", "info")
                print_with_rich(f"  Swap Used: {format_bytes(swap.used)} ({swap.percent:.1f}%)", "info")
        
        except ImportError:
            print_with_rich("Install 'psutil' for memory information: pip install psutil", "warning")
        except Exception:
            print_with_rich("💾 Memory Information: N/A", "warning")

def processes_command(args: List[str]):
    """Show running processes."""
    try:
        import psutil
        
        print_with_rich("🔄 Top Processes by CPU:", "info")
        processes = []
        
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                proc.cpu_percent()  # First call to initialize
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Wait a bit for accurate CPU readings
        time.sleep(0.5)
        
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                pinfo = proc.as_dict(attrs=['pid', 'name', 'cpu_percent', 'memory_percent'])
                processes.append(pinfo)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Sort by CPU usage
        processes = sorted(processes, key=lambda x: x['cpu_percent'] or 0, reverse=True)
        
        # Show top 10
        for proc in processes[:10]:
            cpu_percent = proc['cpu_percent'] or 0
            mem_percent = proc['memory_percent'] or 0
            print_with_rich(f"  PID {proc['pid']:>6}: {proc['name']:<20} CPU: {cpu_percent:>5.1f}% MEM: {mem_percent:>5.1f}%", "info")
        
    except ImportError:
        print_with_rich("Install 'psutil' for process information: pip install psutil", "warning")
    except Exception as e:
        print_with_rich(f"Error getting process info: {e}", "error")

def compare_command(args: List[str]):
    """Compare two files (advanced unified diff)."""
    if len(args) < 2:
        print_with_rich("Usage: compare <file1> <file2>", "info")
        return
    
    file1, file2 = args[0], args[1]
    
    def compare_files():
        if not os.path.exists(file1):
            raise FileNotFoundError(f"File not found: {file1}")
        if not os.path.exists(file2):
            raise FileNotFoundError(f"File not found: {file2}")
        
        with open(file1, 'r', encoding='utf-8') as f1:
            content1 = f1.read()
        with open(file2, 'r', encoding='utf-8') as f2:
            content2 = f2.read()
        
        # Reuse advanced diff preview UI (treat file2 as the "updated" version of file1)
        _show_advanced_diff_preview(file2, content1, content2)
        return True
    
    result = execute_with_error_recovery(compare_files, context=f"Comparing files: {file1} and {file2}")


def diff_command(args: List[str]):
    """Show differences between files (alias for compare)."""
    compare_command(args)


def diff_dir_command(args: List[str]):
    """Diff two directories with a tree-like overview and optional batch comparison.

    Usage:
        diff_dir <dir1> <dir2>

    Now supports explain/recovery mode and validates *both* directories,
    reporting all missing paths in one go.
    """
    if len(args) < 2:
        print_with_rich("Usage: diff_dir <dir1> <dir2>", "info")
        return
    
    dir1, dir2 = args[0], args[1]

    def _diff_directories():
        missing = []
        if not os.path.isdir(dir1):
            missing.append(dir1)
        if not os.path.isdir(dir2):
            missing.append(dir2)

        if missing:
            if len(missing) == 1:
                raise FileNotFoundError(f"Directory not found: {missing[0]}")
            else:
                raise FileNotFoundError("Directories not found: " + ", ".join(missing))

        import hashlib

        def build_index(root: str) -> dict:
            index = {}
            for current_root, _, files in os.walk(root):
                for name in files:
                    full_path = os.path.join(current_root, name)
                    rel_path = os.path.relpath(full_path, root)
                    try:
                        with open(full_path, 'rb') as f:
                            data = f.read()
                        index[rel_path.replace('\\', '/') ] = hashlib.sha1(data).hexdigest()
                    except Exception:
                        # If we can't read a file, skip it but note in hash as None
                        index[rel_path.replace('\\', '/') ] = None
            return index
        
        print_with_rich(f"🔍 Building directory indexes...", "info")
        idx1 = build_index(dir1)
        idx2 = build_index(dir2)
        
        set1 = set(idx1.keys())
        set2 = set(idx2.keys())
        only1 = sorted(set1 - set2)
        only2 = sorted(set2 - set1)
        common = sorted(set1 & set2)
        changed = [p for p in common if idx1[p] != idx2[p]]
        
        print_with_rich(f"\n📂 Directory diff: {os.path.abspath(dir1)}  ⇄  {os.path.abspath(dir2)}", "info")
        print_with_rich(f"  Added: {len(only2)}  Removed: {len(only1)}  Modified: {len(changed)}", "info")
        
        def print_entries(label: str, paths: list, marker: str, style: str):
            if not paths:
                return
            print_with_rich(f"\n{label}", style)
            for rel in paths:
                parts = rel.split('/')
                indent = '  ' * (len(parts) - 1)
                name = parts[-1]
                print_with_rich(f"{indent}{marker} {name}  ({rel})", style)
        
        print_entries("➕ Added in second directory:", only2, "+", "success")
        print_entries("➖ Removed from second directory:", only1, "-", "error")
        print_entries("✏ Modified in both:", changed, "*", "warning")
        
        # Optional batch comparison for modified files
        # Default is Yes (Y/n) so pressing Enter will run compares for all modified files.
        if changed and confirm_action("Run compare on each modified file?", default_yes=True):
            for rel in changed:
                path1 = os.path.join(dir1, rel)
                path2 = os.path.join(dir2, rel)
                print_with_rich(f"\n📄 Comparing: {rel}", "info")
                compare_command([path1, path2])

        return True

    execute_with_error_recovery(_diff_directories, context=f"Command: diff_dir {dir1} {dir2}")


def diff_semantic_command(args: List[str]):
    """AI-powered semantic diff between two files.

    Usage:
        diff_semantic <file1> <file2>

    Now validates both paths and integrates with the explain/recovery system
    for missing files or other I/O issues.
    """
    if len(args) < 2:
        print_with_rich("Usage: diff_semantic <file1> <file2>", "info")
        return
    
    if not AI_ENABLED:
        print_with_rich("AI is required for semantic diff but is not enabled.", "warning")
        return
    
    file1, file2 = args[0], args[1]

    def _semantic_diff():
        missing = []
        if not os.path.exists(file1):
            missing.append(file1)
        if not os.path.exists(file2):
            missing.append(file2)

        if missing:
            if len(missing) == 1:
                raise FileNotFoundError(f"File not found: {missing[0]}")
            else:
                raise FileNotFoundError("Files not found: " + ", ".join(missing))

        content1 = read_file_content(file1) or ""
        content2 = read_file_content(file2) or ""
        
        # Truncate very large files to keep prompts manageable
        max_len = 6000
        if len(content1) > max_len:
            content1 = content1[:max_len] + "\n... [truncated]"
        if len(content2) > max_len:
            content2 = content2[:max_len] + "\n... [truncated]"
        
        lang1 = get_file_language(file1)
        lang2 = get_file_language(file2)
        
        prompt = f"""Perform a semantic diff between two files.

File A: {file1}
Language A: {lang1}
Content A:
```{lang1.lower() if lang1 != 'Unknown' else 'text'}
{content1}
```

File B: {file2}
Language B: {lang2}
Content B:
```{lang2.lower() if lang2 != 'Unknown' else 'text'}
{content2}
```

Focus on:
- Functions/classes/modules added, removed, or significantly changed
- Behavior changes (what the program does differently)
- API or interface changes
- Refactors vs bug fixes vs new features
- Risky changes or potential bugs introduced

Ignore purely cosmetic formatting or comment-only changes when possible.
Provide a clear, structured summary of the differences and their impact.
"""
        
        print_with_rich("🤖 VritraAI analyzing semantic differences...", "info")
        result = get_ai_response(prompt)
        if not result:
            raise APIError("Failed to generate semantic diff.")

        cleaned = clean_ai_response(result)
        print_with_rich("\n🧠 Semantic Diff Result\n", "info")
        print_ai_response(cleaned, use_typewriter=True)
        return True

    execute_with_error_recovery(_semantic_diff, context=f"Command: diff_semantic {file1} {file2}")
def hash_command(args: List[str]):
    """Calculate file hash."""
    if not args:
        print_with_rich("Usage: hash <file> [algorithm]", "info")
        print_with_rich("Supported algorithms: md5, sha1, sha256 (default)", "info")
        return
    
    filename = args[0]
    algorithm = args[1].lower() if len(args) > 1 else "sha256"
    
    def calculate_hash():
        if not os.path.exists(filename):
            raise FileNotFoundError(f"File not found: {filename}")
        
        import hashlib
        
        if algorithm == "md5":
            hasher = hashlib.md5()
        elif algorithm == "sha1":
            hasher = hashlib.sha1()
        elif algorithm == "sha256":
            hasher = hashlib.sha256()
        else:
            raise ValueError(f"Unsupported algorithm: {algorithm}")
        
        with open(filename, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        
        hash_value = hasher.hexdigest()
        print_with_rich(f"{algorithm.upper()} hash of {filename}:", "info")
        print_with_rich(hash_value, "success")
        return True
    
    result = execute_with_error_recovery(calculate_hash, context=f"Calculating hash for: {filename}")

def encode_command(args: List[str]):
    """Encode text using various methods."""
    if len(args) < 2:
        print_with_rich("Usage: encode <method> <text>", "info")
        print_with_rich("Methods: base64, url, hex", "info")
        return
    
    method = args[0].lower()
    text = " ".join(args[1:])
    
    try:
        if method == "base64":
            import base64
            encoded = base64.b64encode(text.encode()).decode()
        elif method == "url":
            import urllib.parse
            encoded = urllib.parse.quote(text)
        elif method == "hex":
            encoded = text.encode().hex()
        else:
            print_with_rich(f"Unknown encoding method: {method}", "error")
            return
        
        print_with_rich(f"Encoded ({method}): {encoded}", "success")
        
    except Exception as e:
        print_with_rich(f"Error encoding: {e}", "error")

def decode_command(args: List[str]):
    """Decode text using various methods."""
    if len(args) < 2:
        print_with_rich("Usage: decode <method> <text>", "info")
        print_with_rich("Methods: base64, url, hex", "info")
        return
    
    method = args[0].lower()
    text = " ".join(args[1:])
    
    try:
        if method == "base64":
            import base64
            decoded = base64.b64decode(text).decode()
        elif method == "url":
            import urllib.parse
            decoded = urllib.parse.unquote(text)
        elif method == "hex":
            decoded = bytes.fromhex(text).decode()
        else:
            print_with_rich(f"Unknown decoding method: {method}", "error")
            return
        
        print_with_rich(f"Decoded ({method}): {decoded}", "success")
        
    except Exception as e:
        print_with_rich(f"Error decoding: {e}", "error")

def time_command(args: List[str]):
    """Show current time and date."""
    now = datetime.datetime.now()
    
    print_with_rich(f"🕐 Current Time: {now.strftime('%H:%M:%S')}", "info")
    print_with_rich(f"📅 Current Date: {now.strftime('%Y-%m-%d (%A)')}", "info")
    print_with_rich(f"⏰ Timestamp: {int(now.timestamp())}", "info")
    print_with_rich(f"🌐 UTC Time: {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}", "info")

def calc_command(args: List[str]):
    """Simple calculator."""
    if not args:
        print_with_rich("Usage: calc <expression>", "info")
        print_with_rich("Examples: calc '2+2', calc '10*5+3', calc 'sqrt(16)'", "info")
        return
    
    expression = " ".join(args)
    
    try:
        # Safe evaluation - only allow basic math operations
        import math
        allowed_names = {
            k: v for k, v in math.__dict__.items() if not k.startswith("__")
        }
        allowed_names.update({"abs": abs, "round": round, "min": min, "max": max})
        
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        print_with_rich(f"{expression} = {result}", "success")
        
    except Exception as e:
        print_with_rich(f"Calculation error: {e}", "error")

def generate_command(args: List[str]):
    """Generate content using AI."""
    if not AI_ENABLED:
        print_with_rich("AI is required for content generation", "warning")
        return
    
    if not args:
        print_with_rich("Usage: generate <description>", "info")
        print_with_rich("Examples: generate 'README for Python project', generate 'bash script to backup files'", "info")
        return
    
    description = " ".join(args)
    ai_command(f"generate {description}")

def template_command(args: List[str]):
    """Create template files."""
    if not args:
        print_with_rich("Available templates:", "info")
        templates = {
            "python": "Basic Python script template",
            "bash": "Basic bash script template", 
            "html": "Basic HTML page template",
            "readme": "Project README template"
        }
        for name, desc in templates.items():
            print_with_rich(f"  {name}: {desc}", "info")
        print_with_rich("\nUsage: template <type> [filename]", "info")
        return
    
    template_type = args[0].lower()
    filename = args[1] if len(args) > 1 else None
    
    templates = {
        "python": {
            "filename": "script.py",
            "content": "#!/usr/bin/env python3\n\"\"\"\nTemplate Python Script\n\"\"\"\n\ndef main():\n    print('Hello, World!')\n\nif __name__ == '__main__':\n    main()\n"
        },
        "bash": {
            "filename": "script.sh",
            "content": "#!/bin/bash\n\n# Template Bash Script\n\nset -e  # Exit on error\n\necho 'Hello, World!'\n"
        },
        "html": {
            "filename": "index.html",
            "content": "<!DOCTYPE html>\n<html lang='en'>\n<head>\n    <meta charset='UTF-8'>\n    <meta name='viewport' content='width=device-width, initial-scale=1.0'>\n    <title>Template Page</title>\n</head>\n<body>\n    <h1>Hello, World!</h1>\n</body>\n</html>\n"
        },
        "readme": {
            "filename": "README.md",
            "content": "# Project Title\n\n## Description\n\nA brief description of your project.\n\n## Installation\n\n```bash\n# Installation steps\n```\n\n## Usage\n\n```bash\n# Usage examples\n```\n\n## License\n\nThis project is licensed under the MIT License.\n"
        }
    }
    
    if template_type in templates:
        template = templates[template_type]
        base_filename = filename or template["filename"]
        
        # Use smart filename generation - only auto-rename if user didn't specify filename
        if filename:
            # User specified filename - use it as-is (but still check if exists)
            target_filename = filename
            if os.path.exists(target_filename):
                if not confirm_action(f"File '{target_filename}' exists. Overwrite?"):
                    print_with_rich("Template creation cancelled", "info")
                    return
        else:
            # Auto-generate smart filename to avoid conflicts
            target_filename = generate_unique_filename(base_filename, use_timestamp=False)
            if target_filename != base_filename:
                print_with_rich(f"⚠️  File '{base_filename}' already exists. Creating '{target_filename}' instead.", "warning")
        
        try:
            with open(target_filename, 'w', encoding='utf-8') as f:
                f.write(template["content"])
            print_with_rich(f"✅ Template created: {target_filename}", "success")
            # Track in session
            if target_filename not in session.modified_files:
                session.modified_files.append(target_filename)
        except Exception as e:
            print_with_rich(f"Error creating template: {e}", "error")
    else:
        print_with_rich(f"Unknown template type: {template_type}", "error")
        template_command([])  # Show available templates

def validate_command(args: List[str]):
    """Validate file syntax or format."""
    if not args:
        print_with_rich("Usage: validate <file>", "info")
        return
    
    filename = args[0]
    if not os.path.exists(filename):
        print_with_rich(f"File not found: {filename}", "error")
        return
    
    file_ext = os.path.splitext(filename)[1].lower()
    
    try:
        if file_ext == '.py':
            import ast
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read()
            ast.parse(content)
            print_with_rich(f"✅ Python syntax is valid: {filename}", "success")
        
        elif file_ext == '.json':
            import json
            with open(filename, 'r', encoding='utf-8') as f:
                json.load(f)
            print_with_rich(f"✅ JSON format is valid: {filename}", "success")
        
        else:
            print_with_rich(f"Validation not supported for {file_ext} files", "warning")
            if AI_ENABLED:
                ai_command(f"validate and check syntax of {filename}")
    
    except Exception as e:
        print_with_rich(f"❌ Validation failed: {e}", "error")

def format_command(args: List[str]):
    """Format Python code files only - creates *_formatted.py output."""
    if not args:
        print_with_rich("Usage: format <python_file.py>", "info")
        print_with_rich("Note: This command only supports Python (.py) files", "warning")
        print_with_rich("Output will be saved as <filename>_formatted.py", "info")
        return
    
    filename = args[0]
    if not os.path.exists(filename):
        print_with_rich(f"File not found: {filename}", "error")
        return
    
    file_ext = os.path.splitext(filename)[1].lower()
    
    # Only support Python files
    if file_ext != '.py':
        print_with_rich(f"⚠️ This command only supports Python (.py) files!", "error")
        print_with_rich(f"You provided: {filename} ({file_ext})", "warning")
        print_with_rich("\nPlease use a Python file. Example: format script.py", "info")
        return
    
    # Generate output filename
    base_name = os.path.splitext(filename)[0]
    output_filename = f"{base_name}_formatted.py"
    
    # Try to use black or autopep8
    if check_package_installed("black"):
        try:
            print_with_rich(f"🔧 Formatting Python file with black...", "info")
            print_with_rich(f"Input:  {filename}", "info")
            print_with_rich(f"Output: {output_filename}", "success")
            
            # First copy the file to new name, then format it
            import shutil
            shutil.copy2(filename, output_filename)
            
            # Execute black on the new file
            process = subprocess.Popen(
                f"black {output_filename}",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = process.communicate()
            
            # Show black's output (but simplified)
            if process.returncode != 0 and stderr:
                print_with_rich(stderr, "error")
                # Remove the failed output file
                if os.path.exists(output_filename):
                    os.remove(output_filename)
                if AI_ENABLED:
                    error = Exception(f"Black formatter error: {stderr}")
                    # Use interactive error recovery with menu options
                    handle_error_with_recovery(error, context=f"Formatting file: {filename}", show_suggestion=True, auto_mode=False)
            elif process.returncode == 0:
                # Black succeeded
                if "reformatted" in stdout.lower():
                    print_with_rich(f"\n✅ File formatted successfully!", "success")
                    print_with_rich(f"📄 Formatted file saved as: {output_filename}", "success")
                elif "left unchanged" in stdout.lower() or "already well formatted" in stdout.lower():
                    print_with_rich(f"\n✓ File already properly formatted", "info")
                    print_with_rich(f"📄 Copy saved as: {output_filename}", "info")
                else:
                    print_with_rich(f"\n✅ Formatting complete!", "success")
                    print_with_rich(f"📄 Formatted file saved as: {output_filename}", "success")
                    
        except Exception as e:
            print_with_rich(f"Error running formatter: {e}", "error")
            # Clean up on error
            if os.path.exists(output_filename):
                os.remove(output_filename)
            
    elif check_package_installed("autopep8"):
        try:
            print_with_rich(f"🔧 Formatting Python file with autopep8...", "info")
            print_with_rich(f"Input:  {filename}", "info")
            print_with_rich(f"Output: {output_filename}", "success")
            
            # Use autopep8 to format and output to new file
            process = subprocess.Popen(
                f"autopep8 {filename} > {output_filename}",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = process.communicate()
            
            if process.returncode != 0 and stderr:
                print_with_rich(stderr, "error")
                # Remove the failed output file
                if os.path.exists(output_filename):
                    os.remove(output_filename)
                if AI_ENABLED:
                    error = Exception(f"autopep8 formatter error: {stderr}")
                    # Use interactive error recovery with menu options
                    handle_error_with_recovery(error, context=f"Formatting file: {filename}", show_suggestion=True, auto_mode=False)
            else:
                print_with_rich(f"\n✅ File formatted successfully!", "success")
                print_with_rich(f"📄 Formatted file saved as: {output_filename}", "success")
                
        except Exception as e:
            print_with_rich(f"Error running formatter: {e}", "error")
            # Clean up on error
            if os.path.exists(output_filename):
                os.remove(output_filename)
    else:
        print_with_rich("⚠️ Python formatter not found!", "warning")
        print_with_rich("Install one of the following:", "info")
        print_with_rich("  • black (recommended): pip install black", "info")
        print_with_rich("  • autopep8: pip install autopep8", "info")

# === AI CODE REVIEW & ANALYSIS COMMANDS ===

def get_file_language(file_path: str) -> str:
    """Detect programming language from file extension."""
    ext_to_lang = {
        '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript', '.jsx': 'React JSX',
        '.tsx': 'React TSX', '.java': 'Java', '.cs': 'C#', '.cpp': 'C++', '.c': 'C',
        '.go': 'Go', '.rs': 'Rust', '.php': 'PHP', '.rb': 'Ruby', '.swift': 'Swift',
        '.kt': 'Kotlin', '.scala': 'Scala', '.r': 'R', '.m': 'MATLAB', '.sh': 'Bash',
        '.ps1': 'PowerShell', '.bat': 'Batch', '.sql': 'SQL', '.html': 'HTML',
        '.css': 'CSS', '.scss': 'SCSS', '.less': 'LESS', '.xml': 'XML', '.json': 'JSON',
        '.yaml': 'YAML', '.yml': 'YAML', '.toml': 'TOML', '.ini': 'INI', '.cfg': 'Config'
    }
    
    file_ext = os.path.splitext(file_path.lower())[1]
    return ext_to_lang.get(file_ext, 'Unknown')

def explain_last_command(args: List[str]):
    """Explain the last executed system command and its output using AI."""
    # Check if user provided any arguments - this command should be standalone
    if args:
        print_with_rich("⚠️  Usage: explain_last (no arguments needed)", "warning")
        print_with_rich("This command analyzes the last executed system command independently.", "info")
        return
    
    # Check if AI is enabled
    if not AI_ENABLED:
        print_with_rich("❌ AI features disabled. Configure API key first.", "error")
        return
    
    # Check if lastcmd.log exists
    if not os.path.exists(LASTCMD_LOG_FILE):
        print_with_rich("No previous command recorded.", "info")
        return
    
    # Read the log file
    try:
        with open(LASTCMD_LOG_FILE, 'r', encoding='utf-8') as f:
            log_data = json.load(f)
    except Exception as e:
        print_with_rich(f"❌ Error reading last command log: {e}", "error")
        return
    
    command = log_data.get("command", "")
    output = log_data.get("output", "")
    exit_code = log_data.get("exit_code", 0)
    timestamp = log_data.get("timestamp", "")
    
    # Check if the last command should be logged (system commands or whitelisted built-ins)
    if not should_log_command(command):
        print_with_rich("⚠️  This command/output isn't supported. explain_last only works with system commands or whitelisted built-in commands.", "warning")
        return
    
    print_with_rich(f"🔍 Analyzing last command: {command}", "info")
    if timestamp:
        print_with_rich(f"📅 Executed at: {timestamp}", "dim")
    print_with_rich(f"📊 Exit code: {exit_code}", "dim")
    print()
    
    # Get current working directory and system info
    cwd = os.getcwd()
    
    # Build context similar to error recovery
    try:
        import platform
        system_info = f"OS: {platform.system()} {platform.release()}"
        try:
            import psutil
            system_info += f"\nCPU: {psutil.cpu_count()} cores"
            mem = psutil.virtual_memory()
            system_info += f"\nMemory: {mem.total // (1024**3)} GB total"
        except:
            pass
    except:
        system_info = "System info unavailable"
    
    # Build smart context
    context = f"""Context Information:
- Current Working Directory: {cwd}
- System: {system_info}
- Command: {command}
- Exit Code: {exit_code}
- Timestamp: {timestamp}

Command Output:
{output}
"""
    
    # Build AI prompt similar to error recovery
    prompt = f"""You are VritraAI an expert system administrator and developer. Analyze the following command execution and provide a comprehensive explanation.

{context}

Please provide:
1. What happened: Explain what the command did or attempted to do
2. Why it {'succeeded' if exit_code == 0 else 'failed'}: Detailed analysis of the exit code and output
3. Fixes/Recommendations: If it failed, provide specific fixes. If it succeeded, provide optimization tips or next steps
4. Context: How this relates to the current working directory and system environment
5. possible fixing commands: Provide possible fixing commands to fix the issue.
Be specific, actionable, and professional. Focus on practical solutions.
"""
    
    # Get AI response
    try:
        print_with_rich("🤖 Getting VritraAI explanation...", "info")
        response = get_ai_response(prompt)
        if response:
            print()
            print_with_rich("💡 VritraAI Explanation:", "bold cyan")
            print()
            # Clean and display the response with streaming effect and code block highlighting
            cleaned_response = clean_ai_response(response)
            print_ai_response(cleaned_response, use_typewriter=True)
            print()
        else:
            print_with_rich("❌ Failed to get AI response. Check your API configuration.", "error")
    except Exception as e:
        print_with_rich(f"❌ Error getting AI explanation: {e}", "error")

def review_command(args: List[str]):
    """AI-powered comprehensive code review."""
    if not args:
        print_with_rich("📋 AI Code Review Commands:", "info")
        print_with_rich("  review <file>                 - Comprehensive code review", "info")
        print_with_rich("  review <file> --focus=<area>  - Focus on specific area (security, performance, style)", "info")
        print_with_rich("  review <directory>            - Review all files in directory", "info")
        return
    
    target = args[0]
    focus_area = None
    
    # Check for focus parameter
    if len(args) > 1 and args[1].startswith('--focus='):
        focus_area = args[1].split('=')[1]
    
    if os.path.isfile(target):
        _review_single_file(target, focus_area)
    elif os.path.isdir(target):
        _review_directory(target, focus_area)
    else:
        print_with_rich(f"❌ File or directory not found: {target}", "error")

def _review_single_file(file_path: str, focus_area: str = None):
    """Review a single code file."""
    if not AI_ENABLED:
        print_with_rich("❌ AI features disabled. Configure API key first.", "error")
        return
    
    print_with_rich(f"🔍 Reviewing: {file_path}", "info")
    
    code_content = read_file_content(file_path)
    if not code_content:
        print_with_rich("❌ Could not read file content", "error")
        return
    
    language = get_file_language(file_path)
    file_size = len(code_content)
    line_count = len(code_content.splitlines())
    
    # Truncate very large files
    if len(code_content) > 8000:
        code_content = code_content[:8000] + "\n... [File truncated for analysis]"
        print_with_rich("⚠️ Large file truncated for analysis", "warning")
    
    focus_instruction = ""
    if focus_area:
        focus_areas = {
            'security': "Focus specifically on security vulnerabilities, input validation, authentication, and potential exploits.",
            'performance': "Focus on performance optimizations, algorithmic efficiency, memory usage, and bottlenecks.", 
            'style': "Focus on code style, formatting, naming conventions, and best practices.",
            'bugs': "Focus on finding bugs, logical errors, edge cases, and potential runtime issues.",
            'maintainability': "Focus on code maintainability, readability, modularity, and refactoring opportunities."
        }
        focus_instruction = focus_areas.get(focus_area.lower(), f"Focus on {focus_area} aspects of the code.")
    
    prompt = f"""As a senior software engineer, please review this {language} code comprehensively.

File: {file_path}
Size: {file_size} characters, {line_count} lines
Language: {language}

{focus_instruction if focus_area else ''}

Please analyze the code for:
🐛 **Bugs & Issues**: Logic errors, potential crashes, edge cases
⚡ **Performance**: Optimization opportunities, algorithmic improvements
🔒 **Security**: Vulnerabilities, input validation, security best practices
🎯 **Code Quality**: Readability, maintainability, design patterns
✨ **Best Practices**: Language-specific conventions, modern practices
📊 **Metrics**: Complexity assessment, code smells

Code to review:
```{language.lower()}
{code_content}
```

Provide specific feedback with:
- Line references where applicable
- Severity levels (Critical/High/Medium/Low)
- Actionable recommendations
- Code examples for improvements where helpful

Format as a clear, structured review report."""
    
    print_with_rich("🤖 VritraAI analyzing code...", "info")
    review_result = get_ai_response(prompt)
    
    if review_result:
        cleaned_review = clean_ai_response(review_result)
        
        # Print clean output without borders or panels
        print_with_rich(f"\n📋 Code Review: {os.path.basename(file_path)}", "success")
        print("")
        
        # Print the cleaned response with proper formatting
        print_ai_response_with_code_blocks(cleaned_review)
        print("")
        
        # Log the review
        log_session(f"Code review completed: {file_path} ({language})")
        
    else:
        print_with_rich("❌ Failed to get AI code review", "error")

def _review_directory(directory: str, focus_area: str = None):
    """Review all code files in a directory."""
    code_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cs', '.cpp', '.c',
                      '.go', '.rs', '.php', '.rb', '.swift', '.kt', '.scala'}
    
    code_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if any(file.lower().endswith(ext) for ext in code_extensions):
                code_files.append(os.path.join(root, file))
    
    if not code_files:
        print_with_rich(f"❌ No code files found in {directory}", "warning")
        return
    
    print_with_rich(f"📂 Found {len(code_files)} code files to review", "info")
    
    if len(code_files) > 5:
        if not confirm_action(f"Review {len(code_files)} files? This may take a while", default_yes=False):
            return
    
    for i, file_path in enumerate(code_files, 1):
        print_with_rich(f"\n📄 Reviewing file {i}/{len(code_files)}", "info")
        _review_single_file(file_path, focus_area)
        
        # Brief pause between files
        if i < len(code_files):
            import time
            time.sleep(0.5)

def security_scan_command(args: List[str]):
    """AI-powered security vulnerability scan."""
    if not args:
        print_with_rich("🔒 Security Scan Commands:", "info")
        print_with_rich("  security_scan <file>      - Scan file for security issues", "info")
        print_with_rich("  security_scan <directory> - Scan all files in directory", "info")
        return
    
    target = args[0]
    
    if os.path.isfile(target):
        _security_scan_file(target)
    elif os.path.isdir(target):
        _security_scan_directory(target)
    else:
        print_with_rich(f"❌ File or directory not found: {target}", "error")

def _security_scan_file(file_path: str):
    """Security scan for a single file."""
    if not AI_ENABLED:
        print_with_rich("❌ AI features disabled. Configure API key first.", "error")
        return
    
    print_with_rich(f"🔒 Security scanning: {file_path}", "info")
    
    code_content = read_file_content(file_path)
    if not code_content:
        return
    
    language = get_file_language(file_path)
    
    # Truncate large files
    if len(code_content) > 8000:
        code_content = code_content[:8000] + "\n... [File truncated for analysis]"
    
    prompt = f"""As a cybersecurity expert, perform a thorough security analysis of this {language} code.

File: {file_path}
Language: {language}

Focus on identifying:
🚨 **Critical Vulnerabilities**: SQL injection, XSS, code injection, etc.
⚠️ **High-Risk Issues**: Authentication bypasses, privilege escalation
🔍 **Medium-Risk Issues**: Information disclosure, weak cryptography
💡 **Best Practices**: Security hardening recommendations

Specific areas to check:
- Input validation and sanitization
- Authentication and authorization
- Cryptographic implementations  
- File operations and path traversal
- Network requests and data transmission
- Error handling and information disclosure
- Dependencies and third-party libraries
- Configuration and secrets management

Code to analyze:
```{language.lower()}
{code_content}
```

Provide:
- Vulnerability descriptions with CVSS-like severity ratings
- Specific line references
- Exploitation scenarios
- Remediation steps
- Secure code examples

Format as a structured security assessment report."""
    
    print_with_rich("🛡️ VritraAI performing security analysis...", "info")
    security_result = get_ai_response(prompt)
    
    if security_result:
        cleaned_result = clean_ai_response(security_result)
        
        # Print clean output without borders or panels
        print_with_rich(f"\n🔒 Security Scan: {os.path.basename(file_path)}", "warning")
        print("")
        
        # Print the cleaned response with proper formatting
        print_ai_response_with_code_blocks(cleaned_result)
        print("")
        
        log_session(f"Security scan completed: {file_path}")
    else:
        print_with_rich("❌ Failed to get security analysis", "error")

def _security_scan_directory(directory: str):
    """Security scan for all files in directory."""
    code_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cs', '.cpp', '.c',
                      '.go', '.rs', '.php', '.rb', '.swift', '.kt', '.scala', '.sql'}
    
    code_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if any(file.lower().endswith(ext) for ext in code_extensions):
                code_files.append(os.path.join(root, file))
    
    if not code_files:
        print_with_rich(f"❌ No code files found in {directory}", "warning")
        return
    
    print_with_rich(f"🔒 Found {len(code_files)} files for security scanning", "info")
    
    if len(code_files) > 3:
        if not confirm_action(f"Scan {len(code_files)} files for security issues? This may take a while", default_yes=False):
            return
    
    for i, file_path in enumerate(code_files, 1):
        print_with_rich(f"\n📄 Scanning file {i}/{len(code_files)}", "info")
        _security_scan_file(file_path)
        
        if i < len(code_files):
            import time
            time.sleep(0.5)

def optimize_code_command(args: List[str]):
    """AI-powered code optimization suggestions."""
    if not args:
        print_with_rich("⚡ Code Optimization Commands:", "info")
        print_with_rich("  optimize_code <file>          - Get optimization suggestions", "info")
        print_with_rich("  optimize_code <file> --type=<focus> - Focus on specific optimization", "info")
        print_with_rich("  Types: performance, memory, algorithm, readability", "info")
        return
    
    file_path = args[0]
    optimization_type = None
    
    # Check for optimization type
    if len(args) > 1 and args[1].startswith('--type='):
        optimization_type = args[1].split('=')[1]
    
    if not os.path.isfile(file_path):
        print_with_rich(f"❌ File not found: {file_path}", "error")
        return
    
    if not AI_ENABLED:
        print_with_rich("❌ AI features disabled. Configure API key first.", "error")
        return
    
    print_with_rich(f"⚡ Optimizing: {file_path}", "info")
    
    code_content = read_file_content(file_path)
    if not code_content:
        return
    
    language = get_file_language(file_path)
    
    # Truncate large files
    if len(code_content) > 8000:
        code_content = code_content[:8000] + "\n... [File truncated for analysis]"
    
    optimization_focus = ""
    if optimization_type:
        focus_types = {
            'performance': "Focus on execution speed, algorithmic efficiency, and runtime optimizations.",
            'memory': "Focus on memory usage, object allocation, and memory leak prevention.",
            'algorithm': "Focus on algorithmic improvements, data structure choices, and complexity reduction.",
            'readability': "Focus on code clarity, maintainability, and structural improvements.",
            'scalability': "Focus on scalability, concurrent processing, and resource utilization."
        }
        optimization_focus = focus_types.get(optimization_type.lower(), f"Focus on {optimization_type} optimizations.")
    
    prompt = f"""As a performance optimization expert, analyze this {language} code and provide detailed optimization recommendations.

File: {file_path}
Language: {language}
{optimization_focus if optimization_type else ''}

Analyze for optimization opportunities in:
⚡ **Performance**: Execution speed, bottlenecks, algorithmic improvements
💾 **Memory**: Memory usage, garbage collection, object allocation
🔄 **Algorithms**: Data structures, time complexity, space complexity
📈 **Scalability**: Concurrency, parallelization, resource utilization
🎯 **Code Structure**: Design patterns, architectural improvements

Code to optimize:
```{language.lower()}
{code_content}
```

Provide:
1. Specific optimization recommendations with line references
2. Performance impact estimates (High/Medium/Low)
3. Complexity analysis improvements
4. **IMPORTANT**: Include the COMPLETE optimized version of the entire code in a code block

Make sure to provide the full optimized code (not just snippets) in a properly formatted code block with syntax highlighting.
Prioritize optimizations by impact and implementation difficulty."""
    
    print_with_rich("🚀 VritraAI analyzing optimization opportunities...", "info")
    optimization_result = get_ai_response(prompt)
    
    if optimization_result:
        print_with_rich(f"\n⚡ Code Optimization: {os.path.basename(file_path)}\n", "success")
        print_ai_response(optimization_result, use_typewriter=True)
        print()
        
        # Extract optimized code from response
        import re
        code_pattern = r'```(?:[a-zA-Z]+)?\s*\n(.*?)```'
        matches = re.findall(code_pattern, optimization_result, re.DOTALL)
        
        if matches:
            # Get the largest code block (likely the optimized version)
            optimized_code = max(matches, key=len).strip()
            
            # Ask if user wants to save the optimized code
            print_with_rich("\n💾 Save optimized code?", "info")
            if confirm_action("Would you like to save the optimized code to a new file?", default_yes=True):
                # Generate new filename
                base_name = os.path.splitext(file_path)[0]
                extension = os.path.splitext(file_path)[1]
                optimized_filename = f"{base_name}_optimized{extension}"
                
                # Allow user to customize filename
                custom_name = input(f"Enter filename (press Enter for '{optimized_filename}'): ").strip()
                if custom_name:
                    optimized_filename = custom_name
                
                try:
                    with open(optimized_filename, 'w', encoding='utf-8') as f:
                        f.write(optimized_code)
                    print_with_rich(f"✅ Optimized code saved to: {optimized_filename}", "success")
                    log_session(f"Optimized code saved: {optimized_filename}")
                except Exception as e:
                    print_with_rich(f"❌ Error saving file: {e}", "error")
        
        log_session(f"Code optimization analysis: {file_path}")
    else:
        print_with_rich("❌ Failed to get optimization suggestions", "error")

def refactor_command(args: List[str]):
    """AI-powered code refactoring suggestions."""
    if not args:
        print_with_rich("🔄 Code Refactoring Commands:", "info")
        print_with_rich("  refactor <file> <description>     - Refactor with specific goal", "info")
        #print_with_rich("  refactor <file> --pattern=<name>  - Apply specific refactoring pattern", "info")
        print_with_rich("  Common patterns: extract-method, extract-class, simplify, modernize", "info")
        return
    
    if len(args) < 2:
        print_with_rich("❌ Usage: refactor <file> <description|--pattern=name>", "error")
        return
    
    file_path = args[0]
    refactor_instruction = " ".join(args[1:])
    
    if not os.path.isfile(file_path):
        print_with_rich(f"❌ File not found: {file_path}", "error")
        return
    
    if not AI_ENABLED:
        print_with_rich("❌ AI features disabled. Configure API key first.", "error")
        return
    
    # Detect language conversion requests
    is_language_conversion = False
    target_language = None
    conversion_keywords = ["convert", "translate", "port", "rewrite", "change language", "to"]
    
    # More comprehensive language mappings with aliases
    language_mappings = [
        (["bash", "bash script", "bash scripting", "shell", "shell script", "sh"], ("bash", ".sh")),
        (["python", "py"], ("python", ".py")),
        (["javascript", "js", "node"], ("javascript", ".js")),
        (["typescript", "ts"], ("typescript", ".ts")),
        (["java"], ("java", ".java")),
        (["go", "golang"], ("go", ".go")),
        (["rust", "rs"], ("rust", ".rs")),
        (["c++", "cpp"], ("c++", ".cpp")),
        (["c language", "c code"], ("c", ".c")),
        (["ruby", "rb"], ("ruby", ".rb")),
        (["php"], ("php", ".php")),
    ]
    
    # Check if it's a conversion request
    instruction_lower = refactor_instruction.lower()
    for keyword in conversion_keywords:
        if keyword in instruction_lower:
            # Try to detect target language
            for lang_aliases, lang_info in language_mappings:
                lang_name, ext = lang_info
                for alias in lang_aliases:
                    if alias in instruction_lower:
                        is_language_conversion = True
                        target_language = (lang_name, ext)
                        break
                if is_language_conversion:
                    break
            break
    
    print_with_rich(f"🔄 Refactoring: {file_path}", "info")
    print_with_rich(f"🎯 Goal: {refactor_instruction}", "info")
    
    code_content = read_file_content(file_path)
    if not code_content:
        return
    
    language = get_file_language(file_path)
    
    # Truncate large files
    if len(code_content) > 8000:
        code_content = code_content[:8000] + "\n... [File truncated for analysis]"
        print_with_rich("⚠️ Large file truncated for analysis", "warning")
    
    pattern_instructions = ""
    if refactor_instruction.startswith('--pattern='):
        pattern = refactor_instruction.split('=')[1]
        pattern_guides = {
            'extract-method': "Extract repeated code into reusable methods/functions.",
            'extract-class': "Extract related functionality into separate classes.",
            'simplify': "Simplify complex logic, reduce nesting, improve readability.",
            'modernize': "Update code to use modern language features and best practices.",
            'single-responsibility': "Ensure each function/class has a single responsibility.",
            'dependency-injection': "Apply dependency injection patterns.",
            'strategy-pattern': "Apply strategy pattern for conditional logic."
        }
        pattern_instructions = pattern_guides.get(pattern.lower(), f"Apply {pattern} refactoring pattern.")
        refactor_instruction = pattern_instructions
    
    # Adjust prompt based on whether it's a language conversion
    if is_language_conversion and target_language:
        target_lang_name, _ = target_language
        prompt = f"""As a software expert, convert this {language} code to {target_lang_name}.

File: {file_path}
Source Language: {language}
Target Language: {target_lang_name}
Goal: {refactor_instruction}

Original code:
```{language.lower()}
{code_content}
```

Provide:
1. 📋 **Analysis**: Key differences and conversion approach
2. ✨ **Converted Code**: Complete working code in {target_lang_name}
3. 📊 **Changes Made**: Major changes from original
4. ⚠️ **Notes**: Any important considerations

IMPORTANT: Convert to {target_lang_name}, NOT to C or any other language. Provide the converted code in a code block for {target_lang_name}."""
    else:
        prompt = f"""As a software architecture expert, help refactor this {language} code according to the following requirements:

File: {file_path}
Language: {language}
Refactoring Goal: {refactor_instruction}

Original code:
```{language.lower()}
{code_content}
```

Please provide:
1. 📋 **Analysis**: What needs to be refactored and why
2. 🔄 **Refactoring Plan**: Step-by-step approach
3. ✨ **Improved Code**: Complete refactored version
4. 📊 **Benefits**: What improvements were made
5. ⚠️ **Considerations**: Any trade-offs or migration notes

Focus on:
- Code clarity and maintainability
- Following SOLID principles
- Reducing complexity and duplication
- Improving testability
- Modern best practices for {language}

Provide the refactored code in proper code blocks with clear explanations."""
    
    print_with_rich("🤖 VritraAI planning refactoring strategy...", "info")
    refactor_result = get_ai_response(prompt)
    
    if refactor_result:
        print_with_rich(f"\n🔄 Refactoring Plan: {os.path.basename(file_path)}\n", "success")
        print_ai_response(refactor_result, use_typewriter=True)
        print()
        
        # For language conversion, create new file
        if is_language_conversion and target_language:
            target_lang_name, ext = target_language
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            new_file = f"{base_name}{ext}"
            
            if confirm_action(f"Create converted file '{new_file}'?", default_yes=True):
                _create_converted_file(new_file, refactor_result, target_lang_name)
        else:
            # Ask if user wants to apply the refactoring
            if confirm_action("Apply this refactoring to the file?", default_yes=False):
                _apply_refactoring_interactively(file_path, refactor_result)
        
        log_session(f"Code refactoring analysis: {file_path} - {refactor_instruction}")
    else:
        print_with_rich("❌ Failed to get refactoring suggestions", "error")

def _create_converted_file(new_file: str, ai_response: str, target_language: str):
    """Create a new file with converted code from AI response."""
    try:
        # Extract code blocks from AI response
        import re
        code_pattern = r'```(?:[a-zA-Z]+)?\s*\n(.*?)```'
        matches = re.findall(code_pattern, ai_response, re.DOTALL)
        
        if matches:
            # Use the largest code block (likely the full converted code)
            converted_code = max(matches, key=len).strip()
            
            # Write to new file
            with open(new_file, 'w', encoding='utf-8') as f:
                f.write(converted_code)
            
            print_with_rich(f"✅ File '{new_file}' created successfully.", "success")
            log_session(f"Language conversion: created {new_file}")
        else:
            print_with_rich("⚠️ No code block found in AI response. Please create the file manually.", "warning")
    except Exception as e:
        print_with_rich(f"❌ Error creating converted file: {e}", "error")

def _apply_refactoring_interactively(file_path: str, refactor_result: str):
    """Interactively apply refactoring suggestions."""
    try:
        # Create backup
        backup_path = backup_file(file_path)
        if backup_path:
            print_with_rich(f"📋 Backup created: {os.path.basename(backup_path)}", "info")
        
        print_with_rich("⚠️ Manual refactoring recommended. Review the suggestions above and apply changes carefully.", "warning")
        print_with_rich("💡 The AI has provided a detailed refactoring plan. Please implement the changes manually for safety.", "info")
        
    except Exception as e:
        print_with_rich(f"❌ Error during refactoring: {e}", "error")

# === INTELLIGENT PROJECT DETECTION COMMANDS ===

def project_type_command(args: List[str]):
    """Enhanced project type detection with AI analysis."""
    target_dir = args[0] if args else "."
    # Expand ~ and environment variables
    target_dir = expand_path(target_dir)
    
    if not os.path.isdir(target_dir):
        print_with_rich(f"❌ Directory not found: {target_dir}", "error")
        return
    
    print_with_rich(f"🔍 Analyzing project structure: {os.path.abspath(target_dir)}", "info")
    
    # Enhanced project detection
    project_info = _analyze_project_structure(target_dir)
    
    # Display basic project info
    print_with_rich(f"\n📂 Project Analysis Results:", "success")
    print_with_rich("=" * 50, "info")
    
    print_with_rich(f"🏷️  Primary Type: {project_info['primary_type']}", "info")
    if project_info['secondary_types']:
        print_with_rich(f"🔗 Secondary Types: {', '.join(project_info['secondary_types'])}", "info")
    
    print_with_rich(f"📊 Confidence: {project_info['confidence']}", "info")
    print_with_rich(f"📁 Total Files: {project_info['total_files']}", "info")
    print_with_rich(f"📁 Code Files: {project_info['code_files']}", "info")
    
    # Show key indicators
    if project_info['key_files']:
        print_with_rich(f"\n🔑 Key Project Files:", "info")
        for file in project_info['key_files'][:10]:  # Limit to 10
            print_with_rich(f"  • {file}", "info")
    
    # Show technologies
    if project_info['technologies']:
        print_with_rich(f"\n🛠️  Technologies Detected:", "info")
        for tech in project_info['technologies']:
            print_with_rich(f"  • {tech}", "info")
    
    # Show frameworks
    if project_info['frameworks']:
        print_with_rich(f"\n🎨 Frameworks/Libraries:", "info")
        for framework in project_info['frameworks']:
            print_with_rich(f"  • {framework}", "info")
    
    # AI-powered deeper analysis if AI is enabled
    if AI_ENABLED and len(args) == 0:  # Only for current directory
        _ai_project_analysis(target_dir, project_info)

def _analyze_project_structure(directory: str) -> dict:
    """Analyze project structure and detect technologies."""
    project_info = {
        'primary_type': 'Unknown',
        'secondary_types': [],
        'confidence': 'Low',
        'total_files': 0,
        'code_files': 0,
        'key_files': [],
        'technologies': [],
        'frameworks': [],
        'languages': {},
        'build_tools': [],
        'package_managers': []
    }
    
    # File patterns for different project types
    patterns = {
        'Python': {
            'key_files': ['requirements.txt', 'setup.py', 'pyproject.toml', 'Pipfile', 'conda.yml', 'environment.yml'],
            'extensions': ['.py'],
            'frameworks': ['flask', 'django', 'fastapi', 'streamlit', 'pytest', 'numpy', 'pandas'],
            'build_tools': ['poetry', 'pipenv', 'setuptools']
        },
        'Node.js': {
            'key_files': ['package.json', 'package-lock.json', 'yarn.lock', 'node_modules'],
            'extensions': ['.js', '.ts', '.jsx', '.tsx'],
            'frameworks': ['react', 'vue', 'angular', 'express', 'next', 'nuxt', 'svelte'],
            'build_tools': ['webpack', 'vite', 'rollup', 'parcel']
        },
        'Java': {
            'key_files': ['pom.xml', 'build.gradle', 'gradlew', 'mvnw'],
            'extensions': ['.java', '.jar', '.war'],
            'frameworks': ['spring', 'junit', 'hibernate', 'maven', 'gradle'],
            'build_tools': ['maven', 'gradle', 'ant']
        },
        'C#/.NET': {
            'key_files': ['.csproj', '.sln', 'packages.config', 'project.json'],
            'extensions': ['.cs', '.vb', '.fs'],
            'frameworks': ['asp.net', 'entity framework', 'xamarin', 'unity'],
            'build_tools': ['msbuild', 'dotnet', 'nuget']
        },
        'Go': {
            'key_files': ['go.mod', 'go.sum', 'Gopkg.toml', 'glide.yaml'],
            'extensions': ['.go'],
            'frameworks': ['gin', 'echo', 'fiber', 'gorilla'],
            'build_tools': ['go modules', 'dep', 'glide']
        },
        'Rust': {
            'key_files': ['Cargo.toml', 'Cargo.lock'],
            'extensions': ['.rs'],
            'frameworks': ['actix', 'rocket', 'warp', 'tokio'],
            'build_tools': ['cargo']
        },
        'PHP': {
            'key_files': ['composer.json', 'composer.lock', 'index.php'],
            'extensions': ['.php'],
            'frameworks': ['laravel', 'symfony', 'codeigniter', 'wordpress'],
            'build_tools': ['composer']
        },
        'Ruby': {
            'key_files': ['Gemfile', 'Gemfile.lock', 'Rakefile', 'config.ru'],
            'extensions': ['.rb'],
            'frameworks': ['rails', 'sinatra', 'hanami'],
            'build_tools': ['bundler', 'gem']
        },
        'Docker': {
            'key_files': ['Dockerfile', 'docker-compose.yml', 'docker-compose.yaml', '.dockerignore'],
            'extensions': [],
            'frameworks': ['docker', 'docker-compose', 'kubernetes'],
            'build_tools': ['docker']
        },
        'Frontend': {
            'key_files': ['index.html', 'webpack.config.js', 'vite.config.js', '.babelrc'],
            'extensions': ['.html', '.css', '.scss', '.less', '.vue'],
            'frameworks': ['bootstrap', 'tailwind', 'material-ui', 'bulma'],
            'build_tools': ['webpack', 'vite', 'gulp', 'grunt']
        }
    }
    
    # Analyze files
    for root, dirs, files in os.walk(directory):
        # Skip hidden and common ignore directories
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', '__pycache__', 'target', 'build', 'dist', 'bin', 'obj']]
        
        for file in files:
            if file.startswith('.'):
                continue
                
            project_info['total_files'] += 1
            file_path = os.path.join(root, file)
            
            # Check for key files
            for proj_type, proj_patterns in patterns.items():
                if file.lower() in [f.lower() for f in proj_patterns['key_files']]:
                    project_info['key_files'].append(file_path.replace(directory, '.').replace('\\', '/'))
                    if proj_type not in project_info['secondary_types']:
                        project_info['secondary_types'].append(proj_type)
            
            # Count code files and languages
            file_ext = os.path.splitext(file.lower())[1]
            if file_ext in ['.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cs', '.go', '.rs', '.php', '.rb', '.cpp', '.c', '.h', '.swift', '.kt']:
                project_info['code_files'] += 1
                lang = get_file_language(file_path)
                if lang != 'Unknown':
                    project_info['languages'][lang] = project_info['languages'].get(lang, 0) + 1
    
    # Determine primary type based on key files and file counts
    type_scores = {}
    for proj_type, proj_patterns in patterns.items():
        score = 0
        
        # Score based on key files found
        for key_file in proj_patterns['key_files']:
            if any(key_file.lower() in kf.lower() for kf in project_info['key_files']):
                score += 10
        
        # Score based on file extensions
        for ext in proj_patterns['extensions']:
            lang = get_file_language(f"dummy{ext}")
            if lang in project_info['languages']:
                score += project_info['languages'][lang] * 2
        
        type_scores[proj_type] = score
    
    # Determine primary type
    if type_scores:
        primary_type = max(type_scores, key=type_scores.get)
        max_score = type_scores[primary_type]
        
        if max_score > 0:
            project_info['primary_type'] = primary_type
            project_info['confidence'] = 'High' if max_score >= 20 else 'Medium' if max_score >= 10 else 'Low'
            
            # Add technologies and build tools for primary type
            if primary_type in patterns:
                project_info['technologies'].extend(patterns[primary_type]['frameworks'])
                project_info['build_tools'].extend(patterns[primary_type]['build_tools'])
    
    # Remove duplicates
    project_info['secondary_types'] = list(set(project_info['secondary_types']))
    if project_info['primary_type'] in project_info['secondary_types']:
        project_info['secondary_types'].remove(project_info['primary_type'])
    
    return project_info

def _ai_project_analysis(directory: str, project_info: dict):
    """AI-powered deeper project analysis."""
    print_with_rich("\n🤖 VritraAI performing deeper analysis...", "info")
    
    # Prepare project summary for AI
    summary = f"""Project Directory: {directory}
Primary Type: {project_info['primary_type']}
Secondary Types: {', '.join(project_info['secondary_types'])}
Total Files: {project_info['total_files']}
Code Files: {project_info['code_files']}
Key Files: {', '.join(project_info['key_files'][:10])}
Languages: {', '.join([f'{lang} ({count} files)' for lang, count in project_info['languages'].items()])}"""
    
    prompt = f"""As a software architecture expert, analyze this project structure and provide insights:

{summary}

Please provide:
📈 **Architecture Assessment**: Overall project structure and organization
🎯 **Purpose Detection**: What this project likely does based on structure
🛠️ **Technology Stack**: Detailed analysis of technologies used
📉 **Complexity Level**: Beginner/Intermediate/Advanced project assessment
📊 **Quality Indicators**: Code organization, best practices observed
🕰️ **Development Stage**: Early/Active/Mature development assessment
💡 **Recommendations**: Suggestions for improvement or missing components
🔍 **Potential Issues**: Areas that might need attention

Provide a comprehensive but concise analysis."""
    
    ai_analysis = get_ai_response(prompt)
    if ai_analysis:
        print_with_rich("\n🤖 VritraAI Project Analysis\n", "info")
        print_ai_response(ai_analysis, use_typewriter=True)
        print()

def dependencies_check_command(args: List[str]):
    """Check for outdated dependencies and security issues."""
    target_dir = args[0] if args else "."
    # Expand ~ and environment variables
    target_dir = expand_path(target_dir)
    
    if not os.path.isdir(target_dir):
        print_with_rich(f"❌ Directory not found: {target_dir}", "error")
        return
    
    print_with_rich(f"🔍 Checking dependencies in: {os.path.abspath(target_dir)}", "info")
    
    dependency_files = _find_dependency_files(target_dir)
    
    if not dependency_files:
        print_with_rich("❌ No dependency files found in project", "warning")
        print_with_rich("💡 Common dependency files: package.json, requirements.txt, Gemfile, composer.json, go.mod, Cargo.toml", "info")
        return
    
    print_with_rich(f"\n📄 Found {len(dependency_files)} dependency files:", "success")
    for dep_file in dependency_files:
        print_with_rich(f"  • {dep_file}", "info")
    
    # Analyze each dependency file
    for dep_file in dependency_files:
        _analyze_dependency_file(os.path.join(target_dir, dep_file))

def _find_dependency_files(directory: str) -> list:
    """Find dependency management files."""
    dependency_patterns = [
        'package.json', 'package-lock.json', 'yarn.lock',  # Node.js
        'requirements.txt', 'Pipfile', 'poetry.lock', 'pyproject.toml',  # Python
        'Gemfile', 'Gemfile.lock',  # Ruby
        'composer.json', 'composer.lock',  # PHP
        'go.mod', 'go.sum',  # Go
        'Cargo.toml', 'Cargo.lock',  # Rust
        'pom.xml', 'build.gradle',  # Java
        'project.json', '*.csproj',  # .NET
        'pubspec.yaml'  # Dart/Flutter
    ]
    
    found_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower() in [p.lower() for p in dependency_patterns if not p.startswith('*')]:
                rel_path = os.path.relpath(os.path.join(root, file), directory)
                found_files.append(rel_path.replace('\\', '/'))
    
    return found_files

def _analyze_dependency_file(file_path: str):
    """Analyze a specific dependency file."""
    if not os.path.exists(file_path):
        return
    
    file_name = os.path.basename(file_path)
    print_with_rich(f"\n🔍 Analyzing: {file_name}", "info")
    
    try:
        content = read_file_content(file_path)
        if not content:
            return
        
        # Basic analysis based on file type
        if file_name == 'package.json':
            _analyze_package_json(content)
        elif file_name in ['requirements.txt', 'Pipfile']:
            _analyze_python_deps(content)
        elif file_name == 'Gemfile':
            _analyze_gemfile(content)
        elif file_name == 'composer.json':
            _analyze_composer_json(content)
        elif file_name in ['go.mod', 'Cargo.toml', 'pom.xml']:
            _analyze_generic_deps(content, file_name)
        
        # AI-powered analysis if enabled
        if AI_ENABLED:
            _ai_dependency_analysis(file_path, content, file_name)
            
    except Exception as e:
        print_with_rich(f"❌ Error analyzing {file_name}: {e}", "error")

def _analyze_package_json(content: str):
    """Analyze Node.js package.json file."""
    try:
        import json
        data = json.loads(content)
        
        deps = data.get('dependencies', {})
        dev_deps = data.get('devDependencies', {})
        
        print_with_rich(f"📦 Dependencies: {len(deps)}, Dev Dependencies: {len(dev_deps)}", "info")
        
        # Look for common frameworks
        frameworks = []
        if 'react' in deps: frameworks.append('React')
        if 'vue' in deps: frameworks.append('Vue.js')
        if '@angular/core' in deps: frameworks.append('Angular')
        if 'express' in deps: frameworks.append('Express.js')
        if 'next' in deps: frameworks.append('Next.js')
        
        if frameworks:
            print_with_rich(f"🎨 Frameworks detected: {', '.join(frameworks)}", "success")
        
    except json.JSONDecodeError:
        print_with_rich("❌ Invalid JSON format", "error")

def _analyze_python_deps(content: str):
    """Analyze Python dependency files."""
    lines = [line.strip() for line in content.split('\n') if line.strip() and not line.startswith('#')]
    deps = [line.split('==')[0].split('>=')[0].split('~=')[0] for line in lines if '==' in line or '>=' in line or '~=' in line]
    
    print_with_rich(f"🐍 Python packages: {len(deps)}", "info")
    
    # Look for common frameworks
    frameworks = []
    for dep in deps:
        dep_lower = dep.lower()
        if 'django' in dep_lower: frameworks.append('Django')
        elif 'flask' in dep_lower: frameworks.append('Flask')
        elif 'fastapi' in dep_lower: frameworks.append('FastAPI')
        elif 'streamlit' in dep_lower: frameworks.append('Streamlit')
        elif 'pandas' in dep_lower: frameworks.append('Pandas (Data Science)')
        elif 'tensorflow' in dep_lower: frameworks.append('TensorFlow (ML)')
        elif 'pytorch' in dep_lower: frameworks.append('PyTorch (ML)')
    
    if frameworks:
        print_with_rich(f"🎨 Frameworks detected: {', '.join(set(frameworks))}", "success")

def _analyze_gemfile(content: str):
    """Analyze Ruby Gemfile."""
    lines = [line.strip() for line in content.split('\n') if line.strip()]
    gems = [line for line in lines if line.startswith('gem ')]
    
    print_with_rich(f"💎 Ruby gems: {len(gems)}", "info")
    
    if any('rails' in line for line in gems):
        print_with_rich("🚄 Ruby on Rails detected", "success")

def _analyze_composer_json(content: str):
    """Analyze PHP composer.json."""
    try:
        import json
        data = json.loads(content)
        
        deps = data.get('require', {})
        dev_deps = data.get('require-dev', {})
        
        print_with_rich(f"🐘 PHP packages: {len(deps)}, Dev: {len(dev_deps)}", "info")
        
        # Look for frameworks
        frameworks = []
        for dep in deps:
            if 'laravel' in dep.lower(): frameworks.append('Laravel')
            elif 'symfony' in dep.lower(): frameworks.append('Symfony')
            elif 'codeigniter' in dep.lower(): frameworks.append('CodeIgniter')
        
        if frameworks:
            print_with_rich(f"🎨 Frameworks: {', '.join(frameworks)}", "success")
            
    except json.JSONDecodeError:
        print_with_rich("❌ Invalid JSON format", "error")

def _analyze_generic_deps(content: str, file_name: str):
    """Generic dependency analysis."""
    lines = len([line for line in content.split('\n') if line.strip()])
    print_with_rich(f"📄 {file_name}: {lines} lines of configuration", "info")

def _ai_dependency_analysis(file_path: str, content: str, file_name: str):
    """AI-powered dependency analysis."""
    if len(content) > 4000:
        content = content[:4000] + "\n... [Content truncated]"
    
    prompt = f"""As a software security and dependency management expert, analyze this {file_name} file:

File: {file_path}

{content}

Please provide:
⚠️ **Security Issues**: Outdated packages, known vulnerabilities
📈 **Version Analysis**: Packages that should be updated
🕰️ **Maintenance**: Packages that are no longer maintained
📦 **Dependencies**: Analysis of dependency tree complexity
💡 **Recommendations**: Best practices and improvements
🔒 **Security**: Potential security concerns
🏃 **Performance**: Dependencies that might impact performance

Focus on actionable recommendations for dependency management."""
    
    analysis = get_ai_response(prompt)
    if analysis:
        print_with_rich(f"\n📋 Dependency Analysis: {file_name}\n", "warning")
        print_ai_response(analysis, use_typewriter=True)
        print()

def project_health_command(args: List[str]):
    """Comprehensive project health analysis."""
    target_dir = args[0] if args else "."
    # Expand ~ and environment variables
    target_dir = expand_path(target_dir)
    
    if not os.path.isdir(target_dir):
        print_with_rich(f"❌ Directory not found: {target_dir}", "error")
        return
    
    print_with_rich(f"🎯 Analyzing project health: {os.path.abspath(target_dir)}", "info")
    
    health_report = _generate_health_report(target_dir)
    _display_health_report(health_report)
    
    # AI-powered health analysis
    if AI_ENABLED:
        _ai_health_analysis(target_dir, health_report)

def _generate_health_report(directory: str) -> dict:
    """Generate comprehensive project health report."""
    report = {
        'documentation': {'score': 0, 'details': []},
        'testing': {'score': 0, 'details': []},
        'structure': {'score': 0, 'details': []},
        'dependencies': {'score': 0, 'details': []},
        'security': {'score': 0, 'details': []},
        'maintenance': {'score': 0, 'details': []},
        'overall_score': 0
    }
    
    # Check documentation
    doc_files = ['README.md', 'README.txt', 'README.rst', 'docs/', 'documentation/']
    found_docs = []
    for root, dirs, files in os.walk(directory):
        for item in doc_files:
            if item in files or item.rstrip('/') in dirs:
                found_docs.append(item)
    
    report['documentation']['score'] = min(len(found_docs) * 25, 100)
    report['documentation']['details'] = found_docs if found_docs else ['No documentation files found']
    
    # Check testing
    test_patterns = ['test_', '_test.', 'tests/', 'test/', 'spec/', '__tests__/']
    test_files = 0
    for root, dirs, files in os.walk(directory):
        for file in files:
            if any(pattern in file.lower() for pattern in test_patterns):
                test_files += 1
        for dir_name in dirs:
            if any(pattern.rstrip('/') in dir_name.lower() for pattern in test_patterns):
                test_files += 5  # Bonus for test directories
    
    report['testing']['score'] = min(test_files * 10, 100)
    report['testing']['details'] = [f'Found {test_files} test files/directories']
    
    # Check project structure
    structure_score = 0
    structure_details = []
    
    # Check for common project files
    project_files = ['.gitignore', 'LICENSE', 'CHANGELOG.md', '.github/', 'ci/', '.ci/']
    found_structure = []
    for root, dirs, files in os.walk(directory):
        for item in project_files:
            if item in files or item.rstrip('/') in dirs:
                found_structure.append(item)
                structure_score += 15
    
    report['structure']['score'] = min(structure_score, 100)
    report['structure']['details'] = found_structure if found_structure else ['Basic project files missing']
    
    # Check dependencies
    dep_files = _find_dependency_files(directory)
    dep_score = min(len(dep_files) * 30, 100)
    report['dependencies']['score'] = dep_score
    report['dependencies']['details'] = dep_files if dep_files else ['No dependency management files']
    
    # Security check (basic)
    security_issues = []
    security_score = 100  # Start with full score, deduct for issues
    
    # Check for common security issues
    for root, dirs, files in os.walk(directory):
        for file in files:
            file_lower = file.lower()
            if any(pattern in file_lower for pattern in ['.env', 'secret', 'password', 'key', 'token']):
                if not file_lower.endswith('.example'):
                    security_issues.append(f'Potential secrets file: {file}')
                    security_score -= 20
    
    report['security']['score'] = max(security_score, 0)
    report['security']['details'] = security_issues if security_issues else ['No obvious security issues']
    
    # Maintenance indicators
    maintenance_score = 50  # Neutral starting point
    maintenance_details = []
    
    # Check for recent activity (if git repo)
    git_dir = os.path.join(directory, '.git')
    if os.path.exists(git_dir):
        maintenance_details.append('Git repository detected')
        maintenance_score += 25
    
    report['maintenance']['score'] = maintenance_score
    report['maintenance']['details'] = maintenance_details
    
    # Calculate overall score
    scores = [report[category]['score'] for category in report if category != 'overall_score']
    report['overall_score'] = sum(scores) // len(scores)
    
    return report

def _display_health_report(report: dict):
    """Display the project health report."""
    print_with_rich("\n🏆 Project Health Report", "success")
    print_with_rich("=" * 50, "info")
    
    # Overall score with color coding
    overall = report['overall_score']
    if overall >= 80:
        score_color = "success"
        score_emoji = "🌟"
    elif overall >= 60:
        score_color = "warning"
        score_emoji = "🟡"
    else:
        score_color = "error"
        score_emoji = "🔴"
    
    print_with_rich(f"\n{score_emoji} Overall Health Score: {overall}/100", score_color)
    
    # Category breakdown
    categories = {
        'documentation': '📚 Documentation',
        'testing': '🧪 Testing',
        'structure': '🏧 Project Structure',
        'dependencies': '📦 Dependencies',
        'security': '🔒 Security',
        'maintenance': '🔧 Maintenance'
    }
    
    for category, emoji_name in categories.items():
        score = report[category]['score']
        details = report[category]['details']
        
        # Color code based on score
        if score >= 70:
            color = "success"
        elif score >= 40:
            color = "warning"
        else:
            color = "error"
        
        print_with_rich(f"\n{emoji_name}: {score}/100", color)
        for detail in details[:3]:  # Limit details
            print_with_rich(f"  • {detail}", "info")

def _ai_health_analysis(directory: str, health_report: dict):
    """AI-powered project health analysis."""
    print_with_rich("\n🤖 VritraAI performing comprehensive health analysis...", "info")
    
    # Prepare health summary
    summary = f"""Project Health Summary:
Overall Score: {health_report['overall_score']}/100

Category Scores:
- Documentation: {health_report['documentation']['score']}/100
- Testing: {health_report['testing']['score']}/100
- Structure: {health_report['structure']['score']}/100
- Dependencies: {health_report['dependencies']['score']}/100
- Security: {health_report['security']['score']}/100
- Maintenance: {health_report['maintenance']['score']}/100

Key Issues Identified:
- Documentation: {', '.join(health_report['documentation']['details'])}
- Testing: {', '.join(health_report['testing']['details'])}
- Security: {', '.join(health_report['security']['details'])}"""
    
    prompt = f"""As a software project consultant, analyze this project health report and provide actionable recommendations:

{summary}

Please provide:
🎯 **Priority Issues**: Most critical problems that need immediate attention
🛣️ **Action Plan**: Step-by-step plan to improve project health
📊 **Quick Wins**: Easy improvements that can boost the health score
📚 **Documentation**: Specific documentation recommendations
🧪 **Testing**: Testing strategy recommendations
🔒 **Security**: Security hardening suggestions
🔧 **Maintenance**: Long-term maintenance recommendations
💯 **Best Practices**: Industry best practices for this project type

Provide specific, actionable recommendations prioritized by impact and effort."""
    
    analysis = get_ai_response(prompt)
    if analysis:
        cleaned_analysis = clean_ai_response(analysis)
        
        # Clean output with typewriter effect - NO BORDERS!
        print()
        print_with_rich("="*60, "info")
        print_with_rich("🎯 Project Health Recommendations", "success")
        print_with_rich("="*60, "info")
        print()
        
        # Use typewriter effect for AI response with code block highlighting
        print_ai_response_with_code_blocks(cleaned_analysis)
        print()
        print_with_rich("="*60, "info")

def missing_files_command(args: List[str]):
    """AI suggests missing files for the project."""
    target_dir = args[0] if args else "."
    # Expand ~ and environment variables
    target_dir = expand_path(target_dir)
    
    if not os.path.isdir(target_dir):
        print_with_rich(f"❌ Directory not found: {target_dir}", "error")
        return
    
    if not AI_ENABLED:
        print_with_rich("❌ AI features disabled. Configure API key first.", "error")
        return
    
    print_with_rich(f"🔍 Analyzing missing files for: {os.path.abspath(target_dir)}", "info")
    
    # Get project structure
    project_info = _analyze_project_structure(target_dir)
    
    # Get file list
    existing_files = []
    for root, dirs, files in os.walk(target_dir):
        # Skip hidden and common ignore directories
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', '__pycache__', 'target', 'build', 'dist']]
        
        for file in files:
            if not file.startswith('.'):
                rel_path = os.path.relpath(os.path.join(root, file), target_dir).replace('\\', '/')
                existing_files.append(rel_path)
    
    prompt = f"""As a software project consultant, analyze this project structure and suggest missing files that would improve the project:

Project Type: {project_info['primary_type']}
Secondary Types: {', '.join(project_info['secondary_types'])}
Total Files: {project_info['total_files']}
Code Files: {project_info['code_files']}
Languages: {', '.join([f'{lang} ({count})' for lang, count in project_info['languages'].items()])}

Existing Key Files:
{chr(10).join([f'- {f}' for f in project_info['key_files'][:20]])}

Existing Files (sample):
{chr(10).join([f'- {f}' for f in existing_files[:30]])}

Please suggest missing files that would benefit this project:

📚 **Documentation**: README, CHANGELOG, API docs, etc.
🧪 **Testing**: Test files, test configuration
🔧 **Configuration**: Build files, CI/CD, linting configs
🔒 **Security**: Security policies, .gitignore, etc.
🏃 **Development**: Development helpers, scripts
📦 **Deployment**: Docker files, deployment configs
📄 **Legal**: License, contributing guidelines
🎯 **Quality**: Code quality tools, formatting configs

For each suggestion:
- Explain why it's needed
- Provide template content where helpful
- Indicate priority level (High/Medium/Low)

Focus on files that would have the biggest positive impact on project quality and maintainability."""
    
    print_with_rich("🤖 VritraAI analyzing project structure and suggesting improvements...", "info")
    suggestions = get_ai_response(prompt)
    
    if suggestions:
        cleaned_suggestions = clean_ai_response(suggestions)
        
        # Clean output with typewriter effect - NO BORDERS!
        print()
        print_with_rich("="*60, "info")
        print_with_rich("📁 Missing Files Suggestions", "info")
        print_with_rich("="*60, "info")
        print()
        
        # Use typewriter effect for AI response with code block highlighting
        print_ai_response_with_code_blocks(cleaned_suggestions)
        print()
        print_with_rich("="*60, "info")
        
        log_session(f"Missing files analysis: {target_dir}")
    else:
        print_with_rich("❌ Failed to get missing files suggestions", "error")

def project_optimize_command(args: List[str]):
    """AI suggests project optimizations."""
    target_dir = args[0] if args else "."
    # Expand ~ and environment variables
    target_dir = expand_path(target_dir)
    
    if not os.path.isdir(target_dir):
        print_with_rich(f"❌ Directory not found: {target_dir}", "error")
        return
    
    if not AI_ENABLED:
        print_with_rich("❌ AI features disabled. Configure API key first.", "error")
        return
    
    print_with_rich(f"🚀 Optimizing project: {os.path.abspath(target_dir)}", "info")
    
    # Comprehensive project analysis
    project_info = _analyze_project_structure(target_dir)
    health_report = _generate_health_report(target_dir)
    dependency_files = _find_dependency_files(target_dir)
    
    # Analyze project size and complexity
    total_size = 0
    large_files = []
    file_types = {}
    all_files = []  # Track all files for debugging
    
    # Properly resolve target directory path
    target_dir_abs = os.path.abspath(target_dir)
    
    for root, dirs, files in os.walk(target_dir_abs):
        # Filter directories but don't skip completely - just common build directories
        dirs[:] = [d for d in dirs if d not in ['node_modules', '__pycache__', 'target', 'build', 'dist', '.git', '__MACOSX']]
        
        for file in files:
            # Skip only Mac metadata files and truly hidden system files
            if file in ['.DS_Store', 'Thumbs.db', 'desktop.ini']:
                continue
            
            file_path = os.path.join(root, file)
            try:
                size = os.path.getsize(file_path)
                total_size += size
                
                # Track relative path
                rel_path = os.path.relpath(file_path, target_dir_abs)
                all_files.append((rel_path, size))
                
                if size > 1024 * 1024:  # Files larger than 1MB
                    large_files.append((rel_path, size))
                
                ext = os.path.splitext(file)[1].lower()
                if ext:  # Only track files with extensions
                    file_types[ext] = file_types.get(ext, 0) + 1
                else:
                    file_types['[no extension]'] = file_types.get('[no extension]', 0) + 1
                
            except (OSError, PermissionError) as e:
                # Log but continue on error
                continue
    
    # Debug output to verify we're finding files
    if len(all_files) == 0:
        print_with_rich("⚠️ Warning: No files found in directory. Check permissions.", "warning")
    else:
        print_with_rich(f"✓ Found {len(all_files)} files totaling {total_size / (1024*1024):.2f} MB", "success")
    
    # Prepare comprehensive analysis for AI with actual file samples
    sample_files_str = "\n".join([f"- {file} ({size} bytes)" for file, size in all_files[:20]])
    if len(all_files) > 20:
        sample_files_str += f"\n... and {len(all_files) - 20} more files"
    
    analysis_data = f"""Project Optimization Analysis:

Project Information:
- Type: {project_info['primary_type']}
- Secondary Types: {', '.join(project_info['secondary_types'])}
- Total Files: {len(all_files)} (found in directory walk)
- Code Files: {project_info['code_files']}
- Total Size: {total_size / (1024*1024):.2f} MB
- Languages: {', '.join([f'{lang} ({count})' for lang, count in project_info['languages'].items()])}

Actual Files in Project:
{sample_files_str}

Health Scores:
- Overall: {health_report['overall_score']}/100
- Documentation: {health_report['documentation']['score']}/100
- Testing: {health_report['testing']['score']}/100
- Structure: {health_report['structure']['score']}/100
- Security: {health_report['security']['score']}/100

Dependency Management:
- Dependency Files: {len(dependency_files)}
- Files: {', '.join(dependency_files) if dependency_files else 'None'}

File Distribution:
{chr(10).join([f'- {ext}: {count} files' for ext, count in sorted(file_types.items(), key=lambda x: x[1], reverse=True)[:10]])}

Large Files (>1MB):
{chr(10).join([f'- {file}: {size/(1024*1024):.1f}MB' for file, size in large_files[:5]]) if large_files else 'None'}"""
    
    prompt = f"""As a software optimization expert, analyze this project and provide comprehensive optimization recommendations:

{analysis_data}

Please provide optimization suggestions in these areas:

🚀 **Performance Optimizations**:
- Build process improvements
- Bundle size reduction
- Runtime performance enhancements
- Database/query optimizations

💾 **Storage & Size Optimizations**:
- File size reduction strategies
- Asset optimization
- Dependency cleanup
- Build artifact optimization

🏧 **Project Structure**:
- Code organization improvements
- Modularization suggestions
- Architecture enhancements
- Design pattern recommendations

🔧 **Development Workflow**:
- Build tool optimizations
- Development environment improvements
- CI/CD pipeline enhancements
- Automation opportunities

📦 **Dependency Management**:
- Dependency optimization
- Version management
- Security updates
- Tree shaking opportunities

🔒 **Security Optimizations**:
- Security hardening
- Vulnerability mitigation
- Best practice implementation

📊 **Monitoring & Analytics**:
- Performance monitoring setup
- Error tracking
- Usage analytics

For each recommendation:
- Explain the benefits
- Provide implementation steps
- Estimate effort and impact
- Suggest tools or techniques

Prioritize recommendations by impact vs effort ratio."""
    
    print_with_rich("🤖 VritraAI generating comprehensive optimization recommendations...", "info")
    optimization_result = get_ai_response(prompt)
    
    if optimization_result:
        cleaned_result = clean_ai_response(optimization_result)
        
        # Clean output with typewriter effect - NO BORDERS!
        print()
        print_with_rich("="*60, "info")
        print_with_rich("🚀 Project Optimization Recommendations", "success")
        print_with_rich("="*60, "info")
        print()
        
        # Use typewriter effect for AI response with code block highlighting
        print_ai_response_with_code_blocks(cleaned_result)
        print()
        print_with_rich("="*60, "info")
        
        log_session(f"Project optimization analysis: {target_dir}")
    else:
        print_with_rich("❌ Failed to get optimization recommendations", "error")

def apikey_command(args: List[str]):
    """Manage API keys for different providers."""
    global AI_ENABLED, API_KEY, GEMINI_API_KEY, current_config, API_BASE
    
    if not args or args[0] == "help":
        print_with_rich("\n🔑 API Key Management Commands:", "info")
        print_with_rich("━" * 60, "info")
        print_with_rich("\n📋 Key Management:", "success")
        print_with_rich("  apikey show                    - Show current API key status", "info")
        print_with_rich("  apikey openrouter <key>        - Set/replace OpenRouter API key", "info")
        print_with_rich("  apikey gemini <key>            - Set/replace Gemini API key", "info")
        print_with_rich("  apikey clear <provider>        - Clear specific provider key", "info")
        print_with_rich("  apikey clear all               - Clear all API keys", "info")
        
        print_with_rich("\n🧪 Testing & Validation:", "success")
        print_with_rich("  apikey test                    - Test current API key", "info")
        print_with_rich("  apikey test openrouter         - Test OpenRouter API key", "info")
        print_with_rich("  apikey test gemini             - Test Gemini API key", "info")
        
        print_with_rich("\n🤖 Model Management:", "success")
        print_with_rich("  model list                     - Detailed model listing", "info")
        
        print_with_rich("\n📖 Examples:", "success")
        print_with_rich("  apikey openrouter sk-or-v1-your-key-here", "warning")
        print_with_rich("  apikey gemini AIzaSy-your-gemini-key-here", "warning")
        print_with_rich("  apikey show", "warning")
        print_with_rich("  apikey test openrouter", "warning")
        
        print_with_rich("\n💡 Notes:", "success")
        print_with_rich("  • Keys are automatically saved and persist across sessions", "info")
        print_with_rich("  • Setting a key will replace existing key for that provider", "info")
        print_with_rich("  • Use 'api_base openrouter' or 'api_base gemini' to switch providers", "info")
        print_with_rich("━" * 60, "info")
        return
    
    subcmd = args[0].lower()
    
    if subcmd == "show":
        # Show API key status for all providers
        print_with_rich("\n🔑 Current API Key Status:", "info")
        print_with_rich("━" * 50, "info")
        
        # OpenRouter status
        if API_KEY:
            masked_key = API_KEY[:8] + "*" * (len(API_KEY) - 12) + API_KEY[-4:] if len(API_KEY) > 12 else "*" * len(API_KEY)
            print_with_rich(f"  🟢 OpenRouter: {masked_key}", "success")
        else:
            print_with_rich("  🔴 OpenRouter: Not configured", "warning")
        
        # Gemini status
        if GEMINI_API_KEY:
            masked_key = GEMINI_API_KEY[:8] + "*" * (len(GEMINI_API_KEY) - 12) + GEMINI_API_KEY[-4:] if len(GEMINI_API_KEY) > 12 else "*" * len(GEMINI_API_KEY)
            print_with_rich(f"  🟢 Gemini: {masked_key}", "success")
        else:
            print_with_rich("  🔴 Gemini: Not configured", "warning")
        
        # Current active provider
        print_with_rich(f"\n  🎯 Active Provider: {API_BASE.upper()}", "info")
        if AI_ENABLED:
            print_with_rich(f"  ✅ AI Status: Enabled", "success")
            print_with_rich(f"  🤖 Current Model: {MODEL}", "info")
        else:
            print_with_rich(f"  ❌ AI Status: Disabled", "warning")
        
        print_with_rich("━" * 50, "info")
    
    elif subcmd == "openrouter" and len(args) > 1:
        # Set/replace OpenRouter API key
        new_key = args[1]
        
        if len(new_key) < 20:  # Basic validation
            print_with_rich("⚠️  Warning: API key seems too short. Please verify.", "warning")
        
        old_key_exists = bool(API_KEY)
        API_KEY = new_key
        
        # Update config
        if not current_config:
            current_config = load_config() or {"api_key": "", "model": "gemini-2.0-flash"}
        current_config["api_key"] = API_KEY
        
        # Update AI_ENABLED if we're using OpenRouter
        if API_BASE == "openrouter":
            AI_ENABLED = bool(API_KEY)
            current_config["ai_enabled"] = AI_ENABLED
        
        # Update OpenAI client
        try:
            import openai
            openai.api_key = API_KEY
            openai.api_base = "https://openrouter.ai/api/v1"
        except:
            pass
        
        # Save configuration using config_manager (more reliable)
        save_success = False
        if config_manager:
            try:
                save_success = config_manager.set_value('api_key', API_KEY)
                if save_success and API_BASE == "openrouter":
                    config_manager.set_value('ai_enabled', AI_ENABLED)
            except Exception as e:
                print_with_rich(f"⚠️  Warning: Failed to save via config_manager ({e})", "warning")
        
        # Fallback to legacy save if needed
        if not save_success:
            try:
                from config import save_config
                sync_config_version(current_config)
                save_success = save_config(current_config)
            except Exception as e:
                print_with_rich(f"⚠️  Warning: Failed to save config ({e})", "warning")
        
        # Show result
        action = "replaced" if old_key_exists else "configured"
        if save_success:
            print_with_rich(f"🔑 OpenRouter API key {action} and saved successfully!", "success")
            print_with_rich("✅ Configuration persisted - key will be available in future sessions", "success")
        else:
            print_with_rich(f"🔑 OpenRouter API key {action} in memory!", "success")
            print_with_rich("⚠️  Warning: Configuration not saved to disk - changes may not persist", "warning")
    
    elif subcmd == "gemini" and len(args) > 1:
        # Set/replace Gemini API key
        new_key = args[1]
        
        if len(new_key) < 30:  # Gemini keys are usually longer
            print_with_rich("⚠️  Warning: Gemini API key seems too short. Please verify.", "warning")
        
        old_key_exists = bool(GEMINI_API_KEY)
        GEMINI_API_KEY = new_key
        
        # Update config
        if not current_config:
            current_config = load_config() or {"api_key": "", "model": "gemini-2.0-flash"}
        current_config["gemini_api_key"] = GEMINI_API_KEY
        
        # Update AI_ENABLED if we're using Gemini
        if API_BASE == "gemini":
            AI_ENABLED = bool(GEMINI_API_KEY)
            current_config["ai_enabled"] = AI_ENABLED
        
        # Save configuration using config_manager (more reliable)
        save_success = False
        if config_manager:
            try:
                save_success = config_manager.set_value('gemini_api_key', GEMINI_API_KEY)
                if save_success and API_BASE == "gemini":
                    config_manager.set_value('ai_enabled', AI_ENABLED)
            except Exception as e:
                print_with_rich(f"⚠️  Warning: Failed to save via config_manager ({e})", "warning")
        
        # Fallback to legacy save if needed
        if not save_success:
            try:
                from config import save_config
                sync_config_version(current_config)
                save_success = save_config(current_config)
            except Exception as e:
                print_with_rich(f"⚠️  Warning: Failed to save config ({e})", "warning")
        
        # Show result
        action = "replaced" if old_key_exists else "configured"
        if save_success:
            print_with_rich(f"🔑 Gemini API key {action} and saved successfully!", "success")
            print_with_rich("✅ Configuration persisted - key will be available in future sessions", "success")
        else:
            print_with_rich(f"🔑 Gemini API key {action} in memory!", "success")
            print_with_rich("⚠️  Warning: Configuration not saved to disk - changes may not persist", "warning")
        
        # Initialize API after saving to avoid blocking
        if API_BASE == "gemini":
            try:
                initialize_api()
            except Exception as e:
                print_with_rich(f"⚠️  Warning: API initialization issue ({e})", "warning")
    
    
    elif subcmd == "clear":
        if len(args) < 2:
            print_with_rich("⚠️  Please specify provider: 'openrouter', 'gemini', or 'all'", "warning")
            return
        
        provider = args[1].lower()
        
        if provider == "openrouter":
            if not API_KEY:
                print_with_rich("❌ No OpenRouter API key to clear", "warning")
                return
            
            try:
                user_input = input("⚠️  Are you sure you want to clear the OpenRouter API key? (y/n): ").strip().lower()
                if user_input in ['y', 'yes']:
                    API_KEY = ""
                    
                    if not current_config:
                        current_config = load_config() or {"api_key": "", "model": "gemini-2.0-flash"}
                    current_config["api_key"] = ""
                    
                    # Update AI_ENABLED if OpenRouter is active
                    if API_BASE == "openrouter":
                        AI_ENABLED = False
                        current_config["ai_enabled"] = False
                    
                    # Auto-save configuration
                    try:
                        from config import save_config
                        if save_config(current_config):
                            print_with_rich("🗑️  OpenRouter API key cleared and saved.", "warning")
                            print_with_rich("✅ Configuration persisted", "success")
                        else:
                            raise Exception("Failed to save configuration")
                    except Exception as e:
                        print_with_rich("🗑️  OpenRouter API key cleared.", "warning")
                        print_with_rich(f"⚠️  Warning: Failed to save config automatically ({e})", "warning")
                else:
                    print_with_rich("Operation cancelled", "info")
            except (EOFError, KeyboardInterrupt):
                print_with_rich("\nOperation cancelled", "info")
        
        elif provider == "gemini":
            if not GEMINI_API_KEY:
                print_with_rich("❌ No Gemini API key to clear", "warning")
                return
            
            try:
                user_input = input("⚠️  Are you sure you want to clear the Gemini API key? (y/n): ").strip().lower()
                if user_input in ['y', 'yes']:
                    GEMINI_API_KEY = ""
                    
                    if not current_config:
                        current_config = load_config() or {"api_key": "", "model": "gemini-2.0-flash"}
                    current_config["gemini_api_key"] = ""
                    
                    # Update AI_ENABLED if Gemini is active
                    if API_BASE == "gemini":
                        AI_ENABLED = False
                        current_config["ai_enabled"] = False
                    
                    # Auto-save configuration
                    try:
                        from config import save_config
                        if save_config(current_config):
                            print_with_rich("🗑️  Gemini API key cleared and saved.", "warning")
                            print_with_rich("✅ Configuration persisted", "success")
                        else:
                            raise Exception("Failed to save configuration")
                    except Exception as e:
                        print_with_rich("🗑️  Gemini API key cleared.", "warning")
                        print_with_rich(f"⚠️  Warning: Failed to save config automatically ({e})", "warning")
                else:
                    print_with_rich("Operation cancelled", "info")
            except (EOFError, KeyboardInterrupt):
                print_with_rich("\nOperation cancelled", "info")
        
        elif provider == "all":
            if not API_KEY and not GEMINI_API_KEY:
                print_with_rich("❌ No API keys to clear", "warning")
                return
            
            try:
                user_input = input("⚠️  Are you sure you want to clear ALL API keys? (y/n): ").strip().lower()
                if user_input in ['y', 'yes']:
                    API_KEY = ""
                    GEMINI_API_KEY = ""
                    AI_ENABLED = False
                    
                    if not current_config:
                        current_config = load_config() or {"api_key": "", "model": "gemini-2.0-flash"}
                    current_config["api_key"] = ""
                    current_config["gemini_api_key"] = ""
                    current_config["ai_enabled"] = False
                    
                    # Auto-save configuration
                    try:
                        from config import save_config
                        if save_config(current_config):
                            print_with_rich("🗑️  All API keys cleared and saved. AI features disabled.", "warning")
                            print_with_rich("✅ Configuration persisted", "success")
                        else:
                            raise Exception("Failed to save configuration")
                    except Exception as e:
                        print_with_rich("🗑️  All API keys cleared. AI features disabled.", "warning")
                        print_with_rich(f"⚠️  Warning: Failed to save config automatically ({e})", "warning")
                else:
                    print_with_rich("Operation cancelled", "info")
            except (EOFError, KeyboardInterrupt):
                print_with_rich("\nOperation cancelled", "info")
        
        else:
            print_with_rich(f"❌ Unknown provider: {provider}", "error")
            print_with_rich("💡 Use 'openrouter', 'gemini', or 'all'", "info")
    
    elif subcmd == "test":
        # Test API key functionality
        if not API_KEY:
            print_with_rich("❌ No API key configured for testing", "error")
            return
        
        print_with_rich("🧪 Testing API key functionality...", "info")
        
        # Simple test with AI
        test_response = get_ai_response("Respond with just 'API key working!' to confirm functionality.")
        
        if test_response:
            print_with_rich("✅ API key test successful!", "success")
            print_with_rich(f"🤖 VritraAI Response: {test_response}", "info")
        else:
            print_with_rich("❌ API key test failed. Please check your key and internet connection.", "error")
    
    else:
        print_with_rich(f"Unknown apikey command: {subcmd}", "error")
        apikey_command([])  # Show help

def api_base_command(args: List[str]):
    """Manage API base switching between OpenRouter and Gemini."""
    global API_BASE, AI_ENABLED, MODEL, AI_MODELS, current_config, GEMINI_API_KEY, API_KEY
    
    if not args:
        print_with_rich("API Base Management Commands:", "info")
        print_with_rich("  api_base show           - Show current API base", "info")
        print_with_rich("  api_base openrouter     - Switch to OpenRouter API", "info")
        print_with_rich("  api_base gemini         - Switch to Gemini API", "info")
        print_with_rich("  api_base status         - Show detailed API status", "info")
        return
    
    subcmd = args[0].lower()
    
    if subcmd == "show":
        print_with_rich(f"🌐 Current API Base: {API_BASE}", "info")
        if API_BASE == "gemini":
            status = "✅ Enabled" if GEMINI_API_KEY else "❌ Disabled"
            print_with_rich(f"📡 Gemini API Status: {status}", "success" if "Enabled" in status else "error")
            if GEMINI_API_KEY:
                masked_key = GEMINI_API_KEY[:8] + "*" * (len(GEMINI_API_KEY) - 12) + GEMINI_API_KEY[-4:] if len(GEMINI_API_KEY) > 12 else "*" * len(GEMINI_API_KEY)
                print_with_rich(f"🔑 Gemini API Key: {masked_key}", "info")
            else:
                print_with_rich("⚠️ No Gemini API key configured", "warning")
        else:
            status = "✅ Enabled" if API_KEY else "❌ Disabled"
            print_with_rich(f"📡 OpenRouter API Status: {status}", "success" if "Enabled" in status else "error")
            if API_KEY:
                masked_key = API_KEY[:8] + "*" * (len(API_KEY) - 12) + API_KEY[-4:] if len(API_KEY) > 12 else "*" * len(API_KEY)
                print_with_rich(f"🔑 OpenRouter API Key: {masked_key}", "info")
            else:
                print_with_rich("⚠️ No OpenRouter API key configured", "warning")
        
        print_with_rich(f"🤖 Current Model: {MODEL}", "info")
        print_with_rich(f"🔥 AI Features: {'Enabled' if AI_ENABLED else 'Disabled'}", "success" if AI_ENABLED else "error")
    
    elif subcmd == "openrouter":
        print_with_rich("🔄 Switching to OpenRouter API...", "info")
        API_BASE = "openrouter"
        
        # Update config - preserve current theme and other settings
        from config import config, save_config
        # Preserve theme and other UI settings
        current_theme = config.get("theme")
        current_prompt_style = config.get("prompt_style")
        
        config["api_base"] = "openrouter"
        
        # Preserve or restore the last used OpenRouter model
        last_openrouter_model = config.get("last_openrouter_model", "openai/gpt-3.5-turbo")
        
        # Only switch model if current model is a Gemini model
        if MODEL in [m["name"] for m in GEMINI_MODELS.values()]:
            MODEL = last_openrouter_model
            config["model"] = MODEL
        else:
            # Save current OpenRouter model for future switches
            config["last_openrouter_model"] = MODEL
        
        # Ensure theme and prompt_style are preserved (don't overwrite)
        if current_theme:
            config["theme"] = current_theme
        if current_prompt_style:
            config["prompt_style"] = current_prompt_style
        
        # Update AI models and status
        update_ai_models()
        initialize_api()
        
        # Save config
        if save_config(config):
            print_with_rich("✅ Successfully switched to OpenRouter API", "success")
            print_with_rich(f"🤖 Model set to: {MODEL}", "info")
            if not API_KEY:
                print_with_rich("⚠️ Don't forget to configure your OpenRouter API key with 'apikey set <key>'", "warning")
        else:
            print_with_rich("❌ Failed to save configuration", "error")
    
    elif subcmd == "gemini":
        print_with_rich("🔄 Switching to Gemini API...", "info")
        
        # Save current model as last OpenRouter model if applicable
        from config import config, save_config
        # Preserve theme and other UI settings
        current_theme = config.get("theme")
        current_prompt_style = config.get("prompt_style")
        
        if API_BASE == "openrouter" and MODEL not in [m["name"] for m in GEMINI_MODELS.values()]:
            config["last_openrouter_model"] = MODEL
        
        API_BASE = "gemini"
        config["api_base"] = "gemini"
        
        # Restore or set Gemini model
        last_gemini_model = config.get("last_gemini_model", "gemini-2.0-flash")
        
        # Only switch model if current model is an OpenRouter model
        if MODEL not in [m["name"] for m in GEMINI_MODELS.values()]:
            MODEL = last_gemini_model
            config["model"] = MODEL
        else:
            # Save current Gemini model for future switches
            config["last_gemini_model"] = MODEL
        
        # Ensure theme and prompt_style are preserved (don't overwrite)
        if current_theme:
            config["theme"] = current_theme
        if current_prompt_style:
            config["prompt_style"] = current_prompt_style
        
        # Update AI models and status
        update_ai_models()
        initialize_api()
        
        # Save config
        if save_config(config):
            print_with_rich("✅ Successfully switched to Gemini API", "success")
            print_with_rich(f"🤖 Model set to: {MODEL}", "info")
            if not GEMINI_API_KEY:
                print_with_rich("⚠️ Don't forget to configure your Gemini API key with 'apikey gemini <key>'", "warning")
        else:
            print_with_rich("❌ Failed to save configuration", "error")
    
    elif subcmd == "status":
        print_with_rich("🌐 Complete API Status Report:", "info")
        print_with_rich(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "info")
        
        # Current API Base
        print_with_rich(f"📡 Active API Base: {API_BASE}", "success")
        print_with_rich(f"🤖 Current Model: {MODEL}", "info")
        print_with_rich(f"🔥 AI Features: {'✅ Enabled' if AI_ENABLED else '❌ Disabled'}", "success" if AI_ENABLED else "error")
        
        print_with_rich(f"\n🔧 OpenRouter Status:", "info")
        or_status = "✅ Ready" if API_KEY else "❌ No API Key"
        print_with_rich(f"  Status: {or_status}", "success" if "Ready" in or_status else "error")
        if API_KEY:
            masked_key = API_KEY[:8] + "*" * (len(API_KEY) - 12) + API_KEY[-4:] if len(API_KEY) > 12 else "*" * len(API_KEY)
            print_with_rich(f"  API Key: {masked_key}", "info")
        print_with_rich(f"  Available Models: {len(OPENROUTER_MODELS)}", "info")
        
        print_with_rich(f"\n🔧 Gemini Status:", "info")
        gem_status = "✅ Ready" if GEMINI_API_KEY else "❌ Not Ready"
        print_with_rich(f"  Status: {gem_status}", "success" if "Ready" in gem_status else "error")
        if GEMINI_API_KEY:
            masked_key = GEMINI_API_KEY[:8] + "*" * (len(GEMINI_API_KEY) - 12) + GEMINI_API_KEY[-4:] if len(GEMINI_API_KEY) > 12 else "*" * len(GEMINI_API_KEY)
            print_with_rich(f"  API Key: {masked_key}", "info")
        else:
            print_with_rich("  API Key: ❌ Not configured", "error")
        print_with_rich(f"  API Method: ✅ HTTP Requests (built-in)", "success")
        print_with_rich(f"  Available Models: {len(GEMINI_MODELS)}", "info")
        
        print_with_rich(f"\n💡 Quick Commands:", "info")
        if API_BASE == "gemini" and not GEMINI_API_KEY:
            print_with_rich("  apikey gemini <key>      - Set Gemini API key", "warning")
        elif API_BASE == "openrouter" and not API_KEY:
            print_with_rich("  apikey openrouter <key>  - Set OpenRouter API key", "warning")
        print_with_rich("  model list               - View available models", "info")
        print_with_rich("  api_base gemini          - Switch to Gemini", "info")
        print_with_rich("  api_base openrouter      - Switch to OpenRouter", "info")
    
    else:
        print_with_rich(f"Unknown api_base command: {subcmd}", "error")
        api_base_command([])  # Show help

# --- Startup Animation and Banner System ---

# Central repository of all available MOTD banners.
# Each banner has a stable ID ("1".."15"), a human-readable name, and a
# template string that uses system statistics placeholders filled at runtime.
BANNERS: Dict[str, Dict[str, str]] = {
    "1": {
        "name": "Ubuntu-style MOTD (default)",
        "template": """ Welcome to VritraAI Professional Edition {version}

 * Documentation:  https://vritraai.vritrasec.com/docs/
 * Management:     https://github.com/VritraSecz/VritraAI
 * Support:        https://vritrasec.com/more/get-in-touch/

  System information as of {current_time}:

  System load:    {load}               Memory usage: {mem}%
  Usage of /:     {disk_used}% of {disk_total}  Swap usage:   {swap}%
  Processes:      {procs}                Users logged: {users}
  AI subsystem:   {ai_subsystem:<8}        API status:   {api_status}
  Model loaded:   {model}

{ai_extra}
 * Type 'help' for commands, 'ai <question>' to chat, 'review <file>' for code analysis
 * Use 'apikey help' for API setup, 'project_type' for intelligent detection

Last login: {current_time} from console

{username}@{hostname}:~$ VritraAI Professional Shell initialized
"""
    },
    "2": {
        "name": "Professional Edition – Wide",
        "template": """──────────────────────────────────────────────────────────────
   V R I T R A A I   P R O F E S S I O N A L   E D I T I O N

       Precision • Intelligence • Autonomous Code Analysis
──────────────────────────────────────────────────────────────

  System:       {sys_name} {sys_ver}
  Load:         {load}              Memory: {mem}%
  Disk:         {disk_used}% of {disk_total}    Swap: {swap}%
  Users:        {users}             Processes: {procs}
  Model:        {model}             API: {api_status}

  Hints: help • ai <query> • review <file> • apikey help
──────────────────────────────────────────────────────────────
"""
    },
    "3": {
        "name": "Pro Shell Panel",
        "template": """╔═════════════════════════════════════════════════════════╗
            V R I T R A A I  •  P R O  S H E L L            
 ─────────────────────────────────────────────────────────
  Mode: Professional Edition {version}                      
  AI Core: {model}                                          
  API Link: {api_status}                                    
╠─────────────────────────────────────────────────────────╣
  System Load:  {load}      Memory: {mem}%                  
  Disk Usage:   {disk_used}% of {disk_total}                
  Processes:    {procs}     Logged Users: {users}           
╚═════════════════════════════════════════════════════════╝

Commands: help • ai • review • apikey • project_type
"""
    },
    "4": {
        "name": "Compact Pro Status",
        "template": """[ VritraAI Professional {version} ]
--------------------------------------
 Core Model:     {model}
 API Status:     {api_status}

 Load Avg:       {load}
 Memory:         {mem}%
 Disk:           {disk_used}% / {disk_total}
 Processes:      {procs}
 Logged Users:   {users}

 Tools: help | ai | review <file> | apikey help
--------------------------------------
"""
    },
    "5": {
        "name": "Research Node",
        "template": """━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    V R I T R A A I   •   R E S E A R C H  N O D E
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Edition: Professional {version}
  AI Engine: {model}
  API Link:  {api_status}

  Sys Load:  {load}         Memory Usage: {mem}%
  Disk:      {disk_used}%   Swap: {swap}%
  Tasks:     {procs}        Users: {users}

  Use: help | ai | review | project_type
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    },
    "6": {
        "name": "Professional Shell Box",
        "template": """+-------------------------------------------------------------+
      V R I T R A A I   P R O F E S S I O N A L   S H E L L  
+-------------------------------------------------------------+
 Model:       {model}         API: {api_status}              
 Load:        {load}           Memory: {mem}%                 
 Disk:        {disk_used}% / {disk_total}                    
 Processes:   {procs}                      Users: {users}                 
+-------------------------------------------------------------+
 Commands: help | ai | review | apikey | project_type        
+-------------------------------------------------------------+
"""
    },
    "7": {
        "name": "Initialization Banner",
        "template": """>>> Initializing VritraAI Professional Shell...

  MODEL:        {model}
  API:          {api_status}
  LOAD:         {load}
  MEMORY:       {mem}%
  DISK:         {disk_used}% / {disk_total}
  PROCESSES:    {procs}
  USERS:        {users}

>>> System ready. Type 'help' to begin.
"""
    },
    "8": {
        "name": "VritraAI Pro Block",
        "template": """====================[ VritraAI Pro ]=====================
 Version: {version}
 Model: {model}
 API:   {api_status}
---------------------------------------------------------
 System Load:    {load}
 Memory Used:    {mem}%
 Disk Used:      {disk_used}% of {disk_total}
 Processes:      {procs}
 Logged Users:   {users}
---------------------------------------------------------
 Commands: help | ai | review | apikey help
=========================================================
"""
    },
    "9": {
        "name": "Pro Node Frame",
        "template": """┌───────────────────────────────────────────────────────────┐
                V R I T R A A I   P R O  M O D E           
├───────────────────────────────────────────────────────────┤
 Model: {model}               API: {api_status}            
 Load: {load}                  Memory: {mem}%               
 Disk: {disk_used}% / {disk_total}                         
 Processes: {procs}                        Users: {users}               
└───────────────────────────────────────────────────────────┘

Commands → help | ai | review | apikey | project_type
"""
    },
    "10": {
        "name": "Professional Unit",
        "template": """==== VritraAI Professional Unit {version} ========================
 AI Engine:        {model}
 API Status:       {api_status}

 System Metrics:
   Load:           {load}
   Memory:         {mem}%
   Disk:           {disk_used}% / {disk_total}
   Processes:      {procs}
   Users:          {users}

 Commands Ready: help | ai | review | apikey | project_type
============================================================
"""
    },
    "11": {
        "name": "Professional Edition Minimal",
        "template": """VritraAI • Professional Edition {version}
------------------------------------
 Model:       {model}
 API:         {api_status}
 Load:        {load}       Memory: {mem}%
 Disk:        {disk_used}% / {disk_total}
 Processes:   {procs}      Users:  {users}

 Commands → help | ai | review | project_type
---------------------------------------------
"""
    },
    "12": {
        "name": "Neural Console",
        "template": """╔──────────────────────────═╗
║   V R I T R A A I  •  N C ║  (Neural Console)
╚═══╦═══════════════════════╝
    ║  Edition: Pro {version}
    ║  Model: {model}
    ║  API:   {api_status}
────╫────────────────────────────────────────
    ║  Load:      {load}
    ║  Memory:    {mem}%
    ║  Disk:      {disk_used}% of {disk_total}
    ║  Processes: {procs}
    ║  Users:     {users}
────╫────────────────────────────────────────
    ║  help • ai • review • apikey • project_type
════╩════════════════════════════════════════════
"""
    },
    "13": {
        "name": "Space-Dock Terminal",
        "template": """[VritraAI Space-Dock Terminal • Pro Edition]
──────────────────────────────────────────────
 AI Core:       {model}
 API Link:      {api_status}

 System Status:
   • Load:      {load}
   • Memory:    {mem}%
   • Disk:      {disk_used}% / {disk_total}
   • Tasks:     {procs}
   • Users:     {users}

 Engage: help | ai | review | apikey help
──────────────────────────────────────────────
"""
    },
    "14": {
        "name": "System Blueprint",
        "template": """==================[ SYSTEM BLUEPRINT – VRITRAAI ]===================
  Edition: Pro {version}              Model: {model}
  API Binding: {api_status}
--------------------------------------------------------------------
  Metrics:
     Load        → {load}
     Memory      → {mem}%
     Disk        → {disk_used}% / {disk_total}
     Processes   → {procs}
     Users       → {users}
--------------------------------------------------------------------
  Toolkit:
     help | ai | review <file> | apikey help | project_type
====================================================================
"""
    },
    "15": {
        "name": "Black-Site Terminal",
        "template": """██ VritraAI Black-Site Terminal ██
--------------------------------------------
  Status:
    AI Model:     {model}
    API Link:     {api_status}

  System:
    Load Avg:     {load}
    Memory Use:   {mem}%
    Disk Use:     {disk_used}% / {disk_total}
    Processes:    {procs}
    Users:        {users}

  Operational Commands: help | ai | review | project_type
--------------------------------------------
"""
    },
    "16": {
        "name": "Matrix Rain Edition",
        "template": """▁▂▃▄▅▆▇█ M A T R I X • V R I T R A A I █▇▆▅▄▃▂▁

 [ AI ]   Model: {model}
 [ API ]  Status: {api_status}
───────────────────────────────────────────────
 [ SYS ]  Load:    {load}
 [ RAM ]  Memory:  {mem}%
 [ DISK ] Disk:    {disk_used}%/{disk_total}
 [ PROC ] Tasks:   {procs}
 [ USER ] Logged:  {users}
────────────────────────────────────────────────
 Type 'ai <msg>' to communicate with core system.
"""
    },
    "17": {
        "name": "ASCII Vritra Dragon",
        "template": """        /\\/\\  _ __   ___ _ __ _ __ __ _
       /    \\| '_ \\ / _ \\ '__| '__/ _` |
      / /\\/\\ \\ | | |  __/ |  | | | (_| |
      \\/    \\/_| |_|\\___|_|  |_|  \\__,_|

           V R I T R A A I   C O R E
──────────────────────────────────────────
 Model:     {model}
 API:       {api_status}
 Load:      {load}
 Memory:    {mem}%     Disk: {disk_used}%/{disk_total}
 Processes: {procs}    Users: {users}
──────────────────────────────────────────
 Commands → help | ai | review | project_type
"""
    },
    "18": {
        "name": "Nord Frost Blue",
        "template": """╭─────────────────── VritraAI — Nord Frost ───────────────────╮
 Model: {model}                     API: {api_status}         
 Load:  {load}                       Memory: {mem}%            
 Disk:  {disk_used}% / {disk_total} Processes: {procs}        
 Users: {users}                                              
╰──────────────────────────────────────────────────────────────╯
 Tips: use 'ai <query>' or 'review <file>'
"""
    },
    "19": {
        "name": "Cyberpunk Neon Strips",
        "template": """██████████████████ CYBERPUNK // VRITRAAI ██████████████████

 » MODEL      : {model}
 » API LINK   : {api_status}
────────────────────────────────────────────────────────────
 » LOAD       : {load}
 » MEMORY     : {mem}%
 » DISK       : {disk_used}% of {disk_total}
 » PROCESSES  : {procs}
 » USERS      : {users}
────────────────────────────────────────────────────────────
 Commands: help • ai • review • apikey help
"""
    },
    "20": {
        "name": "Doom Retro Terminal",
        "template": """▒█▀▀█ ▒█▀▀▀ ▀▀█▀▀ ▒█▀▀▀ ▒█▀▀█ ▒█▀▀▀█ ▒█▀▀█
▒█▄▄█ ▒█▀▀▀ ░▒█░░ ▒█▀▀▀ ▒█▄▄█ ░▀▀▀▄▄ ▒█░░░
▒█░░░ ▒█▄▄▄ ░▒█░░ ▒█▄▄▄ ▒█░░░ ▒█▄▄▄█ ▒█▄▄█

 VRITRAAI RETRO-TERMINAL INTERFACE  ({version})
-------------------------------------------------
 Model      : {model}
 API        : {api_status}
 Load       : {load}
 Memory     : {mem}%
 Disk       : {disk_used}%/{disk_total}
 Processes  : {procs}
 Users      : {users}
-------------------------------------------------
 Type HELP to begin.
"""
    },
    "21": {
        "name": "Minimal Ultra-Clean",
        "template": """VritraAI Professional
─────────────────────────────────────
 Model      {model}
 API        {api_status}
 Load       {load}
 Memory     {mem}%
 Disk       {disk_used}% / {disk_total}
 Tasks      {procs}
 Users      {users}
─────────────────────────────────────
 ai <query>  •  review <file>
"""
    },
    "22": {
        "name": "Heavy Metal Frame",
        "template": """╔███████████████████████ VRITRAAI ██████████████████████╗
 MODEL: {model}              STATUS: {api_status}  
 LOAD : {load}                MEMORY: {mem}%        
 DISK : {disk_used}%/{disk_total}                   PROCS: {procs}  
 USERS: {users}                                    
╚███████████████████████████████████████████████████████╝
"""
    },
    "23": {
        "name": "Starship Galaxy Console",
        "template": """✦ VritraAI — Galactic Ops Console ✦

  AI Core     : {model}
  Link Status : {api_status}

  Metrics:
    Load      → {load}
    Memory    → {mem}%
    Disk      → {disk_used}% / {disk_total}
    Tasks     → {procs}
    Users     → {users}

  Use hyperspace command: ai <question>
"""
    },
    "24": {
        "name": "Bloodshed Dark Red",
        "template": """█████████████████████████████████████████████
█      V R I T R A A I   B L O O D X  {version}   █
█████████████████████████████████████████████
 Model      : {model}
 API        : {api_status}
 Load       : {load}
 Memory     : {mem}%
 Disk       : {disk_used}% / {disk_total}
 Tasks      : {procs}
 Users      : {users}
------------------------------------------------
 Commands → help | ai | review | apikey
"""
    },
    "25": {
        "name": "Blueprint Engineering Panel",
        "template": """┏━━━━━━━━━━━━━━ VRITRAAI BLUEPRINT ━━━━━━━━━━━━━━┓
        MODEL       :: {model}                                 
        API STATUS  :: {api_status}                            
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
        LOAD        :: {load}                                  
        MEMORY      :: {mem}%                                  
        DISK        :: {disk_used}%/{disk_total}               
        PROCESSES   :: {procs}                                 
        USERS       :: {users}                                 
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
"""
    },
}

# Inline colored banner templates (originally from bannr.py).
# These use ANSI 256-color escape sequences to give each banner a
# professional multi-color look. We keep the plain `template` above
# for theme-synced Rich rendering and store these variants as
# `color_template` so users can toggle between modes.
COLORED_BANNERS = {
    "2": {
        "name": "Professional Edition – Wide (Colored)",
        "template": """\033[38;5;39m──────────────────────────────────────────────────────────────\033[0m
   \033[38;5;82mV R I T R A A I\033[0m   \033[38;5;15mP R O F E S S I O N A L   E D I T I O N\033[0m

       \033[38;5;208mPrecision\033[0m • \033[38;5;51mIntelligence\033[0m • \033[38;5;13mAutonomous Code Analysis\033[0m
\033[38;5;39m──────────────────────────────────────────────────────────────\033[0m

  \033[38;5;82mSystem:\033[0m       {sys_name} {sys_ver}
  \033[38;5;82mLoad:\033[0m         \033[38;5;51m{load}\033[0m              \033[38;5;82mMemory:\033[0m \033[38;5;51m{mem}%\033[0m
  \033[38;5;82mDisk:\033[0m         {disk_used}% of {disk_total}    \033[38;5;82mSwap:\033[0m {swap}%
  \033[38;5;82mUsers:\033[0m        {users}             \033[38;5;82mProcesses:\033[0m {procs}
  \033[38;5;82mModel:\033[0m        \033[38;5;39m{model}\033[0m             \033[38;5;82mAPI:\033[0m {api_status}

  \033[38;5;208mHints:\033[0m help • ai <query> • review <file> • apikey help
\033[38;5;39m──────────────────────────────────────────────────────────────\033[0m
"""
    },

    "3": {
        "name": "Pro Shell Panel (Colored)",
        "template": """\033[38;5;39m╔═════════════════════════════════════════════════════════╗\033[0m
\033[38;5;82m            V R I T R A A I  •  P R O  S H E L L            \033[0m
\033[38;5;39m ─────────────────────────────────────────────────────────\033[0m
  \033[38;5;82mMode:\033[0m Professional Edition {version}                           
  \033[38;5;82mAI Core:\033[0m \033[38;5;51m{model}\033[0m                                          
  \033[38;5;82mAPI Link:\033[0m {api_status}                                    
\033[38;5;39m╠─────────────────────────────────────────────────────────╣\033[0m
  \033[38;5;82mSystem Load:\033[0m  \033[38;5;51m{load}\033[0m      \033[38;5;82mMemory:\033[0m {mem}%                  
  \033[38;5;82mDisk Usage:\033[0m   {disk_used}% of {disk_total}                
  \033[38;5;82mProcesses:\033[0m    {procs}     \033[38;5;82mLogged Users:\033[0m {users}           
\033[38;5;39m╚═════════════════════════════════════════════════════════╝\033[0m

\033[38;5;208mCommands:\033[0m help • ai • review • apikey • project_type
"""
    },

    "4": {
        "name": "Compact Pro Status (Colored)",
        "template": """\033[38;5;39m[ \033[38;5;82mVritraAI Professional 1.0\033[38;5;39m ]\033[0m
\033[38;5;245m--------------------------------------\033[0m
 \033[38;5;82mCore Model:\033[0m     \033[38;5;51m{model}\033[0m
 \033[38;5;82mAPI Status:\033[0m     {api_status}

 \033[38;5;82mLoad Avg:\033[0m       \033[38;5;51m{load}\033[0m
 \033[38;5;82mMemory:\033[0m         {mem}%
 \033[38;5;82mDisk:\033[0m           {disk_used}% / {disk_total}
 \033[38;5;82mProcesses:\033[0m      {procs}
 \033[38;5;82mLogged Users:\033[0m   {users}

 \033[38;5;208mTools:\033[0m help | ai | review <file> | apikey help
\033[38;5;245m--------------------------------------\033[0m
"""
    },

    "5": {
        "name": "Research Node (Colored)",
        "template": """\033[38;5;13m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m
    \033[38;5;82mV R I T R A A I\033[0m   \033[38;5;51m•   R E S E A R C H  N O D E\033[0m
\033[38;5;13m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m
  \033[38;5;82mEdition:\033[0m Professional v1.0
  \033[38;5;82mAI Engine:\033[0m \033[38;5;51m{model}\033[0m
  \033[38;5;82mAPI Link:\033[0m  {api_status}

  \033[38;5;82mSys Load:\033[0m  \033[38;5;51m{load}\033[0m         \033[38;5;82mMemory Usage:\033[0m {mem}%
  \033[38;5;82mDisk:\033[0m      {disk_used}%   \033[38;5;82mSwap:\033[0m {swap}%
  \033[38;5;82mTasks:\033[0m     {procs}        \033[38;5;82mUsers:\033[0m {users}

  \033[38;5;208mUse:\033[0m help | ai | review | project_type
\033[38;5;13m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m
"""
    },

    "6": {
        "name": "Professional Shell Box (Colored)",
        "template": """\033[38;5;39m+-------------------------------------------------------------+\033[0m
      \033[38;5;82mV R I T R A A I   P R O F E S S I O N A L   S H E L L\033[0m      
\033[38;5;39m+-------------------------------------------------------------+\033[0m
 \033[38;5;82mModel:\033[0m       \033[38;5;51m{model}\033[0m         \033[38;5;82mAPI:\033[0m {api_status}              
 \033[38;5;82mLoad:\033[0m        {load}           \033[38;5;82mMemory:\033[0m {mem}%                 
 \033[38;5;82mDisk:\033[0m        {disk_used}% / {disk_total}                    
 \033[38;5;82mProcesses:\033[0m   {procs}                      \033[38;5;82mUsers:\033[0m {users}                 
\033[38;5;39m+-------------------------------------------------------------+\033[0m
 Commands: help | ai | review | apikey | project_type        
\033[38;5;39m+-------------------------------------------------------------+\033[0m
"""
    },

    "7": {
        "name": "Initialization Banner (Colored)",
        "template": """\033[38;5;208m>>> Initializing VritraAI Professional Shell...\033[0m

  \033[38;5;82mMODEL:\033[0m        \033[38;5;51m{model}\033[0m
  \033[38;5;82mAPI:\033[0m          {api_status}
  \033[38;5;82mLOAD:\033[0m         \033[38;5;51m{load}\033[0m
  \033[38;5;82mMEMORY:\033[0m       {mem}%
  \033[38;5;82mDISK:\033[0m         {disk_used}% / {disk_total}
  \033[38;5;82mPROCESSES:\033[0m    {procs}
  \033[38;5;82mUSERS:\033[0m        {users}

\033[38;5;82m>>> System ready.\033[0m Type 'help' to begin.
"""
    },

    "8": {
        "name": "VritraAI Pro Block (Colored)",
        "template": """\033[38;5;39m====================[\033[38;5;82m VritraAI Pro \033[38;5;39m]====================\033[0m
 \033[38;5;82mVersion:\033[0m {version}
 \033[38;5;82mModel:\033[0m \033[38;5;51m{model}\033[0m
 \033[38;5;82mAPI:\033[0m   {api_status}
\033[38;5;39m---------------------------------------------------------\033[0m
 \033[38;5;82mSystem Load:\033[0m    \033[38;5;51m{load}\033[0m
 \033[38;5;82mMemory Used:\033[0m    {mem}%
 \033[38;5;82mDisk Used:\033[0m      {disk_used}% of {disk_total}
 \033[38;5;82mProcesses:\033[0m      {procs}
 \033[38;5;82mLogged Users:\033[0m   {users}
\033[38;5;39m---------------------------------------------------------\033[0m
 \033[38;5;208mCommands:\033[0m help | ai | review | apikey help
\033[38;5;39m=========================================================\033[0m
"""
    },

    "9": {
        "name": "Pro Node Frame (Colored)",
        "template": """\033[38;5;39m┌───────────────────────────────────────────────────────────┐\033[0m
        \033[38;5;82mV R I T R A A I   P R O  N O D E\033[0m           
\033[38;5;39m├───────────────────────────────────────────────────────────┤\033[0m
 \033[38;5;82mModel:\033[0m \033[38;5;51m{model}\033[0m               \033[38;5;82mAPI:\033[0m {api_status}            
 \033[38;5;82mLoad:\033[0m \033[38;5;51m{load}\033[0m                  \033[38;5;82mMemory:\033[0m {mem}%               
 \033[38;5;82mDisk:\033[0m {disk_used}% / {disk_total}                         
 \033[38;5;82mProcesses:\033[0m {procs}                        \033[38;5;82mUsers:\033[0m {users}               
\033[38;5;39m└───────────────────────────────────────────────────────────┘\033[0m

\033[38;5;208mCommands →\033[0m help | ai | review | apikey | project_type
"""
    },

    "10": {
        "name": "Professional Unit (Colored)",
        "template": """\033[38;5;39m==== \033[38;5;82mVritraAI Professional Unit {version}\033[38;5;39m ========================\033[0m
 \033[38;5;82mAI Engine:\033[0m       \033[38;5;51m{model}\033[0m
 \033[38;5;82mAPI Status:\033[0m      {api_status}

 \033[38;5;82mSystem Metrics:\033[0m
   Load:           \033[38;5;51m{load}\033[0m
   Memory:         {mem}%
   Disk:           {disk_used}% / {disk_total}
   Processes:      {procs}
   Users:          {users}

 \033[38;5;208mCommands Ready:\033[0m help | ai | review | apikey | project_type
\033[38;5;39m============================================================\033[0m
"""
    },

    "11": {
        "name": "Professional Edition Minimal (Color)",
        "template": """\033[38;5;81mVritraAI • Professional Edition {version}\033[0m
\033[38;5;245m------------------------------------\033[0m
 \033[38;5;51mModel:\033[0m       {model}
 \033[38;5;51mAPI:\033[0m         {api_status}
 \033[38;5;51mLoad:\033[0m        \033[38;5;39m{load}\033[0m       \033[38;5;51mMemory:\033[0m {mem}%
 \033[38;5;51mDisk:\033[0m        {disk_used}% / {disk_total}
 \033[38;5;51mProcesses:\033[0m   {procs}      \033[38;5;51mUsers:\033[0m  {users}
\033[38;5;245m------------------------------------\033[0m
 Commands → help | ai | review | project_type
"""
    },

    "12": {
        "name": "Neural Console (Color)",
        "template": """\033[38;5;57m╔──────────────────────────═╗\033[0m
\033[38;5;81m║   V R I T R A A I  •  N C ║\033[0m  \033[38;5;245m(Neural Console)\033[0m
\033[38;5;57m╚═══╦═══════════════════════╝\033[0m
    ║  \033[38;5;51mEdition:\033[0m Pro {version}
    ║  \033[38;5;51mModel:\033[0m   \033[38;5;81m{model}\033[0m
    ║  \033[38;5;51mAPI:\033[0m     {api_status}
\033[38;5;57m────╫────────────────────────────────────────\033[0m
    ║  \033[38;5;51mLoad:\033[0m      \033[38;5;81m{load}\033[0m
    ║  \033[38;5;51mMemory:\033[0m    {mem}%
    ║  \033[38;5;51mDisk:\033[0m      {disk_used}% of {disk_total}
    ║  \033[38;5;51mProcesses:\033[0m {procs}
    ║  \033[38;5;51mUsers:\033[0m     {users}
\033[38;5;57m────╫────────────────────────────────────────\033[0m
    ║  help • ai • review • apikey • project_type
\033[38;5;57m════╩════════════════════════════════════════════\033[0m
"""
    },

    "13": {
        "name": "Space-Dock Terminal (Color)",
        "template": """\033[38;5;141m[VritraAI Space-Dock Terminal • Pro Edition]\033[0m
\033[38;5;245m──────────────────────────────────────────────\033[0m
 \033[38;5;111mAI Core:\033[0m       {model}
 \033[38;5;111mAPI Link:\033[0m      {api_status}

 \033[38;5;39mSystem Status:\033[0m
   • Load:      \033[38;5;39m{load}\033[0m
   • Memory:    {mem}%
   • Disk:      {disk_used}% / {disk_total}
   • Tasks:     {procs}
   • Users:     {users}

\033[38;5;245mEngage:\033[0m help | ai | review | apikey help
\033[38;5;245m──────────────────────────────────────────────\033[0m
"""
    },

    "14": {
        "name": "System Blueprint (Color)",
        "template": """\033[38;5;45m==================[ SYSTEM BLUEPRINT – VRITRAAI ]===================\033[0m
  \033[38;5;81mEdition:\033[0m Pro {version}              \033[38;5;81mModel:\033[0m \033[38;5;45m{model}\033[0m
  \033[38;5;81mAPI Binding:\033[0m {api_status}
\033[38;5;45m--------------------------------------------------------------------\033[0m
  \033[38;5;51mMetrics:\033[0m
     Load        → \033[38;5;39m{load}\033[0m
     Memory      → {mem}%
     Disk        → {disk_used}% / {disk_total}
     Processes   → {procs}
     Users       → {users}
\033[38;5;45m--------------------------------------------------------------------\033[0m
  Toolkit:
     help | ai | review <file> | apikey help | project_type
\033[38;5;45m====================================================================\033[0m
"""
    },

    "15": {
        "name": "Black-Site Terminal (Color)",
        "template": """\033[38;5;196m██ VritraAI Black-Site Terminal ██\033[0m
\033[38;5;245m--------------------------------------------\033[0m
  \033[38;5;203mStatus:\033[0m
    \033[38;5;111mAI Model:\033[0m     \033[38;5;45m{model}\033[0m
    \033[38;5;111mAPI Link:\033[0m     {api_status}

  \033[38;5;203mSystem:\033[0m
    Load Avg:     \033[38;5;39m{load}\033[0m
    Memory Use:   {mem}%
    Disk Use:     {disk_used}% / {disk_total}
    Processes:    {procs}
    Users:        {users}

  \033[38;5;208mOperational Commands:\033[0m help | ai | review | project_type
\033[38;5;245m--------------------------------------------\033[0m
"""
    },

    "16": {
        "name": "Matrix Rain Edition (Color)",
        "template": """\033[38;5;46m▁▂▃▄▅▆▇█ M A T R I X • V R I T R A A I █▇▆▅▄▃▂▁\033[0m

 [ \033[38;5;82mAI\033[0m ]   Model: {model}
 [ \033[38;5;82mAPI\033[0m ]  Status: {api_status}
\033[38;5;22m───────────────────────────────────────────────\033[0m
 [ SYS ]  Load:    \033[38;5;82m{load}\033[0m
 [ RAM ]  Memory:  {mem}%
 [ DISK ] Disk:    {disk_used}%/{disk_total}
 [ PROC ] Tasks:   {procs}
 [ USER ] Logged:  {users}
\033[38;5;22m───────────────────────────────────────────────\033[0m
 Type 'ai <msg>' to communicate with core system.
"""
    },

    "17": {
        "name": "ASCII Vritra Dragon (Color)",
        "template": """\033[38;5;196m        /\\/\\  _ __   ___ _ __ _ __ __ _\033[0m
\033[38;5;203m       /    \\| '_ \\ / _ \\ '__| '__/ _` |\033[0m
\033[38;5;160m      / /\\/\\ \\ | | |  __/ |  | | | (_| |\033[0m
\033[38;5;196m      \\/    \\/_| |_|\\___|_|  |_|  \\__,_|\033[0m

   \033[38;5;160mV R I T R A A I   C O R E\033[0m
\033[38;5;245m──────────────────────────────────────────\033[0m
 \033[38;5;51mModel:\033[0m     \033[38;5;45m{model}\033[0m
 \033[38;5;51mAPI:\033[0m       {api_status}
 \033[38;5;51mLoad:\033[0m      \033[38;5;45m{load}\033[0m
 \033[38;5;51mMemory:\033[0m    {mem}%     
 \033[38;5;51mDisk:\033[0m      {disk_used}%/{disk_total}
 \033[38;5;51mProcesses:\033[0m {procs}
 \033[38;5;51mUsers:\033[0m     {users}
\033[38;5;245m──────────────────────────────────────────\033[0m
 Commands → help | ai | review | project_type
"""
    },

    "18": {
        "name": "Nord Frost Blue (Color)",
        "template": """\033[38;5;117m╭─────────────────── VritraAI — Nord Frost ───────────────────╮\033[0m
\033[38;5;81m Model:\033[0m {model}                     \033[38;5;81mAPI:\033[0m {api_status}         
\033[38;5;117m Load:\033[0m  \033[38;5;39m{load}\033[0m                       \033[38;5;117mMemory:\033[0m {mem}%            
\033[38;5;81m Disk:\033[0m  {disk_used}% / {disk_total} \033[38;5;81mProcesses:\033[0m {procs}        
\033[38;5;81m Users:\033[0m {users}                                              
\033[38;5;117m╰──────────────────────────────────────────────────────────────╯\033[0m
 \033[38;5;245mTips:\033[0m use 'ai <query>' or 'review <file>'
"""
    },

    "19": {
        "name": "Cyberpunk Neon Strips (Color)",
        "template": """\033[38;5;199m██████████████████ CYBERPUNK // VRITRAAI ██████████████████\033[0m

 » \033[38;5;207mMODEL\033[0m      : \033[38;5;45m{model}\033[0m
 » \033[38;5;207mAPI LINK\033[0m   : {api_status}
\033[38;5;129m────────────────────────────────────────────────────────────\033[0m
 » \033[38;5;51mLOAD\033[0m       : \033[38;5;39m{load}\033[0m
 » \033[38;5;51mMEMORY\033[0m     : {mem}%
 » \033[38;5;51mDISK\033[0m       : {disk_used}% of {disk_total}
 » \033[38;5;51mPROCESSES\033[0m  : {procs}
 » \033[38;5;51mUSERS\033[0m      : {users}
\033[38;5;129m────────────────────────────────────────────────────────────\033[0m
 Commands: help • ai • review • apikey help
"""
    },

    "20": {
        "name": "Doom Retro Terminal (Color)",
        "template": """\033[38;5;46m▒█▀▀█ ▒█▀▀▀ ▀▀█▀▀ ▒█▀▀▀ ▒█▀▀█ ▒█▀▀▀█ ▒█▀▀█\033[0m
\033[38;5;82m▒█▄▄█ ▒█▀▀▀ ░▒█░░ ▒█▀▀▀ ▒█▄▄█ ░▀▀▀▄▄ ▒█░░░\033[0m
\033[38;5;46m▒█░░░ ▒█▄▄▄ ░▒█░░ ▒█▄▄▄ ▒█░░░ ▒█▄▄▄█ ▒█▄▄█\033[0m

 \033[38;5;196mVRITRAAI RETRO-TERMINAL INTERFACE  ({version})\033[0m
\033[38;5;245m-------------------------------------------------\033[0m
 \033[38;5;51mModel:\033[0m      {model}
 \033[38;5;51mAPI:\033[0m        {api_status}
 \033[38;5;51mLoad:\033[0m       \033[38;5;46m{load}\033[0m
 \033[38;5;51mMemory:\033[0m     {mem}%
 \033[38;5;51mDisk:\033[0m       {disk_used}%/{disk_total}
 \033[38;5;51mProcesses:\033[0m  {procs}
 \033[38;5;51mUsers:\033[0m      {users}
\033[38;5;245m-------------------------------------------------\033[0m
 Type HELP to begin.
"""
    },

    "21": {
        "name": "Minimal Ultra-Clean (Color)",
        "template": """\033[38;5;252mVritraAI Professional\033[0m
\033[38;5;245m─────────────────────────────────────\033[0m
 \033[38;5;39mModel\033[0m      {model}
 \033[38;5;39mAPI\033[0m        {api_status}
 \033[38;5;39mLoad\033[0m       \033[38;5;45m{load}\033[0m
 \033[38;5;39mMemory\033[0m     {mem}%
 \033[38;5;39mDisk\033[0m       {disk_used}% / {disk_total}
 \033[38;5;39mTasks\033[0m      {procs}
 \033[38;5;39mUsers\033[0m      {users}
\033[38;5;245m─────────────────────────────────────\033[0m
 ai <query>  •  review <file>
"""
    },

    "22": {
        "name": "Heavy Metal Frame (Color)",
        "template": """\033[38;5;250m╔███████████████████████ \033[38;5;208mVRITRAAI\033[38;5;250m ██████████████████████╗\033[0m
 \033[38;5;51mMODEL:\033[0m {model}              \033[38;5;51mSTATUS:\033[0m {api_status}  
 \033[38;5;51mLOAD :\033[0m {load}                \033[38;5;51mMEMORY:\033[0m {mem}%        
 \033[38;5;51mDISK :\033[0m {disk_used}%/{disk_total}                   \033[38;5;51mPROCS:\033[0m {procs}  
 \033[38;5;51mUSERS:\033[0m {users}                                    
\033[38;5;250m╚███████████████████████████████████████████████████████╝\033[0m
"""
    },

    "23": {
        "name": "Starship Galaxy Console (Color)",
        "template": """\033[38;5;141m✦ VritraAI — Galactic Ops Console ✦\033[0m

  \033[38;5;51mAI Core\033[0m     : {model}
  \033[38;5;51mLink Status\033[0m : {api_status}

  \033[38;5;81mMetrics:\033[0m
    Load      → \033[38;5;39m{load}\033[0m
    Memory    → {mem}%
    Disk      → {disk_used}% / {disk_total}
    Tasks     → {procs}
    Users     → {users}

  Use hyperspace command: ai <question>
"""
    },

    "24": {
        "name": "Bloodshed Dark Red (Color)",
        "template": """\033[38;5;196m█████████████████████████████████████████████\033[0m
\033[38;5;160m█      V R I T R A A I   B L O O D X  {version}   █\033[0m
\033[38;5;196m█████████████████████████████████████████████\033[0m
 \033[38;5;203mModel:\033[0m      \033[38;5;45m{model}\033[0m
 \033[38;5;203mAPI:\033[0m        {api_status}
 \033[38;5;203mLoad:\033[0m       \033[38;5;196m{load}\033[0m
 \033[38;5;203mMemory:\033[0m     {mem}%
 \033[38;5;203mDisk:\033[0m       {disk_used}%/{disk_total}
 \033[38;5;203mTasks:\033[0m      {procs}
 \033[38;5;203mUsers:\033[0m      {users}
\033[38;5;160m------------------------------------------------\033[0m
 Commands → help | ai | review | apikey
"""
    },

    "25": {
        "name": "Blueprint Engineering Panel (Color)",
        "template": """\033[38;5;39m┏━━━━━━━━━━━━━━ VRITRAAI BLUEPRINT ━━━━━━━━━━━━━━┓\033[0m
\033[38;5;51m        MODEL       ::\033[0m \033[38;5;45m{model}\033[0m                                 
\033[38;5;51m        API STATUS  ::\033[0m {api_status}                            
\033[38;5;39m┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫\033[0m
\033[38;5;51m        LOAD        ::\033[0m \033[38;5;39m{load}\033[0m                                  
\033[38;5;51m        MEMORY      ::\033[0m {mem}%                                  
\033[38;5;51m        DISK        ::\033[0m {disk_used}%/{disk_total}               
\033[38;5;51m        PROCESSES   ::\033[0m {procs}                                 
\033[38;5;51m        USERS       ::\033[0m {users}                                 
\033[38;5;39m┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\033[0m
"""
    },
}

# Apply colored variants as `color_template` overlays on top of the
# base BANNERS definitions so we can switch between theme-synced Rich
# rendering and hardcoded ANSI-colored banners.
for _bid, _bdef in COLORED_BANNERS.items():
    base = BANNERS.get(_bid, {}).copy()
    if "template" in _bdef:
        base["color_template"] = _bdef["template"]
    if "name" in _bdef:
        base["name"] = _bdef["name"]
    BANNERS[_bid] = base



def get_banner_config() -> tuple[str, bool]:
    global current_config, config_manager
    banner_id = "1"
    banner_random = False
    try:
        if config_manager:
            banner_id = str(config_manager.get_value("banner_id", "1"))
            banner_random = bool(config_manager.get_value("banner_random", False))
        elif current_config:
            banner_id = str(current_config.get("banner_id", "1"))
            banner_random = bool(current_config.get("banner_random", False))
    except Exception:
        # Fall back to defaults on any config error
        banner_id = "1"
        banner_random = False
    return banner_id, banner_random


def set_banner_config(banner_id: str | None = None, banner_random: bool | None = None, banner_sync: bool | None = None) -> bool:
    """Persist banner configuration in the central config file.

    Returns True if the config was updated successfully (best effort).
    """
    global current_config, config_manager
    updated = False
    try:
        if config_manager:
            if banner_id is not None:
                config_manager.set_value("banner_id", str(banner_id))
                updated = True
            if banner_random is not None:
                config_manager.set_value("banner_random", bool(banner_random))
                updated = True
            if banner_sync is not None:
                config_manager.set_value("banner_sync", bool(banner_sync))
                updated = True
        elif current_config is not None:
            if banner_id is not None:
                current_config["banner_id"] = str(banner_id)
                updated = True
            if banner_random is not None:
                current_config["banner_random"] = bool(banner_random)
                updated = True
            if banner_sync is not None:
                current_config["banner_sync"] = bool(banner_sync)
                updated = True
            if updated:
                # Legacy save path
                try:
                    save_config(current_config)  # type: ignore[name-defined]
                except Exception:
                    pass
    except Exception:
        return False
    return updated


def get_banner_stats() -> Dict[str, str]:
    """Collect system and AI stats for banner templates."""
    import getpass
    import warnings

    current_time = datetime.datetime.now()
    username = getpass.getuser()
    hostname = platform.node() or "vritraai-terminal"

    sys_name = platform.system()
    sys_ver = platform.release()

    # Load average - silently handle permission errors
    load_str = "N/A"
    try:
        if hasattr(os, "getloadavg"):
            la1, la5, la15 = os.getloadavg()
            load_str = f"{la1:.2f} {la5:.2f} {la15:.2f}"
    except (PermissionError, OSError, IOError):
        pass
    except Exception:
        pass

    # Disk usage - silently handle permission errors
    disk_total = "N/A"
    disk_used = "0.0"
    try:
        total, used, free = shutil.disk_usage("/")
        disk_total = f"{total // (1024 ** 3)}GB"
        disk_used_pct = (used / total * 100) if total else 0
        disk_used = f"{disk_used_pct:.1f}"
    except (PermissionError, OSError, IOError):
        pass
    except Exception:
        pass

    mem_pct = "0"
    swap_pct = "0"
    procs = "0"
    users_count = "1"
    try:
        import psutil  # type: ignore[import]
        
        # Suppress psutil warnings about permission errors
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            try:
                memory = psutil.virtual_memory()
                mem_pct = f"{memory.percent:.0f}"
            except (PermissionError, OSError, IOError):
                mem_pct = "N/A"
            except Exception:
                pass
            
            try:
                swap = psutil.swap_memory()
                swap_pct = f"{swap.percent:.0f}"
            except (PermissionError, OSError, IOError):
                swap_pct = "N/A"
            except Exception:
                pass
            
            try:
                procs = str(len(psutil.pids()))
            except (PermissionError, OSError, IOError):
                procs = "N/A"
            except Exception:
                pass
            
            try:
                users_list = psutil.users()
                users_count = str(len(users_list) or 1)
            except (PermissionError, OSError, IOError):
                pass
            except Exception:
                pass
    except ImportError:
        # psutil not available – keep simple defaults
        pass
    except Exception:
        pass

    model_display = MODEL or "None"
    api_status = "Connected" if AI_ENABLED else "Offline"
    ai_subsystem = "Active" if AI_ENABLED else "Inactive"

    if AI_ENABLED:
        ai_extra = " * Enhanced AI Code Review & Project Intelligence available"
    else:
        ai_extra = " * Configure API keys for full AI functionality"

    return {
        "current_time": current_time.strftime("%a %b %d %H:%M:%S %Y"),
        "username": username,
        "hostname": hostname,
        "sys_name": sys_name,
        "sys_ver": sys_ver,
        "version": VRITRA_VERSION,
        "load": load_str,
        "mem": mem_pct,
        "disk_used": disk_used,
        "disk_total": disk_total,
        "swap": swap_pct,
        "users": users_count,
        "procs": procs,
        "model": model_display,
        "api_status": api_status,
        "ai_subsystem": ai_subsystem,
        "ai_extra": ai_extra,
    }


def render_default_banner(stats: Dict[str, str]) -> None:
    """Render the default Ubuntu-style banner using fixed ANSI colors.

    This banner intentionally does NOT follow theme sync. Colors are
    hard-coded to match `default_bnr.txt`, and only text/metrics are
    dynamic based on current system and AI status.
    """
    # Convenience locals
    current_time = stats.get("current_time", "")
    username = stats.get("username", "")
    hostname = stats.get("hostname", "")
    load = stats.get("load", "")
    mem = stats.get("mem", "")
    disk_used = stats.get("disk_used", "")
    disk_total = stats.get("disk_total", "")
    swap = stats.get("swap", "")
    procs = stats.get("procs", "")
    users = stats.get("users", "")
    model = stats.get("model", "")
    ai_subsystem = stats.get("ai_subsystem", "")
    api_status = stats.get("api_status", "")

    # Colors copied from script.py (professional banner design)
    TITLE      = "\033[38;5;190m"
    BULLET     = "\033[38;5;152m"   # unused for now but kept for parity
    LABEL      = "\033[38;5;250m"
    CYAN_VALUE = "\033[38;5;81m"
    OLIVE      = "\033[38;5;118m"
    YELLOW_NUM = "\033[38;5;226m"
    USERNAME_C = "\033[38;5;118m"
    PATH_COLOR = "\033[38;5;110m"
    RESET      = "\033[0m"

    # Timestamps broken into colored parts like script.py
    now = datetime.datetime.now()
    day_str = now.strftime('%d')
    time_str = now.strftime('%H:%M:%S')
    year_str = now.strftime('%Y')

    # Status strings
    ai_status_str = ai_subsystem or ("Active" if AI_ENABLED else "Inactive")
    api_status_str = api_status or ("Connected" if AI_ENABLED else "Offline")

    # Build banner text using live stats instead of hard-coded numbers
    text = f"""
{TITLE}Welcome to VritraAI Professional Edition {VRITRA_VERSION}{RESET}

{CYAN_VALUE}* Documentation:  https://vritraai.vritrasec.com/docs/{RESET}
{CYAN_VALUE}* Management:     https://github.com/VritraSecz/VritraAI{RESET}
{CYAN_VALUE}* Support:        https://vritrasec.com/more/get-in-touch/{RESET}

{LABEL}System information as of Mon Nov {CYAN_VALUE}{day_str} {YELLOW_NUM}{time_str}{RESET}  {CYAN_VALUE}{year_str}{RESET}:

{LABEL}  System load:{RESET}      {CYAN_VALUE}{load}{RESET}               {LABEL}Memory usage:{RESET} {CYAN_VALUE}{mem}%{RESET}
{LABEL}  Usage of /:{RESET}       {CYAN_VALUE}{disk_used}% of {disk_total}{RESET}  {LABEL}Swap usage:{RESET}   {CYAN_VALUE}{swap}%{RESET}
{LABEL}  Processes:{RESET}        {CYAN_VALUE}{procs}{RESET}                {LABEL}Users logged:{RESET} {CYAN_VALUE}{users}{RESET}
{OLIVE}  AI subsystem:{RESET}     {OLIVE}{ai_status_str}{RESET}          {OLIVE}API status:{RESET}   {OLIVE}{api_status_str}{RESET}
{CYAN_VALUE}  Model loaded:{RESET}     {CYAN_VALUE}{model}{RESET}

{OLIVE}* Enhanced AI Code Review & Project Intelligence available{RESET}
{LABEL}* Type{OLIVE} 'help' {LABEL}for commands,{OLIVE} 'ai <question>' {LABEL}to chat,{OLIVE} 'review <file>' {LABEL}for code review{RESET}
{LABEL}* Use{OLIVE} 'apikey help' {LABEL}for API setup,{OLIVE} 'project_type' {LABEL}for intelligent detection{RESET}

{LABEL}Last login: Mon Nov {CYAN_VALUE}{day_str} {YELLOW_NUM}{time_str}{LABEL} {CYAN_VALUE}{year_str}{LABEL} from console{RESET}

{USERNAME_C}{username}@{hostname}{RESET}:{PATH_COLOR}~${RESET} VritraAI Professional Shell initialized
"""

    print(text)


def render_banner(banner_id: str) -> None:
    """Render a banner by ID using the configured output system.

    Each banner is rendered with a professional, multi-color layout:
    - Headlines / titles: bold magenta or green
    - Labels (Model, API, Load, Disk, etc.): bright cyan/white
    - Status values (Active, Connected, Offline): green/yellow/red
    """
    stats = get_banner_stats()

    # Banner 1 is a special case: it uses a dedicated ANSI-colored
    # Ubuntu-style MOTD and does NOT participate in theme sync.
    if str(banner_id) == "1":
        render_default_banner(stats)
        return

    banner = BANNERS.get(str(banner_id)) or BANNERS["1"]
    # Determine whether banners should be theme-synced (Rich-colored) or
    # use hardcoded ANSI-colored templates from bannr.py.
    banner_sync = True
    try:
        if config_manager:
            banner_sync = bool(config_manager.get_value("banner_sync", True))
        elif current_config is not None:
            banner_sync = bool(current_config.get("banner_sync", True))
    except Exception:
        banner_sync = True

    # Choose template based on sync mode:
    # - sync ON  → use base (non-colored) template and let Rich apply theme colors
    # - sync OFF → prefer `color_template` (ANSI-colored); fall back to base template
    if not banner_sync and "color_template" in banner:
        template = banner.get("color_template", "")
    else:
        template = banner.get("template", "")

    try:
        text = template.format(**stats)
    except Exception:
        # If formatting fails for any reason, fall back to raw template
        text = template

    # If sync is OFF and the banner template already contains ANSI color
    # escape codes (used by bannr.py for multi-color professional banners),
    # print it directly so the terminal handles the coloring as designed.
    if not banner_sync and "\033[" in text:
        print(text)
        return

    if RICH_AVAILABLE and console:
        from rich.text import Text

        is_default_banner = str(banner_id) == "1"

        # Theme-aware palette for non-default banners
        theme_name = getattr(config_state, 'theme', 'dark')
        if theme_name in ["matrix", "hacker_green", "terminal_green", "forest", "forest_night"]:
            header_style = "bold green"
            bullet_style = "green"
            model_style = "bright_green"
            metric_style = "bright_white"
        elif theme_name in ["ocean", "deep_sea", "ice", "electric"]:
            header_style = "bold cyan"
            bullet_style = "cyan"
            model_style = "bright_cyan"
            metric_style = "bright_white"
        elif theme_name in ["galaxy", "purple", "lavender", "synthwave"]:
            header_style = "bold magenta"
            bullet_style = "magenta"
            model_style = "bright_magenta"
            metric_style = "bright_white"
        elif theme_name in ["sunset", "desert_sunset", "volcano", "lava", "sunrise"]:
            header_style = "bold yellow"
            bullet_style = "yellow"
            model_style = "bright_yellow"
            metric_style = "bright_white"
        else:
            header_style = "bold magenta"
            bullet_style = "cyan"
            model_style = "bright_cyan"
            metric_style = "bright_white"

        # Track first non-empty line so every banner gets a strong header even
        # if the text doesn't explicitly contain "VritraAI".
        first_nonempty_seen = False

        for line in text.splitlines():
            stripped = line.strip()
            t = Text(line)

            # --- DEFAULT BANNER (ID 1) COLOR RULES ---
            if is_default_banner:
                # Header: Ubuntu-style green
                if "VritraAI" in line or stripped.startswith("Welcome"):
                    t.stylize("bold green")

                # The three * Documentation/Management/Support helper lines → cyan
                elif stripped.startswith("* Documentation") or stripped.startswith("* Management") or stripped.startswith("* Support"):
                    t.stylize("cyan")

                # "System information as of" line → bright white (matches default_bnr)
                elif "System information as of" in line:
                    t.stylize("bright_white")

                # Metric/stat lines (load, disk, processes, users) → plain white
                elif any(keyword in line for keyword in [
                    "System load", "Usage of /", "Processes", "Users logged",
                    "Memory usage", "Swap usage"]):
                    t.stylize("white")

                # AI subsystem / API status line → green when active, yellow otherwise
                elif "AI subsystem" in line:
                    if "Active" in line or "Connected" in line:
                        t.stylize("green")
                    else:
                        t.stylize("yellow")

                # Model loaded line → blue, with model name still highlighted later
                elif "Model loaded" in line:
                    t.stylize("blue")

                # Last login line → bright black
                elif stripped.startswith("Last login"):
                    t.stylize("bright_black")

                # Final shell initialized line → bright green
                elif "Professional Shell initialized" in line:
                    t.stylize("bright_green")

                # Generic command/hint lines at the bottom → white (matches txt)
                elif stripped.startswith("* Type 'help'") or stripped.startswith("* Use 'apikey help'"):
                    t.stylize("white")

                # Fallback: no special color here; other logic (numbers, tokens) still applies

            # --- NON-DEFAULT BANNERS: existing themed logic ---
            else:
                # Headline / title lines
                if "VritraAI" in line or "VRITRAAI" in line or stripped.startswith("Welcome") \
                   or (not first_nonempty_seen and stripped):
                    t.stylize(header_style)

                # Section separators or frames (ASCII boxes, heavy lines)
                elif any(ch in stripped for ch in ["═", "─", "━", "=", "┌", "└", "╔", "╚", "╠", "╩", "+", "│", "┃", "┓", "┗", "┏", "┛"]) and len(stripped) > 5:
                    t.stylize("bright_black")

                # Bullet / helper lines
                elif stripped.startswith("* ") or stripped.startswith("• "):
                    t.stylize(bullet_style)

                # Metric lines (system / load / disk / memory / processes / users)
                elif any(keyword in line for keyword in [
                    "System load", "Usage of /", "Sys Load", "System Status",
                    "System Metrics", "Load", "Memory", "Disk", "Tasks",
                    "Processes", "Users", "Metrics", "Status:"]):
                    t.stylize(metric_style)

                # Model / API related lines
                elif any(keyword in line for keyword in [
                    "Model", "AI Core", "AI Engine", "AI subsystem", "AI Model",
                    "API Status", "API Link", "API Binding", "AI Core:", "AI:  ", "API:"]):
                    t.stylize(model_style)

                # Generic commands/help lines
                elif any(stripped.startswith(prefix) for prefix in [
                    "Commands", "Engage", "Toolkit", "Tools", "Tips", "Type HELP", "Type 'help'", "Engage:", "Use:"]):
                    t.stylize("green")

            # Status tokens highlighted within the line (Applied to all banners)
            for token, style in [
                ("Active", "bold green"),
                ("Inactive", "bold yellow"),
                ("Connected", "bold green"),
                ("Offline", "bold red"),
            ]:
                idx = line.find(token)
                if idx != -1:
                    t.stylize(style, idx, idx + len(token))

            # Numeric metric highlighting (load, %, GB, etc.) for non-default banners
            # Default banner uses plain white metrics per default_bnr.txt, so we
            # skip per-number recoloring there.
            import re as _re
            if (not is_default_banner) and any(k in line for k in [
                "System load", "Usage of /", "Memory", "Swap", "Disk", "Processes", "Users", "Load", "Metrics", "RAM", "DISK", "Tasks"]):
                for match in _re.finditer(r"\d+(?:\.\d+)?(?:GB|%)?", line):
                    t.stylize(metric_style, match.start(), match.end())

            # Per-banner professional labeling: color labels vs values for
            # metrics/model/API lines so banners become multi‑color but still
            # clean and readable.
            if not is_default_banner and stripped:
                # Decide whether this line looks like a key/value metric line
                is_metric_line = any(k in line for k in [
                    "Load", "Memory", "Disk", "Tasks", "Processes", "Users", "RAM", "DISK", "Status", "Model", "API", "Core", "Engine"])

                if is_metric_line:
                    # Prefer double-colon / arrows, then fall back to single colon
                    separators = ["::", "→", ":"]
                    sep_pos = None
                    sep_len = 0
                    for sep in separators:
                        idx = line.find(sep)
                        if idx != -1:
                            sep_pos = idx
                            sep_len = len(sep)
                            break

                    if sep_pos is not None:
                        # Label is everything up to separator (trim trailing spaces)
                        label_start = 0
                        label_end = sep_pos
                        while label_end > label_start and line[label_end - 1].isspace():
                            label_end -= 1

                        # Value starts after separator + following spaces
                        value_start = sep_pos + sep_len
                        while value_start < len(line) and line[value_start].isspace():
                            value_start += 1

                        # Choose styles: labels get a crisp accent; values inherit
                        # model/metric style depending on content.
                        label_style = bullet_style
                        if any(k in line for k in ["Model", "AI Core", "AI Engine", "API", "Core"]):
                            value_style = model_style
                        else:
                            value_style = metric_style

                        if label_end > label_start:
                            t.stylize(label_style, label_start, label_end)
                        if value_start < len(line):
                            t.stylize(value_style, value_start, len(line))

            # Commands / hint lines: highlight command tokens individually to
            # create a subtle rainbow of accents without looking toy‑ish.
            if any(stripped.startswith(prefix) for prefix in [
                "Commands", "Engage", "Toolkit", "Tools", "Tips", "Type HELP", "Type 'help'", "Engage:", "Use:", "Type HELP to", "ai <", "help |", "Commands Ready"]):
                # Color command names (help, ai, review, apikey, project_type, etc.)
                cmd_tokens = ["help", "ai", "review", "project_type", "apikey", "apikey help",
                              "apikey set", "apikey openrouter", "apikey gemini", "project", "cheat"]
                for cmd in cmd_tokens:
                    idx = line.find(cmd)
                    while idx != -1:
                        t.stylize(bullet_style, idx, idx + len(cmd))
                        idx = line.find(cmd, idx + len(cmd))

            # Extra per-value coloring only for the default banner (unchanged)
            if is_default_banner:
                # Highlight model name on the "Model loaded" line
                if "Model loaded" in line:
                    model_val = stats.get("model", "")
                    if model_val:
                        m_idx = line.find(model_val)
                        if m_idx != -1:
                            t.stylize("bold bright_magenta", m_idx, m_idx + len(model_val))

            if stripped and not first_nonempty_seen:
                first_nonempty_seen = True

            console.print(t)
    else:
        # Fallback: plain text without Rich
        print(text)


def clear_screen():
    """Clear the terminal screen"""
    if platform.system() == "Windows":
        os.system('cls')
    else:
        os.system('clear')



def show_motd():
    """Display the configured Message of the Day banner."""
    import random as _random

    banner_id, banner_random = get_banner_config()
    available_ids = sorted(BANNERS.keys(), key=lambda x: int(x))

    if banner_random and available_ids:
        banner_id = _random.choice(available_ids)
    elif banner_id not in BANNERS:
        banner_id = "1"

    render_banner(banner_id)

# --- Version Info and What's New ---
def extract_version_number(version_str: str) -> tuple:
    """Extract version number from version string (e.g., 'v0.29.5' -> (0, 29, 5))"""
    try:
        # Remove 'v' prefix if present
        version_str = version_str.lstrip('vV')
        parts = version_str.split('.')
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return (major, minor, patch)
    except (ValueError, IndexError):
        return (0, 0, 0)

def compare_versions(version1: str, version2: str) -> int:
    """Compare two version strings. Returns: -1 if v1 < v2, 0 if v1 == v2, 1 if v1 > v2"""
    v1_tuple = extract_version_number(version1)
    v2_tuple = extract_version_number(version2)
    
    if v1_tuple < v2_tuple:
        return -1
    elif v1_tuple > v2_tuple:
        return 1
    else:
        return 0

def get_whats_new_highlights() -> List[str]:
    """Get 'What's New' highlights for current version."""
    return WHATS_NEW_HIGHLIGHTS

def read_version_info_file() -> Optional[Dict[str, str]]:
    """Read version info from the version info file."""
    try:
        if not os.path.exists(VERSION_INFO_FILE):
            return None
        
        with open(VERSION_INFO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not isinstance(data, dict) or 'version' not in data:
            return None
        
        return data
    except Exception:
        return None

def write_version_info_file(version: str):
    """Write version info to the version info file."""
    try:
        data = {"version": version}
        with open(VERSION_INFO_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass  # Silently fail

def show_whats_new(version: str, highlights: List[str]):
    """Display 'What's New' information in a professional and colorful format."""
    if not highlights:
        return
    
    if not RICH_AVAILABLE or not console:
        # Fallback for non-rich environments
        print(f"\n{'='*60}")
        print(f"What's New in VritraAI {version}")
        print(f"{'='*60}\n")
        for item in highlights:
            print(f"  • {item}")
        print()
        return
    
    from rich.panel import Panel
    from rich.text import Text
    
    # Create header
    header_text = Text()
    header_text.append("What's New in ", style="bold bright_white")
    header_text.append(f"VritraAI {version}", style="bold bright_cyan")
    
    console.print("")
    # Panel with expand=False to only take width of content, not full terminal
    console.print(Panel(header_text, border_style="bright_cyan", padding=(1, 2), expand=False))
    console.print("")
    
    # Display highlights with professional colors
    highlight_colors = ["bright_green", "bright_yellow", "bright_blue", "bright_magenta", "bright_cyan"]
    for idx, item in enumerate(highlights):
        item_text = Text()
        # Use different colors for each highlight
        color = highlight_colors[idx % len(highlight_colors)]
        item_text.append("  • ", style="bright_cyan")
        item_text.append(item, style=color)
        console.print(item_text)
    
    console.print("")

def should_show_version_info() -> bool:
    """Check if we should show version info (only for interactive shell launches)."""
    args = sys.argv[1:]
    
    # Check if help or version flags are used
    skip_flags = ['-h', '--help', '-v', '--version']
    for arg in args:
        if arg in skip_flags:
            return False
    
    # Show for interactive mode (no flags or -i/--interactive)
    return True

def check_and_show_version_info() -> bool:
    """Check version info and show 'What's New' if needed. Returns True if should continue."""
    try:
        if not should_show_version_info():
            return True
        
        current_version = VRITRA_VERSION.lstrip('vV')  # Remove 'v' prefix for comparison
        
        # Read version info file
        version_info = read_version_info_file()
        
        should_show_whats_new = False
        should_update_file = False
        show_outdated_warning = False
        
        if version_info is None:
            # File doesn't exist or is invalid - create/update it
            write_version_info_file(current_version)
            should_show_whats_new = True
        else:
            saved_version = version_info.get('version', '').lstrip('vV')
            
            if not saved_version:
                # Empty or missing version data
                write_version_info_file(current_version)
                should_show_whats_new = True
            else:
                # Compare versions
                comparison = compare_versions(current_version, saved_version)
                
                if comparison > 0:
                    # Current version is newer - update and show what's new
                    write_version_info_file(current_version)
                    should_show_whats_new = True
                elif comparison < 0:
                    # Saved version is newer - show outdated warning
                    show_outdated_warning = True
                # If equal, do nothing
        
        # Show outdated warning if needed
        if show_outdated_warning:
            if RICH_AVAILABLE and console:
                from rich.panel import Panel
                from rich.text import Text
                
                warning_text = Text()
                warning_text.append("⚠️  ", style="bold bright_yellow")
                warning_text.append("Outdated Version Detected", style="bold bright_yellow")
                warning_text.append("\n\n", style="white")
                warning_text.append("You're using an outdated version of VritraAI.", style="white")
                warning_text.append("\n", style="white")
                warning_text.append("Please upgrade to the latest version:", style="white")
                warning_text.append("\n\n", style="white")
                warning_text.append("  pip install vritraai --upgrade", style="bold bright_green")
                
                console.print("")
                console.print(Panel(warning_text, border_style="bright_yellow", padding=(1, 2)))
                console.print("")
            else:
                print("\n⚠️  WARNING: You're using an outdated version of VritraAI.")
                print("Please upgrade: pip install vritraai --upgrade\n")
        
        # Show what's new if needed
        if should_show_whats_new:
            highlights = get_whats_new_highlights()
            
            # Only show if there's content
            if highlights:
                show_whats_new(VRITRA_VERSION, highlights)
                
                # Get user confirmation with colorful prompt
                if RICH_AVAILABLE and console:
                    from rich.text import Text
                    console.print("")
                    prompt_text = Text()
                    prompt_text.append("Press ", style="dim white")
                    prompt_text.append("Enter", style="bold bright_green")
                    prompt_text.append(" to continue or ", style="dim white")
                    prompt_text.append("'q'", style="bold bright_red")
                    prompt_text.append(" to quit: ", style="dim white")
                    console.print(prompt_text, end="")
                    try:
                        response = input().strip().lower()
                        if response == 'q':
                            return False
                    except (EOFError, KeyboardInterrupt):
                        return False
                else:
                    try:
                        response = input("\nPress Enter to continue or 'q' to quit: ").strip().lower()
                        if response == 'q':
                            return False
                    except (EOFError, KeyboardInterrupt):
                        return False
        
        return True
        
    except Exception as e:
        # Silently handle errors - just continue
        return True

def startup_sequence():
    """Run a simple, clean startup sequence with professional MOTD"""
    # Clear screen for clean start
    clear_screen()
    
    # Show Ubuntu-style MOTD with all system information
    show_motd()
    
    # Initialize session tracking
    session.add_command("startup", "VritraAI Shell initialized successfully")
    log_session("Shell startup completed")

# --- Main Loop ---
def main():
    """The main loop of the AI shell."""
    # Parse command-line flags first (for entry point compatibility)
    # This allows flags to work when called via 'vritraai' command
    # parse_flags() will exit if help/version flags are used, or return True to continue
    parse_flags()
    
    global shell_running
    
    # Check and show version info / What's New (only for interactive shell)
    if not check_and_show_version_info():
        # User chose to quit
        return
    
    # Setup signal handlers for proper Ctrl+C handling
    setup_signal_handlers()
    
    # Run startup sequence
    startup_sequence()

    prompt_session = PromptSession(
        history=FileHistory(HISTORY_FILE),
        auto_suggest=AutoSuggestFromHistory(),
    )

    while shell_running:
        try:
            cwd = os.getcwd()
            home = os.path.expanduser("~")
            if cwd.startswith(home):
                cwd = "~" + cwd[len(home):]

            # Get current prompt style template
            prompt_template = PROMPT_STYLES[config_state.prompt_style]["template"]
            prompt_parts = []
            
            for style_class, text in prompt_template:
                if "{path}" in text:
                    prompt_parts.append((style_class, text.format(path=cwd)))
                else:
                    prompt_parts.append((style_class, text))

            # NOTE: Use single-line input so Enter executes the command.
            # Multi-line commands can still be composed using shell-style line continuation (e.g., \\ at EOL).
            command = prompt_session.prompt(
                prompt_parts,
                style=get_style(),
                completer=get_completer(),
                complete_while_typing=True,
                multiline=False,
            )
            
            # Record command to history file with timestamp (before execution)
            if command and command.strip():
                record_command_to_history(command.strip())
            
            execute_command(command)
        except EOFError:
            # EOFError can be from Ctrl+D or exit command
            print("\n")
            # Check if last command was exit to show appropriate message
            try:
                if (hasattr(session, 'commands_history') and 
                    session.commands_history and 
                    len(session.commands_history) > 0 and 
                    isinstance(session.commands_history[-1], dict) and
                    'command' in session.commands_history[-1] and
                    session.commands_history[-1]['command'].strip() == "exit"):
                    show_session_summary("User exit command")
                else:
                    show_session_summary("EOF (Ctrl+D)")
            except (IndexError, AttributeError, TypeError, KeyError):
                # Fallback if there's any issue accessing command history
                show_session_summary("Session ended")
            break
        except KeyboardInterrupt:
            # Ctrl+C pressed - handled by signal handler, just continue
            continue
        except Exception as e:
            print_with_rich(f"An unexpected error occurred: {e}", "error")
            continue

# --- Command-line Flag Handlers ---
def show_version():
    """Display version information with Rich formatting."""
    if RICH_AVAILABLE and console:
        from rich.text import Text
        
        console.print("")
        version_line = Text()
        version_line.append("VritraAI ", style="bold bright_cyan")
        version_line.append(VRITRA_VERSION, style="bold bright_green")
        console.print(version_line)
        
        info_line = Text()
        info_line.append("AI-Powered Terminal Shell", style="bright_white")
        console.print(info_line)
        
        python_line = Text()
        python_line.append(f"Python {platform.python_version()}", style="dim white")
        console.print(python_line)
        
        platform_line = Text()
        platform_line.append(f"Platform: {platform.system()}", style="dim white")
        console.print(platform_line)
        console.print("")
    else:
        print(f"VritraAI {VRITRA_VERSION}")
        print("AI-Powered Terminal Shell")
        print(f"Python {platform.python_version()}")
        print(f"Platform: {platform.system()}")

def show_compact_help():
    """Display compact help menu with Rich formatting."""
    if RICH_AVAILABLE and console:
        from rich.text import Text
        
        console.print("")
        header = Text("VritraAI - AI-Powered Terminal Shell", style="bold bright_cyan")
        console.print(header)
        console.print("")
        
        usage_header = Text("Usage:", style="bold bright_white")
        console.print(usage_header)
        console.print("  vritraai [OPTIONS]", style="white")
        console.print("")
        
        options_header = Text("Options:", style="bold bright_white")
        console.print(options_header)
        console.print("  -h, --help       Show this help message", style="green")
        console.print("  -v, --version    Show version information", style="green")
        console.print("  -i, --interactive Launch in interactive mode (default)", style="green")
        console.print("")
        
        quick_start_header = Text("Quick Start:", style="bold bright_white")
        console.print(quick_start_header)
        console.print("  Run without flags to start interactive shell", style="yellow")
        console.print("  Type 'help' inside the shell for full command list", style="yellow")
        console.print("")
    else:
        print("VritraAI - AI-Powered Terminal Shell")
        print("\nUsage:")
        print("  vritraai [OPTIONS]")
        print("\nOptions:")
        print("  -h, --help       Show this help message")
        print("  -v, --version    Show version information")
        print("  -i, --interactive Launch in interactive mode (default)")
        print("\nQuick Start:")
        print("  Run without flags to start interactive shell")
        print("  Type 'help' inside the shell for full command list")

def parse_flags():
    """Parse command-line flags and handle them appropriately."""
    valid_flags = {
        '-h': 'help',
        '--help': 'help',
        '-v': 'version',
        '--version': 'version',
        '-i': 'interactive',
        '--interactive': 'interactive'
    }
    
    args = sys.argv[1:]  # Skip script name
    
    # Filter out empty arguments
    args = [arg for arg in args if arg.strip()]
    
    # Check for invalid flags and invalid arguments
    invalid_flags = []
    invalid_arguments = []
    valid_flag_actions = []
    
    for arg in args:
        if arg in valid_flags:
            valid_flag_actions.append(valid_flags[arg])
        elif arg.startswith('-'):
            # Invalid flag (starts with - but not in valid_flags)
            invalid_flags.append(arg)
        else:
            # Invalid argument (doesn't start with -)
            invalid_arguments.append(arg)
    
    # Handle invalid flags
    if invalid_flags:
        if RICH_AVAILABLE and console:
            print_with_rich(f"❌ Invalid flag(s): {', '.join(invalid_flags)}", "error")
            print_with_rich("\n💡 Valid flags:", "info")
            print_with_rich("  -h, --help       Show help message", "info")
            print_with_rich("  -v, --version     Show version information", "info")
            print_with_rich("  -i, --interactive Launch in interactive mode", "info")
            print_with_rich("\n💡 Use only one flag at a time.", "warning")
        else:
            print(f"Error: Invalid flag(s): {', '.join(invalid_flags)}")
            print("Valid flags: -h/--help, -v/--version, -i/--interactive")
        sys.exit(1)
    
    # Handle invalid arguments (non-flag arguments)
    if invalid_arguments:
        if RICH_AVAILABLE and console:
            print_with_rich(f"❌ Invalid argument(s): {', '.join(invalid_arguments)}", "error")
            print_with_rich("\n💡 VritraAI doesn't accept non-flag arguments.", "warning")
            print_with_rich("\n💡 Valid usage:", "info")
            print_with_rich("  vritraai              # Launch interactive shell", "green")
            print_with_rich("  vritraai -h           # Show help", "green")
            print_with_rich("  vritraai -v           # Show version", "green")
            print_with_rich("  vritraai -i           # Launch interactive shell", "green")
            print_with_rich("\n💡 To run commands, launch the interactive shell first.", "info")
        else:
            print(f"Error: Invalid argument(s): {', '.join(invalid_arguments)}")
            print("VritraAI doesn't accept non-flag arguments.")
            print("Valid usage: vritraai [flag]")
            print("Valid flags: -h/--help, -v/--version, -i/--interactive")
        sys.exit(1)
    
    # Remove duplicates while preserving order
    unique_actions = []
    for action in valid_flag_actions:
        if action not in unique_actions:
            unique_actions.append(action)
    
    # Handle multiple flags
    if len(unique_actions) > 1:
        if RICH_AVAILABLE and console:
            print_with_rich("❌ Multiple flags detected. Please use only one flag at a time.", "error")
            print_with_rich(f"   Flags used: {', '.join(unique_actions)}", "warning")
            print_with_rich("\n💡 Valid usage:", "info")
            print_with_rich("  vritraai -h", "green")
            print_with_rich("  vritraai -v", "green")
            print_with_rich("  vritraai -i", "green")
        else:
            print(f"Error: Multiple flags detected: {', '.join(unique_actions)}")
            print("Please use only one flag at a time.")
        sys.exit(1)
    
    # Handle single valid flag
    if len(unique_actions) == 1:
        action = unique_actions[0]
        if action == 'help':
            show_compact_help()
            sys.exit(0)  # Exit after showing help
        elif action == 'version':
            show_version()
            sys.exit(0)  # Exit after showing version
        elif action == 'interactive':
            # Launch interactive mode (same as no flags)
            return True
    
    # No flags - launch interactive mode normally
    return True

if __name__ == "__main__":
    # main() now handles flag parsing internally
    main()
