# Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org).

This page describes how Windows releases of **Spotify Now Playing** are built and signed.

## What gets signed

- `SpotifyNowPlaying.exe`, the application
- `SpotifyNowPlaying-Setup-x.y.z.exe`, the installer

Only binaries built from this repository are signed. Third-party files bundled by PyInstaller (the Python runtime and `winrt` packages) keep their upstream signatures, or stay unsigned.

## How releases are built

1. A version tag `vX.Y.Z` is pushed to this repository.
2. GitHub Actions ([`.github/workflows/build.yml`](../.github/workflows/build.yml)) builds the app on a clean `windows-latest` runner, using [`build.ps1`](../build.ps1): PyInstaller for the app, then Inno Setup for the installer.
3. The build artifact is submitted to SignPath. SignPath verifies that it came from this repository's GitHub Actions workflow.
4. An approver manually approves the signing request.
5. The same workflow publishes the signed installer on [GitHub Releases](https://github.com/mohammadraflyy/spotify-now-playing/releases), with its SHA-256 in the release notes.

Locally built binaries are never signed.

Every binary carries the same metadata: product name `Spotify Now Playing`, with the product version taken from `spotify_now_playing/__init__.py`.

## Team roles

| Role | Members |
|---|---|
| Committers and reviewers | [mohammadraflyy](https://github.com/mohammadraflyy) |
| Approvers | [mohammadraflyy](https://github.com/mohammadraflyy) |

Changes from anyone outside the team, such as pull requests, are reviewed by a committer before they are merged. Build scripts and CI configuration (`build.ps1`, `installer.iss`, `scripts/`, `.github/`) get extra attention during review.

All team members use multi-factor authentication for GitHub and SignPath.

## Privacy policy

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
