@echo off
pip install virtualenv
virtualenv .env
call .env\Scripts\activate
pip install --no-cache-dir -r requirements