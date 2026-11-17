# bluelink-mcp

An [MCP](https://modelcontextprotocol.io) server that lets AI assistants such as Claude read and
control your Hyundai, Kia or Genesis vehicle: lock and unlock, remote climate, charging, status,
location and trips.

It wraps the open-source
[`hyundai_kia_connect_api`](https://github.com/Hyundai-Kia-Connect/hyundai_kia_connect_api) library
and runs on your own computer. Your credentials never leave your machine except to log in to
Hyundai or Kia.

> **Disclaimer.** This project is not affiliated with, endorsed by, or supported by Hyundai, Kia or
> Genesis. It uses unofficial, reverse-engineered APIs that the manufacturers can change or block at
> any time. Remote commands act on a real vehicle. Use it at your own risk.

## Requirements

- An active Bluelink / Kia Connect / Genesis Connected Services account.
- [uv](https://docs.astral.sh/uv/) (recommended), or Python 3.13 or later with `pip`.
- An MCP client that runs local servers: Claude Desktop, Claude Code, Cursor, VS Code, and others.

Claude on the web and mobile, ChatGPT and Grok cannot start a program on your computer, so they
cannot use this server.

## Configuration

The server reads these environment variables:

| Variable | Required | Description |
|---|---|---|
| `BLUELINK_USERNAME` | yes | Account email or username. |
| `BLUELINK_PASSWORD` | yes | Account password. |
| `BLUELINK_PIN` | Hyundai or Genesis in the USA | Remote-command PIN. |
| `BLUELINK_REGION` | yes | `USA`, `Canada`, `Europe`, `Australia`, `New Zealand`, `China`, `India` or `Brazil`. |
| `BLUELINK_BRAND` | yes | `Hyundai`, `Kia` or `Genesis`. |
| `BLUELINK_LANGUAGE` | no | Default `en`. |
| `BLUELINK_TOKEN_PATH` | no | Default `~/.bluelink-mcp/token.json`. |

Values are case-insensitive. The server also reads a `.env` file from the current working
directory; real environment variables take priority. See `.env.example`.

## Add it to your client

### Claude Desktop

1. Open **Settings → Developer → Edit Config**. This opens `claude_desktop_config.json`.
2. Add a `bluelink` entry inside `mcpServers`:

   ```json
   {
     "mcpServers": {
       "bluelink": {
         "command": "uvx",
         "args": ["bluelink-mcp"],
         "env": {
           "BLUELINK_USERNAME": "you@example.com",
           "BLUELINK_PASSWORD": "your-password",
           "BLUELINK_PIN": "0000",
           "BLUELINK_REGION": "USA",
           "BLUELINK_BRAND": "Hyundai"
         }
       }
     }
   }
   ```

3. Quit Claude Desktop completely and start it again.

### Claude Code

```
claude mcp add bluelink -e BLUELINK_USERNAME=you@example.com -e BLUELINK_PASSWORD=your-password -e BLUELINK_PIN=0000 -e BLUELINK_REGION=USA -e BLUELINK_BRAND=Hyundai -- uvx bluelink-mcp
```

### Without uv

Run `pip install bluelink-mcp`, then use `bluelink-mcp` as the command instead of `uvx`.

Then ask your assistant something like "Is my car locked?"

## Tools

The server registers only the tools that your region and brand support. It logs the list at
startup.

| Area | Tools |
|---|---|
| Vehicles and status | `list_vehicles`, `get_vehicle_status`, `get_location`, `get_trip_info_month`, `get_trip_info_day`, `check_action_status` |
| Doors | `lock`, `unlock`, `door_power_off`, `open_frunk` |
| Climate | `start_climate`, `stop_climate`, `start_pet_care`, `stop_pet_care`, `start_battery_conditioning`, `stop_battery_conditioning` |
| Charging (EV/PHEV) | `start_charge`, `stop_charge`, `set_charge_limits`, `set_charging_current`, `open_charge_port`, `close_charge_port`, `set_charge_alarm`, `set_v2l_discharge_limit` |
| Other | `start_hazard_lights`, `start_hazard_lights_and_horn`, `set_windows`, `start_valet_mode`, `stop_valet_mode`, `turn_off_lamp`, `stop_rear_seat_alarm`, `set_navigation` |
| Schedules | `schedule_charging_and_climate`, `schedule_reservation_charge`, `schedule_reservation_hvac`, `schedule_reservation_engine` |
| Login (OTP regions) | `send_otp`, `verify_otp` |

For example, Hyundai USA gets 15 tools: status, location, trips, lock and unlock, climate, charging,
and hazard lights and horn.

Each vehicle's `vehicle_id` is the last 6 characters of its VIN.

### Safety: `confirm=true`

These tools send nothing unless you pass `confirm=true`: `unlock`, `start_hazard_lights_and_horn`,
`open_charge_port`, `set_windows` (when a window opens), `start_valet_mode`, `stop_valet_mode`,
`open_frunk`, `door_power_off` and `set_v2l_discharge_limit`. Without it they return a message that
names the effect, so the assistant must ask you first. They also carry the MCP destructive hint.

`start_climate` is not guarded. On gas vehicles it starts the engine.

### One-time passcode (Kia USA and others)

Some regions need a one-time passcode at login. The assistant calls `send_otp` (email or SMS), you
give it the code, and it calls `verify_otp`.

## Token file

After login the server stores the session token in `~/.bluelink-mcp/token.json`, or in
`BLUELINK_TOKEN_PATH`. The file never holds your password or PIN, and only your user account can
read it. Delete the file to force a fresh login.

## Development

```
git clone https://github.com/gowthamand7/bluelink-mcp
cd bluelink-mcp
uv venv
uv pip install -e ".[dev]"
uv run pytest
```

## License

MIT. See [LICENSE](LICENSE).
