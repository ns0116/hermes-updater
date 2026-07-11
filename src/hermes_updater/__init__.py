from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("hermes-updater")
except PackageNotFoundError:
    __version__ = "unknown"
