import os
import sqlite3
import wx
import pcbnew
import webbrowser

from .config import COLUMNS, default_db_relpath, default_db_filename, plugin_version
from .settings import load_options, save_options, SettingsDialog
from .importer import get_db_stats, ensure_schema, ImportDialog
from .log_util import log_message


class SearchDatabasePlugin(pcbnew.ActionPlugin):
    def __init__(self):
        super().__init__()
        self.name = "Component Search"
        self.category = "Component Management"
        self.description = "Search for components in the database"
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), 'icon.png')

    def Run(self):
        frame = wx.GetActiveWindow()
        dlg = SearchDialog(frame)
        dlg.ShowModal()
        dlg.Destroy()


class SearchDialog(wx.Dialog):
    # Fixed SELECT order; displayed columns are a subset chosen in settings
    DB_COLUMN_ORDER = [c[0] for c in COLUMNS]

    def __init__(self, parent):
        title = "Search Components  Ki-Search V{}{}(c)2026 jpkh/fi".format(
            plugin_version, ' ' * 10)
        super().__init__(parent, title=title, size=(1200, 420))
        self.options = load_options()

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Row 1: search + actions
        hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        self.search_ctrl = wx.TextCtrl(panel, size=(400, -1), style=wx.TE_PROCESS_ENTER)
        self.search_btn = wx.Button(panel, label="Search")
        self.import_btn = wx.Button(panel, label="Import CSV…")
        self.settings_btn = wx.Button(panel, label="Settings…")
        hbox1.Add(wx.StaticText(panel, label="Search: "),
                  flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)
        hbox1.Add(self.search_ctrl,
                  flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)
        hbox1.Add(self.search_btn,
                  flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)
        hbox1.Add(self.import_btn,
                  flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)
        hbox1.Add(self.settings_btn, flag=wx.ALIGN_CENTER_VERTICAL, border=5)
        vbox.Add(hbox1, flag=wx.EXPAND | wx.ALL, border=10)

        # Row 2: results
        self.result_list = wx.ListCtrl(panel, style=wx.LC_REPORT)
        self._rebuild_columns()
        vbox.Add(self.result_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        # Row 3: info line
        self.info_label = wx.StaticText(panel, label="")
        vbox.Add(self.info_label,
                 flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        # Row 4: copyright with clickable link (window titles can't be links)
        hbox_bottom = wx.BoxSizer(wx.HORIZONTAL)
        hbox_bottom.Add(wx.StaticText(panel, label="(c)2026 "),
                        flag=wx.ALIGN_CENTER_VERTICAL)
        hbox_bottom.Add(wx.adv.HyperlinkCtrl(panel, wx.ID_ANY, "jpkh/fi",
                                             "https://github.com/jpkh"),
                        flag=wx.ALIGN_CENTER_VERTICAL)
        vbox.Add(hbox_bottom, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        self.search_btn.Bind(wx.EVT_BUTTON, self.on_search)
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_search)
        self.import_btn.Bind(wx.EVT_BUTTON, self.on_import)
        self.settings_btn.Bind(wx.EVT_BUTTON, self.on_settings)
        self.result_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_item_click)
        self.result_list.Bind(wx.EVT_MOTION, self.on_result_motion)
        self._row_meta = []  # (import_id, source file) aligned with list rows

        panel.SetSizer(vbox)
        # Defer the info refresh so the main dialog shows before any
        # create-database prompt appears
        wx.CallAfter(self._refresh_info)

    # ----- UI helpers ------------------------------------------------------

    def _rebuild_columns(self):
        self.result_list.ClearAll()
        active = self.options['active_columns']
        self.columns = [c for c in COLUMNS if c[0] in active]
        for i, (key, header, width, right) in enumerate(self.columns):
            fmt = wx.LIST_FORMAT_RIGHT if right else wx.LIST_FORMAT_LEFT
            self.result_list.InsertColumn(i, header, format=fmt, width=width)
        self.lcsc_col = next(
            (i for i, c in enumerate(self.columns) if c[0] == 'lcsc_part_number'), None)

    def _refresh_info(self):
        db_path = self.get_database_path()
        stats = get_db_stats(db_path)
        if not stats['exists']:
            if not self._ensure_database(db_path):
                self.info_label.SetLabel("Database not found: {}".format(db_path))
                return
            stats = get_db_stats(db_path)
        last = stats['last_update'] or 'unknown'
        self.info_label.SetLabel(
            "Components in DB: {}   |   DB: {}   |   Last update: {}".format(
                stats['total'], db_path, last))

    def _ensure_database(self, db_path):
        """Ask the user to create the database when it does not exist."""
        if os.path.isfile(db_path):
            return True
        dlg = wx.MessageDialog(
            self,
            "Database not found:\n{}\n\nCreate a new empty database?".format(db_path),
            "Database missing", wx.YES_NO | wx.ICON_QUESTION)
        result = dlg.ShowModal()
        dlg.Destroy()
        if result == wx.ID_YES:
            ensure_schema(db_path)
            return True
        return False

    # ----- Paths -----------------------------------------------------------

    def get_database_path(self):
        """Database file path: settings folder override, else USER_DOCS default."""
        override = (self.options.get('db_path') or '').strip()
        if override:
            return os.path.join(override, default_db_filename)
        user_docs = os.getenv('USER_DOCS')
        if not user_docs:
            user_docs = os.path.expanduser("~/Documents")  # Fallback for safety
        return os.path.join(user_docs, default_db_relpath)

    # ----- Events ----------------------------------------------------------

    def on_item_click(self, event):
        """Open the LCSC search page when clicking an LCSC part number."""
        if self.lcsc_col is None:
            return
        item_index = event.GetIndex()
        lcsc_part_number = self.result_list.GetItemText(item_index, self.lcsc_col)
        if lcsc_part_number:
            url = "https://www.lcsc.com/search?q={}".format(lcsc_part_number)
            webbrowser.open(url)

    def on_search(self, event):
        """Perform a database search based on user input."""
        search_term = self.search_ctrl.GetValue().strip()
        self.result_list.DeleteAllItems()
        self._row_meta = []

        if not search_term:
            wx.MessageBox("Please enter a search term", "Warning", wx.OK | wx.ICON_WARNING)
            return

        db_path = self.get_database_path()
        if not self._ensure_database(db_path):
            return
        results = self.search_database(db_path, search_term)

        if not results:
            wx.MessageBox("No results found.", "Info", wx.OK | wx.ICON_INFORMATION)
            return

        link_font = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL,
                            wx.FONTWEIGHT_NORMAL, underline=True)
        for row in results:
            values = dict(zip(self.DB_COLUMN_ORDER + ['import_id', 'source_file'], row))
            first_value = str(values.get(self.columns[0][0], ''))
            index = self.result_list.InsertItem(self.result_list.GetItemCount(), first_value)
            for col, (key, _header, _width, _right) in enumerate(self.columns):
                self.result_list.SetItem(index, col, str(values.get(key, '')))
            if self.lcsc_col is not None:
                # Style the LCSC Pn column as a blue, underlined link
                self.result_list.SetItemFont(index, link_font)
                self.result_list.SetItemTextColour(index, wx.Colour(0, 0, 255))
            self._row_meta.append((values.get('import_id'), values.get('source_file')))

    def on_result_motion(self, event):
        """Show the source CSV file of the hovered row as a tooltip."""
        if not self.options.get('show_source_tooltip', True):
            if self.result_list.GetToolTip():
                self.result_list.SetToolTip(None)
            event.Skip()
            return
        item, _flags = self.result_list.HitTest(event.GetPosition())
        if 0 <= item < len(self._row_meta):
            source = self._row_meta[item][1] or 'unknown'
            tip = self.result_list.GetToolTip()
            if tip is None:
                tip = wx.ToolTip('')
                self.result_list.SetToolTip(tip)
            if tip.GetTip() != source:
                tip.SetTip('Source: {}'.format(source))
        else:
            self.result_list.SetToolTip(None)
        event.Skip()

    def on_import(self, event):
        dlg = ImportDialog(self, self.get_database_path())
        if dlg.ShowModal() == wx.ID_OK:
            self._refresh_info()
        dlg.Destroy()

    def on_settings(self, event):
        dlg = SettingsDialog(self, self.options)
        if dlg.ShowModal() == wx.ID_OK:
            self.options.update(dlg.get_options())
            save_options(self.options)
            self._rebuild_columns()
            self._refresh_info()
            log_message("Settings saved: db folder = '{}'".format(
                self.options.get('db_path', '')))
        dlg.Destroy()

    # ----- Search ----------------------------------------------------------

    def search_database(self, db_path, search_term):
        """Query the SQLite database for matching components."""
        if not os.path.isfile(db_path):
            wx.MessageBox("Database not found at {}".format(db_path),
                          "Error", wx.OK | wx.ICON_ERROR)
            return []

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            query = '''
            SELECT c.lcsc_part_number, c.manufacture_part_number, c.manufacturer, c.package,
                   c.description, c.order_qty, c.unit_price, c.order_price,
                   c.import_id, i.file_name
            FROM components c
            LEFT JOIN imports i ON i.rowid = c.import_id
            WHERE c.lcsc_part_number LIKE ?
            OR c.manufacture_part_number LIKE ?
            OR c.manufacturer LIKE ?
            OR c.package LIKE ?
            OR c.description LIKE ?
            OR CAST(c.order_qty AS TEXT) LIKE ?
            OR CAST(c.unit_price AS TEXT) LIKE ?
            OR CAST(c.order_price AS TEXT) LIKE ?
            '''
            search_value = "%{}%".format(search_term)
            cursor.execute(query, [search_value] * 8)
            results = cursor.fetchall()
            conn.close()
            return results
        except Exception as e:
            wx.MessageBox("Database error: {}".format(e), "Error", wx.OK | wx.ICON_ERROR)
            return []
