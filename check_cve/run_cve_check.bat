@echo off
chcp 65001 >nul
title check_cve_whitelist -- Needful Things

echo.
echo ================================================================
echo   check_cve_whitelist -- CVE Relevance Filter
echo ================================================================
echo.

cd /d "%~dp0"

:: Needs pip-audit in the python that runs this: pip install pip-audit
:: pip-audit queries an online advisory service with the names and versions of your
:: dependencies (no source code is sent).
:: Pass --full to list the unsure and not-relevant findings in detail.

python check_cve_whitelist.py %*

echo.
pause
