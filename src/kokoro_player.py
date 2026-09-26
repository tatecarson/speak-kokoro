"""Playback controls and word highlighting for the speak-kokoro menu bar app.

Two views of the same daemon events:

- a floating panel with voice and speed pickers and rewind / play-pause /
  forward, showing the whole text with the sentence and word being read
  marked, which works for any text (and shrinks to just the controls when the
  document shows the words itself). Like Word's Read Aloud it stays open:
  select other text and press play to read that instead;
- an overlay drawn over the word in the document it came from, which needs
  Accessibility permission and an app that reports where its text is on
  screen (Word, TextEdit, Pages and most native text views do).

Everything here runs on the main thread. The menu bar app forwards daemon
events with AppHelper.callAfter.
"""
import re
import sys
import threading
import time
import unicodedata

import objc
from AppKit import (NSApp, NSAttributedString, NSBackgroundColorAttributeName,
                    NSBackingStoreBuffered, NSButton, NSColor,
                    NSFont,
                    NSFontAttributeName, NSFontWeightRegular,
                    NSForegroundColorAttributeName, NSImage, NSImageOnly,
                    NSImageSymbolConfiguration, NSMaxYEdge, NSMenuItem,
                    NSMinYEdge, NSPanel, NSPopover,
                    NSPopoverBehaviorTransient, NSSlider,
                    NSTextAlignmentRight, NSTextField,
                    NSViewController,
                    NSPasteboard, NSPasteboardItem, NSPasteboardTypeString,
                    NSPopUpButton, NSRunningApplication, NSScreen, NSScrollView, NSTextView, NSView, NSViewHeightSizable,
                    NSViewMaxXMargin, NSViewMinXMargin, NSViewMinYMargin,
                    NSViewWidthSizable, NSWindow,
                    NSWindowCollectionBehaviorCanJoinAllSpaces,
                    NSWindowCollectionBehaviorFullScreenAuxiliary,
                    NSWindowCollectionBehaviorIgnoresCycle,
                    NSWindowCollectionBehaviorTransient,
                    NSFloatingWindowLevel, NSWindowStyleMaskBorderless,
                    NSWindowStyleMaskClosable, NSWindowStyleMaskHUDWindow,
                    NSWindowStyleMaskNonactivatingPanel,
                    NSWindowStyleMaskResizable, NSWindowStyleMaskTitled, NSWindowStyleMaskUtilityWindow,
                    NSWorkspace)
from Foundation import NSMakeRange, NSMakeRect, NSObject, NSTimer
from PyObjCTools import AppHelper

try:
    import ApplicationServices as AX
    import Quartz
except ImportError:           # pyobjc-framework-ApplicationServices missing
    AX = Quartz = None

WIDTH, HEIGHT = 400, 300
MIN_WIDTH = 260
COMPACT = 48                  # panel content height with only the controls
REFRESH = 0.25                # seconds between overlay position checks
AX_TIMEOUT = 0.25             # never let a busy app stall the menu bar
FIND_FOR = 2.5                # seconds to keep asking an app for its selection


VOICES = {
    "US female": "af_heart af_bella af_nicole af_sarah af_sky af_alloy af_aoede "
                 "af_jessica af_kore af_nova af_river".split(),
    "US male": "am_michael am_adam am_echo am_eric am_fenrir am_liam am_onyx "
               "am_puck am_santa".split(),
    "UK female": "bf_emma bf_alice bf_isabella bf_lily".split(),
    "UK male": "bm_george bm_daniel bm_fable bm_lewis".split(),
}
SPEEDS = ["0.8", "0.9", "1.0", "1.1", "1.2", "1.3", "1.5", "1.75", "2.0"]
HINT = "Select text in any app, then press play."


def ax_available():
    return AX is not None and AX.AXIsProcessTrusted()


def ask_for_accessibility():
    """Show the system prompt that adds this app to Accessibility."""
    if AX is not None:
        AX.AXIsProcessTrustedWithOptions({AX.kAXTrustedCheckOptionPrompt: True})


def _skip(ch):
    # Word reports paragraph marks, soft breaks and object placeholders that
    # the Services copy of the text may render differently or not at all.
    return ch.isspace() or ch == "￼" or unicodedata.category(ch) in ("Cc", "Cf")


def align(spoken, selected):
    """Map each index in spoken to a UTF-16 (start, end) in selected.

    The two should be the same text, but may disagree on whitespace and
    invisible characters. Anything else and they are not the same text, so
    return None rather than highlight the wrong words.
    """
    u16, n = [], 0
    for ch in selected:
        u16.append(n)
        n += 2 if ord(ch) > 0xFFFF else 1
    u16.append(n)
    starts, ends = [None] * len(spoken), [None] * len(spoken)
    j = 0
    for i, ch in enumerate(spoken):
        if _skip(ch):
            continue
        while j < len(selected) and _skip(selected[j]):
            j += 1
        if j >= len(selected) or selected[j] != ch:
            return None
        starts[i], ends[i] = u16[j], u16[j + 1]
        j += 1
    return starts, ends


def selected_text():
    """What is selected in the frontmost app, or "" if nothing can be found.

    Asks through Accessibility first. Apps that don't answer (some browsers,
    Electron apps) get a simulated Copy, with the clipboard put back after.
    Called off the main thread, since the copy has to wait for the app.
    """
    if not ax_available():
        return ""
    try:
        element = _attr(AX.AXUIElementCreateSystemWide(), "AXFocusedUIElement")
        if element is not None:
            AX.AXUIElementSetMessagingTimeout(element, AX_TIMEOUT)
            text = _attr(element, "AXSelectedText")
            if text and str(text).strip():
                return str(text)
    except Exception:
        pass
    return copied_text()


def copied_text():
    pb = NSPasteboard.generalPasteboard()
    saved = [{t: item.dataForType_(t) for t in item.types()}
             for item in pb.pasteboardItems() or []]
    before = pb.changeCount()
    for down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(None, 8, down)    # "c"
        Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
    for _ in range(15):
        time.sleep(0.02)
        if pb.changeCount() != before:
            break
    else:
        return ""             # nothing selected, so nothing was copied
    text = pb.stringForType_(NSPasteboardTypeString) or ""
    pb.clearContents()
    items = []
    for types in saved:
        item = NSPasteboardItem.alloc().init()
        for kind, data in types.items():
            if data is not None:
                item.setData_forType_(data, kind)
        items.append(item)
    if items:
        pb.writeObjects_(items)
    return text


def _same(a, b):
    return re.sub(r"\s+", " ", a).strip() == re.sub(r"\s+", " ", b).strip()


def _attr(element, name):
    err, value = AX.AXUIElementCopyAttributeValue(element, name, None)
    return None if err else value


def _range(value):
    ok, rng = AX.AXValueGetValue(value, AX.kAXValueCFRangeType, None)
    return tuple(rng) if ok else None


def log(message):
    sys.stderr.write(f"{message}\n")
    sys.stderr.flush()


def locate_selection(text):
    """Where text sits in the focused app's selection, as a highlight target.

    Returns ((element, pid, selection start, offsets), None), or
    (None, reason) when the app can't say or the selection is other text.
    """
    try:
        system = AX.AXUIElementCreateSystemWide()
        AX.AXUIElementSetMessagingTimeout(system, AX_TIMEOUT)
        element = _attr(system, "AXFocusedUIElement")
        if element is None:
            return None, "no focused element"
        AX.AXUIElementSetMessagingTimeout(element, AX_TIMEOUT)
        selection = _attr(element, "AXSelectedTextRange")
        selected = _attr(element, "AXSelectedText")
        role = _attr(element, "AXRole")
        if selection is None or not selected:
            return None, f"no selection in focused {role}"
        offsets = align(text, str(selected))
        if not offsets:
            return None, f"selection in {role} is different text"
        err, pid = AX.AXUIElementGetPid(element, None)
        if err:
            return None, "no process for element"
        return (element, pid, _range(selection)[0], offsets), None
    except Exception as exc:
        return None, f"error {exc!r}"


class DocumentHighlighter:
    """Draws a highlight over the spoken word in the app it was selected in."""

    def __init__(self):
        self.window = None
        self.text = None
        self.target = None        # (element, pid, selection start, offsets)
        self.span = None
        self.searches = 0         # bumped per reading, to drop stale answers

    def attach(self, text, found):
        """Find the selection that text was read from, if the app exposes it.

        Called as reading starts, while the text is still selected. Asks off
        the main thread and keeps asking for a while: when reading is started
        from a Services hotkey, the app is often still busy handling the
        Service and doesn't answer the first time. found() is called on the
        main thread with whether the selection was located.

        A replay of the same text keeps the earlier target, since by then the
        user may have clicked elsewhere.
        """
        self.searches += 1
        if text == self.text and self.target:
            found(True)
            return
        self.text, self.target, self.span = text, None, None
        if not ax_available():
            found(False)
            return
        search = self.searches

        def look():
            deadline, tries = time.time() + FIND_FOR, 0
            while True:
                tries += 1
                target, why = locate_selection(text)
                if target or time.time() > deadline:
                    break
                time.sleep(0.1)
            AppHelper.callAfter(self.located, search, target, why, tries, found)

        threading.Thread(target=look, daemon=True).start()

    def located(self, search, target, why, tries, found):
        if search != self.searches:
            return                # a newer reading started meanwhile
        if target is None:
            log(f"highlight off: {why} (asked {tries} times)")
            found(False)
            return
        if tries > 1:
            log(f"highlight: selection found on try {tries}")
        self.target = target
        found(True)
        self.refresh()

    def show(self, s, e):
        self.span = (s, e)
        self.refresh()

    def clear(self):
        self.span = None
        self.hide()

    def refresh(self):
        """Reposition over the current word, following scrolls and moves."""
        rect = self.locate()
        if rect is None:
            self.hide()
            return
        if self.window is None:
            self.window = self.make_window()
        self.window.setFrame_display_(rect, True)
        self.window.orderFrontRegardless()

    def locate(self):
        if not self.target or not self.span:
            return None
        element, pid, base, (starts, ends) = self.target
        s, e = self.span
        if e - 1 >= len(ends) or starts[s] is None or ends[e - 1] is None:
            return None
        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        if front is None or front.processIdentifier() != pid:
            return None           # user switched away; don't paint over it
        loc, length = base + starts[s], ends[e - 1] - starts[s]
        try:
            visible = _attr(element, "AXVisibleCharacterRange")
            if visible is not None:
                vloc, vlen = _range(visible)
                if loc < vloc or loc + length > vloc + vlen:
                    return None   # scrolled out of view
            query = AX.AXValueCreate(AX.kAXValueCFRangeType, (loc, length))
            err, value = AX.AXUIElementCopyParameterizedAttributeValue(
                element, "AXBoundsForRange", query, None)
            if err or value is None:
                return None
            ok, r = AX.AXValueGetValue(value, AX.kAXValueCGRectType, None)
        except Exception:
            return None
        if not ok or r.size.width <= 0 or r.size.height <= 0:
            return None
        # Accessibility measures from the top of the primary screen, AppKit
        # from the bottom.
        top = NSScreen.screens()[0].frame().size.height
        pad = 2
        return NSMakeRect(r.origin.x - pad, top - r.origin.y - r.size.height - pad,
                          r.size.width + 2 * pad, r.size.height + 2 * pad)

    def make_window(self):
        w = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 1, 1), NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered, False)
        w.setOpaque_(False)
        w.setBackgroundColor_(NSColor.clearColor())
        w.setHasShadow_(False)
        w.setIgnoresMouseEvents_(True)
        w.setReleasedWhenClosed_(False)
        w.setLevel_(NSFloatingWindowLevel)
        w.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces
                                 | NSWindowCollectionBehaviorTransient
                                 | NSWindowCollectionBehaviorIgnoresCycle)
        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 1))
        view.setWantsLayer_(True)
        # Yellow rather than blue, so it stands out against the selection.
        view.layer().setBackgroundColor_(
            NSColor.systemYellowColor().colorWithAlphaComponent_(0.45).CGColor())
        view.layer().setCornerRadius_(3)
        w.setContentView_(view)
        return w

    def hide(self):
        if self.window is not None:
            self.window.orderOut_(None)


class KokoroPlayerTarget(NSObject):
    """Receives button clicks, window close and timers for a Player."""

    def initWithPlayer_(self, player):
        self = objc.super(KokoroPlayerTarget, self).init()
        if self is None:
            return None
        self.player = player
        return self

    def prev_(self, _):
        self.player.command("PREV")

    def toggle_(self, _):
        self.player.play_pressed()

    def next_(self, _):
        self.player.command("NEXT")

    def windowShouldClose_(self, _):
        self.player.close()
        return False

    def settings_(self, sender):
        self.player.toggle_settings(sender)

    def popoverDidClose_(self, _):
        self.player.give_back_focus()

    def voice_(self, sender):
        self.player.set_voice(sender.selectedItem().representedObject())

    def speed_(self, sender):
        self.player.set_speed(SPEEDS[int(round(sender.doubleValue()))])

    def refresh_(self, _):
        self.player.highlighter.refresh()


def _symbol(name, label, size):
    image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, label)
    config = NSImageSymbolConfiguration.configurationWithPointSize_weight_(
        size, NSFontWeightRegular)
    return image.imageWithSymbolConfiguration_(config)


def _settings_symbol():
    """A speaker with a small gear, like Read Aloud's settings button."""
    speaker = _symbol("speaker.wave.2.fill", "Voice and speed", 17)
    gear = _symbol("gearshape.fill", None, 9)
    size = (speaker.size().width + 7, speaker.size().height + 5)

    def draw(rect):
        speaker.drawInRect_(((0, 5), speaker.size()))
        gear.drawInRect_(((size[0] - gear.size().width, 0), gear.size()))
        return True

    image = NSImage.imageWithSize_flipped_drawingHandler_(size, False, draw)
    image.setTemplate_(True)          # tinted like the other buttons
    return image


class Player:
    """The floating controls, and the glue from daemon events to highlights.

    send is called with a daemon command ("TOGGLE", "NEXT", ...). cfg is the
    menu bar app's settings dict (VOICE, SPEED), and save writes it out.
    """

    def __init__(self, send, cfg, save):
        self.send, self.cfg, self.save = send, cfg, save
        self.show_panel = True
        self.highlight = True
        self.target = KokoroPlayerTarget.alloc().initWithPlayer_(self)
        self.highlighter = DocumentHighlighter()
        self.panel = None
        self.id = None
        self.text = ""
        self.spans = []
        self.sentence = None
        self.word = None
        self.u16 = [0]            # UTF-16 offset of each index in self.text
        self.marks = []           # ranges painted in the panel, to undo
        self.full_height = HEIGHT # panel content height when showing text
        self.compact = False
        self.active = False       # an utterance is loaded, playing or paused
        self.playing = False
        self.ticker = None
        self.settings = None      # the voice and speed popover
        self.return_to = None     # app to hand focus back to after it

    # --- daemon events -------------------------------------------------
    def handle(self, ev):
        kind = ev.get("ev")
        if kind == "start":
            self.begin(ev)
        elif kind == "gone":
            if self.active:
                self.finish()
        elif ev.get("id") != self.id:
            return                # a superseded utterance winding down
        elif kind == "sentence":
            self.show_sentence(ev["i"])
        elif kind == "word":
            self.show_word(ev["s"], ev["e"])
        elif kind == "state":
            self.set_playing(not ev["paused"])
        elif kind == "end":
            self.finish()

    def begin(self, ev):
        self.id, self.text, self.spans = ev["id"], ev["text"], ev["spans"]
        self.active = True
        self.highlighter.clear()
        self.u16 = [0]
        for ch in self.text:
            self.u16.append(self.u16[-1] + (2 if ord(ch) > 0xFFFF else 1))
        self.sentence = self.word = None
        if self.show_panel or self.visible():
            self.ensure_panel()
            # Guess the last reading's layout until we know whether the
            # document can show the words itself; usually it's the same app.
            self.fit(compact=self.compact and self.highlight)
            self.load_text()
            self.panel.orderFrontRegardless()
        if self.highlight:
            self.highlighter.attach(self.text, self.document_found)
        else:
            self.document_found(False)
        self.set_playing(True)
        self.show_sentence(0)
        if self.ticker is None:
            self.ticker = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                REFRESH, self.target, "refresh:", None, True)

    def document_found(self, found):
        """Hide the panel's copy of the text if the document is showing it."""
        if self.active and self.panel is not None and found != self.compact:
            self.fit(compact=found)

    def finish(self):
        """Reading ended. The panel stays open, ready for the next selection."""
        self.active = False
        self.set_playing(False)
        self.highlighter.clear()
        self.sentence = self.word = None
        self.paint()
        if self.panel is not None:
            self.panel.setTitle_("Kokoro")
        if self.ticker is not None:
            self.ticker.invalidate()
            self.ticker = None

    # --- controls ------------------------------------------------------
    def command(self, cmd):
        self.send(cmd)

    def play_pressed(self):
        """Pause, or read: the new selection if there is one, as Word does."""
        if self.settings is not None and self.settings.isShown():
            self.settings.close()           # also hands focus back
        if self.playing:
            self.send("TOGGLE")
            return
        # Finding the selection can mean waiting on another app; not here.
        threading.Thread(target=self.play_selection, daemon=True).start()

    def play_selection(self):
        # Wait for the document's app to be frontmost again, or we would be
        # asking ourselves what is selected.
        me = NSRunningApplication.currentApplication().processIdentifier()
        for _ in range(25):
            front = NSWorkspace.sharedWorkspace().frontmostApplication()
            if front is None or front.processIdentifier() != me:
                break
            time.sleep(0.02)
        text = selected_text()
        if text.strip() and not _same(text, self.text):
            self.say(text)
        elif self.active:
            self.send("TOGGLE")             # resume where it paused
        elif self.text:
            self.say(self.text)             # read the last text again

    def say(self, text):
        self.send(f"SAY {self.cfg['VOICE']} {self.cfg['SPEED']} {text}")

    def toggle_settings(self, button):
        if self.settings is None:
            self.settings = self.make_settings()
        if self.settings.isShown():
            self.settings.close()
            return
        # Using the popover's controls makes this app active; remember where
        # the user was so their document gets focus back afterwards.
        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        me = NSRunningApplication.currentApplication()
        if front is not None and front.processIdentifier() != me.processIdentifier():
            self.return_to = front
        edge = NSMaxYEdge if button.isFlipped() else NSMinYEdge   # below it
        self.settings.showRelativeToRect_ofView_preferredEdge_(
            button.bounds(), button, edge)

    def give_back_focus(self):
        app, self.return_to = self.return_to, None
        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        me = NSRunningApplication.currentApplication().processIdentifier()
        # NSApp.isActive() can still say False here, so ask the system.
        if app is None or front is None or front.processIdentifier() != me:
            return
        if hasattr(NSApp, "yieldActivationToApplication_"):    # macOS 14+
            NSApp.yieldActivationToApplication_(app)
        app.activateWithOptions_(0)

    def set_voice(self, voice):
        self.cfg["VOICE"] = voice
        self.settings_changed()

    def set_speed(self, speed):
        self.cfg["SPEED"] = speed
        if self.settings is not None:
            self.speed_label.setStringValue_(f"{float(speed):g}×")
        self.settings_changed()

    def settings_changed(self):
        self.save()
        if self.active:
            self.send(f"SET {self.cfg['VOICE']} {self.cfg['SPEED']}")

    def open(self):
        """Show the panel without reading anything, e.g. from the menu."""
        self.ensure_panel()
        if not self.active:
            self.fit(compact=False)
            self.load_text()
        self.panel.orderFrontRegardless()

    def visible(self):
        return self.panel is not None and self.panel.isVisible()

    def close(self):
        """The panel's close button stops reading, as in Word."""
        if self.active:
            self.send("STOP")
        self.highlighter.clear()
        if self.panel is not None:
            self.panel.orderOut_(None)

    def set_options(self, show_panel, highlight):
        self.show_panel, self.highlight = show_panel, highlight
        if not highlight:
            self.highlighter.clear()

    # --- drawing -------------------------------------------------------
    def set_playing(self, playing):
        self.playing = playing
        if self.panel is None:
            return
        name, label = ("pause.fill", "Pause") if playing else ("play.fill", "Play")
        self.play_button.setImage_(_symbol(name, label, 22))
        self.play_button.setToolTip_(label)

    def show_sentence(self, i):
        if not (0 <= i < len(self.spans)):
            return
        self.sentence, self.word = i, None
        if self.panel is not None:
            self.panel.setTitle_(f"Kokoro  ·  {i + 1} of {len(self.spans)}")
        self.paint()

    def show_word(self, s, e):
        self.word = (s, e)
        if self.highlight:
            self.highlighter.show(s, e)
        self.paint()

    def fit(self, compact):
        """Show the text, or shrink to the buttons, keeping the top edge put."""
        self.compact = compact
        panel = self.panel
        content = panel.contentRectForFrameRect_(panel.frame())
        if compact:
            if content.size.height > COMPACT:
                self.full_height = content.size.height
            height = COMPACT
            panel.setContentMinSize_((MIN_WIDTH, COMPACT))
            panel.setContentMaxSize_((4000, COMPACT))
        else:
            height = max(self.full_height, 140)
            panel.setContentMinSize_((MIN_WIDTH, 140))
            panel.setContentMaxSize_((4000, 4000))
        self.scroll.setHidden_(compact)
        if height != content.size.height:
            top = content.origin.y + content.size.height
            content = NSMakeRect(content.origin.x, top - height,
                                 content.size.width, height)
            panel.setFrame_display_(panel.frameRectForContentRect_(content), True)
        if not compact:
            # Shrinking squashed the text area to nothing; lay it out again.
            self.scroll.setFrame_(NSMakeRect(12, 10, content.size.width - 24,
                                             height - 60))

    def load_text(self):
        """Put the whole selection in the panel; reading then marks it in place."""
        color = NSColor.labelColor() if self.text else NSColor.secondaryLabelColor()
        attrs = {NSFontAttributeName: NSFont.systemFontOfSize_(14),
                 NSForegroundColorAttributeName: color}
        self.text_view.textStorage().setAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(
                self.text or HINT, attrs))
        self.marks = []
        self.text_view.scrollRangeToVisible_(NSMakeRange(0, 0))

    def ns_range(self, s, e):
        return NSMakeRange(self.u16[s], self.u16[e] - self.u16[s])

    def paint(self):
        """Tint the sentence being read and mark the word being heard."""
        if self.panel is None:
            return
        storage = self.text_view.textStorage()
        storage.beginEditing()
        for r in self.marks:
            storage.removeAttribute_range_(NSBackgroundColorAttributeName, r)
            storage.addAttribute_value_range_(
                NSForegroundColorAttributeName, NSColor.labelColor(), r)
        self.marks = []
        focus = None
        if self.sentence is not None:
            focus = self.ns_range(*self.spans[self.sentence])
            storage.addAttribute_value_range_(
                NSBackgroundColorAttributeName,
                NSColor.systemYellowColor().colorWithAlphaComponent_(0.18), focus)
            self.marks.append(focus)
        if self.word is not None:
            focus = self.ns_range(*self.word)
            storage.addAttribute_value_range_(
                NSBackgroundColorAttributeName, NSColor.systemYellowColor(), focus)
            storage.addAttribute_value_range_(
                NSForegroundColorAttributeName, NSColor.blackColor(), focus)
            self.marks.append(focus)
        storage.endEditing()
        if focus is not None:
            self.follow(focus)

    def follow(self, rng):
        """Scroll so what is being read sits a third of the way down.

        Only when it has drifted out of the upper part of the view, so the
        text does not twitch on every word.
        """
        view = self.text_view
        layout = view.layoutManager()
        glyphs = layout.glyphRangeForCharacterRange_actualCharacterRange_(rng, None)
        if isinstance(glyphs, tuple):
            glyphs = glyphs[0]
        rect = layout.boundingRectForGlyphRange_inTextContainer_(
            glyphs, view.textContainer())
        clip = view.enclosingScrollView().contentView()
        visible = clip.documentVisibleRect()
        top, height = visible.origin.y, visible.size.height
        if top <= rect.origin.y and rect.origin.y + rect.size.height <= top + height * 0.75:
            return
        y = max(0, min(rect.origin.y - height / 3, view.frame().size.height - height))
        clip.scrollToPoint_((0, y))
        view.enclosingScrollView().reflectScrolledClipView_(clip)

    def make_settings(self):
        """The popover behind the speaker button: a speed slider and voices."""
        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 240, 128))

        def label(text, frame, secondary=False):
            field = NSTextField.labelWithString_(text)
            field.setFrame_(frame)
            if secondary:
                field.setTextColor_(NSColor.secondaryLabelColor())
                field.setAlignment_(NSTextAlignmentRight)
            view.addSubview_(field)
            return field

        label("Reading speed", NSMakeRect(16, 100, 150, 17))
        self.speed_label = label(f"{float(self.cfg['SPEED']):g}×",
                                 NSMakeRect(170, 100, 54, 17), secondary=True)
        slider = NSSlider.alloc().initWithFrame_(NSMakeRect(14, 72, 212, 24))
        slider.setMinValue_(0)
        slider.setMaxValue_(len(SPEEDS) - 1)
        slider.setNumberOfTickMarks_(len(SPEEDS))
        slider.setAllowsTickMarkValuesOnly_(True)
        slider.setContinuous_(False)       # re-voice once, on release
        if self.cfg["SPEED"] in SPEEDS:
            slider.setDoubleValue_(SPEEDS.index(self.cfg["SPEED"]))
        slider.setTarget_(self.target)
        slider.setAction_("speed:")
        view.addSubview_(slider)

        label("Voice", NSMakeRect(16, 44, 150, 17))
        voices = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(12, 12, 216, 26), False)
        for group, names in VOICES.items():
            voices.menu().addItem_(NSMenuItem.sectionHeaderWithTitle_(group))
            for name in names:
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    name.split("_", 1)[1].capitalize(), None, "")
                item.setRepresentedObject_(name)
                item.setIndentationLevel_(1)
                voices.menu().addItem_(item)
        index = voices.indexOfItemWithRepresentedObject_(self.cfg["VOICE"])
        if index >= 0:
            voices.selectItemAtIndex_(index)
        voices.setTarget_(self.target)
        voices.setAction_("voice:")
        view.addSubview_(voices)

        controller = NSViewController.alloc().init()
        controller.setView_(view)
        popover = NSPopover.alloc().init()
        popover.setContentViewController_(controller)
        popover.setContentSize_(view.frame().size)
        popover.setBehavior_(NSPopoverBehaviorTransient)
        popover.setDelegate_(self.target)
        return popover

    def ensure_panel(self):
        if self.panel is not None:
            return
        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                 | NSWindowStyleMaskResizable | NSWindowStyleMaskUtilityWindow
                 | NSWindowStyleMaskHUDWindow | NSWindowStyleMaskNonactivatingPanel)
        visible = NSScreen.mainScreen().visibleFrame()
        frame = NSMakeRect(visible.origin.x + visible.size.width - WIDTH - 24,
                           visible.origin.y + visible.size.height - HEIGHT - 24,
                           WIDTH, HEIGHT)
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, NSBackingStoreBuffered, False)
        panel.setTitle_("Kokoro")
        panel.setFloatingPanel_(True)
        panel.setLevel_(NSFloatingWindowLevel)
        # Clicking a button must not pull focus from the document being read,
        # or its selection (and our highlight) would be lost.
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setHidesOnDeactivate_(False)      # this app is never active
        panel.setReleasedWhenClosed_(False)
        panel.setMovableByWindowBackground_(True)
        panel.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces
                                     | NSWindowCollectionBehaviorFullScreenAuxiliary)
        panel.setDelegate_(self.target)
        content = panel.contentView()

        top = HEIGHT - 44
        mid = WIDTH / 2
        for x, symbol, label, action in (
                (mid - 70, "backward.fill", "Previous sentence", "prev:"),
                (mid - 20, "pause.fill", "Pause", "toggle:"),
                (mid + 30, "forward.fill", "Next sentence", "next:")):
            button = NSButton.alloc().initWithFrame_(NSMakeRect(x, top, 40, 36))
            button.setBordered_(False)
            button.setImagePosition_(NSImageOnly)
            button.setImage_(_symbol(symbol, label, 22 if action == "toggle:" else 18))
            button.setContentTintColor_(NSColor.labelColor())
            button.setToolTip_(label)
            button.setTarget_(self.target)
            button.setAction_(action)
            button.setAutoresizingMask_(NSViewMinXMargin | NSViewMaxXMargin
                                        | NSViewMinYMargin)
            content.addSubview_(button)
            if action == "toggle:":
                self.play_button = button

        button = NSButton.alloc().initWithFrame_(NSMakeRect(WIDTH - 48, top, 40, 36))
        button.setBordered_(False)
        button.setImagePosition_(NSImageOnly)
        button.setImage_(_settings_symbol())
        button.setContentTintColor_(NSColor.labelColor())
        button.setToolTip_("Voice and speed")
        button.setTarget_(self.target)
        button.setAction_("settings:")
        button.setAutoresizingMask_(NSViewMinXMargin | NSViewMinYMargin)
        content.addSubview_(button)

        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(12, 10, WIDTH - 24, top - 16))
        scroll.setDrawsBackground_(False)
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        size = scroll.contentSize()
        text_view = NSTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, size.width, size.height))
        text_view.setEditable_(False)
        text_view.setSelectable_(False)
        text_view.setDrawsBackground_(False)
        text_view.setVerticallyResizable_(True)
        text_view.setHorizontallyResizable_(False)
        text_view.setAutoresizingMask_(NSViewWidthSizable)
        text_view.textContainer().setWidthTracksTextView_(True)
        scroll.setDocumentView_(text_view)
        content.addSubview_(scroll)
        self.scroll = scroll
        self.text_view = text_view

        # Restore the saved frame only now, so it resizes the views above
        # rather than leaving them laid out for the default size.
        panel.setFrameAutosaveName_("KokoroPlayerText")
        saved = panel.contentRectForFrameRect_(panel.frame()).size.height
        if saved > COMPACT:
            self.full_height = saved
        self.panel = panel
        self.set_playing(self.playing)
