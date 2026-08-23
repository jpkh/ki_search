import json
import os
import wx

from .config import settingsFileName, COLUMNS


def get_settings_file_path():
    """Settings live next to the plugin code (created at runtime, never shipped)."""
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), settingsFileName)


DEFAULT_OPTIONS = {
    'active_columns': [c[0] for c in COLUMNS],
    'db_path': '',
}


def load_options():
    try:
        with open(get_settings_file_path(), 'r') as f:
            user = json.load(f)
    except Exception:
        user = {}

    options = DEFAULT_OPTIONS.copy()
    options.update(user)

    # Validate columns against the known list
    valid = [c[0] for c in COLUMNS]
    active = [k for k in options.get('active_columns', []) if k in valid]
    options['active_columns'] = active if active else valid
    options['db_path'] = (options.get('db_path') or '').strip()
    return options


def save_options(options):
    try:
        with open(get_settings_file_path(), 'w') as f:
            json.dump(options, f, indent=4)
    except Exception as e:
        wx.MessageBox("Error saving settings: {}".format(e), "Error", wx.OK | wx.ICON_ERROR)


class SettingsDialog(wx.Dialog):
    def __init__(self, parent, options):
        super().__init__(parent, title="KI-Search Settings", size=(420, 520))

        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(wx.StaticText(self, label="Visible columns:"),
                 flag=wx.ALL, border=10)

        self.column_checks = {}
        for key, header, _width, _right in COLUMNS:
            cb = wx.CheckBox(self, label=header)
            cb.SetValue(key in options.get('active_columns', []))
            self.column_checks[key] = cb
            vbox.Add(cb, flag=wx.LEFT | wx.RIGHT, border=20)

        vbox.Add(wx.StaticText(self, label="Database folder (components.db is created inside;\nempty = auto from USER_DOCS):"),
                 flag=wx.ALL, border=10)
        self.db_path_ctrl = wx.DirPickerCtrl(self, message="Choose the database folder")
        self.db_path_ctrl.SetPath(options.get('db_path', ''))
        vbox.Add(self.db_path_ctrl,
                 flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        btns = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        vbox.Add(btns, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)

        self.SetSizer(vbox)
        self.Fit()
        self.SetMinSize(self.GetSize())
        self.Centre(wx.BOTH)

    def get_options(self):
        active = [k for k, cb in self.column_checks.items() if cb.GetValue()]
        if not active:
            active = [c[0] for c in COLUMNS]
        return {
            'active_columns': active,
            'db_path': self.db_path_ctrl.GetValue().strip(),
        }
