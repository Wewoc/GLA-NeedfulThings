@echo off
setlocal

rem run_all_checks.bat — code_metrics
rem Runs all six metric scripts in sequence:
rem   1. count_project.py           -> project_stats.md
rem   2. list_functions.py          -> FUNCTION_MAP.md
rem   3. list_gui_bindings.py       -> GUI_BINDINGS.md
rem   4. list_longest_functions.py  -> LONGEST_FUNCTIONS.md (reads FUNCTION_MAP.md)
rem   5. list_complexity.py         -> COMPLEXITY_MAP.md (independent, own scan)
rem   6. build_profile.py           -> PROJECT_PROFILE.md (reads 1, 2, 3, 4 above)
rem
rem PROJECT_ROOT / OUTPUT_DIR are maintained centrally in metrics_config.py.

echo === 1/6: count_project.py ===
python count_project.py
if errorlevel 1 goto :error

echo.
echo === 2/6: list_functions.py ===
python list_functions.py
if errorlevel 1 goto :error

echo.
echo === 3/6: list_gui_bindings.py ===
python list_gui_bindings.py
if errorlevel 1 goto :error

echo.
echo === 4/6: list_longest_functions.py ===
python list_longest_functions.py
if errorlevel 1 goto :error

echo.
echo === 5/6: list_complexity.py ===
python list_complexity.py
if errorlevel 1 goto :error

echo.
echo === 6/6: build_profile.py ===
python build_profile.py
if errorlevel 1 goto :error

echo.
echo Done. PROJECT_PROFILE.md is in code_metrics\output\.
goto :end

:error
echo.
echo ERROR — run aborted. See message above.
exit /b 1

:end
endlocal
