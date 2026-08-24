##########################################################
#
# Script: __init__.py
# Author: Jani Hirvinen (jpkh)
# Contact: jphelirc@gmail.com
# Repository: https://github.com/jpkh/ki_search
#
# Copyright (c) 2026 Jani Hirvinen
# License: GPL-3.0 - see the LICENSE file
#
# Description: Plugin registration for KI-Search.
#
##########################################################

from .log_util import log_message

try:
    from .search import SearchDatabasePlugin
    plugin = SearchDatabasePlugin()
    plugin.register()
    log_message("Plugin initialized successfully.")
except Exception as e:
    log_message(f"Error initializing plugin: {repr(e)}", log_type="ERROR")
