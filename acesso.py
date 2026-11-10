"""Camada de acesso e armazenamento da plataforma fechada DT2-SC.

- Cada empresa tem uma pasta própria; usuários só enxergam a pasta da sua empresa.
- Senhas guardadas só como hash PBKDF2-SHA256 com sal; bloqueio temporário após tentativas erradas.
- Trilha de auditoria (quem fez o quê e quando). Só biblioteca padrão.
Não há criptografia em repouso: proteja o disco/volume onde ficam os dados (ver README).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime
from pathlib import Path

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,39}$")
USER_RE = re.compile(r"^[a-z0-9][a-z0-9_.@-]{2,59}$")
MAX_UPLOAD_MB = 50
MIN_SENHA = 10
TENTATIVAS, BLOQUEIO_S = 5, 300
PAPEIS = ("admin", "empresa")


def _hash(senha: str, sal: bytes | None = None, it: int = 200_000) -> str:
    sal = sal or secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, it)
    return f"pbkdf2${it}${sal.hex()}${h.hex()}"


def _confere(senha: str, reg: str) -> bool:
    try:
        _, it, sal, h = reg.split("$")
        novo = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), bytes.fromhex(sal), int(it))
        return hmac.compare_digest(novo.hex(), h)
    except Exception:
        return False


def _escrever(caminho: Path, obj) -> None:
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, caminho)


def _ler(caminho: Path, padrao):
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else padrao


class Plataforma:
    def __init__(self, raiz: str | Path | None = None):
        self.raiz = Path(raiz or os.environ.get("DT2SC_DADOS", "dados_plataforma")).resolve()
        (self.raiz / "empresas").mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.raiz, 0o700)
        except OSError:
            pass
        self._usuarios = self.raiz / "usuarios.json"
        self._empresas = self.raiz / "empresas.json"
        self._tent = self.raiz / "tentativas.json"
        self._audit = self.raiz / "auditoria.jsonl"

    # ------------------------------------------------------------- administração
    def usuarios(self) -> dict:
        return _ler(self._usuarios, {})

    def empresas(self) -> dict:
        return _ler(self._empresas, {})

    def criar_empresa(self, eid: str, nome: str, por: str = "sistema") -> None:
        if not ID_RE.match(eid):
            raise ValueError("id da empresa: 3-40 caracteres, minúsculas, números, '-' ou '_'")
        emp = self.empresas()
        if eid in emp:
            raise ValueError("empresa já existe")
        emp[eid] = {"nome": nome.strip() or eid, "criada": datetime.now().isoformat(timespec="seconds")}
        _escrever(self._empresas, emp)
        (self.raiz / "empresas" / eid / "uploads").mkdir(parents=True, exist_ok=True)
        (self.raiz / "empresas" / eid / "resultados").mkdir(parents=True, exist_ok=True)
        self.auditar(por, "criar_empresa", eid)

    def criar_usuario(self, usuario: str, senha: str, empresa: str | None, papel: str = "empresa", por: str = "sistema") -> None:
        usuario = usuario.strip().lower()
        if not USER_RE.match(usuario):
            raise ValueError("usuário: 3-60 caracteres (letras minúsculas, números, . _ @ -)")
        if papel not in PAPEIS:
            raise ValueError("papel inválido")
        if len(senha) < MIN_SENHA:
            raise ValueError(f"senha com pelo menos {MIN_SENHA} caracteres")
        if papel == "empresa" and empresa not in self.empresas():
            raise ValueError("empresa inexistente")
        u = self.usuarios()
        if usuario in u:
            raise ValueError("usuário já existe")
        u[usuario] = {"hash": _hash(senha), "empresa": empresa if papel == "empresa" else None, "papel": papel,
                      "ativo": True, "criado": datetime.now().isoformat(timespec="seconds")}
        _escrever(self._usuarios, u)
        self.auditar(por, "criar_usuario", f"{usuario} ({papel}, {empresa})")

    def alterar_senha(self, usuario: str, nova: str, por: str | None = None) -> None:
        if len(nova) < MIN_SENHA:
            raise ValueError(f"senha com pelo menos {MIN_SENHA} caracteres")
        u = self.usuarios()
        if usuario not in u:
            raise ValueError("usuário inexistente")
        u[usuario]["hash"] = _hash(nova)
        _escrever(self._usuarios, u)
        self.auditar(por or usuario, "alterar_senha", usuario)

    def definir_ativo(self, usuario: str, ativo: bool, por: str) -> None:
        u = self.usuarios()
        u[usuario]["ativo"] = bool(ativo)
        _escrever(self._usuarios, u)
        self.auditar(por, "ativar" if ativo else "desativar", usuario)

    # ------------------------------------------------------------- autenticação
    def autenticar(self, usuario: str, senha: str) -> dict | None:
        usuario = (usuario or "").strip().lower()
        agora = time.time()
        t = _ler(self._tent, {})
        reg = t.get(usuario, {"n": 0, "ate": 0})
        if reg["ate"] > agora:
            self.auditar(usuario, "login_bloqueado", "")
            return None
        u = self.usuarios().get(usuario)
        ok = bool(u and u["ativo"] and _confere(senha or "", u["hash"]))
        if not u:
            _confere(senha or "", _hash("x"))      # custo de tempo parecido, não revela se o usuário existe
        if ok:
            t.pop(usuario, None); _escrever(self._tent, t)
            self.auditar(usuario, "login", "")
            return {"usuario": usuario, "empresa": u["empresa"], "papel": u["papel"]}
        reg["n"] += 1
        if reg["n"] >= TENTATIVAS:
            reg = {"n": 0, "ate": agora + BLOQUEIO_S}
        t[usuario] = reg
        _escrever(self._tent, t)
        self.auditar(usuario, "login_falhou", "")
        return None

    def bloqueado_ate(self, usuario: str) -> float:
        return _ler(self._tent, {}).get((usuario or "").strip().lower(), {"ate": 0})["ate"]

    # ------------------------------------------------------------- dados da empresa
    def _pasta(self, empresa: str, sub: str = "") -> Path:
        if empresa not in self.empresas() or not ID_RE.match(empresa):
            raise PermissionError("empresa inválida")
        p = (self.raiz / "empresas" / empresa / sub).resolve()
        if not str(p).startswith(str(self.raiz / "empresas" / empresa)):
            raise PermissionError("caminho fora da área da empresa")
        p.mkdir(parents=True, exist_ok=True)
        return p

    def salvar_upload(self, empresa: str, nome: str, conteudo: bytes, por: str) -> str:
        if len(conteudo) > MAX_UPLOAD_MB * 1_048_576:
            raise ValueError(f"arquivo maior que {MAX_UPLOAD_MB} MB")
        base = re.sub(r"[^A-Za-z0-9._-]", "_", Path(nome).name)[-80:] or "dados.csv"
        if not base.lower().endswith((".csv", ".txt")):
            raise ValueError("somente arquivos .csv ou .txt")
        final = f"{datetime.now():%Y%m%d-%H%M%S}_{base}"
        (self._pasta(empresa, "uploads") / final).write_bytes(conteudo)
        self.auditar(por, "upload", f"{empresa}/{final} ({len(conteudo)} bytes)")
        return final

    def listar_uploads(self, empresa: str) -> list[dict]:
        return [{"nome": p.name, "kb": round(p.stat().st_size / 1024, 1)}
                for p in sorted(self._pasta(empresa, "uploads").iterdir()) if p.is_file()]

    def ler_upload(self, empresa: str, nome: str) -> Path:
        p = (self._pasta(empresa, "uploads") / Path(nome).name)
        if not p.is_file():
            raise FileNotFoundError(nome)
        return p

    def apagar_upload(self, empresa: str, nome: str, por: str) -> None:
        self.ler_upload(empresa, nome).unlink()
        self.auditar(por, "apagar_upload", f"{empresa}/{nome}")

    def config(self, empresa: str) -> dict:
        return _ler(self._pasta(empresa) / "config.json", {"mapa": {}, "fator": {}, "tarifa_gas": 0.0,
                                                            "cavaco_r_t": 0.0, "gate_fee": 0.0})

    def salvar_config(self, empresa: str, cfg: dict, por: str) -> None:
        _escrever(self._pasta(empresa) / "config.json", cfg)
        self.auditar(por, "config", empresa)

    def salvar_resultado(self, empresa: str, res: dict, por: str) -> str:
        nome = f"{datetime.now():%Y%m%d-%H%M%S}.json"
        _escrever(self._pasta(empresa, "resultados") / nome, res)
        self.auditar(por, "resultado", f"{empresa}/{nome}")
        return nome

    def listar_resultados(self, empresa: str) -> list[str]:
        return sorted((p.name for p in self._pasta(empresa, "resultados").glob("*.json")), reverse=True)

    def ler_resultado(self, empresa: str, nome: str) -> dict:
        return json.loads((self._pasta(empresa, "resultados") / Path(nome).name).read_text(encoding="utf-8"))

    def excluir_empresa_dados(self, empresa: str, por: str) -> None:
        import shutil
        shutil.rmtree(self._pasta(empresa))
        self.auditar(por, "apagar_dados_empresa", empresa)

    # ------------------------------------------------------------- auditoria
    def auditar(self, quem: str, acao: str, detalhe: str) -> None:
        with open(self._audit, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), "quem": quem,
                                "acao": acao, "detalhe": detalhe}, ensure_ascii=False) + "\n")

    def ler_auditoria(self, ultimas: int = 500, empresa: str | None = None) -> list[dict]:
        if not self._audit.exists():
            return []
        L = [json.loads(x) for x in self._audit.read_text(encoding="utf-8").splitlines() if x.strip()]
        if empresa:
            L = [x for x in L if empresa in x["detalhe"] or x["quem"] in
                 {u for u, r in self.usuarios().items() if r["empresa"] == empresa}]
        return L[-ultimas:][::-1]
