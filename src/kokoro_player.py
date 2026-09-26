"""Playback controls and word highlighting for the speak-kokoro menu bar app.

Two views of the same daemon events:

- a floating panel with rewind / play-pause / forward, showing the whole
  text with the sentence and word being read marked, which works for any text
  (and shrinks to just the buttons when the document shows the words itself);
- an overlay drawn over the word in the document it came from, which needs
  Accessibility permission and an app that reports where its text is on
  screen (Word, TextEdit, Pages and most native text views do).

Everything here runs on the main thread. The menu bar app forwards daemon
events with AppHelper.callAfter.
"""
import unicodedata

import objc
from AppKit import (NSAttributedString, NSBackgroundColorAttributeName,
                    NSBackingStoreBuffered, NSButton, NSColor, NSFont,
                    NSFontAttributeName, NSFontWeightRegular,
                    NSForegroundColorAttributeName, NSImage, NSImageOnly,
                    NSImageSymbolConfiguration, NSPanel, NSScreen,
                    NSScrollView, NSTextAlignmentRight, NSTextField,
                    NSTextView, NSView, NSViewHeightSizable,
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

try:
    import ApplicationServices as AX
except ImportError:           # pyobjc-framework-ApplicationServices missing
    AX = None

WIDTH, HEIGHT = 400, 300
COMPACT = 48                  # panel content height with only the buttons
LINGER = 4.0                  # seconds the panel stays up after reading ends
REFRESH = 0.25                # seconds between overlay position checks
AX_TIMEOUT = 0.25             # never let a busy app stall the menu bar


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


def _attr(element, name):
    err, value = AX.AXUIElementCopyAttributeValue(element, name, None)
    return None if err else value


def _range(value):
    ok, rng = AX.AXValueGetValue(value, AX.kAXValueCFRangeType, None)
    return tuple(rng) if ok else None


class DocumentHighlighter:
    """Draws a highlight over the spoken word in the app it was selected in."""

    def __init__(self):
        self.window = None
        self.text = None
        self.target = None        # (element, pid, selection start, offsets)
        self.span = None

    def attach(self, text):
        """Find the selection that text was read from, if the app exposes it.

        Called as reading starts, while the text is still selected. A replay
        of the same text keeps the earlier target, since by then the user may
        have clicked elsewhere.
        """
        if text == self.text and self.target:
            return
        self.text, self.target, self.span = text, None, None
        if not ax_available():
            return
        try:
            element = _attr(AX.AXUIElementCreateSystemWide(), "AXFocusedUIElement")
            if element is None:
                return
            AX.AXUIElementSetMessagingTimeout(element, AX_TIMEOUT)
            selection = _attr(element, "AXSelectedTextRange")
            selected = _attr(element, "AXSelectedText")
            if selection is None or not selected:
                return
            offsets = align(text, selected)
            err, pid = AX.AXUIElementGetPid(element, None)
            if offsets and not err:
                self.target = (element, pid, _range(selection)[0], offsets)
        except Exception:
            self.target = None

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
        self.player.command("TOGGLE")

    def next_(self, _):
        self.player.command("NEXT")

    def windowShouldClose_(self, _):
        self.player.close()
        return False

    def linger_(self, _):
        self.player.linger_done()

    def refresh_(self, _):
        self.player.highlighter.refresh()


def _symbol(name, label, size):
    image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, label)
    config = NSImageSymbolConfiguration.configurationWithPointSize_weight_(
        size, NSFontWeightRegular)
    return image.imageWithSymbolConfiguration_(config)


class Player:
    """The floating controls, and the glue from daemon events to highlights.

    send is called with a daemon command ("TOGGLE", "NEXT", ...).
    """

    def __init__(self, send):
        self.send = send
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
        self.active = False       # an utterance is loaded, playing or paused
        self.playing = False
        self.linger = None
        self.ticker = None

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
        self.cancel_linger()
        if self.highlight:
            self.highlighter.attach(self.text)
        else:
            self.highlighter.clear()
        self.u16 = [0]
        for ch in self.text:
            self.u16.append(self.u16[-1] + (2 if ord(ch) > 0xFFFF else 1))
        self.sentence = self.word = None
        if self.show_panel:
            self.ensure_panel()
            # If the words are being marked in the document itself, a second
            # copy of the text in the panel is just a distraction.
            self.fit(compact=self.highlighter.target is not None)
            self.load_text()
            self.panel.orderFrontRegardless()
        self.set_playing(True)
        self.show_sentence(0)
        if self.ticker is None:
            self.ticker = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                REFRESH, self.target, "refresh:", None, True)

    def finish(self):
        self.active = False
        self.set_playing(False)
        self.highlighter.clear()
        self.sentence = self.word = None
        self.paint()
        if self.ticker is not None:
            self.ticker.invalidate()
            self.ticker = None
        if self.panel is not None and self.panel.isVisible():
            self.cancel_linger()
            self.linger = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                LINGER, self.target, "linger:", None, False)

    # --- controls ------------------------------------------------------
    def command(self, cmd):
        self.cancel_linger()
        self.send(cmd)

    def close(self):
        """The panel's close button stops reading, as in Word."""
        self.cancel_linger()
        if self.active:
            self.send("STOP")
        self.highlighter.clear()
        if self.panel is not None:
            self.panel.orderOut_(None)

    def linger_done(self):
        self.linger = None
        if not self.active and self.panel is not None:
            self.panel.orderOut_(None)

    def cancel_linger(self):
        if self.linger is not None:
            self.linger.invalidate()
            self.linger = None

    def set_options(self, show_panel, highlight):
        self.show_panel, self.highlight = show_panel, highlight
        if not show_panel and self.panel is not None:
            self.panel.orderOut_(None)
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
            self.counter.setStringValue_(f"{i + 1} / {len(self.spans)}")
        self.paint()

    def show_word(self, s, e):
        self.word = (s, e)
        if self.highlight:
            self.highlighter.show(s, e)
        self.paint()

    def fit(self, compact):
        """Show the text, or shrink to the buttons, keeping the top edge put."""
        panel = self.panel
        content = panel.contentRectForFrameRect_(panel.frame())
        if compact:
            if content.size.height > COMPACT:
                self.full_height = content.size.height
            height = COMPACT
            panel.setContentMinSize_((260, COMPACT))
            panel.setContentMaxSize_((4000, COMPACT))
        else:
            height = max(self.full_height, 140)
            panel.setContentMinSize_((260, 140))
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
        attrs = {NSFontAttributeName: NSFont.systemFontOfSize_(14),
                 NSForegroundColorAttributeName: NSColor.labelColor()}
        self.text_view.textStorage().setAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(self.text, attrs))
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

        counter = NSTextField.labelWithString_("")
        counter.setFrame_(NSMakeRect(WIDTH - 76, top + 9, 64, 18))
        counter.setAlignment_(NSTextAlignmentRight)
        counter.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(11, NSFontWeightRegular))
        counter.setTextColor_(NSColor.secondaryLabelColor())
        counter.setAutoresizingMask_(NSViewMinXMargin | NSViewMinYMargin)
        content.addSubview_(counter)
        self.counter = counter

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
