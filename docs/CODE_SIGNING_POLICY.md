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
5. The signed installer is published on [GitHub Releases](https://github.com/mohammadraflyy/spotify-now-playing/releases).

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
| Google Fonts | When an overlay or the settings page is opened in a browser or OBS | A standard font request from the browser |

- The program has no telemetry, analytics, crash reporting or automatic update check.
- The local web server listens on `127.0.0.1` only, so it cannot be reached from other devices.
- Settings and login tokens are stored only on the user's PC, in `%APPDATA%\SpotifyNowPlaying\config.json`.
- The installer does not need administrator rights and does not change system configuration. Uninstalling it through Windows *Settings → Apps* removes the program.

Use of LRCLIB and Spotify is subject to their own privacy policies.
