# 空间记忆

Private desktop release and cloud-trial source. No personal archives or local path configuration are included.

- Desktop: install qzone-memory/requirements-desktop.txt, run scripts/build-release.py on macOS or Windows.
- Windows: GitHub Actions runs offline regression tests, creates a clean x64 package and runs its packaged offline self-test.
- Cloud: Render blueprint in render.yaml. One Gunicorn worker, eight HTTP threads, one collector at a time. QQ cookies stay in job memory. Private results expire after one hour; users can delete earlier.
- Trial limits: 1200 seconds of text scanning, 1800 seconds total collection, 1200 collection requests, no practical image-count cap, 4 MiB per image; 512 MiB source-image capacity per task. Deep checkpoints can continue after same-account reauthentication. ZIP parts target 64 MiB source images; single-file HTML is available only for archives up to 16 MiB of images. Results can be incomplete.
- Default public trial quota: 20 jobs per UTC day, ten per browser per day including continuation; 4 GiB monthly private-file transfer quota. Do not scale to multiple processes without moving job ownership, quotas and scheduling into a shared service.
- Cloud collection saves text and image references first; social enrichment and bounded image downloads follow. Exact repeated cards and fully covered offset probes are skipped, without treating unknown or empty ranges as covered. Optional details have a bounded pass and remain resumable if unfinished.
- Signed session secret must be stable and at least 32 characters. Use a dedicated data directory. Never reuse a desktop archive root.
- Service restarts interrupt active QQ sessions. Private results use ephemeral storage and may be lost early. The current Free deployment has no persistent disk: quota counters also reset on restart. A future paid deployment may persist quota counters separately; no QQ archives or cookies belong there. Temporary data is not a permanent backup.
- The macOS app is ad-hoc signed, not notarized. Windows code signing is not configured. Successful offline self-tests do not replace native-window and real QQ authentication tests on target machines.
