call setup-environment.bat
.env\Scripts\python.exe run_perf_time_analysis.py -mf %1
call cleanup-environment.bat