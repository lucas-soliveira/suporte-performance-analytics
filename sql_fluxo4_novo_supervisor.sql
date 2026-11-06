/* ============================================================================
   Fluxo 4 - Novo supervisor (Power Automate -> SQL Server)
   Rode UMA VEZ no SSMS, conectado em  pc-lucas\sqldev  /  db_suporte_bi.

   O que cria:
     dw.usp_upsert_supervisor  -> grava (ou atualiza) um supervisor e os paises dele,
                                  tudo numa transacao so. Se qualquer pais nao existir,
                                  nada e gravado.
   Chamada pelo fluxo:
     EXEC dw.usp_upsert_supervisor @nome, @email, @perfil, @paises
       @paises = nomes separados por virgula, ex.: 'Brasil,Chile'
       @perfil = 'SUPERVISOR' ou 'GESTOR' (os dois valores que ja existem no banco)

   A tabela de origem e dw.dim_supervisor (id_supervisor, nome, email, ativo, perfil)
   e dw.supervisor_pais (id_supervisor, id_pais). A RLS do Power BI usa o e-mail.
   ============================================================================ */
USE db_suporte_bi;
GO

CREATE OR ALTER PROCEDURE dw.usp_upsert_supervisor
    @nome   VARCHAR(100),
    @email  VARCHAR(150),
    @perfil VARCHAR(20),
    @paises VARCHAR(500)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;           -- qualquer erro desfaz tudo

    SET @email = LOWER(LTRIM(RTRIM(@email)));
    SET @perfil = UPPER(LTRIM(RTRIM(@perfil)));

    IF @email NOT LIKE '_%@_%._%'
        THROW 50001, 'E-mail invalido.', 1;
    IF @perfil NOT IN ('SUPERVISOR', 'GESTOR')
        THROW 50002, 'Perfil deve ser SUPERVISOR ou GESTOR.', 1;

    -- paises pedidos (sem espacos sobrando) e conferencia: todos precisam existir
    DECLARE @lista TABLE (nome_pais VARCHAR(50) PRIMARY KEY);
    INSERT INTO @lista (nome_pais)
    SELECT DISTINCT LTRIM(RTRIM(value))
    FROM STRING_SPLIT(@paises, ',')
    WHERE LTRIM(RTRIM(value)) <> '';

    IF NOT EXISTS (SELECT 1 FROM @lista)
        THROW 50003, 'Informe pelo menos um pais.', 1;

    IF EXISTS (SELECT 1 FROM @lista l
               WHERE NOT EXISTS (SELECT 1 FROM dw.dim_pais p WHERE p.nome_pais = l.nome_pais))
        THROW 50004, 'Algum pais informado nao existe em dw.dim_pais.', 1;

    BEGIN TRAN;

    DECLARE @id INT = (SELECT id_supervisor FROM dw.dim_supervisor WITH (UPDLOCK, HOLDLOCK)
                       WHERE email = @email);

    IF @id IS NULL
    BEGIN
        IF COLUMNPROPERTY(OBJECT_ID('dw.dim_supervisor'), 'id_supervisor', 'IsIdentity') = 1
        BEGIN
            INSERT INTO dw.dim_supervisor (nome, email, ativo, perfil)
            VALUES (@nome, @email, 1, @perfil);
            SET @id = SCOPE_IDENTITY();
        END
        ELSE
        BEGIN
            SET @id = (SELECT ISNULL(MAX(id_supervisor), 0) + 1
                       FROM dw.dim_supervisor WITH (UPDLOCK, HOLDLOCK));
            INSERT INTO dw.dim_supervisor (id_supervisor, nome, email, ativo, perfil)
            VALUES (@id, @nome, @email, 1, @perfil);
        END
    END
    ELSE
        UPDATE dw.dim_supervisor
           SET nome = @nome, ativo = 1, perfil = @perfil
         WHERE id_supervisor = @id;

    -- refaz os paises do supervisor
    DELETE FROM dw.supervisor_pais WHERE id_supervisor = @id;
    INSERT INTO dw.supervisor_pais (id_supervisor, id_pais)
    SELECT @id, p.id_pais
    FROM dw.dim_pais p
    JOIN @lista l ON l.nome_pais = p.nome_pais;

    COMMIT;

    -- devolve o que ficou gravado (o fluxo usa para montar o e-mail de boas-vindas)
    SELECT s.id_supervisor, s.nome, s.email, s.perfil,
           STRING_AGG(p.nome_pais, ', ') AS paises
    FROM dw.dim_supervisor s
    JOIN dw.supervisor_pais sp ON sp.id_supervisor = s.id_supervisor
    JOIN dw.dim_pais p ON p.id_pais = sp.id_pais
    WHERE s.id_supervisor = @id
    GROUP BY s.id_supervisor, s.nome, s.email, s.perfil;
END
GO

/* ---- TESTE (opcional): cria e depois remove um supervisor de teste ----------
EXEC dw.usp_upsert_supervisor 'Teste Fluxo', 'teste.fluxo@techsupport.global', 'SUPERVISOR', 'Brasil,Chile';

DELETE sp FROM dw.supervisor_pais sp
JOIN dw.dim_supervisor s ON s.id_supervisor = sp.id_supervisor
WHERE s.email = 'teste.fluxo@techsupport.global';
DELETE FROM dw.dim_supervisor WHERE email = 'teste.fluxo@techsupport.global';
------------------------------------------------------------------------------ */
