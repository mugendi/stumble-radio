# Voice announcements: the built-in announcer

[← Stumble Radio](../README.md)

A Stumble Radio installation can speak on its own. Two announcer voices, Alan
(male) and Jenny (female), are synthesised locally with
[Piper](https://github.com/OHF-Voice/piper1-gpl): no speech-service account, no
cloud upload, no microphone.

Announcements are still ordinary clips in your
[voice library](podmoro.md#set-up-your-voice-library). The announcer only
generates the WAV files for command folders you have not filled yourself, and
the radio dips while they play.

## What happens on first launch

- `piper-tts` ships with the app, so there is nothing to install.
- At startup a background worker downloads the chosen announcer voice (about
  60–80 MB per voice, English `en_GB` medium quality) into
  `<data dir>/piper` and warms the speech engine.
- Every default command folder that is still empty is filled with generated
  clips. A folder that already holds anything you added is left alone.
- Downloads need a network connection. Offline installs fall back to the
  visual reminders; cached voices keep working offline.

## Switching the announcer

Press **Ctrl+P** and type "voices" (the palette entry reads
*Voices: announcer is Alan*). Choosing Jenny switches future announcements,
saves the choice, and downloads her voice files if needed. Clips already on
disk are not regenerated — delete the generated `tts-*.wav` files and restart
to remaster a folder with the new voice.

## Generated files

| Location | Contents |
| --- | --- |
| `<data dir>/pomodoro/audio/commands/<folder>/` | `tts-<hash>.wav` clips with a matching `.txt` caption next to each |
| `<data dir>/piper/` | announcer models (`en_GB-alan-medium.onnx[.json]`, `en_GB-jenny_dioco-medium.onnx[.json]`) |

Each command folder receives two phrasings so repeats feel less canned:

| Command folder | Generated phrasings |
| --- | --- |
| `focus-start` | "Focus time starting. See you when it is done." / "Ready to concentrate. I will tell you when focus ends." |
| `focus-ending` | "Focus wrapping up in a minute." / "Almost done. Tidy up your desk." |
| `short-break-start` | "Short break. Stretch your legs." / "Time for a short break." |
| `long-break-start` | "Long break. Step away for a while." / "Great work. Take a long break." |
| `break-ending` | "Break ending soon. Head back to the desk." / "Back to the desk in a minute." |
| `session-complete` | "Session complete. Well done." / "That is the session. Nice work." |
| `reminders/water` | "Time for a glass of water." / "Remember to hydrate." |
| `reminders/stretch` | "Stand up and stretch for a moment." / "Loosen up your shoulders." |
| `reminders/eyes` | "Rest your eyes for a moment." / "Look away from the screen briefly." |

Custom command folders generate the folder's label instead — `reminders/
mad-stretch` is spoken as "Mad stretch" — so name custom folders the way you
want to hear them.

## Rules worth knowing

- Announcements that fire while a folder is empty generate one clip on demand
  from the folder's own wording, as long as the voice is already available; a
  clip is never downloaded mid-announcement.
- Different announcements reuse the same WAV when the wording repeats; the
  hash in the filename prevents duplicates.
- Text is capped at 600 characters per clip and playback at 120 seconds
  (see [podmoro audio behaviour](podmoro.md#audio-sleep-and-recovery-behaviour)).
- Generated speech never enters recordings or Last Play Search, exactly like
  your own clips.
- Deleting all clips from a folder and restarting the app refills it. One
  manual clip in a folder disables generation for that folder.

Manual: [Podmoro voices and schedules](podmoro.md)
