@echo off
rem Executado pelo Agendador de Tarefas do Windows todo dia as 10h.
rem Roda a carga incremental e guarda a saida em logs\agendador.log
cd /d "C:\Projetos\Projeto - Performance de Suporte"
if not exist logs mkdir logs
echo ==== %date% %time% ==== >> logs\agendador.log
python gerar_chamados_diario.py --executar >> logs\agendador.log 2>&1
set RC=%errorlevel%
echo codigo_saida=%RC% >> logs\agendador.log
exit /b %RC%
