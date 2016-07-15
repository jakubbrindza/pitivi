# -*- coding: utf-8 -*-
# Pitivi video editor
# Copyright (c) 2016, Jakub Brindza <jakub.brindza@gmail.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin St, Fifth Floor,
# Boston, MA 02110-1301, USA.
import os
import tempfile
from unittest import mock
from unittest import TestCase

from pitivi.shortcuts import ShortcutsManager

class TestShortcuts(TestCase):

    def test_groups(self):
        app = mock.MagicMock()
        manager = ShortcutsManager(app)

        # Test register_group method
        manager.register_group("alpha_group", "The very first test group")
        self.assertListEqual(manager.groups, ["alpha_group"])
        manager.register_group("beta_group", "Another test group")
        self.assertListEqual(manager.groups, ["alpha_group", "beta_group"])

        # Test grouping using the stripping away group name from action name
        manager.add("alpha_group.first", ["<Control>A"], "First action")
        self.assertIn(("alpha_group.first", "First action"),
                      manager.group_actions["alpha_group"])
        manager.add("alpha_group.second", ["<Control>B"], "Second action")
        self.assertIn(("alpha_group.second", "Second action"),
                      manager.group_actions["alpha_group"])
        manager.add("beta_group.first", ["<Control>C"], "First beta action")
        self.assertIn(("beta_group.first", "First beta action"),
                      manager.group_actions["beta_group"])

        # Test grouping using the group optional argument
        # if group parameter is set, the action prefix can be anything,
        # it should be disregarded in favour of the group value.
        manager.add("anything.third_action", ["<Control>D"], "Third action",
                    group="beta_group")
        self.assertIn(("anything.third_action", "Third action"),
                      manager.group_actions["beta_group"])

    def test_add_shortcut(self):
        app = mock.MagicMock()

        # Test number of calls to set_accels_for_action method
        with mock.patch("pitivi.shortcuts.xdg_config_home") as xdg_config_home,\
                tempfile.TemporaryDirectory() as temp_dir:
            xdg_config_home.return_value = temp_dir
            manager = ShortcutsManager(app)
            # Test the add is calling set_accels_for_action(),
            # since there is no shortcuts.conf in the directory.
            manager.register_group("general", "General group")
            manager.add("prefix.action1", ["<Control>P"], "Action one")
            self.assertEqual(app.set_accels_for_action.call_count, 1)

            # Create the temporary shortcuts.conf file
            # and test that add is not calling set_accels_for_action()
            open(os.path.sep.join([temp_dir, "shortcuts.conf"]), "w").close()
            manager2 = ShortcutsManager(app)
            manager2.register_group("other", "Other group")

            manager2.add("prefix.action4", ["<Control>W"],
                               "Action addition not invoking set_accels_for_action")
            # No. of calls to set_accels_for_action should be unchanged now
            # because calling set_accels_for_action isn't allowed with .conf existing
            self.assertEqual(app.set_accels_for_action.call_count, 1)
