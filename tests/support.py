# SPDX-License-Identifier: Apache-2.0
"""Construct the real application without terminal setup or network requests."""

from app_state import Options
from application import App


class Screen:
    def getmaxyx(self):
        return (32, 120)

    def erase(self):
        pass

    def refresh(self):
        pass

    def addstr(self, y, x, text, style=0):
        pass


def make_app():
    return App(Screen(), Options(demo=True), interactive=False, autoload=False)
