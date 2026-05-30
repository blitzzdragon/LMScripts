python3 AutoSorter.py               # watch ~/Downloads (poll every 5s)
python3 AutoSorter.py --once        # single pass then exit
python3 AutoSorter.py --dry-run     # preview only
python3 AutoSorter.py --undo        # reverse last run
python3 AutoSorter.py --backup      # copy instead of move
python3 AutoSorter.py --config      # show current rules
python3 AutoSorter.py --stats       # show sorting history
python3 AutoSorter.py --install     # install as systemd service
python3 AutoSorter.py --uninstall   # remove systemd service

Requires python3.
Optional: pip install watchdog (inotify mode, faster).
