@echo off
call .env\Scripts\deactivate.bat
rd /s /q .env
IF EXIST .results (rd /s /q .results)
