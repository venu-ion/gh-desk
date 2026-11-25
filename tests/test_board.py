# SPDX-License-Identifier: Apache-2.0
import argparse
import curses
import tempfile
import unittest
from unittest.mock import patch

from support import make_app

from local_store import Store
from models import Action


class Screen:
    def __init__(self, width=120, height=32):
        self.width, self.height, self.output = (width, height, [])

    def getmaxyx(self):
        return (self.height, self.width)

    def erase(self):
        self.output.clear()

    def refresh(self):
        pass

    def addstr(self, y, x, text, style):
        self.output.append((y, x, text))


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = app = make_app()
        app.store = Store(self.tmp.name, "test")
        app.state.project, app.state.tab, app.state.repo = (
            {"id": "PROJECT", "title": "Roadmap"},
            4,
            None,
        )
        app.state.rows = [
            dict(id="one", title="First", status="Todo", content={}),
            dict(id="two", title="Second", status="Todo", content={}),
            dict(id="three", title="Third", status="Done", content={}),
            dict(id="four", title="No status", status=None, content={}),
        ]
        app.store.put(
            "fields:PROJECT",
            {
                "fields": [
                    {"name": "Status", "options": [{"name": n} for n in ["Todo", "Doing", "Done"]]}
                ]
            },
        )
        app.state.query, app.state.status_filter, app.state.board_status = ("", None, None)
        app.state.board_enabled, app.state.board_offsets, app.state.board_hits = (True, {}, [])
        app.state.selected, app.state.top, app.state.scroll = (0, 0, 0)
        app.state.focus, app.state.issue_state = ("list", "open")
        app.state.detail_generation, app.state.modal = (0, None)
        app.args = argparse.Namespace(limit=100)
        app.state.syncing, app.state.loading, app.state.error, app.state.message = (
            False,
            False,
            "",
            "",
        )
        app.state.busy = False
        app.screen, app.state.colors = (Screen(), False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_columns_use_field_order_and_include_empty_and_unassigned(self):
        self.assertEqual(
            self.app.navigation.status_names(), ["Todo", "Doing", "Done", "Unassigned"]
        )
        self.assertEqual(
            [(n, len(rows)) for n, rows in self.app.navigation.board_groups()],
            [("Todo", 2), ("Doing", 0), ("Done", 1), ("Unassigned", 1)],
        )

    def test_navigation_within_column_and_across_empty_column(self):
        app = self.app
        self.assertEqual(app.navigation.current()["id"], "one")
        app.navigation.move(1)
        self.assertEqual(app.navigation.current()["id"], "two")
        app.navigation.move(100)
        self.assertEqual(app.navigation.current()["id"], "two")
        app.navigation.move_column(1)
        self.assertIsNone(app.navigation.current())
        self.assertEqual(app.state.board_status, "Doing")
        app.navigation.move(1)
        self.assertIsNone(app.navigation.current())
        app.navigation.move_column(1)
        self.assertEqual(app.navigation.current()["id"], "three")
        app.navigation.move_column(100)
        self.assertEqual(app.navigation.current()["id"], "four")

    def test_status_and_search_compose_without_fetching(self):
        app = self.app
        app.navigation.filter_status()
        label, choose = next(e for e in app.state.modal[2] if e[0].startswith("Todo"))
        self.assertEqual(label, "Todo (2)")
        with patch.object(app, "launch") as network:
            app.state.modal_index = next(
                (i for i, e in enumerate(app.state.modal[2]) if e[0].startswith("Todo"))
            )
            app.actions.choose()
            app.state.query = "second"
            self.assertEqual([r["id"] for r in app.navigation.visible()], ["two"])
            self.assertEqual([n for n, _ in app.navigation.board_groups()], ["Todo"])
            app.input.handle("\x1b")
            self.assertEqual(len(app.navigation.visible()), 2)
            app.input.handle("\x1b")
            self.assertEqual(len(app.navigation.visible()), 4)
            network.assert_not_called()
        self.assertEqual(len(app.state.rows), 4)

    def test_toggle_preserves_selected_card_and_details_open_in_popup(self):
        app = self.app
        app.navigation.move_column(2)
        self.assertEqual(app.navigation.current()["id"], "three")
        app.navigation.enter()
        self.assertEqual(app.state.modal[0], "detail")
        self.assertIn("Third", app.state.modal[2])
        app.state.modal = None
        app.navigation.toggle_board()
        self.assertFalse(app.navigation.board_active())
        app.state.selected = 1
        app.navigation.toggle_board()
        self.assertEqual(app.state.board_status, "Todo")
        self.assertEqual(app.navigation.current()["id"], "two")

    def test_actions_open_from_detail_with_colon_and_a(self):
        app = self.app
        for key in (":", "a"):
            app.navigation.enter()
            self.assertEqual(app.state.modal[0], "detail")
            app.input.handle(key)
            self.assertEqual(app.state.modal[:2], ("menu", "Actions"))
            index = next(
                (
                    i
                    for i, entry in enumerate(app.state.modal[2])
                    if isinstance(entry, tuple) and entry[0] == "Change status…"
                )
            )
            app.state.modal_index = index
            app.args.demo = False
            with patch.object(app, "launch") as launch:
                app.actions.choose()
                self.assertEqual(launch.call_args.args[0], "fields")
                self.assertEqual(launch.call_args.args[2][1]["id"], "one")
            app.state.busy = False

    def test_new_issue_shortcut_works_from_detail_and_actions_menu(self):
        app = self.app
        app.navigation.enter()
        with patch.object(app.actions, "new_issue") as new_issue:
            app.input.handle("n")
            new_issue.assert_called_once()
            self.assertIsNone(app.state.modal)
        app.navigation.enter()
        app.input.handle("a")
        with patch.object(app.actions, "new_issue") as new_issue:
            app.input.handle("n")
            new_issue.assert_called_once()
            self.assertIsNone(app.state.modal)

    def test_detail_actions_never_target_replacement_after_remote_removal(self):
        app = self.app
        app.navigation.enter()
        app.state.rows = app.state.rows[1:]
        app.input.handle(":")
        self.assertEqual(app.state.modal[:2], ("text", "Item changed"))

    def test_linked_issue_comment_is_queued_for_card_repo_and_survives_selection_change(self):
        app = self.app
        app.args = argparse.Namespace(limit=100, demo=False, offline=True, owner=None)
        app.state.rows[0]["content"] = dict(
            type="Issue",
            number=42,
            url="https://github.com/example-owner/example-repo/issues/42",
            body="Original issue",
        )
        app.state.repo = "different/repository"
        app.navigation.enter()
        app.input.handle(":")
        app.state.modal_index = next(
            (
                i
                for i, e in enumerate(app.state.modal[2])
                if isinstance(e, tuple) and e[0] == "Write a comment…"
            )
        )
        app.state.rows = app.state.rows[1:]
        with patch.object(app.input, "editor", return_value="A useful update"):
            app.actions.choose()
        self.assertEqual(app.state.modal[0], "confirm")
        app.state.modal_index = 1
        with patch.object(app.workspace, "load"), patch.object(app.workspace, "start_sync"):
            app.actions.choose()
        job = app.store.jobs()[0]
        payload = job["payload"]
        self.assertEqual(
            payload["args"][:5], ["issue", "comment", "42", "--repo", "example-owner/example-repo"]
        )
        self.assertEqual(payload["repo"], "example-owner/example-repo")
        self.assertEqual(payload["tab"], 1)
        self.assertEqual(payload["body"], "A useful update")
        self.assertIn("gh-desk:", payload["args"][-1])
        key = __import__("json").dumps(dict(tab=4, project="PROJECT", repo=None, state="open"))
        rows = [
            dict(
                id="target",
                content=dict(
                    url="https://github.com/example-owner/example-repo/issues/42",
                    body="Original issue",
                ),
            ),
            dict(
                id="other",
                content=dict(url="https://github.com/other/repo/issues/42", body="Unchanged"),
            ),
        ]
        local = app.store.overlay(key, rows)
        self.assertIn("A useful update", local[0]["content"]["body"])
        self.assertIn("Original issue", local[0]["content"]["body"])
        self.assertEqual(local[1]["content"]["body"], "Unchanged")
        self.assertEqual(rows[0]["content"]["body"], "Original issue")

    def test_linked_pr_conversation_and_enterprise_target(self):
        app = self.app
        app.state.rows[0]["content"] = dict(
            type="PullRequest", url="https://git.example.com/me/repo/pull/12"
        )
        app.actions.show_menu()
        view = next(
            e
            for e in app.state.modal[2]
            if isinstance(e, Action) and e.label == "Read conversation"
        )
        self.assertEqual(
            view.args, ["pr", "view", "12", "--repo", "git.example.com/me/repo", "--comments"]
        )
        self.assertTrue(view.viewer)
        self.assertEqual(
            app.actions.comment_target(app.state.rows[0])["hostname"], "git.example.com"
        )

    def test_draft_card_does_not_offer_github_comments(self):
        app = self.app
        app.state.rows[0]["content"] = dict(type="DraftIssue", body="Local draft")
        app.actions.show_menu()
        self.assertFalse(
            any(isinstance(e, tuple) and e[0] == "Write a comment…" for e in app.state.modal[2])
        )
        self.assertFalse(
            any(
                isinstance(e, Action) and e.label == "Read conversation" for e in app.state.modal[2]
            )
        )

    def test_render_handles_narrow_empty_filtered_and_scrolling_columns(self):
        app = self.app
        for width in (55, 80, 160):
            app.screen = Screen(width=width, height=14)
            app.renderer.draw_board()
            self.assertTrue(app.state.board_hits)
            app.navigation.move_column(2)
            app.renderer.draw_board()
        app.state.rows = []
        app.state.board_status = None
        app.renderer.draw_board()
        self.assertTrue(any(("No items" in text for _, _, text in app.screen.output)))
        app.state.status_filter, app.state.board_status = ("Removed status", "Removed status")
        app.renderer.draw_board()
        self.assertEqual(app.navigation.board_groups(), [("Removed status", [])])

    def test_board_list_and_details_show_all_four_metadata_fields(self):
        app = self.app
        app.state.rows[0].update(
            assignees=["alice", {"login": "bob"}],
            labels=["bug", {"name": "urgent"}],
            startDate="2026-11-20",
            **{"target date": "2026-12-15"},
        )
        app.screen = Screen(width=160, height=32)
        app.args.owner, app.args.demo = (None, False)
        for board in (True, False):
            app.state.board_enabled = board
            with patch.object(app, "launch") as network:
                app.renderer.draw()
                network.assert_not_called()
            text = "\n".join((value for _, _, value in app.screen.output))
            for expected in (
                "Assignees: @alice, @bob",
                "Labels: bug, urgent",
                "Start: 2026-11-20",
                "Due: 2026-12-15",
            ):
                self.assertIn(expected, text)
        details = app.renderer.detail_text()
        self.assertIn("Start date: 2026-11-20", details)
        self.assertIn("Due date: 2026-12-15", details)

    def test_empty_fields_and_newer_snapshot_do_not_restore_old_cleared_date(self):
        app = self.app
        app.store.put("date-fields:PROJECT", [dict(id="DATE", name="Due date")])
        app.store.put("item-date:PROJECT:one:DATE", "2026-12-15")
        app.state.view_key = "snapshot"
        app.store.put("snapshot", app.state.rows)
        self.assertEqual(
            app.issue_actions.display_metadata(app.state.rows[0]),
            ["Assignees: —", "Labels: —", "Start: —", "Due: —"],
        )
        app.store.put("item-date:PROJECT:one:DATE", "2026-12-20")
        self.assertEqual(app.issue_actions.display_dates(app.state.rows[0]), ("", "2026-12-20"))
        app.state.rows[0]["due date"] = ""
        self.assertEqual(app.issue_actions.display_dates(app.state.rows[0]), ("", ""))

    def test_expanded_cards_keep_due_line_clickable_and_clear_of_footers(self):
        app = self.app
        app.renderer.draw_board()
        card = next(hit for hit in app.state.board_hits if hit[5] == 1)
        x, y = (card[0] + 2, card[1] + 6)
        with patch("curses.getmouse", return_value=(0, x, y, 0, curses.BUTTON1_CLICKED)):
            app.input.mouse()
        self.assertEqual(app.navigation.current()["id"], "two")
        for height in (14, 18, 20, 24, 32):
            app.screen = Screen(height=height)
            app.renderer.draw_board()
            for _, y, _, lines, _, position in app.state.board_hits:
                if position is not None:
                    self.assertLess(y + lines - 1, height - 5)

    def test_expanded_list_metadata_click_selects_its_own_item(self):
        app = self.app
        app.args.owner, app.args.demo = (None, False)
        app.state.board_enabled = False
        app.renderer.draw()
        with patch(
            "curses.getmouse",
            return_value=(0, 10, 6 + app.state.list_stride + 4, 0, curses.BUTTON1_CLICKED),
        ):
            app.input.mouse()
        self.assertEqual(app.navigation.current()["id"], "two")

    def test_mouse_selects_card_and_wheel_stays_in_column(self):
        app = self.app
        app.renderer.draw_board()
        card = next(hit for hit in app.state.board_hits if hit[5] == 1)
        x, y = (card[0] + 2, card[1])
        app.state.modal = None
        with patch("curses.getmouse", return_value=(0, x, y, 0, curses.BUTTON1_CLICKED)):
            app.input.mouse()
        self.assertEqual(app.navigation.current()["id"], "two")
        with patch("curses.getmouse", return_value=(0, x, y, 0, curses.BUTTON4_PRESSED)):
            app.input.mouse()
        self.assertEqual(app.navigation.current()["id"], "one")


if __name__ == "__main__":
    unittest.main()
