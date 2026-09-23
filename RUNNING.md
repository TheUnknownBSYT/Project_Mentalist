# Run and keep updated

1. Extract to a permanent folder. Keep your existing `.scanner` folder when updating: it contains recorded forecasts and learned coefficients. Keep the same browser and http://127.0.0.1:8765 address to retain your local portfolio. Export a backup first.
2. Run the Mac/Windows launcher, or `python3 server.py --open` (Windows: `py server.py --open`). Do not run two copies on the same port.
3. Open **My portfolio → Set share quantities** and enter exact quantities from your broker. Previously reported holding values do not imply quantities or purchase dates. No precise updated valuation is possible without quantities.
4. Quotes are checked every 60 seconds for your holdings and shortlist. The UI reads updates every 15 seconds. The feed may be delayed; the quote timestamp is displayed. A failed refresh retains the last quote with a warning. Verify the timestamp, price, previous close and share count against your broker.
5. Full scans repeat every 30 minutes, reusing cached histories and scores. Completed daily candles drive forecasts; intraday quotes do not train the model. Today's candle becomes eligible after 16:00 IST, allowing a buffer after normal trading hours; this is not an exchange holiday calendar. Missing or partial candles are excluded.
6. The browser can close. The Python process and internet connection must remain active. Sleeping/shut-down computers cannot fetch data. On restart the model evaluates pending forecasts from downloaded history. Keep `.scanner` backed up; do not share it publicly.

## Automatic startup

Stop the foreground launcher first. On Mac run `python3 background.py install`; it creates a login service and starts it now. Remove with `python3 background.py remove`. Logs are in `.scanner/service.log` and `.scanner/service-error.log`.

On Windows run `py background.py install`; it starts now and at your next login. Remove with `py background.py remove`, then stop the existing Python server in Task Manager. Both options require the computer to stay awake and the folder to remain in place. These installers are provided for your device; they are not installed by downloading this ZIP.

## Always-on Linux machine

Use an existing private Linux machine/VPS with Python 3.10+. Copy the folder and `.scanner` state. Create `~/.config/systemd/user/mentalist.service` with the following, replacing paths with actual absolute paths:

```
[Unit]
Description=Mentalist market research
After=network-online.target
[Service]
WorkingDirectory=/absolute/path/Project_Mentalist
ExecStart=/usr/bin/python3 /absolute/path/Project_Mentalist/server.py
Restart=on-failure
RestartSec=30
[Install]
WantedBy=default.target
```

Run `systemctl --user daemon-reload` then `systemctl --user enable --now mentalist`. Your administrator may need to enable user lingering for it to survive logout. Access privately with `ssh -L 8765:127.0.0.1:8765 user@host`, then open the usual local address. Do not expose this unauthenticated single-user app to the internet. Portfolio storage remains in your browser; opening the page registers your holdings for the server quote watch. Defaults cover the five original holding symbols.

## What “learning” means

Two regression models estimate returns over 5 and 21 trading sessions. Inputs are past returns, relative strength, moving-average distance, volatility, volume and drawdown. It does not read news or financial statements. Existing predictions remain immutable. Only completed outcomes update coefficients, once each. Each new forward outcome reduces the accumulated influence of older training examples by 0.5%, so historical warm-up does not dominate indefinitely. Historical warm-up is excluded from forward accuracy.

Model results compares actual prediction errors with a no-price-change baseline. Improving the coefficients does not guarantee improving forecasts. Small samples, correlated stocks and market changes can make apparent improvement unreliable. A high technical score is not a buy instruction. No order is placed.
