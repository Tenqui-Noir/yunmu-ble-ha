"""Constants for the experimental Yunmu BLE meter integration."""

DOMAIN = "yunmu_ble"

CONF_POLL_INTERVAL = "poll_interval"
DEFAULT_POLL_INTERVAL = 10  # Minutes; deliberately low traffic.
MIN_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 120

SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
NOTIFY_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"
WRITE_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"
RESPONSE_TIMEOUT = 8.0

MANUAL_READ_COOLDOWN_SECONDS = 30.0

PLATFORMS = ["button", "sensor"]
