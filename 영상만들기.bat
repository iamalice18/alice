@echo off
chcp 65001 >nul
REM 원고 파일(.txt 또는 scenes.yaml)을 이 파일 위로 끌어다 놓으면 영상이 만들어집니다.
cd /d "%~dp0"
if "%~1"=="" (
  echo 원고 파일을 이 아이콘 위로 끌어다 놓으세요.
  pause
  exit /b
)
python make_video.py "%~1"
echo.
echo 결과는 output 폴더에 있습니다.
pause
