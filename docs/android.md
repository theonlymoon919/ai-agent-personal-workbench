# Android

The Android app is a small WebView shell for a user-selected AI Agent Personal Workbench HTTPS origin. Same-origin workbench navigation stays in the app; external HTTP(S) and custom-scheme links are handed to Android intents. The repository contains no production server address or signing key.

## Build a debug APK

Requirements:

- JDK 17
- Android SDK platform 35 and build-tools 35.0.0
- Gradle 8.11.1, or the Windows helper that downloads it

Windows:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_android.ps1
```

Linux/macOS with Gradle available:

```bash
cd mobile
gradle --no-daemon clean assembleDebug
```

The debug APK is generated under `mobile/app/build/outputs/apk/debug/`. APKs are ignored by Git and must not be committed.

## Install

Enable installation from the trusted file source on the Android device, install the debug or maintainer-signed release APK, verify the published SHA-256 checksum, open **Connection settings**, and enter the deployment's HTTPS origin. Alpha assets whose filename ends in `-debug.apk` use the standard Android debug signature; they are installable test builds, not maintainer-signed production releases. Do not use credentials from another person's workspace.

## Release signing model

Debug builds use the Android debug keystore. Official release builds must be signed outside Git with one of these models:

1. A maintainer's protected local keystore and password manager.
2. GitHub Actions encrypted secrets made available only to the protected tag workflow.

Recommended secret names are `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEY_ALIAS`, `ANDROID_KEYSTORE_PASSWORD`, and `ANDROID_KEY_PASSWORD`. Workflows must decode the keystore into a temporary runner directory, avoid command echoing, sign the unsigned artifact, verify it, calculate SHA-256, upload the APK and checksum as Release assets, and delete temporary files when the job ends.

Never put `.jks`, `.keystore`, `.p12`, `.pem`, passwords, `local.properties`, signed APKs, or signing logs in Git. Pull requests from forks must never receive release secrets.

## Known limitations

- Notifications can be shown while the app process is alive. Reliable delivery after force-stop requires an operator-configured vendor push service or FCM.
- WebView behavior depends on the Android System WebView version.
- The alpha build targets SDK 35 and supports Android 8.0 (API 26) or newer.
