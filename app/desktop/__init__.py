"""TapBook control panel: a window to start and stop the server.

  process.py   the server as a separate process (JSON events, password, stop)
  theme.py     look consistent with the web interface (colours, fonts, shapes)
  window.py    the window and its dialogs (password, confirmation on close)

It opens with `python -m app desktop`, or from the shortcut created by the installer.
`python -m app desktop --check` builds the window without showing it and closes it
right away: the installers use it to confirm that the panel really starts.
"""
import os
import sys


def main(config, check: bool = False):
    if os.name == "nt":
        # Crisp window on high-resolution Windows screens.
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    import tkinter as tk
    from .window import ControlPanel
    root = tk.Tk(className="TapBook")
    if check:
        root.withdraw()
        ControlPanel(root, config, check_updates=False)
        root.update()
        root.destroy()
        return
    ControlPanel(root, config)
    root.mainloop()
    sys.exit(0)


def report_failure(log_path, text: str):
    """The panel could not open. Started from the shortcut there is no terminal
    (pythonw on Windows), so the error is saved to a file and shown in a
    message box instead of disappearing silently."""
    try:
        log_path.write_text(text, encoding="utf-8")
    except OSError:
        pass
    message = ("TapBook non è riuscito ad aprirsi.\n\n"
               f"{text.strip().splitlines()[-1] if text.strip() else ''}\n\n"
               f"Dettagli in: {log_path}\n"
               "Prova a reinstallare TapBook con l'installer.")
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("TapBook", message)
        root.destroy()
    except Exception:
        if os.name == "nt":
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, message, "TapBook", 0x10)
            except (AttributeError, OSError):
                pass
