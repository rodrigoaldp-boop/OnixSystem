# Build no Linux (AlmaLinux / servidor)

No servidor Linux **nao** e possivel gerar um `.exe` nativo para Windows: o PyInstaller embute o interpretador da plataforma em que roda (aqui, ELF Linux).

Use este roteiro para gerar um pacote executavel **para rodar no proprio Linux**.

```bash
cd /caminho/OnixSystem
chmod +x scripts/build_linux_bundle.sh
./scripts/build_linux_bundle.sh
```

Saida:

- `dist/OnixSystem/OnixSystem` — binario
- pasta `dist/OnixSystem/` com dependencias

Para distribuir instalador **Windows** (`OnixSystem-Setup.exe`), use uma maquina Windows ou o workflow GitHub Actions ja configurado em `.github/workflows/windows-installer.yml`.
