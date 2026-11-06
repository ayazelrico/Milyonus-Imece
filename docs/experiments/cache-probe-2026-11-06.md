# Gerçek Docker üzerinde tekrarlanan doğrulama ölçümü

Bu kayıt `9e12ccb` sürümündeki ilk ölçümdür. Sonraki çalışma kimliği sorguları
ek maliyet getirir; güncel araç aşağıdaki eski sayıları birebir üretmez.
[Güncel ölçüm ve toplam CLI süreçleri](cache-runtime-probe-2026-11-06.md).

6 Kasım 2026'da `evals.imece.cache_probe` çalıştırıldı. Model çağrısı yapılmadı.
Üç açık ve deterministik Python örneği beşer kez aynı imajda doğrulandı.
Kontrol kolunda önbellek yoktu. Aday kol soğuk önbellekle başladı; operatörün
bu örnekler için onayladığı baseline kanıt kimlikleriyle normal izinli yolu
kullandı. Ajan çıktısı kendisine önbellek izni veremedi.

| Ölçüm | Sonuç |
| --- | ---: |
| Mantıksal doğrulama / kol | 15 |
| Önbelleksiz Docker süreci | 15 |
| Soğuk önbellekten başlayan aday süreç | 3 |
| Bu iş yükünde süreç azalması | %80 |
| Kaynak, kontrol, timeout değişiminde yeniden yürütme | 3/3 |
| Değişmiş kimlik tekrarında önbellek kullanımı | 3/3 |
| Onaysız aynı kontrolün yeniden yürütülmesi | 2/2 |
| Başarısız kontrolün yeniden yürütülmesi | 2/2 |

Sonuçlar gerçek `PythonExecutor.processes_started` sayacından gelir; sahte
yürütücü kullanılmadı. Her gözlemde geçme durumu, çıkış kodu, hata sınıfı,
yeniden kullanım ve süreç artışı doğrulandı. Altyapı hatası beklenen bir test
başarısızlığı gibi kabul edilmez. Ham kayıt kaynak dosyalarının SHA-256
özetlerini, iş yükü özetini ve sabit imaj kimliğini içerir.

Bu kurulan tekrar örüntüsü üretimde tekrar oranını, tüm 50 × 5 görev matrisinde
%60 azalmayı veya P2'nin tamamını kanıtlamaz. Gerçek geçersizleşme ölçümü
kaynak, kontrol ve timeout boyutlarıyla sınırlıdır; farklı imaj/politika ve
diğer ortam değişimlerinin tamamı ölçülmedi. Süre veya dolar tasarrufu iddiası
yapılmaz; `accepted_5x=false` korunur.

Ham sonuç: `experiments/cache-probe-2026-11-06.json`.
Yeniden çalıştırma (Docker çalışır durumda ve imaj erişilebilir olmalı):

```sh
uv run python -m evals.imece.cache_probe --repeats 5 --out cache-probe.json
```

`test_real_docker_cache_probe_preserves_results_and_invalidates_changes`
aynı akışı üç tekrar ile CI'nin gerçek Docker adımına dahil eder. Test,
değişen kanıt kimliklerini ve değişmiş kimliğin sonraki kullanımını da kontrol
eder. `MILYONUS_TEST_DOCKER=1` olmadan yerel testte atlanır.
