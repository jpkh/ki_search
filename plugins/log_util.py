import pcbnew

def log_message(message, log_type="INFO"):
    """Logs a message in the KiCad scripting console."""
    full_message = f"[KI-Search] [{log_type}] {message}"
    print(full_message)  # Prints to KiCad's scripting console
    pcbnew.GetKernel().GetLogManager().Log(full_message)  # Logs to KiCad messages panel
