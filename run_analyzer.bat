call scripts\setup-environment.bat
.env\Scripts\python.exe src\run_perf_time_analysis.py -mf "%1" --es-host "%4" --es-region "%5" --es-access-key-id "%6" --es-secret-access-key "%7"
.env\Scripts\python.exe src\notify_slack.py -f "%1" --slack-notification-url "%2" --slack-channel "#tp-development" --build-url "%3"
call scripts\cleanup-environment.bat