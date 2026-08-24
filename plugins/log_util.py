##########################################################
#
# Script: log_util.py
# Author: Jani Hirvinen (jpkh)
# Contact: jphelirc@gmail.com
# Repository: https://github.com/jpkh/ki_search
#
# Copyright (c) 2026 Jani Hirvinen
# License: GPL-3.0 - see the LICENSE file
#
# Description: Logging helper.
#
##########################################################

import pcbnew

def log_message(message, log_type="INFO"):
    """Logs a message in the KiCad scripting console."""
    full_message = f"[KI-Search] [{log_type}] {message}"
    print(full_message)  # Prints to KiCad's scripting console
    pcbnew.GetKernel().GetLogManager().Log(full_message)  # Logs to KiCad messages panel
