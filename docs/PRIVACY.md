# Privacy policy

This program will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it.

The connections the program makes are all part of features the user turns on or uses:

| Service | When | Data sent |
|---|---|---|
| [LRCLIB](https://lrclib.net) | To fetch lyrics for the song currently playing | Track title, artist, album and duration |
| Spotify (`accounts.spotify.com`, `api.spotify.com`) | Only in *Spotify account* mode, after the user enters their own Client ID and logs in | OAuth requests and the user's access token, to read the current track |
| Twitch (`id.twitch.tv`, `irc.chat.twitch.tv`) | Only if the user turns on the chat bot for Twitch and connects their account | OAuth login, then the bot reads the user's own channel chat and sends replies to chat commands |
| Google / YouTube (`accounts.google.com`, `oauth2.googleapis.com`, `www.googleapis.com`) | Only if the user turns on the chat bot for YouTube with their own Google OAuth client and logs in | OAuth login, then the bot checks whether the user's channel is live, reads its live chat and sends replies to chat commands |
| Euler Stream (`ws.eulerstream.com`), a third-party bridge to TikTok LIVE | Only if the user turns on the TikTok listener and enters their own Euler Stream API key | The user's TikTok username and API key, to receive chat messages from the user's own TikTok LIVE. Nothing is sent to TikTok chat |
| GitHub (`api.github.com`) | Only if the user turns on *new version notifications* (off by default), once a day | A request for the latest release, with no user data |

- The program has no telemetry, analytics or crash reporting. Fonts are bundled, so no font service is contacted.
- Errors are written to a local log file (`%APPDATA%\SpotifyNowPlaying\app.log`) that is never uploaded.
- The local web server listens on `127.0.0.1` only, so it cannot be reached from other devices.
- Settings, login tokens (Spotify, Twitch, Google), API keys, the lyrics cache, the song history and the song request queue are stored only on the user's PC, in `%APPDATA%\SpotifyNowPlaying\`.
- The installer does not need administrator rights and does not change system configuration. The optional *run at Windows startup* setting adds a per-user `Run` registry value, which the uninstaller removes. Uninstalling it through Windows *Settings → Apps* removes the program.

Use of LRCLIB and Spotify is subject to their own privacy policies.
