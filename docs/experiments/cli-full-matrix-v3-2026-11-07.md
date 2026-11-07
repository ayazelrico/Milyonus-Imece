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

İlk parti tamamlandığında 8/500 satır kayıtlı, 492 satır açıktı. İlk dört
görev (`stable_unique`, `runs`, `rotate`, `window_sums`) iki kolda da
dış oracle'dan geçti. Baseline 120 çağrı/1.269.113 token, aday 116 çağrı/
757.194 token kullandı. Her satırın token toplamı tamamlanan kalıcı çağrı
kayıtlarıyla eşleştirildi. Bu sınırda yanlış kabul veya belirsiz kullanım
yoktu. İki kol beşinci görev `balanced` ile devam etti.

Beşinci eşleşmede `balanced` iki kolda da dış oracle'dan geçti. Kontrol
kolunda son onay aşamasındaki bir Codex bağlantı hatası nedeniyle koşunun
tam token kullanımı bilinmiyor. Kalıcı kayıtta 306.176 gözlenen token ve
bir belirsiz çağrı var. Aday 187.094 token kullandı. 10 satır kayıtlı,
490 satır açık. Kontrol kolu `--continue-after-uncertain-trial` ile
sonraki göreve geçti. Belirsiz çağrı ilk kaydıyla birlikte korunur.

Altıncı eşleşmede `gcd_list` iki kolda da dış oracle'dan geçti. Kontrol
317.173, aday 188.706 token kullandı. Kayıtlı 12 satırın kullanım bilgisi
kalıcı çağrı kayıtlarıyla eşleşti. 488 satır açık ve sıradaki görev `divisors`.

Yedinci eşleşmede `divisors` iki kolda da dış oracle'dan geçti. Her kol
28 çağrı kaydetti. Kontrol 294.191, aday 178.179 token kullandı. Her iki
toplam kalıcı çağrı kayıtlarıyla eşleşti. 14 satır kayıtlı, 486 satır açık.
İki kol `flatten` ile devam etti.

`flatten` sırasında Docker ortam doğrulaması iki kolu durdurdu. Daha
sonra alınan dört parmak izi donmuş ortamla eşleşti ve iki kol günlüklerden
devam etti. Kontrolün kesinti anında açık kalan çağrısının kullanımı
bilinmediği için `flatten` satırı `budget` olarak kaydedildi. Adayın
`flatten` çözümü dış oracle'dan geçti (29 çağrı, 189.045 token). Kontrolün
bilinen 104.622 tokenı ve bir belirsiz çağrısı kayıtta. 16 satırdan 15'i
doğrulandı, 484 satır açık. İki kol `transpose` ile devam etti.

Kontrolün `transpose` koşusu aynı Docker doğrulama hatasıyla kesildi.
Aday `transpose` dış oracle'dan geçti (177.968 token) ve `prime_flags`
görevine başladı. Bu noktada 17 satır kayıtlı, 16'sı doğrulanmış başarı.
Kontrolün devamı aday sürecinin kapanmasına bağlandı. Böylece bir sonraki
kontrol partisi Docker'ı tek başına kullanacak.

Aday `prime_flags` görevini ikinci turda dış oracle'dan geçirdi ve üç
satırlık toparlanma partisini tamamladı. Bu noktada 18 satır kayıtlı,
17'si doğrulanmış başarı. Kontrol `transpose` günlüğünden tek başına
devam etmeye başladı.

Kontrol `transpose` görevini tek başına sürdürdüğünde dış oracle'dan
geçti. 30 tamamlanmış çağrıdaki 317.843 token raporla eşleşti. Adayın
`prime_flags` kaydı 41 tamamlanmış çağrı ve 275.096 token içeriyor.
19 satır kayıtlı, 18'i doğrulanmış başarı ve 481'i açık. Kontrol
`prime_flags` görevine geçti. Adayın sonraki partisi kontrolün bitişine
bağlandı.

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
