@echo off
setlocal enabledelayedexpansion
title Claude Chat Pipeline

echo.
echo ====================================================
echo   Claude Chat Pipeline
echo ====================================================
echo.

:: ── Step 1: Configuration ─────────────────────────────────────────────────────

:start
echo   [1/3] Configuration
echo   ------------------------------------------
echo.

set /p "SEARCH_LABEL=  Label prefix to filter (default: Garmin): "
if "!SEARCH_LABEL!"=="" set SEARCH_LABEL=Garmin

set /p "INPUT_DIR=  Folder with exported JSON (default: .): "
if "!INPUT_DIR!"=="" set INPUT_DIR=.

set /p "MODEL=  Ollama model (default: qwen2.5-coder:14b-instruct-q8_0): "
if "!MODEL!"=="" set MODEL=qwen2.5-coder:14b-instruct-q8_0

set /p "OLLAMA_TIMEOUT=  Ollama timeout in seconds (default: 300): "
if "!OLLAMA_TIMEOUT!"=="" set OLLAMA_TIMEOUT=300

echo.
echo   Configuration:
echo     SEARCH_LABEL  : !SEARCH_LABEL!
echo     INPUT_DIR     : !INPUT_DIR!
echo     MODEL         : !MODEL!
echo     OLLAMA_TIMEOUT: !OLLAMA_TIMEOUT!
echo.

:confirm
set /p "CONFIRM=  Confirm configuration? [y/n]: "
if /i "!CONFIRM!"=="n" (
    echo.
    echo   Restarting configuration ...
    echo.
    goto :start
)
if /i not "!CONFIRM!"=="y" (
    echo   Invalid input -- please enter y or n.
    goto :confirm
)

:: Values are passed via environment variables -- config.py reads them via os.getenv()
echo   Configuration set.
echo.

:: ── Step 2: Select steps ──────────────────────────────────────────────────────

echo   [2/3] Select steps
echo   ------------------------------------------
echo.
echo   Required:
echo     [1] Step 1 -- Sort chats by label
echo     [2] Step 2 -- Summarize chats via Ollama
echo     [3] Step 3 -- Sort summaries chronologically
echo.
echo   Optional:
echo     [4] Step 4 -- Merge chats into single file
echo     [5] Step 5 -- Export JSON to Markdown
echo     [6] Step 6 -- Export JSON to Word (.docx)
echo.
echo   Enter numbers separated by commas, e.g. 1,2,3 or 1,2,3,4,5
echo   Leave empty for default: 1,2,3
echo.

set /p "STEPS=  Run steps: "
if "!STEPS!"=="" set STEPS=1,2,3

echo.
echo   Selected steps: !STEPS!
echo.

:: ── Step 3: Execute ───────────────────────────────────────────────────────────

echo   [3/3] Executing
echo   ------------------------------------------
echo.

for %%S in (!STEPS!) do (
    set "STEP=%%S"
    set "STEP=!STEP: =!"

    if "!STEP!"=="1" (
        echo   -- Step 1: Sorting chats ...
        python "Step 1 - sort_chats.py"
        if errorlevel 1 ( echo   ERROR in Step 1. & goto :error )
        echo.
    )
    if "!STEP!"=="2" (
        echo   -- Step 2: Summarizing chats ...
        python "Step 2 - summarize_chats.py"
        if errorlevel 1 ( echo   ERROR in Step 2. & goto :error )
        echo.
    )
    if "!STEP!"=="3" (
        echo   -- Step 3: Sorting summaries ...
        python "Step 3 - sort_summaries.py"
        if errorlevel 1 ( echo   ERROR in Step 3. & goto :error )
        echo.
    )
    if "!STEP!"=="4" (
        echo   -- Step 4: Merging chats ...
        python "Step 4 - optional - merge_chats.py"
        if errorlevel 1 ( echo   ERROR in Step 4. & goto :error )
        echo.
    )
    if "!STEP!"=="5" (
        echo   -- Step 5: JSON to Markdown ...
        python "Step 5 - optional - sorted_json_to_md.py"
        if errorlevel 1 ( echo   ERROR in Step 5. & goto :error )
        echo.
    )
    if "!STEP!"=="6" (
        echo   -- Step 6: JSON to Word ...
        python "Step 6 - optional - chats_to_word.py"
        if errorlevel 1 ( echo   ERROR in Step 6. & goto :error )
        echo.
    )
)

echo ====================================================
echo   Done.
echo ====================================================
echo.
pause
exit /b 0

:error
echo.
echo ====================================================
echo   Aborted -- see error above.
echo ====================================================
echo.
pause
exit /b 1