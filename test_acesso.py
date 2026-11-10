import pytest
from dt2sc.acesso import Plataforma


@pytest.fixture
def plat(tmp_path):
    p = Plataforma(tmp_path)
    p.criar_empresa("alfa", "Alfa Têxtil"); p.criar_empresa("beta", "Beta Têxtil")
    p.criar_usuario("ana", "senhaforte123", "alfa"); p.criar_usuario("bruno", "outrasenha123", "beta")
    p.criar_usuario("adm", "adminforte123", None, "admin")
    return p


def test_login_e_senha_nao_em_claro(plat):
    assert plat.autenticar("ana", "senhaforte123")["empresa"] == "alfa"
    assert plat.autenticar("ana", "errada") is None
    assert "senhaforte123" not in (plat.raiz / "usuarios.json").read_text()


def test_bloqueio_apos_tentativas(plat):
    for _ in range(5):
        plat.autenticar("ana", "x")
    assert plat.autenticar("ana", "senhaforte123") is None      # bloqueada mesmo com a senha certa


def test_isolamento_entre_empresas(plat):
    n = plat.salvar_upload("alfa", "a.csv", b"timestamp,producao_kg_h,eletrica_kw\n", "ana")
    assert plat.listar_uploads("beta") == []
    with pytest.raises(FileNotFoundError):
        plat.ler_upload("beta", n)
    with pytest.raises(FileNotFoundError):
        plat.ler_upload("beta", "../../alfa/uploads/" + n)     # path traversal vira só o nome do arquivo


def test_upload_validacoes(plat):
    with pytest.raises(ValueError):
        plat.salvar_upload("alfa", "x.exe", b"a", "ana")
    with pytest.raises(ValueError):
        plat.salvar_upload("alfa", "x.csv", b"0" * (51 * 1_048_576), "ana")
    n = plat.salvar_upload("alfa", "../../etc/passwd.csv", b"a", "ana")
    assert "/" not in n


def test_empresa_inexistente_e_ids(plat):
    with pytest.raises(PermissionError):
        plat.listar_uploads("../alfa")
    with pytest.raises(ValueError):
        plat.criar_empresa("../x", "x")
    with pytest.raises(ValueError):
        plat.criar_usuario("novo", "curta", "alfa")


def test_usuario_desativado_nao_entra(plat):
    plat.definir_ativo("ana", False, "adm")
    assert plat.autenticar("ana", "senhaforte123") is None


def test_auditoria_registra(plat):
    plat.autenticar("ana", "senhaforte123")
    assert any(x["acao"] == "login" for x in plat.ler_auditoria())
