# Açık JSON arayüzüyle core-v3 matrisi

7 Kasım 2026'da kaynak `379ebad` üzerinde 50 görev × 5 tekrar × 2 kol
yeniden ve ayrı protokol olarak hazırlandı. Checkpoint dizini
`experiments/cli-full-matrix-v3-2026-11-07/`. Önceki v2 deneyinin
29 satırı bu matrise taşınmaz. v2'de bulunan JSON arayüzü eksikliği
görünür v3 sözleşmesinde giderildi; gizli vakalar ve host scorer değişmedi.
[Bulgu kaydı](../audits/2026-11-07-oracle-interface.md).

Hazırlıkta model çağrısı yapılmadı. Aynı kaynak ve ortamla ayrı tek görevlik
`experiments/cli-v3-interface-2026-11-07/` medyan kalibrasyonu da hazırlandı.
Bu kalibrasyon ana 500 satıra dahil değildir.
İki kol da medyanı ilk turda dış doğrulamadan geçirdi; çağrı kayıtları
doğrulandı. [Kalibrasyon sonucu](cli-v3-interface-2026-11-07.md).
Ardından tam matrisin ilk dörder görevlik partisi başlatıldı.

Kontrol standart CLI talimatı ve sabit üretim, aday kısa CLI talimatı ve
uyarlanan üretim kullanır. Sonuç iki değişikliğin birleşik etkisini ölçer.
Her kol 250 satır, görev sırası `repeat-major`, her koltuk
`gpt-6.1-sol`, 17 ajan, tek eşzamanlı model çağrısı, en çok dört tur,
ajan timeout 300 saniye. Tamamlanan kullanıma dayalı yumuşak token sınırı
görev başına 500.000; kalıcı CLI çağrı tavanı kol başına 12.500.

Docker imajı
`python@sha256:e695ab189fa2d082b1c61c69a6b888a5adeca61ceeccad107b1ed2a125721a9e`;
gerçek ortam parmak izi manifestte donduruludur. Devam sırasında kaynak ve
ortam eşleşmelidir. Kaynak değişikliği yeni deney gerektirir.

Canlı koşu komutu (baseline için):

```sh
TMPDIR=/Users/ayazelrico/.cache/imece-docker-tests \
DOCKER_CONTEXT=colima-imece-tests \
uv run python -m evals.imece.run --engine codex --model gpt-6.1-sol \
  --suite core-v3 --repeats 5 --trial-order repeat-major \
  --max-tokens 500000 --max-cli-calls 12500 --max-new-trials 1 \
  --backend docker --image python@sha256:e695ab189fa2d082b1c61c69a6b888a5adeca61ceeccad107b1ed2a125721a9e \
  --config docs/imece-codex-baseline.toml --resume \
  --out experiments/cli-full-matrix-v3-2026-11-07/baseline.json
```

Aday için config `docs/imece-codex-adaptive.toml`, çıktı `candidate.json`
ve ek seçenek `--compact-cli-instructions`. Önce ayrılmış Docker ortamı
`colima start imece-tests --activate=false` ile açılır. Başarısız veya
belirsiz çağrı olursa yeniden göndermeden önce günlükler incelenir.

Durum `uv run python scripts/imece_matrix_status.py
experiments/cli-full-matrix-v3-2026-11-07` ile okunur. `false_acceptances`
iç onay alıp dış oracle'dan geçemeyen koordinatları listeler. Devam için
checkpoint, `.journal/` ve `.calls/` dizinleri birlikte korunmalıdır.

Gerçek çağrı bazında USD dökümü bulunmuyor. Bu belge bağımsız denetim
veya 5X kabul belgesi değildir. Tam matris, gerçek ücret mutabakatı ve
bağımsız denetçi şartları ayrıca karşılanmalıdır.
