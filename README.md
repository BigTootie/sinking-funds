# SinkingFundsPython app

## Run the app

### uv

Run as a desktop app:

```bash
uv run flet run
```

Run as a web app:

```bash
uv run flet run --web
```

For more details on running the app, refer to the [Getting Started Guide](https://docs.flet.dev/).

## Run the tests

Run the Flet UI integration tests and the offline model, persistence, and
Nextcloud tests with:

```bash
uv run flet test
```

The UI tests use Flet's tester to interact with the app. They keep all saved
data in pytest temporary directories and stub the Nextcloud server check. On
Linux, the first run also needs the Flutter and GTK development prerequisites
used by Flet to build its test host.

## Build the app

### Android

```bash
flet build apk -v
```

For more details on building and signing `.apk` or `.aab`, refer to the [Android Packaging Guide](https://docs.flet.dev/publish/android/).

### iOS

```bash
flet build ipa -v
```

For more details on building and signing `.ipa`, refer to the [iOS Packaging Guide](https://docs.flet.dev/publish/ios/).

### macOS

```bash
flet build macos -v
```

For more details on building macOS package, refer to the [macOS Packaging Guide](https://docs.flet.dev/publish/macos/).

### Linux

```bash
flet build linux -v
```

For more details on building Linux package, refer to the [Linux Packaging Guide](https://docs.flet.dev/publish/linux/).

### Windows

```bash
flet build windows -v
```

For more details on building Windows package, refer to the [Windows Packaging Guide](https://docs.flet.dev/publish/windows/).

### Web

```bash
flet build web -v
```

For more details on building Web app, refer to the [Web Packaging Guide](https://docs.flet.dev/publish/web/).
