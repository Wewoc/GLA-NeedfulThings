@echo off
REM mcp-llm-tester/run_mcp_llm_test_gui.bat
REM Starts the Tkinter GUI (mcp_test_gui.py) for the MCP-LLM test runner.
REM Prerequisite: your MCP server is already running (see config.py),
REM Ollama is running locally.

setlocal
cd /d "%~dp0"

echo ============================================================
echo MCP-LLM test runner (GUI)
echo Prerequisite: your MCP server is already running (see config.py)
echo ============================================================
echo.

python mcp_test_gui.py
