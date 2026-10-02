from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version('taxi_tipee')
except PackageNotFoundError:
    # Imported from a checkout that was never installed.
    __version__ = 'unknown'
