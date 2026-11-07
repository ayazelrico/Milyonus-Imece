# Sabit yürütücüyle core-v3 kıyaslaması

Önceki v3 matrisi CLI otomatik güncellemesi nedeniyle 27 kayıtla arşivlendi.
Yeni deney `0.167.0-alpha.3.2` sürümüne ve yürütücü SHA-256 özetine bağlı.
İki kol da açık `--executable` ile şu sabit kopyayı kullanır.

```text
/Users/ayazelrico/.cache/imece-cli/0.167.0-alpha.3.2-a636331ed876/CodexCLI.app/Contents/MacOS/codex
sha256 a636331ed87605efc4cf84028ac2884a75363f9d10ead63cffb57ea0016d486e
```

Tam matris `experiments/cli-pinned-matrix-2026-11-07/` altında 50 görev,
beş tekrar ve iki kol olarak hazırlandı. Model tüm koltuklarda
`gpt-6.1-sol`, görev sırası `repeat-major`, ajan sayısı 17, paralel model
çağrısı 1, en fazla tur 4. Görev başına yumuşak token sınırı 500.000,
kol başına kalıcı çağrı sınırı 12.500. Baseline standart CLI talimatı ve
sabit üretim, aday kısa talimat ve uyarlanan üretim kullanır. Bu iki
değişikliğin birleşik etkisi ölçülür.

Docker imajı
`python@sha256:e695ab189fa2d082b1c61c69a6b888a5adeca61ceeccad107b1ed2a125721a9e`.
Manifest gerçek doğrulama ortamını ve kaynak özetini içerir. Kollar sırayla
çalıştırılır. Makinedeki komutlar `DOCKER_CONTEXT=colima-imece-tests` ve
`TMPDIR=/Users/ayazelrico/.cache/imece-docker-tests` kullanır.

Önce ayrı tek görevlik medyan kalibrasyonu hazırlandı. Aday ilk turda
dış oracle'dan geçti ve 188.327 token kullandı. Kontrol kalibrasyonu
başlatıldı. Bu kayıtlar `experiments/cli-pinned-calibration-2026-11-07/`
altındadır. Tam matris kalibrasyon sonrasında başlatılacaktır.

Güncel matris durumu şu komutla okunur.

```sh
uv run python scripts/imece_matrix_status.py experiments/cli-pinned-matrix-2026-11-07
```

Gerçek çağrı bazında USD dökümü ve bağımsız denetçi kabulü açık koşullardır.
