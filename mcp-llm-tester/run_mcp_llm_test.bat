@echo off
REM mcp-llm-tester/run_mcp_llm_test.bat
REM Starts mcp_llm_test_runner.py with a live log in the console.
REM Prerequisite: your MCP server is already running, Ollama is running.

setlocal
cd /d "%~dp0"

echo ============================================================
echo MCP LLM Test Runner
echo Prerequisite: your MCP server is already running (see config.py)
echo ============================================================
echo.

python mcp_llm_test_runner.py

echo.
echo ============================================================
echo Test run finished. Results are in results\
echo ============================================================
pause
