"""WanXue API package.

This package uses a hyphenated directory name (wanxue-api) which Python
cannot import directly, so main.py bootstraps the package via importlib.
This __init__.py exists to make the directory a proper Python package
when sys.path contains this directory (i.e. for direct python -m execution).
"""
