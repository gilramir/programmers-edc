#!/usr/bin/env python3
"""predc's zone picker: reordering it, and the two things that made the order
wrong.

The echo first, because it is the one that was invisible. A list box's
highlight is moved by two parties -- the user moves it and is reported, the
model moves it by rendering a `focused` -- and reporting the second as well as
the first was a loop the mouse wheel exposed, because a wheel arrives as a
burst the model is several renders behind. Every echo of a stale index dragged
the list back, so a click landed on a row that was no longer under the pointer
and the zone that got added was one the user had never seen.

Then Move Up and Move Down, which carry a Gren trap: `Array.get` indexes from
the *end* when the index is negative, so `Array.get -1` is the last row and
never `Nothing`, and Move Up on the top row swapped the first zone with the
last. And Cancel, which cannot be "do not commit" because the picker applies
every change as it happens -- it is an undo, back to what the converter was
showing when the picker opened.

Starts where `drive_time_picker.py` stops, which `time_common.picker_with_three`
builds; see `time_common.py`.
"""

import sys

from time_common import (
    Checks, burst_wheel, click_button, click_in, clock, config_of, launch,
    pane, picker_heading, picker_with_three, posix, relaunch, row,
    type_in_find,
)


def main():
    check = Checks()
    app, home = launch()
    picker_with_three(app)

    # ---- the wheel, and the echo that used to drag the list back ----
    #
    # A list box's highlight is moved by two parties. The user moves it and is
    # reported; the model moves it by rendering a `focused`. Reporting the
    # second as well as the first was a loop -- the model writes the highlight,
    # hears that it moved, stores what it hears, writes it again -- and it was
    # invisible until the mouse wheel, which arrives as a burst of events the
    # model is several renders behind. Every echo of a stale index dragged the
    # list back to where it had been, so a click landed on a row that was no
    # longer under the pointer, and the zone that got added was one the user
    # had never seen.
    #
    # The check is a burst, then a click on a row read off the screen, and the
    # question is whether what was committed is the row that was clicked.
    type_in_find(app, "America/", clear=True)
    r, heading = picker_heading(app)
    zone_col = heading.index("Zone")
    before_wheel = pane(app, "Zone")
    burst_wheel(app, zone_col + 3, r + 3, 10)
    scrolled = pane(app, "Zone")
    check("a burst on the wheel scrolls the list under the pointer",
          scrolled != before_wheel, f"{scrolled} == {before_wheel}")

    aimed = scrolled[3]
    app.click(zone_col + 2, r + 2 + 3, settle=1.5)
    check("and the list stays where the wheel left it when a row is clicked",
          pane(app, "Zone") == scrolled, f"{pane(app, 'Zone')} != {scrolled}")

    app.send(b" ", settle=1.4)
    check("so the zone that arrives is the one that was under the pointer",
          (config_of(home) or {}).get("timezones", [])[-1] == aimed,
          f"{(config_of(home) or {}).get('timezones')} does not end in {aimed}")

    # Put the list back to the three the checks below read.
    click_in(app, "Displaying", aimed)
    click_button(app, "<< Remove")
    check("and the borrowed zone comes off again",
          (config_of(home) or {}).get("timezones")
          == ["America/Chicago", "Asia/Katmandu", "Asia/Seoul"],
          str(config_of(home)))

    # ---- Move Up and Move Down ----
    #
    # The order of the Displaying list is the order the converter shows the
    # zones in, and it was the order they happened to be added in with no way
    # to change it. These act on the same highlight the Remove button does.
    click_in(app, "Displaying", "Asia/Seoul")
    click_button(app, "Move Up")
    check("Move Up moves the highlighted row one place",
          (config_of(home) or {}).get("timezones")
          == ["America/Chicago", "Asia/Seoul", "Asia/Katmandu"],
          str(config_of(home)))

    click_button(app, "Move Up")
    check("and the highlight travels with the row, so twice is two places",
          (config_of(home) or {}).get("timezones")
          == ["Asia/Seoul", "America/Chicago", "Asia/Katmandu"],
          str(config_of(home)))

    # The check that pins a Gren trap rather than a picker one: `Array.get`
    # indexes from the *end* when the index is negative, so `Array.get -1` is
    # the last row and never `Nothing`. Move Up on the top row therefore
    # swapped the first zone with the last one, which is neither a move nor a
    # no-op. The bounds test in `move` is written out for this reason.
    click_button(app, "Move Up")
    check("and off the top is a no-op, not a swap with the bottom",
          (config_of(home) or {}).get("timezones")
          == ["Asia/Seoul", "America/Chicago", "Asia/Katmandu"],
          str(config_of(home)))

    click_button(app, "Move Down")
    check("and Move Down is the same the other way",
          (config_of(home) or {}).get("timezones")
          == ["America/Chicago", "Asia/Seoul", "Asia/Katmandu"],
          str(config_of(home)))

    click_button(app, "Done")
    check("Done closes the picker", "Time zones" not in app.render(), app.render())

    # With the picker out of the way, the rows it chose can be read. All three
    # are the same instant, which is the whole claim of the window.
    check("the chosen zones are all at the one instant",
          clock(app, "Asia/Seoul") == ("2026", "09", "02", "04", "32")
          and clock(app, "UTC") == ("2026", "09", "01", "19", "32"),
          str(clock(app, "Asia/Seoul")) + " " + str(clock(app, "UTC")))

    # Seoul has no abbreviation in en-US -- CLDR only carries them for North
    # America -- and `GMT+9` is the offset column spelled differently, so the
    # row shows the offset alone rather than the same fact twice.
    check("a zone with no abbreviation shows its offset alone",
          row(app, "Asia/Seoul")[5] == "+09:00", str(row(app, "Asia/Seoul")))
    check("a zone at a quarter past the hour is exact",
          row(app, "Asia/Katmandu")[5] == "+05:45", str(row(app, "Asia/Katmandu")))
    check("and its clock is quarter-hour offset from UTC",
          clock(app, "Asia/Katmandu") == ("2026", "09", "02", "01", "17"),
          str(clock(app, "Asia/Katmandu")))

    # Emptying the list is a choice and has to survive a restart, which is the
    # whole reason the config field is a `Maybe` rather than an array: an empty
    # array means "the user removed them all" and an absent key means "predc
    # has never been told", and they render differently.
    app.send(b"\x1bz", settle=1.5)
    for _ in range(3):
        click_button(app, "<< Remove")
    check("and an emptied list is written as empty",
          (config_of(home) or {}).get("timezones") == [], str(config_of(home)))

    click_button(app, "Done")
    check("every zone can be removed",
          row(app, "America/Chicago") is None and row(app, "Asia/Seoul") is None,
          app.render())
    check("UTC stays anyway, because it was never on the list",
          row(app, "UTC") is not None, app.render())

    # ---- Cancel puts back the list the picker opened on ----
    #
    # The picker applies every add and remove to the converter as it happens,
    # which is what makes it a workspace rather than a form. So there is no
    # draft to throw away and Cancel cannot be "do not commit": it is an undo,
    # back to what the converter was showing when the picker opened. The
    # config file follows without being told, because the shell writes it
    # whenever the two disagree.
    app.send(b"\x1bz", settle=1.5)
    type_in_find(app, "Asia/Seoul")
    click_in(app, "Zone", "Asia/Seoul")
    app.send(b" ", settle=1.4)
    # The config file and not the screen, for the same reason the first add was
    # checked that way: the picker is correctly in front of the converter, so
    # the row it just added is behind it. The screen is read after Cancel,
    # when there is nothing in the way.
    check("a zone added after the list was emptied is written down",
          (config_of(home) or {}).get("timezones") == ["Asia/Seoul"],
          str(config_of(home)))

    click_button(app, "Cancel")
    check("Cancel closes the picker", "Time zones" not in app.render(), app.render())
    check("and puts back the list it opened on",
          (config_of(home) or {}).get("timezones") == [], str(config_of(home)))
    check("so the row it added is gone again",
          row(app, "Asia/Seoul") is None, app.render())


    #     And the restart, which is Cancel's check from the other side: the
    #     list this section emptied has to still be empty in a second process,
    #     rather than springing back to the machine's own zone. It reads the
    #     config file the way every check above does, only through predc.
    app.send(b"\x1bx", settle=1.0)
    app.wait(timeout=6)

    # A second run, on the config the first one wrote: an empty list stays
    # empty rather than springing back to the machine's zone.
    again = relaunch(home)
    check("an emptied list stays empty across a restart",
          row(again, "America/Chicago") is None, again.render())
    check("with UTC and POSIX still there",
          row(again, "UTC") is not None and posix(again) is not None, again.render())
    again.send(b"\x1bx", settle=1.0)
    again.wait(timeout=6)


    return check.report(again)


if __name__ == "__main__":
    sys.exit(main())
