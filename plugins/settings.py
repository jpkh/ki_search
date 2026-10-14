##########################################################
#
# Script: settings.py
# Author: Jani Hirvinen (jpkh)
# Contact: jphelirc@gmail.com
# Repository: https://github.com/jpkh/ki_search
#
# Copyright (c) 2026 Jani Hirvinen
# License: GPL-3.0 - see the LICENSE file
#
# Description: Settings dialog and options persistence.
#
##########################################################

import json
import os
import wx

from .config import settingsFileName, COLUMNS
from .importer import (get_locations, add_location, update_location,
                       set_location_disabled)


def get_settings_file_path():
    """Settings live next to the plugin code (created at runtime, never shipped)."""
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), settingsFileName)


DEFAULT_OPTIONS = {
    'active_columns': [c[0] for c in COLUMNS],
    'db_path': '',
    'show_source_tooltip': True,
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
    options['show_source_tooltip'] = bool(options.get('show_source_tooltip', True))
    return options


def save_options(options):
    try:
        with open(get_settings_file_path(), 'w') as f:
            json.dump(options, f, indent=4)
    except Exception as e:
        wx.MessageBox("Error saving settings: {}".format(e), "Error", wx.OK | wx.ICON_ERROR)


class SettingsDialog(wx.Dialog):
    def __init__(self, parent, options, db_path):
        super().__init__(parent, title="KI-Search Settings", size=(860, 540))
        self.db_path = db_path

        vbox = wx.BoxSizer(wx.VERTICAL)

        columns_box = wx.BoxSizer(wx.VERTICAL)

        columns_box.Add(wx.StaticText(self, label="Visible columns:"),
                        flag=wx.ALL, border=10)

        self.column_checks = {}
        for key, header, _width, _right in COLUMNS:
            cb = wx.CheckBox(self, label=header)
            cb.SetValue(key in options.get('active_columns', []))
            self.column_checks[key] = cb
            columns_box.Add(cb, flag=wx.LEFT | wx.RIGHT, border=20)

        columns_box.Add(wx.StaticText(self, label="Database folder (components.db is created inside;\nempty = Documents/KiCad/ki-search):"),
                        flag=wx.ALL, border=10)
        self.db_path_ctrl = wx.DirPickerCtrl(self, message="Choose the database folder")
        if options.get('db_path'):
            self.db_path_ctrl.SetPath(options.get('db_path', ''))
        else:
            # Empty setting: leave the picker field empty (SetPath('') would
            # show the current directory instead).
            self.db_path_ctrl.GetTextCtrl().SetValue('')
        columns_box.Add(self.db_path_ctrl,
                        flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        self.show_tooltip_check = wx.CheckBox(self, label='Show source CSV file name in row tooltips')
        self.show_tooltip_check.SetValue(bool(options.get('show_source_tooltip', True)))
        columns_box.Add(self.show_tooltip_check, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(columns_box, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)
        hbox.Add(self._build_locations_panel(), proportion=1,
                 flag=wx.EXPAND | wx.ALL, border=10)
        vbox.Add(hbox, proportion=1, flag=wx.EXPAND)

        btns = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        vbox.Add(btns, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)

        self.SetSizer(vbox)
        self.Fit()
        self.SetMinSize(self.GetSize())
        self.Centre(wx.BOTH)

        self._refresh_locations()

    # ----- Storage locations editor --------------------------------------

    def _build_locations_panel(self):
        box = wx.StaticBox(self, label="Storage locations")
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        self.loc_list = wx.ListBox(self, size=(220, 250))
        sizer.Add(self.loc_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        fields = wx.GridSizer(3, 2, 5, 5)
        fields.Add(wx.StaticText(self, label="UID:"),
                   flag=wx.ALIGN_CENTER_VERTICAL)
        self.loc_uid_ctrl = wx.TextCtrl(self)
        self.loc_uid_ctrl.SetEditable(False)
        fields.Add(self.loc_uid_ctrl, flag=wx.EXPAND)
        fields.Add(wx.StaticText(self, label="CODE:"),
                   flag=wx.ALIGN_CENTER_VERTICAL)
        self.loc_code_ctrl = wx.TextCtrl(self)
        fields.Add(self.loc_code_ctrl, flag=wx.EXPAND)
        fields.Add(wx.StaticText(self, label="NAME:"),
                   flag=wx.ALIGN_CENTER_VERTICAL)
        self.loc_name_ctrl = wx.TextCtrl(self)
        fields.Add(self.loc_name_ctrl, flag=wx.EXPAND)
        sizer.Add(fields, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.loc_upd_btn = wx.Button(self, label="UPD")
        self.loc_add_btn = wx.Button(self, label="Add")
        self.loc_dien_btn = wx.Button(self, label="DI")
        btn_row.Add(self.loc_upd_btn, flag=wx.RIGHT, border=5)
        btn_row.Add(self.loc_add_btn, flag=wx.RIGHT, border=5)
        btn_row.Add(self.loc_dien_btn)
        sizer.Add(btn_row, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=10)

        note = wx.StaticText(
            self,
            label="Disabled locations stay listed after the\n"
                  "active ones and cannot be newly assigned;\n"
                  "existing rows keep them. UPD saves CODE\n"
                  "and NAME of the selected row. Add uses\n"
                  "the CODE box; the UID is auto-assigned.")
        note_font = note.GetFont()
        note_font.SetPointSize(max(6, note_font.GetPointSize() - 1))
        note.SetFont(note_font)
        note.SetForegroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
        sizer.Add(note, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        self.loc_list.Bind(wx.EVT_LISTBOX, self.on_loc_select)
        self.loc_upd_btn.Bind(wx.EVT_BUTTON, self.on_loc_update)
        self.loc_add_btn.Bind(wx.EVT_BUTTON, self.on_loc_add)
        self.loc_dien_btn.Bind(wx.EVT_BUTTON, self.on_loc_toggle)
        return sizer

    def _refresh_locations(self, select_id=None, select_code=None):
        try:
            self._loc_rows = get_locations(self.db_path, include_disabled=True)
        except Exception:
            self._loc_rows = []
        self.loc_list.Set(
            ["{}  {}  {}".format(loc_id, code, name)
             for loc_id, code, name, _disabled in self._loc_rows])
        index = None
        if select_id is not None:
            for i, (loc_id, _c, _n, _d) in enumerate(self._loc_rows):
                if loc_id == select_id:
                    index = i
                    break
        elif select_code is not None:
            for i, (_i, code, _n, _d) in enumerate(self._loc_rows):
                if code == select_code:
                    index = i
                    break
        if index is None and self._loc_rows:
            index = 0
        if index is None:
            self.loc_list.SetSelection(wx.NOT_FOUND)
            self._clear_loc_fields()
        else:
            self.loc_list.SetSelection(index)
            self._fill_loc_fields(index)

    def _clear_loc_fields(self):
        self.loc_uid_ctrl.SetValue('')
        self.loc_code_ctrl.SetValue('')
        self.loc_name_ctrl.SetValue('')
        self.loc_dien_btn.SetLabel("DI")
        self._loc_index = None

    def _fill_loc_fields(self, index):
        loc_id, code, name, disabled = self._loc_rows[index]
        self.loc_uid_ctrl.SetValue(str(loc_id))
        self.loc_code_ctrl.SetValue(code)
        self.loc_name_ctrl.SetValue(name)
        self.loc_dien_btn.SetLabel("EN" if disabled else "DI")
        self._loc_index = index

    def on_loc_select(self, event):
        index = self.loc_list.GetSelection()
        if index != wx.NOT_FOUND:
            self._fill_loc_fields(index)
        else:
            self._clear_loc_fields()

    def on_loc_update(self, event):
        if self._loc_index is None:
            wx.MessageBox("Select a location first.", "Warning",
                          wx.OK | wx.ICON_WARNING)
            return
        loc_id, _code, _name, _disabled = self._loc_rows[self._loc_index]
        try:
            update_location(self.db_path, loc_id,
                            self.loc_code_ctrl.GetValue(),
                            self.loc_name_ctrl.GetValue())
        except Exception as e:
            wx.MessageBox(str(e), "Error", wx.OK | wx.ICON_ERROR)
        self._refresh_locations(select_id=loc_id)

    def on_loc_add(self, event):
        code = self.loc_code_ctrl.GetValue().strip()
        if not code:
            wx.MessageBox("Type the new location code in the CODE box first.",
                          "Warning", wx.OK | wx.ICON_WARNING)
            return
        try:
            add_location(self.db_path, code, self.loc_name_ctrl.GetValue())
        except Exception as e:
            wx.MessageBox(str(e), "Error", wx.OK | wx.ICON_ERROR)
        self._refresh_locations(select_code=code)

    def on_loc_toggle(self, event):
        if self._loc_index is None:
            wx.MessageBox("Select a location first.", "Warning",
                          wx.OK | wx.ICON_WARNING)
            return
        loc_id, _code, _name, disabled = self._loc_rows[self._loc_index]
        try:
            set_location_disabled(self.db_path, loc_id, not disabled)
        except Exception as e:
            wx.MessageBox(str(e), "Error", wx.OK | wx.ICON_ERROR)
        self._refresh_locations(select_id=loc_id)

    def get_options(self):
        active = [k for k, cb in self.column_checks.items() if cb.GetValue()]
        if not active:
            active = [c[0] for c in COLUMNS]
        db_path = self.db_path_ctrl.GetPath().strip()
        if db_path:
            db_path = os.path.normpath(db_path)
        return {
            'active_columns': active,
            'db_path': db_path,
            'show_source_tooltip': self.show_tooltip_check.GetValue(),
        }
