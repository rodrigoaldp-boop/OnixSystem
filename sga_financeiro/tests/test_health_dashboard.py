"""Testes unitarios do diagnostico Saude do sistema (somente leitura)."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from sga_financeiro.services import health_dashboard_service as hds
from sga_financeiro.routes.sistema import HealthDashboardOut, _exigir_admin_health


class HealthHelpersTests(unittest.TestCase):
    def test_sanitizar_senha_e_token(self):
        texto = hds._sanitizar_erro("password=segredo token=abc123 url=postgres://u:p@h/db")
        self.assertNotIn("segredo", texto)
        self.assertNotIn("abc123", texto)
        self.assertIn("***", texto)

    def test_status_disco_limites(self):
        self.assertEqual(hds._status_disco_pct(10), hds.STATUS_OK)
        self.assertEqual(hds._status_disco_pct(70), hds.STATUS_AVISO)
        self.assertEqual(hds._status_disco_pct(85), hds.STATUS_RISCO)
        self.assertEqual(hds._status_disco_pct(90), hds.STATUS_ERRO)

    def test_status_ram_limites(self):
        self.assertEqual(hds._status_ram_pct(10), hds.STATUS_OK)
        self.assertEqual(hds._status_ram_pct(75), hds.STATUS_AVISO)
        self.assertEqual(hds._status_ram_pct(90), hds.STATUS_ERRO)

    def test_cn_de_subject(self):
        self.assertEqual(hds._cn_de_subject("CN=EMPRESA LTDA,O=X"), "EMPRESA LTDA")


class HealthDiskDedupeTests(unittest.TestCase):
    def test_disco_nao_duplica_mesma_particao(self):
        uso = MagicMock(total=1000, used=400, free=600)

        class P:
            def __init__(self, name, exists=True, dev=1):
                self.name = name
                self._exists = exists
                self._dev = dev

            def exists(self):
                return self._exists

            def __str__(self):
                return self.name

            def stat(self):
                st = MagicMock()
                st.st_dev = self._dev
                return st

        candidatos = [
            ("/", P("/", True, 1)),
            ("/opt/onixsystem-prod", P("/opt/onixsystem-prod", True, 1)),
            ("logs", P("/var/log", True, 1)),
            ("/mnt/hd_A", P("/mnt/hd_A", False, 2)),
        ]
        with patch.object(hds, "_load_backup_auto_config_safe", return_value={}), patch.object(
            hds, "_candidatos_disco", return_value=candidatos
        ), patch.object(hds, "_disk_usage_safe", return_value=uso):
            item = hds.checar_disco()
        self.assertEqual(item["id"], "disco")
        self.assertEqual(len(item["metricas"]["particoes"]), 1)
        self.assertIn("mesma particao", item["detalhe"])


class HealthCertBackupTests(unittest.TestCase):
    def test_certificado_aviso_60_dias(self):
        fim = (date.today() + timedelta(days=45)).isoformat()
        with patch.object(
            hds,
            "_inspecionar_cert_local",
            return_value={"ok": True, "validade_fim": fim, "subject": "CN=TESTE"},
        ):
            item = hds.checar_certificado()
        self.assertEqual(item["status"], hds.STATUS_AVISO)
        self.assertIn("Vence", item["resumo"])

    def test_certificado_vermelho_30_dias(self):
        fim = (date.today() + timedelta(days=20)).isoformat()
        with patch.object(
            hds,
            "_inspecionar_cert_local",
            return_value={"ok": True, "validade_fim": fim, "subject": "CN=TESTE"},
        ):
            item = hds.checar_certificado()
        self.assertIn(item["status"], {hds.STATUS_AVISO, hds.STATUS_ERRO})

    def test_backup_atrasado_alerta(self):
        antigo = (datetime.now() - timedelta(hours=20)).isoformat(timespec="seconds")
        with patch.object(
            hds,
            "_load_backup_auto_config_safe",
            return_value={
                "enabled": True,
                "pasta_destino": "/tmp/fake-backups-onix",
                "last_backup_at": antigo,
                "intervalo_minutos": 180,
            },
        ), patch.object(hds, "_scan_backups_pasta", return_value=(1, 1000, None, None)):
            item = hds.checar_backup()
        self.assertIn(item["status"], {hds.STATUS_AVISO, hds.STATUS_ERRO})


class HealthIsolationTests(unittest.TestCase):
    def _patch_all_ok(self, postgres_resumo="a"):
        return [
            patch.object(hds, "checar_postgres", return_value=hds._item("postgres", "PG", hds.STATUS_OK, postgres_resumo)),
            patch.object(hds, "checar_whatsapp", return_value=hds._item("whatsapp", "WA", hds.STATUS_INFO, "ok")),
            patch.object(hds, "checar_backup", return_value=hds._item("backup", "B", hds.STATUS_OK, "ok")),
            patch.object(hds, "checar_certificado", return_value=hds._item("certificado", "C", hds.STATUS_OK, "ok")),
            patch.object(hds, "checar_smtp", return_value=hds._item("smtp", "S", hds.STATUS_INFO, "ok")),
            patch.object(hds, "checar_disco", return_value=hds._item("disco", "D", hds.STATUS_OK, "ok")),
            patch.object(hds, "checar_cpu", return_value=hds._item("cpu", "CPU", hds.STATUS_OK, "ok")),
            patch.object(hds, "checar_memoria", return_value=hds._item("memoria", "RAM", hds.STATUS_OK, "ok")),
            patch.object(hds, "checar_nginx", return_value=hds._item("nginx", "N", hds.STATUS_INFO, "ok")),
            patch.object(hds, "checar_wireguard", return_value=hds._item("wireguard", "W", hds.STATUS_INFO, "ok")),
            patch.object(hds, "checar_containers", return_value=hds._item("containers", "C", hds.STATUS_INFO, "ok")),
            patch.object(hds, "checar_servicos", return_value=hds._item("servicos", "Svc", hds.STATUS_OK, "ok")),
            patch.object(hds, "checar_armazenamento", return_value=hds._item("armazenamento", "A", hds.STATUS_OK, "ok")),
        ]

    def test_refresh_limpa_cache(self):
        from contextlib import ExitStack

        hds.limpar_cache_health()
        with ExitStack() as stack:
            for p in self._patch_all_ok("a"):
                stack.enter_context(p)
            p1 = hds.coletar_health_dashboard(None, refresh=True)

        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in self._patch_all_ok("b")]
            p2 = hds.coletar_health_dashboard(None, refresh=False)
            mocks[0].assert_not_called()
            self.assertEqual(
                next(i for i in p1["itens"] if i["id"] == "postgres")["resumo"],
                next(i for i in p2["itens"] if i["id"] == "postgres")["resumo"],
            )

        hds.limpar_cache_health()
        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in self._patch_all_ok("c")]
            p3 = hds.coletar_health_dashboard(None, refresh=True)
            mocks[0].assert_called()
            self.assertEqual(next(i for i in p3["itens"] if i["id"] == "postgres")["resumo"], "c")

    def test_falha_postgres_nao_derruba_coleta(self):
        from contextlib import ExitStack

        def boom(_db=None):
            raise RuntimeError("password=secreta falhou")

        patches = self._patch_all_ok()
        # substituir postgres pelo boom via _executar_check path: patch function used in CHECK_SPECS
        hds.limpar_cache_health()
        with ExitStack() as stack:
            stack.enter_context(patch.object(hds, "checar_postgres", side_effect=boom))
            for p in patches[1:]:
                stack.enter_context(p)
            payload = hds.coletar_health_dashboard(None, refresh=True)

        ids = [i["id"] for i in payload["itens"]]
        self.assertIn("saude_geral", ids)
        self.assertIn("postgres", ids)
        self.assertIn("containers", ids)
        pg = next(i for i in payload["itens"] if i["id"] == "postgres")
        self.assertEqual(pg["status"], hds.STATUS_INFO)
        blob = str(payload)
        self.assertNotIn("secreta", blob)
        HealthDashboardOut(**payload)

    def test_containers_ausente_nao_e_erro(self):
        with patch.object(hds, "_runtime_bin", return_value=(None, "")):
            item = hds.checar_containers()
        self.assertEqual(item["status"], hds.STATUS_INFO)
        self.assertIn("nao utilizado", item["resumo"].lower())

    def test_wireguard_ausente_nao_e_erro(self):
        with patch.object(hds, "_which", return_value=None):
            item = hds.checar_wireguard()
        self.assertEqual(item["status"], hds.STATUS_INFO)

    def test_timeout_isolado(self):
        def lento(_db=None):
            import time

            time.sleep(2)
            return hds._item("x", "x", hds.STATUS_OK, "ok")

        item = hds._executar_check("lento", lento, None, timeout=0.1)
        self.assertEqual(item["status"], hds.STATUS_INFO)
        self.assertIn("timeout", (item.get("erro") or item.get("resumo") or "").lower())


class HealthAuthTests(unittest.TestCase):
    def test_sem_usuario_401(self):
        req = MagicMock()
        req.state = MagicMock()
        req.state.auth_user_id = None
        req.headers = {}
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            _exigir_admin_health(req)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_nao_admin_403(self):
        req = MagicMock()
        req.state = MagicMock()
        req.state.auth_user_id = 7
        req.headers = {}
        from fastapi import HTTPException

        fake_conn = MagicMock()
        fake_conn.__enter__ = MagicMock(return_value=fake_conn)
        fake_conn.__exit__ = MagicMock(return_value=False)
        fake_conn.execute.return_value.mappings.return_value.first.return_value = {"perfil": "gerencial"}
        with patch("sga_financeiro.routes.sistema.engine") as eng:
            eng.connect.return_value = fake_conn
            with self.assertRaises(HTTPException) as ctx:
                _exigir_admin_health(req)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_ok(self):
        req = MagicMock()
        req.state = MagicMock()
        req.state.auth_user_id = None
        req.headers = {"X-Onix-Usuario-Id": "3"}
        fake_conn = MagicMock()
        fake_conn.__enter__ = MagicMock(return_value=fake_conn)
        fake_conn.__exit__ = MagicMock(return_value=False)
        fake_conn.execute.return_value.mappings.return_value.first.return_value = {"perfil": "admin"}
        with patch("sga_financeiro.routes.sistema.engine") as eng:
            eng.connect.return_value = fake_conn
            uid = _exigir_admin_health(req)
        self.assertEqual(uid, 3)


if __name__ == "__main__":
    unittest.main()
