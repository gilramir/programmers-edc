#!/usr/bin/env python3
"""predc's zone picker: the two levels and the filter that are one mechanism.

An area is a saved search rather than a second axis -- choosing `Asia` types
`Asia/` into Find, and typing narrows further -- so there is no precedence rule
to get wrong because there is only one piece of state.

Two of the three sections here are about Turbo Vision rather than about predc.
A wheel turn is not a positional event (`views.h`: `positionalEvents = evMouse
& ~evMouseWheel`), so `TGroup::handleEvent` offers it to every view in z-order
and the frontmost scroll bar answered for the whole window -- invisible until
three lists sit side by side. And a list box's highlight lives in Turbo
Vision, so the buttons read the model's copy of an index that nothing wrote
between one `Selected` and the next, and Add added the first row rather than
the highlighted one.

`drive_time_moves.py` picks up where this stops; see `time_common.py`.
"""

import sys

from time_common import (
    Checks, WHEN, click_button, click_in, config_of, config_path, find_text,
    launch, pane, pane_point, pin_instant, posix_at, retype, space_on,
    type_in_find,
)


def main():
    check = Checks()
    app, home = launch()
    pin_instant(app)

    retype(app, posix_at(app), str(WHEN), settle=1.2)
    app.send(b"\x1bz", settle=1.5)
    check("Alt-Z opens the zone picker", "Time zones" in app.render(), app.render())
    check("with every zone node knows", "418" in app.render(), app.render())
    check("and no filter to start with", "Africa/Abidjan" in app.render(), app.render())

    # An area is a saved search rather than a second axis: choosing one writes
    # its prefix into Find, and there is no rule about which of the two wins
    # because there is only one of them.
    for r, line in enumerate(app.render().split("\n")):
        if "Asia 82" in line:
            app.click(line.index("Asia 82") + 2, r + 1, settle=1.2)
            break
    check("choosing an area types its prefix", "Asia/" in app.render(), app.render())
    check("and the list is only that area", "Africa/Abidjan" not in app.render(),
          app.render())

    # ... and typing narrows it further, in the same box.
    type_in_find(app, "seo")
    check("typing after it narrows further", "Asia/Seoul" in app.render(), app.render())
    check("to exactly one", " 1 of 418" in app.render(), app.render())

    space_on(app, "Asia/Seoul")
    # Checked against the config file rather than the screen, and that is not a
    # dodge: the picker is now correctly in front of the converter, so the row
    # it just added is behind it. The file is written the moment the list
    # changes, so it is the earliest and the strongest evidence there is.
    check("Space on the zone list adds it, and it is written down at once",
          (config_of(home) or {}).get("timezones") == ["America/Chicago", "Asia/Seoul"],
          str(config_of(home)))
    # And the key predc has just invented arrives explained, with a blank line
    # holding its block off the key above it. That is what the config file is
    # TOML for, and it is a property of what `Config.apply` asks for rather
    # than of anything the converter did -- so this is the one place in the
    # suite that reads the file as text.
    written = open(config_path(home)).read()
    check("the key it invented arrives with a sentence saying what it is for",
          "\n\n# The time zones the time converter shows" in written, repr(written))

    # A quarter-hour zone, which is the case a whole-hour offset table gets
    # wrong and the reason the offset crosses the port in minutes rather than
    # hours. Nepal is +05:45 now and was +05:30 until 1986.
    #
    # Spelled `Katmandu` because that is what `Intl.supportedValuesOf` calls
    # it -- the canonical list still carries a handful of legacy spellings,
    # while `Intl` itself accepts the modern alias. So a config file with
    # `Asia/Kathmandu` in it works and cannot be found by browsing, which is a
    # fact about the database rather than about predc.
    type_in_find(app, "Katmandu", clear=True)
    space_on(app, "Asia/Katmandu")
    check("and a second one goes on the end, in the order they were chosen",
          (config_of(home) or {}).get("timezones")
          == ["America/Chicago", "Asia/Seoul", "Asia/Katmandu"],
          str(config_of(home)))

    # ---- the wheel turns the list it is pointing at ----
    #
    # A wheel turn is not a positional event: `views.h` defines
    # `positionalEvents = evMouse & ~evMouseWheel`, so `TGroup::handleEvent`
    # never asks which view is under the pointer -- it offers the turn to every
    # view in z-order until one clears it, and `TScrollBar` is the only stock
    # view that asks for `evMouseWheel` at all. The frontmost bar therefore
    # answered for the whole window, and the frontmost is the last one
    # inserted: turning the wheel over the zone list scrolled `Displaying`, two
    # panes to the right, while the list under the pointer sat still. In a
    # window that is one list and its bar the old rule is invisible and right;
    # it takes three lists side by side to see it. `PaneScrollBar` in
    # `tvnode.h` is the answer -- a list's own bar takes the wheel only over
    # its own list.
    type_in_find(app, "Asia/", clear=True)
    zones = pane(app, "Zone")
    chosen = pane(app, "Displaying")
    check("the whole area is on offer again", zones[0] == "Asia/Aden", str(zones))
    check("with the three chosen zones beside it",
          chosen == ["America/Chicago", "Asia/Seoul", "Asia/Katmandu"], str(chosen))

    # Four turns and not one: a turn is three `arrowStep`s and the list is nine
    # rows deep, so the first three only move the highlight down inside what is
    # already on the screen. Nothing above the tenth row can prove anything.
    where = pane_point(app, "Zone")
    app.wheel(where[0], where[1], turns=4)
    check("the wheel scrolls the list under the pointer",
          pane(app, "Zone")[0] != zones[0], str(pane(app, "Zone")))
    check("and not the one two panes over",
          pane(app, "Displaying") == chosen, str(pane(app, "Displaying")))

    # The area list under the pointer, which says the same thing from the other
    # end and says it in text: choosing an area writes its prefix into Find, so
    # a wheel that reaches the areas at all is a wheel that changes the box.
    before = find_text(app)
    where = pane_point(app, "Area")
    app.wheel(where[0], where[1], turns=1)
    check("an area under the pointer answers for itself",
          find_text(app) != before, str((before, find_text(app))))

    # ---- the buttons act on the highlight, and the highlight is C++'s ----
    #
    # A list box's highlight lives in Turbo Vision, and `Focused` is the only
    # way a model that cannot call into it finds out where the highlight went.
    # `Selected` carries an index of its own, so `Space` and a double click
    # were always right; the buttons read the model's copy, and nothing wrote
    # to it between one `Selected` and the next. So Add added whichever row
    # the last filter reset had left it pointing at -- the first one -- however
    # far down the list the highlight had since been clicked or wheeled.
    type_in_find(app, "Asia/", clear=True)
    zones = pane(app, "Zone")
    wanted = zones[2]
    click_in(app, "Zone", wanted)
    click_button(app, "Add >>")
    check("Add adds the row the highlight is on, not the first one",
          (config_of(home) or {}).get("timezones")
          == ["America/Chicago", "Asia/Seoul", "Asia/Katmandu", wanted],
          str(config_of(home)) + " wanted " + wanted)

    # And the other list, whose highlight is a second copy of the same bug.
    click_in(app, "Displaying", "Asia/Seoul")
    click_button(app, "<< Remove")
    check("Remove removes the row the highlight is on, not the first one",
          (config_of(home) or {}).get("timezones")
          == ["America/Chicago", "Asia/Katmandu", wanted],
          str(config_of(home)))

    # Seoul back, and the borrowed zone off again, so that the checks after
    # Done have the three rows they read -- in a different order, which none of
    # them looks at. `Space` for the add, which is the route that was never
    # broken, and the button for the remove, which is the route that was.
    type_in_find(app, "Asia/Seoul", clear=True)
    # `click_in` and not `space_on`, which searches the whole line: the name is
    # now in the Find box as well, and the box is the first place it is found.
    click_in(app, "Zone", "Asia/Seoul")
    app.send(b" ", settle=1.4)
    click_in(app, "Displaying", wanted)
    click_button(app, "<< Remove")
    check("and the borrowed zone comes off the same way",
          (config_of(home) or {}).get("timezones")
          == ["America/Chicago", "Asia/Katmandu", "Asia/Seoul"],
          str(config_of(home)))


    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
