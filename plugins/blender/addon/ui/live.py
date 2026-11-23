"""The text is checked while it is typed, and the tree follows it as soon as it is valid.

A timer looks at the .bn texts shown in a Text Editor. Once a changed text has paused
for a moment, it is checked (parsed and typed, nothing built): its errors are underlined
and listed in the sidebar, even when live apply is off. Once the text of a tree has
rested longer and is valid, it is built; a build either succeeds whole or changes nothing.
"""

import time
import traceback

import bpy

from ..lang import BnError
from . import actions, prefs

TICK = 0.15  # seconds between two looks
PAUSE = 0.1  # a text unchanged for this long is checked: no check between two keys typed fast
REST = 0.5   # the text of a tree unchanged for this long is built

_seen = {}  # text name -> (source, when it was first seen so)
_tried = {}  # text name -> the source last built, valid or not


def shown_texts():
    """The .bn texts open in a Text Editor, with the areas that show them."""
    found = {}
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "TEXT_EDITOR":
                text = area.spaces.active.text
                if actions.is_bn(text):
                    found.setdefault(text, []).append(area)
    return found


def unchanged_for(name, source, now):
    """Seconds this source has been the text's, as the ticks saw it: 0 when it just changed."""
    seen = _seen.get(name)
    if seen is None or seen[0] != source:
        _seen[name] = (source, now)
        return 0.0
    return now - seen[1]


def check_due(name, source, now):
    """True when this source has paused long enough and its errors are not known yet."""
    return unchanged_for(name, source, now) >= PAUSE and actions.CHECKED.get(name) != source


def due(name, source, now):
    """True when this source has rested long enough and was not built yet."""
    return unchanged_for(name, source, now) >= REST and _tried.get(name) != source


def redraw(areas, nodes=False):
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area in areas or nodes and area.type in {"NODE_EDITOR", "VIEW_3D"}:
                area.tag_redraw()


def tick():
    try:
        look(time.monotonic())
    except Exception:
        # Blender drops a timer that raises: one text that breaks the check must not
        # end the live check of every text, for the rest of the session
        traceback.print_exc()
    return TICK


def look(now):
    texts = shown_texts()
    names = {t.name for t in texts}
    for name in list(_seen):
        if name not in names:
            _seen.pop(name, None)
            _tried.pop(name, None)
    apply = prefs.get().live_apply
    for text, areas in texts.items():
        source = text.as_string()
        view = actions.is_view(text)
        if view and actions.is_applied(text):
            # The tree holds it: it is valid
            _seen.pop(text.name, None)
            _tried[text.name] = source
            if actions.CHECKED.get(text.name) != source:
                actions.found(text, source)
                redraw(areas)
            continue
        if check_due(text.name, source, now):
            actions.check_text(text)
            redraw(areas)
        if not (view and apply) or not due(text.name, source, now):
            continue
        _tried[text.name] = source
        if actions.CHECKED.get(text.name) == source and actions.DIAGNOSTICS.get(text.name):
            continue  # its errors are known: a build would fail on them
        try:
            actions.apply_view(text, live=True)
        except BnError:
            pass  # the tree keeps what it had; the sidebar lists the errors
        except Exception:
            traceback.print_exc()
        redraw(areas, nodes=True)


def register():
    bpy.app.timers.register(tick, first_interval=TICK, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
    _seen.clear()
    _tried.clear()
