"""fabprint has been renamed to estampo. Please update your imports."""

import warnings

warnings.warn(
    "fabprint has been renamed to estampo. "
    "Please run: pip install estampo && pip uninstall fabprint. "
    "This wrapper will be removed in a future release.",
    DeprecationWarning,
    stacklevel=2,
)

from estampo import *  # noqa: E402, F401, F403
from estampo import __version__  # noqa: E402, F401
