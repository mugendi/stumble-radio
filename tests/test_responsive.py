from dataclasses import replace

from test_app import FakePlayer, OfflineAPI
from textual.widgets import Button, DataTable, Footer, Static

from stumble_radio.app import StumbleRadio


async def test_layout_bounds_and_scroll_survive_resizing(db, station, tmp_path):
    long_station = replace(
        station,
        name='BBC RADIO 1 ANTHEMS: All-day anthems from the 00s to now 日本語 🎵' * 2,
        country='The United Kingdom Of Great Britain And Northern Ireland',
        tags='jazz,soul,happy tunes' * 10,
    )
    db.upsert([
        replace(long_station, stationuuid=f'long-{i}', url=f'https://example.test/{i}', votes=i)
        for i in range(120)
    ])
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    async with app.run_test(size=(180, 45)) as pilot:
        app.current = long_station
        app.play_state = 'PLAYING'
        app.player.auto_level_state = 'active'
        app.player.auto_level_correction_db = 6.7
        app.update_pinned_station()
        table = app.query_one(DataTable)
        table.move_cursor(row=65)
        await pilot.pause()
        table.scroll_to(y=50, animate=False, force=True)
        await pilot.pause()
        assert table.scroll_y > 0
        selected = app.selected_station().stationuuid
        for width, height in ((180, 45), (120, 40), (80, 24), (60, 24), (40, 24), (180, 45)):
            await pilot.resize_terminal(width, height)
            await pilot.pause()
            pinned = app.query_one('#playing-station', Static)
            status = app.query_one('#status-line', Static)
            browser = app.query_one('#browser')
            actions = app.query_one('#table-actions')
            assert pinned.region.bottom == status.region.y
            assert table.region.right == app.query_one('#clear-filters').region.right
            assert table.region.bottom == app.query_one(Footer).region.y
            assert status.region.right <= browser.region.right
            assert not actions.region.overlaps(status.region)
            assert sum(c.width + 2 for c in table.ordered_columns) == table.size.width - 1
            assert app.selected_station().stationuuid == selected
            assert table.scroll_y > 0, (width, height)
            for button in app.default_screen.query(Button):
                if button.region.width and button.display:
                    assert 0 <= button.region.x < button.region.right <= width, (width, button.id, button.region)
            assert 'vol ' in str(status.content)
            assert 'Auto' in str(status.content)
            assert 'LUFS' in status.tooltip
