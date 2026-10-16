import asyncio
from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from .equalizer import BAND_FREQUENCIES, PRESETS, EqualizerSettings
from .models import clean
from .player import PlayerError


class EqualizerScreen(ModalScreen):
    BINDINGS: ClassVar = [("escape", "cancel", "Cancel"), ("ctrl+s", "save", "Save")]

    def __init__(self, settings: EqualizerSettings):
        super().__init__()
        self.original = settings
        self.preview_timer = None
        self.revision = 0
        self.closing = self.finished = False
        self.apply_lock = asyncio.Lock()

    def compose(self) -> ComposeResult:
        with Vertical(id="equalizer-dialog"):
            yield Label("Equalizer & gain", classes="dialog-title")
            with Horizontal(id="eq-options"):
                yield Checkbox("Bypass", not self.original.enabled, id="eq-bypass")
                yield Checkbox(
                    "Auto level", self.original.auto_level, id="eq-auto-level",
                    tooltip="Balance station loudness toward the target set by gain",
                )
                yield Select(
                    [(name, name) for name in (*PRESETS, "Custom")],
                    value=self.original.preset, allow_blank=False, id="eq-preset",
                    tooltip="EQ preset · changes bands only, keeping gain",
                )
            with VerticalScroll(id="eq-fields"):
                for index, hz in enumerate(BAND_FREQUENCIES):
                    label = f"{hz / 1000:g} kHz" if hz >= 1000 else f"{hz} Hz"
                    with Horizontal(classes="eq-row"):
                        yield Label(label)
                        yield Button("−", id=f"eq-minus-{index}", tooltip=f"Lower {label} by 1 dB")
                        yield Input(str(self.original.bands[index]), type="integer", id=f"eq-band-{index}")
                        yield Static("dB", classes="eq-unit")
                        yield Button("+", id=f"eq-plus-{index}", tooltip=f"Raise {label} by 1 dB")
                with Horizontal(classes="eq-row", id="eq-gain-row"):
                    yield Label("Gain / boost")
                    yield Button("−", id="eq-minus-gain", tooltip="Lower gain by 1 dB")
                    yield Input(str(self.original.gain_db), type="integer", id="eq-gain")
                    yield Static("dB", classes="eq-unit")
                    yield Button("+", id="eq-plus-gain", tooltip="Raise gain by 1 dB")
            yield Static(
                "Bands −12…+12 dB · Gain 0…+12 dB\n"
                "Auto maps Gain to −23…−11 LUFS · limiter protects peaks.",
                classes="muted", markup=False,
            )
            yield Static("", id="eq-error", markup=False)
            with Horizontal(classes="dialog-actions"):
                yield Button("Reset", id="eq-reset")
                yield Button("Save", variant="primary", id="eq-save")
                yield Button("Cancel", id="eq-cancel")

    def on_mount(self):
        self.query_one("#eq-error", Static).display = False
        self.query_one("#eq-band-0", Input).focus()

    def read_settings(self) -> EqualizerSettings:
        try:
            bands = tuple(int(self.query_one(f"#eq-band-{index}", Input).value) for index in range(5))
            gain = int(self.query_one("#eq-gain", Input).value)
        except ValueError as error:
            raise ValueError("Use whole numbers: bands −12…+12 dB; gain 0…+12 dB.") from error
        return EqualizerSettings(
            bands, gain, not self.query_one("#eq-bypass", Checkbox).value,
            self.query_one("#eq-auto-level", Checkbox).value,
        )

    def feedback(self, message: str = ""):
        error = self.query_one("#eq-error", Static)
        resized = error.display != bool(message)
        error.update(clean(message))
        error.display = bool(message)
        if resized and isinstance(self.app.focused, Input):
            self.call_after_refresh(
                self.app.focused.scroll_visible, animate=False, immediate=True
            )

    def queue_preview(self):
        if self.closing:
            return
        self.revision += 1
        if self.preview_timer:
            self.preview_timer.stop()
        revision = self.revision
        self.preview_timer = self.set_timer(
            0.2, lambda: self.run_worker(self.preview(revision), group="eq-preview")
        )

    async def preview(self, revision: int):
        async with self.apply_lock:
            if self.closing or revision != self.revision or not self.is_mounted:
                return
            try:
                settings = self.read_settings()
                await self.app.player.set_equalizer(settings)
            except (ValueError, PlayerError, OSError) as error:
                if revision == self.revision and not self.closing:
                    self.feedback(str(error))
            else:
                if revision == self.revision and not self.closing:
                    self.query_one("#eq-preset", Select).value = settings.preset
                    self.feedback()

    def on_input_changed(self, event: Input.Changed):
        event.stop()
        if self.closing:
            return
        self.queue_preview()

    def on_input_submitted(self, event: Input.Submitted):
        event.stop()
        self.queue_preview()

    def on_checkbox_changed(self, event: Checkbox.Changed):
        event.stop()
        self.queue_preview()

    def on_select_changed(self, event: Select.Changed):
        event.stop()
        if (
            self.closing or event.value not in PRESETS
            or event.value != self.query_one("#eq-preset", Select).value
        ):
            return
        for index, value in enumerate(PRESETS[event.value]):
            self.query_one(f"#eq-band-{index}", Input).value = str(value)
        self.queue_preview()

    async def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        key = event.button.id
        if key == "eq-save":
            await self.action_save()
        elif key == "eq-cancel":
            await self.action_cancel()
        elif key == "eq-reset":
            self.query_one("#eq-bypass", Checkbox).value = False
            self.query_one("#eq-auto-level", Checkbox).value = False
            self.query_one("#eq-gain", Input).value = "0"
            for index in range(5):
                self.query_one(f"#eq-band-{index}", Input).value = "0"
            self.queue_preview()
        elif key and key.startswith(("eq-minus-", "eq-plus-")):
            band = key.rsplit("-", 1)[1]
            field = self.query_one("#eq-gain" if band == "gain" else f"#eq-band-{band}", Input)
            try:
                value = int(field.value)
            except ValueError:
                value = 0
            delta = -1 if key.startswith("eq-minus-") else 1
            field.value = str(max(0 if band == "gain" else -12, min(12, value + delta)))

    async def finish(self, *, save: bool):
        if self.closing:
            return
        self.closing = True
        if self.preview_timer:
            self.preview_timer.stop()
        for control in self.query("Button, Input, Checkbox, Select"):
            control.disabled = True
        async with self.apply_lock:
            try:
                settings = self.read_settings() if save else self.original
                await self.app.player.set_equalizer(settings)
                if save:
                    await self.app.save_equalizer(settings)
            except (ValueError, PlayerError, OSError) as error:
                self.feedback(str(error))
                self.closing = False
                for control in self.query("Button, Input, Checkbox, Select"):
                    control.disabled = False
                return
            self.finished = True
            self.dismiss()

    async def action_save(self):
        await self.finish(save=True)

    async def action_cancel(self):
        await self.finish(save=False)

    async def on_unmount(self):
        self.closing = True
        if self.preview_timer:
            self.preview_timer.stop()
        if not self.finished and self.app.is_running:
            async with self.apply_lock:
                try:
                    await self.app.player.set_equalizer(self.original)
                except (PlayerError, OSError) as error:
                    self.app.notify(clean(str(error)), severity="warning", markup=False)
