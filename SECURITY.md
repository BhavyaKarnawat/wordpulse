# Security

If you find a security problem in WordPulse, please **don't open a public issue**. Report it privately through GitHub's [private vulnerability reporting](https://github.com/BhavyaKarnawat/wordpulse/security/advisories/new) instead, with steps to reproduce.

You can expect a reply within a week. Fixes ship in a new release, and you'll be credited unless you'd rather not be.

## What WordPulse touches

- It runs as your user, with no admin rights.
- It reads the media session Windows shares (song title, artist, position, cover), and the audio that's playing for beat detection. Audio is analysed in memory and never saved or sent anywhere.
- It connects to LRCLIB (lyrics), MusicBrainz (genre tags) and Apple's iTunes search (cover art), sending only the song title and artist. It also connects to GitHub (update check, only if you turn it on).
- It writes only to `%APPDATA%\WordPulse` and `%USERPROFILE%\.wordpulse`, plus one registry value if you turn on Start with Windows.
