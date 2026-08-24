from .log_util import log_message

try:
    from .search import SearchDatabasePlugin
    plugin = SearchDatabasePlugin()
    plugin.register()
    log_message("Plugin initialized successfully.")
except Exception as e:
    log_message(f"Error initializing plugin: {repr(e)}", log_type="ERROR")
