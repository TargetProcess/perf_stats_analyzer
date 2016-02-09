@echo off
pip install virtualenv
virtualenv .env
call .env\Scripts\activate
pip install -r requirements