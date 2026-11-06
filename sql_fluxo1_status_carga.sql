/* ============================================================================
   Fluxo 1 - Conferencia da carga diaria (Power Automate -> SQL Server)
   Rode UMA VEZ no SSMS, conectado em  pc-lucas\sqldev  /  db_suporte_bi.

   O fluxo da nuvem roda as 10h30 e chama:
     EXEC dw.usp_status_carga
   A procedure so le dados (nao altera nada) e devolve uma linha:
     situacao        'OK' se entrou chamado aberto hoje, senao 'ATRASADA'
     total_chamados  linhas em dw.fato_chamados
     abertos_hoje    chamados com data_abertura de hoje
     ultima_abertura data/hora do chamado mais recente
     abertos_agora   chamados ainda nao fechados
   O login svc_automate ja tem EXECUTE no schema dw, entao nao precisa de GRANT.
   ============================================================================ */
USE db_suporte_bi;
GO

CREATE OR ALTER PROCEDURE dw.usp_status_carga
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @hoje DATE = CAST(GETDATE() AS DATE);

    SELECT
        CASE WHEN MAX(data_abertura) >= @hoje THEN 'OK' ELSE 'ATRASADA' END AS situacao,
        COUNT(*)                                                     AS total_chamados,
        SUM(CASE WHEN data_abertura >= @hoje THEN 1 ELSE 0 END)      AS abertos_hoje,
        CONVERT(VARCHAR(16), MAX(data_abertura), 120)                AS ultima_abertura,
        SUM(CASE WHEN data_fechamento IS NULL THEN 1 ELSE 0 END)     AS abertos_agora
    FROM dw.fato_chamados;
END
GO

/* TESTE: deve devolver uma linha */
EXEC dw.usp_status_carga;
