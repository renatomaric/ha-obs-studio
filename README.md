# OBS Studio for Home Assistant

Switch OBS scenes and toggle sources from Home Assistant over the obs-websocket v5 protocol built into OBS 28 and newer.

## What you get

- `select.<name>_scene`: the current program scene. Pick an option to switch scenes.
- `switch.<name>_<scene>_<source>`: one switch per source in each scene, the same as the eye icon in OBS.

State updates are pushed from OBS, so changes made in OBS show up in Home Assistant right away. If OBS closes, the entities go unavailable and the integration reconnects every 10 seconds.

## Install

1. In OBS: Tools > WebSocket Server Settings, enable the server and note the port and password.
2. In HACS: Custom repositories, add this repository as an Integration, then download "OBS Studio".
3. Restart Home Assistant, then Settings > Devices & services > Add integration > OBS Studio.

## Tests

```bash
uv run --python 3.13 --with aiohttp --with pytest --with pytest-asyncio --no-project pytest tests/test_client.py
uv run --python 3.14 --with pytest-homeassistant-custom-component --no-project pytest tests/ha
```
