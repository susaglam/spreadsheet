# Yerel CI — OCA Botlari Ev Bilgisayarinda

Bu belge, OCA'nin GitHub PR'larinda gordugun botlarin (pre-commit, pylint-odoo, prettier, eslint, ruff) kendi modullerinde **yerel olarak** nasil calistirilacagini gosterir.

## Neden?

- **Erken hata tespiti** — push etmeden once lint/format hatalarini gor
- **Daha kaliteli kod** — Odoo OCA standartlarina uygunluk otomatik
- **Daha az CI cycle** — Her push'ta CI hata verip tekrar commit atmaya gerek kalmaz

## Kurulum (Tek Seferlik)

### 1. pre-commit Kur

```bash
pip install pre-commit
```

Windows'ta Python Scripts dizinini PATH'e ekle:

```bash
# git bash / Linux
export PATH="$PATH:$HOME/AppData/Local/Python/pythoncore-3.14-64/Scripts"
```

### 2. Node (prettier + eslint icin)

[nodejs.org](https://nodejs.org) uzerinden 22+ kur. Zaten yuklu mu:

```bash
node --version   # v22+ olmali
npm --version
```

### 3. Repo'nuzda .pre-commit-config.yaml Olustur

En basit yol: OCA'nin kendisinden kopyala.

```bash
# Bizim kullandigimiz
cp e:/Odoo-2026-modules/spreadsheet/.pre-commit-config.yaml \
   e:/your-custom-modules-repo/.pre-commit-config.yaml

cp e:/Odoo-2026-modules/spreadsheet/prettier.config.cjs \
   e:/your-custom-modules-repo/

cp e:/Odoo-2026-modules/spreadsheet/eslint.config.cjs \
   e:/your-custom-modules-repo/

cp e:/Odoo-2026-modules/spreadsheet/checklog-odoo.cfg \
   e:/your-custom-modules-repo/
```

Not: Custom repo'lariniz varsa **OCA standardi konfigurasyonlar** yeterli. Versiyon `branch` parametresini module'un hedefine gore degistir: `19.0`, `saas-19.2`, `18.0`.

### 4. Pre-commit Hook'larini Kur

```bash
cd e:/your-custom-modules-repo/
pre-commit install
```

Artik **her `git commit` oncesi otomatik calisir**.

## Kullanim

### Tek seferlik: butun dosyalarda calistir

```bash
pre-commit run --all-files
```

Ilk calisma yavastir (hook environment'lari indiriyor). Sonraki calismalar hizli.

### Belirli dosyalarda calistir

```bash
pre-commit run --files path/to/file1.py path/to/file2.xml
```

### Belirli hook'u calistir

```bash
pre-commit run prettier --all-files
pre-commit run pylint_odoo --all-files
pre-commit run eslint --all-files
```

### Hook'lari es gecerek commit at (acil durum, onerilmez)

```bash
git commit --no-verify
```

## Botlarin Kontrol Ettikleri

| Hook | Nedir | Ne Bulur |
|------|-------|----------|
| **prettier** | Kod formatlayici | JSON/JS/XML icin tutarsiz indent, uzun satirlar, trailing newline |
| **eslint** | JS linter | ES6 syntax hatalari, unused vars, import sirasi |
| **pylint-odoo** | Odoo ozel pylint | `_()` yerine `self.env._()` (W8161), missing-manifest-dependency, method-inheritability (E8148) |
| **ruff** | Hizli Python linter | PEP8, unused imports, shadowed names |
| **check-merge-conflict** | Git marker'lari | `<<<<<<<` conflict marker'larini algilar |
| **mixed-line-ending** | CRLF/LF | Satir sonu karistirmasini fix eder |
| **odoo-pre-commit-hooks** | Odoo-specific | XML schema, field types, manifest formati |

## Bizim Custom Modullerimize Uygulama Senaryosu

Eger spreadsheet_template_oca, spreadsheet_api_oca vs. moduellerini **ayri bir GitHub repo** olarak paylasmak istersen:

```bash
# Yeni repo'da
mkdir spreadsheet-custom-modules
cd spreadsheet-custom-modules
git init

# Modulleri kopyala (spreadsheet_oca vs. olan core'lari haric)
cp -r e:/Odoo-2026-modules/spreadsheet/spreadsheet_template_oca .
cp -r e:/Odoo-2026-modules/spreadsheet/spreadsheet_kpi_alert_oca .
# ... diger 24 modul

# OCA CI konfigurasyonlari
cp e:/Odoo-2026-modules/spreadsheet/.pre-commit-config.yaml .
cp e:/Odoo-2026-modules/spreadsheet/prettier.config.cjs .
cp e:/Odoo-2026-modules/spreadsheet/eslint.config.cjs .

# pre-commit kurulumu
pre-commit install
pre-commit run --all-files  # Ilk tarama — muhtemelen bazi hatalar bulur

# Bulunan hatalari duzelt
# ... commit ...
```

## GitHub Actions (Push'ta CI Calistirmak Icin)

Eger kendi repo'nda push sonrasi CI calistirmak istersen, OCA'nin workflow'unu kopyala:

```bash
mkdir -p .github/workflows
cp e:/Odoo-2026-modules/spreadsheet/.github/workflows/*.yml .github/workflows/ 2>/dev/null
```

Bu sana **bedava GitHub Actions ile** PR kontrolu verir — ayni bizim gordugumuz 7 check.

## Hizli Ornekler

### Sadece modifiye edilmis dosyalara hizli lint

```bash
# Git'te staged olan dosyalari kontrol et
git diff --cached --name-only | xargs pre-commit run --files
```

### Bir modulunu sifirdan temizle

```bash
pre-commit run --files spreadsheet_api_oca/**/*
```

### Manifestoo ile manifest dogrulama

```bash
pip install manifestoo
manifestoo --select-addons-dir . list
manifestoo --select-addons-dir . check-dev-status
```

## Troubleshoot

| Hata | Cozum |
|------|-------|
| `pre-commit: command not found` | Python Scripts dir'i PATH'e ekle |
| `prettier not found` | `npm install -g prettier` veya repo'da `npm install` |
| `pylint: unknown option value` | .pylintrc dosyasi eski pylint surumuyle uyumsuz — OCA maintainer-tools'tan en guncel sablon |
| Sinir yavas | Ilk calisma hook environment'lari indirir; subsequent runs hizli. `.cache/pre-commit` dizini bunlari tutar. |
| CRLF vs LF | Windows'ta `git config core.autocrlf false` ve `.gitattributes` dosyasi ile LF enforce |

## Ipucu

`pre-commit` calistiginda hatalari **auto-fix** ediyor genelde. Sonra git'te degisiklikleri gormek icin `git diff`. Auto-fixed dosyalari tekrar stage etmeyi unutma:

```bash
pre-commit run --all-files   # Fix'ler uygulanir
git add -u                     # Fix'lenmis dosyalari stage et
git commit -m "fix: apply pre-commit fixes"
```
