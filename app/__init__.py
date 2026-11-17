"""RunHub application package.

Package layout
--------------
app.core       Application facade, configuration and JSON database.
app.models     Data models (Project, Profile, Settings).
app.services   Process manager, log manager, detector, plugins, monitors.
app.ui         PyQt5 interface: theme, icons, views and widgets.
app.utils      Filesystem and general helpers.
"""

__title__ = "runhub"
__version__ = "1.0.0"
__all__ = ["__version__"]
