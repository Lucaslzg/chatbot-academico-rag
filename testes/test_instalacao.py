"""Testes do instalar_avaliacao.py: a instalação do RAGAS que mantém os pacotes
do chatbot nas versões instaladas. Nenhum teste chama o pip de verdade."""
from __future__ import annotations

import importlib.metadata
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import instalar_avaliacao as ia


class _Resultado:
    def __init__(self, codigo=0, saida="", erro=""):
        self.returncode, self.stdout, self.stderr = codigo, saida, erro


def _versao_falsa(instaladas):
    def versao(nome):
        if nome not in instaladas:
            raise importlib.metadata.PackageNotFoundError(nome)
        return instaladas[nome]
    return versao


class TestComando(unittest.TestCase):
    def test_so_os_pacotes_instalados_sao_fixados(self):
        versoes = ia.versoes_instaladas(("chromadb", "torch", "nao-instalado"),
                                        versao=_versao_falsa({"chromadb": "1.5.9", "torch": "2.12.1+cpu"}))
        self.assertEqual(versoes, {"chromadb": "1.5.9", "torch": "2.12.1+cpu"})

    def test_comando_fixa_as_versoes_e_aceita_caminho_com_espacos(self):
        caminho = Path("C:/Users/Lucas/Documents/Projeto - Tcc/chatbot-academico/requirements-avaliacao.txt")
        comando = ia.comando_instalacao({"transformers": "5.12.1", "torch": "2.12.1"}, requisitos=caminho,
                                        python="python")
        self.assertEqual(comando[:5], ["python", "-m", "pip", "install", "-r"])
        self.assertEqual(comando[5], str(caminho))  # um argumento só, com os espaços
        self.assertEqual(comando[6:], ["transformers==5.12.1", "torch==2.12.1"])

    def test_os_pacotes_do_chatbot_estao_na_lista(self):
        for nome in ("chromadb", "sentence-transformers", "transformers", "torch", "pymupdf", "ollama"):
            self.assertIn(nome, ia.FIXAR)
        # os que o RAGAS pode precisar mudar ficam livres
        for nome in ("huggingface-hub", "numpy", "fsspec"):
            self.assertNotIn(nome, ia.FIXAR)


class TestListaAntes(unittest.TestCase):
    def test_grava_na_primeira_vez_e_mantem_depois(self):
        with tempfile.TemporaryDirectory() as pasta:
            destino = Path(pasta) / "pacotes_antes_da_avaliacao.txt"
            chamadas = []

            def executar(comando, **_):
                chamadas.append(comando)
                return _Resultado(saida="chromadb==1.5.9\ntransformers==5.12.1\n")

            self.assertTrue(ia.guardar_lista_antes(destino, python="python", executar=executar))
            self.assertEqual(chamadas, [["python", "-m", "pip", "freeze"]])
            self.assertIn("transformers==5.12.1", destino.read_text(encoding="utf-8"))
            # segunda vez: a lista de antes da primeira instalação fica
            self.assertFalse(ia.guardar_lista_antes(destino, python="python",
                                                    executar=lambda *a, **k: _Resultado(saida="mudou\n")))
            self.assertIn("transformers==5.12.1", destino.read_text(encoding="utf-8"))

    def test_falha_do_pip_freeze_nao_grava_arquivo(self):
        with tempfile.TemporaryDirectory() as pasta:
            destino = Path(pasta) / "lista.txt"
            with self.assertRaises(RuntimeError):
                ia.guardar_lista_antes(destino, executar=lambda *a, **k: _Resultado(codigo=1, erro="falhou"))
            self.assertFalse(destino.exists())


class TestConferencias(unittest.TestCase):
    def test_conflitos(self):
        self.assertEqual(ia.conflitos(executar=lambda *a, **k: _Resultado(saida="No broken requirements found.")), [])
        linha = "transformers 5.12.1 has requirement huggingface-hub<2.0,>=1.5.0, but you have huggingface-hub 2.4.0."
        self.assertEqual(ia.conflitos(executar=lambda *a, **k: _Resultado(codigo=1, saida=linha + "\n")), [linha])

    def test_importacoes_num_python_novo(self):
        saida = subprocess.run([sys.executable, "-c", ia._CONFERIR_IMPORTACOES, "json", "modulo_que_nao_existe_xyz"],
                               capture_output=True, text=True)
        self.assertEqual(saida.returncode, 1)
        self.assertIn("ok    json", saida.stdout)
        self.assertIn("ERRO  modulo_que_nao_existe_xyz", saida.stdout)
        calado = lambda comando: subprocess.run(comando, capture_output=True)
        self.assertTrue(ia.conferir_importacoes(("json",), executar=calado))
        self.assertFalse(ia.conferir_importacoes(("modulo_que_nao_existe_xyz",), executar=calado))


class TestPrincipal(unittest.TestCase):
    def _rodar(self, respostas, existe_antes=False):
        """Roda o main com o pip simulado; respostas: código de saída de cada etapa."""
        chamadas = []

        def executar(comando, **_):
            chamadas.append(comando)
            if comando[1:4] == ["-m", "pip", "freeze"]:
                return _Resultado(saida="chromadb==1.5.9\n")
            if comando[1:4] == ["-m", "pip", "install"]:
                return _Resultado(codigo=respostas.get("install", 0))
            if comando[1:4] == ["-m", "pip", "check"]:
                codigo = respostas.get("check", 0)
                return _Resultado(codigo=codigo, saida="pacote 1 has requirement x<2, but you have x 2." if codigo else "")
            if comando[1] == "-c":
                return _Resultado(codigo=respostas.get("importar", 0))
            raise AssertionError(comando)

        with tempfile.TemporaryDirectory() as pasta:
            antes = Path(pasta) / "pacotes_antes_da_avaliacao.txt"
            if existe_antes:
                antes.write_text("antigo\n", encoding="utf-8")
            saida = io.StringIO()
            with mock.patch.object(ia, "ARQUIVO_ANTES", antes), \
                    mock.patch.object(ia.subprocess, "run", side_effect=executar), \
                    mock.patch.object(ia, "versoes_instaladas", return_value={"transformers": "5.12.1"}), \
                    mock.patch.object(sys, "prefix", "/ambiente"), mock.patch.object(sys, "base_prefix", "/sistema"), \
                    redirect_stdout(saida):
                codigo = ia.main()
            conteudo_antes = antes.read_text(encoding="utf-8") if antes.exists() else None
        return codigo, saida.getvalue(), chamadas, conteudo_antes

    def test_tudo_certo(self):
        codigo, texto, chamadas, antes = self._rodar({})
        self.assertEqual(codigo, 0)
        self.assertIn("o chatbot continua funcionando", texto)
        self.assertEqual(antes, "chromadb==1.5.9\n")
        instalacao = [c for c in chamadas if c[1:4] == ["-m", "pip", "install"]][0]
        self.assertIn("transformers==5.12.1", instalacao)

    def test_lista_de_antes_nao_e_sobrescrita(self):
        codigo, texto, _, antes = self._rodar({}, existe_antes=True)
        self.assertEqual(codigo, 0)
        self.assertEqual(antes, "antigo\n")
        self.assertIn("já existe", texto)

    def test_falha_da_instalacao(self):
        codigo, texto, chamadas, _ = self._rodar({"install": 1})
        self.assertEqual(codigo, 1)
        self.assertIn("ResolutionImpossible", texto)
        self.assertIn("pip install -r pacotes_antes_da_avaliacao.txt", texto)
        self.assertFalse([c for c in chamadas if c[1:4] == ["-m", "pip", "check"]])

    def test_conflito_depois_da_instalacao(self):
        codigo, texto, _, _ = self._rodar({"check": 1})
        self.assertEqual(codigo, 1)
        self.assertIn("conflitos", texto)

    def test_modulo_que_nao_importa(self):
        codigo, texto, _, _ = self._rodar({"importar": 1})
        self.assertEqual(codigo, 1)
        self.assertIn("pip install -r pacotes_antes_da_avaliacao.txt", texto)

    def test_fora_do_ambiente_virtual_nao_instala(self):
        saida = io.StringIO()
        with mock.patch.object(sys, "prefix", "/sistema"), mock.patch.object(sys, "base_prefix", "/sistema"), \
                mock.patch.object(ia.subprocess, "run", side_effect=AssertionError("não devia chamar o pip")), \
                redirect_stdout(saida):
            self.assertEqual(ia.main(), 1)
        self.assertIn("ambiente virtual", saida.getvalue())


if __name__ == "__main__":
    unittest.main()
