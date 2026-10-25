# Mac reading panel and highlighting

Install with the [macOS steps](../README.md#mac) first.

## Playback controls and highlighting

While it reads, a floating panel shows rewind, play/pause and forward buttons,
where you are ("3 of 12", in its title), and, unless the document is already
showing it, the text being read. Rewind goes to the start of the current
sentence, or to the previous one if you are less than a second and a half in.

Like Word's Read Aloud, the panel stays open. Select other text in any app and
press play to read that instead; with nothing new selected, play resumes or
reads the last text again. Open it without reading anything from Open Reading
Panel in the menu. Closing it stops reading. To keep it from opening by
itself when you use the hotkey, untick Show Panel When Reading.

The speaker button opens voice and speed. Changes are saved for next time and
apply straight away: the current sentence starts again in the new voice.

Play finds your selection through Accessibility (see below). For apps that
don't report it, it presses Copy for you and then puts your clipboard back.

Kokoro reports when each word starts, so the daemon knows which word you are
hearing. With Highlight Words in Document on, the menu bar app also draws a
yellow marker over that word in the app you selected it from, the way Word's
Read Aloud does. It finds the word through macOS Accessibility, which needs two
things:

- Permission. Choosing the menu item the first time opens the system prompt;
  allow Python under System Settings > Privacy & Security > Accessibility.
  This grants it to the Python interpreter the app runs under, so any script
  run by that interpreter gets it too.
- An app that reports where its text is on screen. Word, TextEdit, Pages and
  most native text views do. Browsers mostly do not, and text read from the
  clipboard has no document to point at. In those cases only the panel
  highlights.

The marker follows scrolling and hides when you switch to another app or
scroll the word out of view. If the text in the app no longer matches what
was selected, it stays off rather than marking the wrong words.

When the marker is working, the words are already highlighted in your
document, so the panel shrinks to just its buttons. When it isn't, the panel
shows the whole text with the sentence and word being read marked in it.

Voice and speed live in `~/.config/kokoro-tts.conf`. The menu bar app loads them
at startup. Restart the app after editing this file by hand. Changes made in
the app take effect immediately.

