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

Önce ayrı tek görevlik medyan kalibrasyonu tamamlandı. İki kol ilk turda
dış oracle'dan geçti. Kontrol 30 çağrı ve 318.871 token, aday 29 çağrı ve
188.327 token kullandı. Her iki rapor `validate_report` ile doğrulandı.
Bu kayıtlar `experiments/cli-pinned-calibration-2026-11-07/` altındadır.
Ardından tam matrisin aday kolunda ilk üç görev başlatıldı.

İlk aday görevi `stable_unique` dış oracle'dan geçti. 29 tamamlanmış
çağrıdaki 185.955 token raporla eşleşti. Matrisin ilk satırı kaydedildi
ve aday `runs` göreviyle devam etti.

Adayın ilk üç görevlik partisi tamamlandı. `runs` 180.716 token ve
28 çağrı, `rotate` 189.989 token ve 29 çağrıyla dış oracle'dan geçti.
Üç görevin toplamı 556.660 token. Her satırın kullanımı tamamlanmış
çağrı kayıtlarıyla eşleşti. 3/500 satır kayıtlı ve kontrol partisi başladı.

Kontrol `stable_unique` ve `runs` görevlerinde dış oracle'dan geçti.
Sırasıyla 313.998 ve 319.293 token, her görevde 30 tamamlanmış çağrıyla
eşleşti. İki eşleşme tamamlandı ve toplam beş satır kaydedildi. Kontrol
`rotate` göreviyle devam etti.

Kontrol `rotate` görevini dış oracle'dan geçirdi. İlk üç görev iki kolda
da doğrulandı. Kontrol toplam 951.594, aday 556.660 token kullandı. Altı
satırın token toplamı tamamlanmış çağrı kayıtlarıyla eşleşti. 494 satır
açık. Aday `window_sums` ile sonraki üç görevlik partiye başladı.

Aday `window_sums` ve `balanced` görevlerinde dış oracle'dan geçti.
Bu iki satırın token kullanımı tamamlanmış çağrı kayıtlarıyla eşleşti.
Toplam sekiz satır kaydedildi, aday `gcd_list` görevine başladı.

Aday `gcd_list` görevini de dış oracle'dan geçirerek ikinci partiyi
tamamladı. Altı aday sonucu doğrulanmış başarı, toplam kullanım
1.108.167 token. Matris dokuz satıra ulaştı. Kontrol `window_sums`
ile sonraki üç görevlik partiye başladı.

Kontrol `window_sums` ve `balanced` görevlerini dış oracle'dan geçirdi.
Her iki satırdaki token toplamı tamamlanmış çağrı kayıtlarıyla eşleşti.
Beş eşleşme tamamlandı, toplam 11 satır kayıtlı. Kontrol `gcd_list`
göreviyle devam etti.

Kontrol `fix_chunk_tail` görevini dış oracle'dan geçirdi ve partisini
tamamladı. Token toplamı tamamlanmış çağrı kayıtlarıyla eşleşti. 24 satır
kayıtlı, 21'i doğrulanmış başarı ve 476'sı açık. Aday `fix_negative_max`
göreviyle sonraki partiye başladı.

Aday `fix_negative_max` ve `fix_even_median` görevlerini dış oracle'dan
geçirdi. Her iki satırın token toplamları tamamlanmış çağrı kayıtlarıyla
eşleşti. 26 satır kayıtlı, 23'ü doğrulanmış başarı. Aday `fix_empty_prefix`
görevine geçti.

Aday `fix_empty_prefix` görevini dış oracle'dan geçirerek partisini
tamamladı. Token toplamı tamamlanmış çağrı kayıtlarıyla eşleşti. 27 satır
kayıtlı, 24'ü doğrulanmış başarı ve 473'ü açık. Kontrol `fix_negative_max`
ile sonraki partiye başladı.

Kontrol `gcd_list` görevini de dış oracle'dan geçirdi. İlk altı görev
iki kolda da doğrulanmış başarı. Kontrol toplam 1.904.163, aday 1.108.167
token kullandı. On iki satırın toplamları tamamlanmış çağrı kayıtlarıyla
eşleşti. 488 satır açık. Aday `divisors` ile sonraki partiye başladı.

Aday `divisors` görevini dış oracle'dan geçirdi. 28 çağrıdaki 181.143
token raporla eşleşti. Sonraki `flatten` görevi model listesini yenileme
sırasında CLI bağlantı hatasıyla `budget` sonucuna ulaştı. Bu çağrının
kullanımı bilinmiyor. 14 satır kayıtlı, 13'ü doğrulanmış başarı ve 486'sı
açık. 8 Kasım devamında kontrol kolu `divisors` ile yeniden başlatıldı.

Kontrol `divisors` görevini dış oracle'dan geçirdi. Token toplamı
tamamlanmış çağrı kayıtlarıyla eşleşti. 15 satır kayıtlı, 14'ü doğrulanmış
başarı. Kontrol `flatten` göreviyle devam etti.

Kontrol `flatten` sırasında model listesini yenileyen CLI bağlantı
hatasıyla durdu. Ardından aday `transpose` ilk aşamada başarısız bir CLI
turu bildirdi. Her iki satır `budget`, çağrı kullanımları bilinmiyor.
17 satır kayıtlı, 14'ü doğrulanmış başarı. 8 Kasım saat 13.03 kontrolünde
CLI oturumu açık, genel ChatGPT HTTPS bağlantısı erişilebilir ve kısa
kota %18 kullanılmıştı. Kontrol sonraki `transpose` görevine tek koşuluk
partiyle devam etti.

Kontrol `transpose` görevini bağlantı hatası tekrarlamadan dış oracle'dan
geçirdi. Token kullanımı tamamlanmış çağrı kayıtlarıyla eşleşti.
18 satır kayıtlı, 15'i doğrulanmış başarı ve 482'si açık. Aday
`prime_flags` ile sonraki üç görevlik partiye başladı.

Aday `prime_flags` ve `fix_binary_search` görevlerini dış oracle'dan
geçirdi. Sırasıyla 179.509 ve 193.530 token, tamamlanmış çağrı kayıtlarıyla
eşleşti. 20 satır kayıtlı, 17'si doğrulanmış başarı. Aday `fix_chunk_tail`
görevine geçti.

Aday `fix_chunk_tail` görevini dış oracle'dan geçirdi. Tamamlanmış çağrı
kayıtları token toplamıyla eşleşti. 21 satır kayıtlı, 18'i doğrulanmış
başarı ve 479'u açık. Kontrol `prime_flags` ile sonraki partiye başladı.

Kontrol `prime_flags` ve `fix_binary_search` görevlerinde dış oracle'dan
geçti. Her satırın token toplamı tamamlanmış çağrı kayıtlarıyla eşleşti.
23 satır kayıtlı, 20'si doğrulanmış başarı. Kontrol `fix_chunk_tail`
göreviyle devam etti.

Güncel matris durumu şu komutla okunur.

```sh
uv run python scripts/imece_matrix_status.py experiments/cli-pinned-matrix-2026-11-07
```

Gerçek çağrı bazında USD dökümü ve bağımsız denetçi kabulü açık koşullardır.
