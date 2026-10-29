# 空间记忆

Private desktop release and cloud-trial source. No personal archives or local path configuration are included.

- Desktop: install qzone-memory/requirements-desktop.txt, run scripts/build-release.py on macOS or Windows.
- Windows: GitHub Actions runs offline regression tests, creates a clean x64 package and runs its packaged offline self-test.
- Cloud: Render blueprint in render.yaml. One Gunicorn worker, eight HTTP threads, one collector at a time. QQ cookies stay in job memory. Private results expire after one hour; users can delete earlier.
- Trial limits: 120 seconds of text scanning, 180 seconds total collection, 40 collection requests, 12 images, 4 MiB per image. Results can be incomplete.
- Default public trial quota: 20 jobs per UTC day, three per browser per day; 1 GiB monthly private-file transfer quota. Do not scale to multiple processes without moving job ownership, quotas and scheduling into a shared service.
- Signed session secret must be stable and at least 32 characters. Use a dedicated data directory. Never reuse a desktop archive root.
- Service restarts interrupt active QQ sessions. Private results use ephemeral storage and may be lost early. Only quota counters use the persistent disk; no QQ archives or cookies belong there. Temporary data is not a permanent backup.
- The macOS app is ad-hoc signed, not notarized. Windows code signing is not configured. Successful offline self-tests do not replace native-window and real QQ authentication tests on target machines.
