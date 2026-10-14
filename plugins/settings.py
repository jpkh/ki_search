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
from .importer import (get_locations, add_location, rename_location,
                       remove_location, count_location_rows)


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

        self.loc_list = wx.ListBox(self, size=(220, 300))
        sizer.Add(self.loc_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.add_loc_btn = wx.Button(self, label="Add")
        self.rename_loc_btn = wx.Button(self, label="Rename")
        self.remove_loc_btn = wx.Button(self, label="Remove")
        btn_row.Add(self.add_loc_btn, flag=wx.RIGHT, border=5)
        btn_row.Add(self.rename_loc_btn, flag=wx.RIGHT, border=5)
        btn_row.Add(self.remove_loc_btn)
        sizer.Add(btn_row, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        note = wx.StaticText(
            self,
            label="Rename updates every component row using\n"
                  "that code. Remove clears the code from\n"
                  "those rows.")
        note_font = note.GetFont()
        note_font.SetPointSize(max(6, note_font.GetPointSize() - 1))
        note.SetFont(note_font)
        note.SetForegroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
        sizer.Add(note, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        self.add_loc_btn.Bind(wx.EVT_BUTTON, self.on_add_location)
        self.rename_loc_btn.Bind(wx.EVT_BUTTON, self.on_rename_location)
        self.remove_loc_btn.Bind(wx.EVT_BUTTON, self.on_remove_location)
        return sizer

    def _refresh_locations(self):
        try:
            self.loc_list.Set(get_locations(self.db_path))
        except Exception:
            self.loc_list.Set([])

    def _selected_location(self):
        sel = self.loc_list.GetSelection()
        if sel == wx.NOT_FOUND:
            return None
        return self.loc_list.GetString(sel)

    def on_add_location(self, event):
        dlg = wx.TextEntryDialog(self, "New location code:", "Add Location")
        if dlg.ShowModal() == wx.ID_OK:
            try:
                add_location(self.db_path, dlg.GetValue())
            except Exception as e:
                wx.MessageBox(str(e), "Error", wx.OK | wx.ICON_ERROR)
            self._refresh_locations()
        dlg.Destroy()

    def on_rename_location(self, event):
        old_name = self._selected_location()
        if not old_name:
            wx.MessageBox("Select a location first.", "Warning",
                          wx.OK | wx.ICON_WARNING)
            return
        dlg = wx.TextEntryDialog(
            self, "New code for '{}':".format(old_name), "Rename Location",
            value=old_name)
        if dlg.ShowModal() == wx.ID_OK:
            try:
                rename_location(self.db_path, old_name, dlg.GetValue())
            except Exception as e:
                wx.MessageBox(str(e), "Error", wx.OK | wx.ICON_ERROR)
            self._refresh_locations()
        dlg.Destroy()

    def on_remove_location(self, event):
        name = self._selected_location()
        if not name:
            wx.MessageBox("Select a location first.", "Warning",
                          wx.OK | wx.ICON_WARNING)
            return
        affected = count_location_rows(self.db_path, name)
        msg = "Remove '{}'?".format(name)
        if affected:
            msg += "\n{} component row(s) will have their location cleared.".format(affected)
        dlg = wx.MessageDialog(self, msg, "Remove Location",
                               wx.YES_NO | wx.ICON_QUESTION)
        if dlg.ShowModal() == wx.ID_YES:
            try:
                remove_location(self.db_path, name)
            except Exception as e:
                wx.MessageBox(str(e), "Error", wx.OK | wx.ICON_ERROR)
            self._refresh_locations()
        dlg.Destroy()

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
