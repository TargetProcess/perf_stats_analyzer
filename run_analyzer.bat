call setup-environment.bat
.env\Scripts\python.exe run_perf_time_analysis.py -mf %1
.env\Scripts\python.exe notify_tp.py -f %1 --tp-url %2 --tp-token %3 --build-url %4
call cleanup-environment.bat