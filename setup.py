#!/usr/bin/env python3
"""
Setup script for VritraAI
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read the contents of README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding="utf-8")

# Read requirements
requirements = []
with open("requirements.txt", "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#"):
            requirements.append(line)

setup(
    name="vritraai",
    version="0.29.0",
    author="Alex Butler",
    author_email="contact@vritrasec.com",
    description="An intelligent, AI-enhanced terminal shell with advanced features, beautiful theming, and powerful command execution capabilities",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/VritraSecz/VritraAI",
    project_urls={
        "Bug Reports": "https://github.com/VritraSecz/VritraAI/issues",
        "Source": "https://github.com/VritraSecz/VritraAI",
        "Documentation": "https://vritraai.vritrasec.com/",
        "Website": "https://vritrasec.com",
    },
    py_modules=["vritraai", "config_manager", "config"],
    install_requires=[
        "openai>=0.28.0",
        "requests>=2.28.0",
        "prompt-toolkit>=3.0.0",
        "rich>=13.0.0",
    ],
    extras_require={
        "optional": [
            "pygments>=2.13.0",
            "psutil>=5.9.0",
        ],
        "formatting": [
            "black>=23.0.0",
            "autopep8>=2.0.0",
        ],
        "all": [
            "pygments>=2.13.0",
            "psutil>=5.9.0",
            "black>=23.0.0",
            "autopep8>=2.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "vritraai=vritraai:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "Topic :: System :: Shells",
        "Topic :: System :: System Shells",
        "Topic :: Terminals",
        "Topic :: Utilities",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS",
        "Environment :: Console",
    ],
    python_requires=">=3.7",
    keywords="terminal shell ai cli command-line assistant automation",
    include_package_data=True,
    zip_safe=False,
)

