@echo off
echo ============================================================
echo  Criando a tarefa agendada "Carga diaria chamados"
echo  Roda todo dia as 10:00 o arquivo rodar_carga_diaria.bat
echo ============================================================
schtasks /Create /F /TN "Carga diaria chamados" /SC DAILY /ST 10:00 /TR "\"C:\Projetos\Projeto - Performance de Suporte\rodar_carga_diaria.bat\""
if errorlevel 1 (
  echo.
  echo Nao consegui criar a tarefa. Tire um print desta janela e me mande.
  pause
  exit /b 1
)
echo.
echo Tarefa criada. Conferindo:
schtasks /Query /TN "Carga diaria chamados" /FO LIST
echo.
pause
