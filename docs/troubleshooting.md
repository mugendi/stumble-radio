# Troubleshooting

[← Stumble Radio](../README.md)

Start with `stumble-radio --doctor` to check executables and storage paths.

**`stumble-radio: command not found`**

Run `uv tool update-shell` or `pipx ensurepath`, then open a new terminal. Confirm
that the tool installation succeeded. The command is `stumble-radio`.

**No stations appear on first launch**

Allow the initial batch to arrive, press `s`, or enter filters and use `Online ↻`.
Check the status line for a directory connection failure. The cache starts empty;
there are no bundled pretend stations.

**Missing mpv or FFmpeg**

Run `stumble-radio --doctor`. Install the missing executable and ensure the terminal
running Stumble Radio can find it on `PATH`. FFmpeg alone is enough for recording,
but mpv is required for playback.

**A station fails or there is no sound**

Try a different station. Some listed streams are offline, restricted by location,
or temporarily unavailable. Check system volume and the TUI volume. To separate
audio-device problems from a stream problem, try `mpv 'STREAM_URL'` in a terminal.
The app uses mpv with `--no-config`, so user mpv scripts and settings do not affect it.

**Search finds fewer stations than expected**

Wait for catalogue sync or use `Online ↻` in Explore. Clear extra filters, try the
country's two-letter code, vary tag spelling, and check whether you enabled HTTPS,
bitrate, health, or geographic restrictions. Radius filtering cannot include
stations without coordinates.

**Recording fails**

Confirm FFmpeg is available, the destination is writable, and the disk has space.
Some stations reject a second connection or use an incompatible stream. The error
notification includes the end of FFmpeg's error output. Use a different station
to determine whether the problem is broadcaster-specific.

**A dialog is too tall or columns are cut off**

Enlarge the terminal, reduce its font size, or scroll. The advanced-search form
scrolls independently. The station table scrolls horizontally; narrow terminals
hide the sidebar, and the Library button still switches views.
For connection statuses and automatic retries, see [playback recovery](playback.md#reconnection-internet-outages-and-dead-streams). For missing or silent voice clips, follow [Podmoro sound setup](podmoro.md#set-up-your-voice-library).
