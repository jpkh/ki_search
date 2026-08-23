import os
import sqlite3
import wx
import pcbnew
import webbrowser


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
    def __init__(self, parent):
        super().__init__(parent, title="Search Components", size=(1200, 400))

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        self.search_ctrl = wx.TextCtrl(panel, size=(400, -1))
        self.search_btn = wx.Button(panel, label="Search")
        hbox1.Add(wx.StaticText(panel, label="Search: "), flag=wx.RIGHT, border=5)
        hbox1.Add(self.search_ctrl, flag=wx.RIGHT, border=5)
        hbox1.Add(self.search_btn, flag=wx.RIGHT, border=5)
        vbox.Add(hbox1, flag=wx.EXPAND | wx.ALL, border=10)

        self.result_list = wx.ListCtrl(panel, style=wx.LC_REPORT)
        self.result_list.InsertColumn(0, "LCSC Pn", width=120)
        self.result_list.InsertColumn(1, "Mfg Part Nr", width=150)
        self.result_list.InsertColumn(2, "Manufacturer", width=120)
        self.result_list.InsertColumn(3, "Package", width=100)
        self.result_list.InsertColumn(4, "Description", width=400)
        self.result_list.InsertColumn(5, "O-Qty", wx.LIST_FORMAT_RIGHT, width=70)
        self.result_list.InsertColumn(6, "UP($)", wx.LIST_FORMAT_RIGHT, width=70)
        self.result_list.InsertColumn(7, "OP($)", wx.LIST_FORMAT_RIGHT, width=70)
        vbox.Add(self.result_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        self.search_btn.Bind(wx.EVT_BUTTON, self.on_search)
        self.result_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_item_click)

        panel.SetSizer(vbox)

    def on_item_click(self, event):
        """Open the LCSC search page when clicking an LCSC part number."""
        item_index = event.GetIndex()
        lcsc_part_number = self.result_list.GetItemText(item_index, 0)
        if lcsc_part_number:
            url = f"https://www.lcsc.com/search?q={lcsc_part_number}"
            webbrowser.open(url)

    def get_database_path(self):
        """Determine the database path using KiCad's USER_DOCS environment variable."""
        user_docs = os.getenv('USER_DOCS')
        if not user_docs:
            wx.MessageBox("KiCad's USER_DOCS variable is not set. Using default path.",
                          "Warning", wx.OK | wx.ICON_WARNING)
            user_docs = os.path.expanduser("~/Documents")  # Fallback for safety
        return os.path.join(user_docs, "KiCAD", "Gen", "scripts", "components.db")

    def on_search(self, event):
        """Perform a database search based on user input."""
        search_term = self.search_ctrl.GetValue().strip()
        self.result_list.DeleteAllItems()

        if not search_term:
            wx.MessageBox("Please enter a search term", "Warning", wx.OK | wx.ICON_WARNING)
            return

        db_path = self.get_database_path()
        results = self.search_database(db_path, search_term)

        if not results:
            wx.MessageBox("No results found.", "Info", wx.OK | wx.ICON_INFORMATION)
        else:
            for row in results:
                index = self.result_list.InsertItem(self.result_list.GetItemCount(), row[0])

                # Style the LCSC Pn (column 0) as a blue, underlined link
                font = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL,
                               wx.FONTWEIGHT_NORMAL, underline=True)
                self.result_list.SetItem(index, 0, row[0])
                self.result_list.SetItemTextColour(index, wx.Colour(0, 0, 255))
                self.result_list.SetItemFont(index, font)

                # Fill the other columns normally
                for col, value in enumerate(row[1:], 1):
                    self.result_list.SetItem(index, col, str(value))
                    self.result_list.SetItemTextColour(index, wx.Colour(0, 0, 0))

    def search_database(self, db_path, search_term):
        """Query the SQLite database for matching components."""
        if not os.path.exists(db_path):
            wx.MessageBox(f"Database not found at {db_path}", "Error", wx.OK | wx.ICON_ERROR)
            return []

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            query = '''
            SELECT lcsc_part_number, manufacture_part_number, manufacturer, package, description,
                   order_qty, unit_price, order_price
            FROM components
            WHERE lcsc_part_number LIKE ?
            OR manufacture_part_number LIKE ?
            OR manufacturer LIKE ?
            OR package LIKE ?
            OR description LIKE ?
            OR CAST(order_qty AS TEXT) LIKE ?
            OR CAST(unit_price AS TEXT) LIKE ?
            OR CAST(order_price AS TEXT) LIKE ?
            '''
            search_value = f"%{search_term}%"
            cursor.execute(query, [search_value] * 8)
            results = cursor.fetchall()
            conn.close()
            return results
        except Exception as e:
            wx.MessageBox(f"Database error: {e}", "Error", wx.OK | wx.ICON_ERROR)
            return []
