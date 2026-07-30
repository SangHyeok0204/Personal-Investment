@echo off
chcp 65001 >nul
title 성과보고 러너 (:8010)
REM 대시보드 [보고서 생성] 버튼이 호출하는 Windows 러너.
REM claude CLI 가 이 PC 에만 있고 구독 OAuth 인증이라 컨테이너로 옮길 수 없어서
REM 계산(컨테이너) / 서사 작성(이 러너)으로 나눈 구조. 이 창을 닫으면 버튼이 멈춥니다.

REM ── 필요 시 여기서 조정 ──
REM set PERF_BRIEF_MODEL=sonnet
REM set PERF_BRIEF_RUNNER_TOKEN=원하는토큰
REM set PERF_BRIEF_TIMEOUT_S=900

set PYTHONUTF8=1
python "%~dp0perf_brief_runner.py"

echo.
echo 러너가 종료되었습니다. 창을 닫으려면 아무 키나 누르세요.
pause >nul
